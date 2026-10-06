"""
MongoDB-backed store.

Important:
This file keeps the old name: in_memory_store.py

Why?
Many existing files already import:
    from app.services.in_memory_store import store

If we rename the file now, all those imports must be changed.
So we keep the same file name but replace the internal storage with MongoDB.

Purpose:
- Store projects in MongoDB
- Store features in MongoDB
- Store artifacts in MongoDB
- Store approvals in MongoDB
- Store LLM settings in MongoDB

This replaces temporary in-memory storage.

Main benefit:
Data will not be lost when the backend restarts.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection

from app.core.config import settings


def _to_mongo_value(value: Any) -> Any:
    """
    Convert Python values into MongoDB-safe values.

    Why this is needed:
    MongoDB can store strings, numbers, booleans, lists, dicts, and datetimes.
    But it may not directly store Python Enum objects, Path objects, or Pydantic models.

    Example:
        AgentName.REQUIREMENT should be stored as "requirement_agent"
        Path("abc/file.md") should be stored as "abc/file.md"
    """

    # Convert Enum values to their actual string/value.
    if isinstance(value, Enum):
        return value.value

    # Convert pathlib.Path to string because MongoDB cannot store Path directly.
    if isinstance(value, Path):
        return str(value)

    # Datetime is supported by MongoDB, so keep it as it is.
    if isinstance(value, datetime):
        return value

    # Convert list items one by one.
    if isinstance(value, list):
        return [_to_mongo_value(item) for item in value]

    # Convert dictionary values one by one.
    if isinstance(value, dict):
        return {
            key: _to_mongo_value(inner_value)
            for key, inner_value in value.items()
            if key != "_id"
        }

    # Convert Pydantic models if any are passed accidentally.
    if hasattr(value, "model_dump"):
        return _to_mongo_value(value.model_dump(mode="json"))

    return value


def _from_mongo_document(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Clean MongoDB document before returning it to the application.

    MongoDB automatically adds an '_id' field.
    Our application already uses custom IDs like:
        project_id
        feature_id
        artifact_id
        approval_id

    So we remove MongoDB's internal '_id' before returning the document.
    """

    if document is None:
        return None

    cleaned = dict(document)
    cleaned.pop("_id", None)
    return cleaned


class MongoDocument(dict):
    """
    Dictionary that auto-saves changes back to MongoDB.

    Why this class is useful:
    Existing code may do this:

        feature = store.features.get(feature_id)
        feature["feature_status"] = "in_progress"

    In normal MongoDB, changing that returned dictionary would NOT save automatically.

    This class fixes that problem.
    When a value is changed, it writes the updated document back to MongoDB.
    """

    def __init__(self, data: dict[str, Any], parent_collection: "MongoCollectionProxy", document_key: str,):
        # Avoid saving while the object is being initialized.
        object.__setattr__(self, "_parent_collection", parent_collection)
        object.__setattr__(self, "_document_key", document_key)
        object.__setattr__(self, "_initializing", True)

        super().__init__(data)

        object.__setattr__(self, "_initializing", False)

    def __setitem__(self, key: str, value: Any) -> None:
        """
        Save field change to MongoDB.

        Example:
            feature["current_agent"] = "requirement_agent"

        This will update the local dict and also update MongoDB.
        """

        super().__setitem__(key, value)

        if not self._initializing:
            self._parent_collection[self._document_key] = dict(self)

    def update(self, *args: Any, **kwargs: Any) -> None:
        """
        Save dictionary update to MongoDB.

        Example:
            feature.update({"feature_status": "completed"})
        """

        super().update(*args, **kwargs)

        if not self._initializing:
            self._parent_collection[self._document_key] = dict(self)


class MongoCollectionProxy:
    """
    MongoDB collection wrapper that behaves like a Python dictionary.

    Why:
    Your current project uses code like:
        store.projects[project_id] = project_data
        store.projects.get(project_id)
        store.artifacts.values()

    Instead of rewriting every route and service now,
    this class gives MongoDB a dictionary-like interface.
    """

    def __init__(self, collection: Collection, id_field: str):
        """
        collection:
            MongoDB collection object.

        id_field:
            The custom ID field used by the application.
            Example:
                projects use project_id
                features use feature_id
                artifacts use artifact_id
                approvals use approval_id
        """

        self.collection = collection
        self.id_field = id_field

    def __setitem__(self, key: str, value: dict[str, Any]) -> None:
        """
        Insert or update one document.

        Example:
            store.projects["project_123"] = {...}

        This becomes MongoDB upsert:
            update if exists, insert if not exists
        """

        document = _to_mongo_value(value)

        # Make sure the document has the correct ID field.
        document[self.id_field] = key

        self.collection.update_one(
            {self.id_field: key},
            {"$set": document},
            upsert=True,
        )

    def __getitem__(self, key: str) -> MongoDocument:
        """
        Get one document.

        Example:
            project = store.projects["project_123"]

        If not found, raise KeyError like a normal dictionary.
        """

        document = self.collection.find_one({self.id_field: key})
        cleaned = _from_mongo_document(document)

        if cleaned is None:
            raise KeyError(key)

        return MongoDocument(
            data=cleaned,
            parent_collection=self,
            document_key=key,
        )

    def get(self, key: str, default: Any = None) -> MongoDocument | Any:
        """
        Get one document safely.

        Example:
            feature = store.features.get(feature_id)

        If not found, return default instead of crashing.
        """

        document = self.collection.find_one({self.id_field: key})
        cleaned = _from_mongo_document(document)

        if cleaned is None:
            return default

        return MongoDocument(
            data=cleaned,
            parent_collection=self,
            document_key=key,
        )

    def values(self) -> list[MongoDocument]:
        """
        Return all documents as a list.

        Example:
            for artifact in store.artifacts.values():
                ...
        """

        results: list[MongoDocument] = []

        for document in self.collection.find({}):
            cleaned = _from_mongo_document(document)

            if cleaned is None:
                continue

            key = cleaned[self.id_field]

            results.append(
                MongoDocument(
                    data=cleaned,
                    parent_collection=self,
                    document_key=key,
                )
            )

        return results

    def items(self) -> list[tuple[str, MongoDocument]]:
        """
        Return all documents as key-value pairs.

        Example:
            for project_id, project in store.projects.items():
                ...
        """

        return [
            (document[self.id_field], document)
            for document in self.values()
        ]

    def keys(self) -> list[str]:
        """
        Return all custom IDs in this collection.
        """

        return [
            document[self.id_field]
            for document in self.values()
        ]

    def clear(self) -> None:
        """
        Delete all documents from this collection.

        This replaces old in-memory:
            self.projects.clear()
        """

        self.collection.delete_many({})

    def __contains__(self, key: str) -> bool:
        """
        Support:
            if project_id in store.projects:
        """

        return self.collection.count_documents({self.id_field: key}, limit=1) > 0


class MongoLLMSettingsProxy(MutableMapping):
    """
    MongoDB-backed dictionary for LLM settings.

    Why this is separate:
    LLM settings are not multiple documents like projects or features.
    They are one active settings document.

    Existing code can still use:
        store.llm_settings["provider"]
        store.llm_settings.get("model")
        store.llm_settings.update({...})
    """

    DOCUMENT_KEY = "active"

    def __init__(self, collection: Collection):
        self.collection = collection
        self._ensure_default_settings()

    def _ensure_default_settings(self) -> None:
        """
        Create default LLM settings if they do not exist yet.
        """

        existing = self.collection.find_one({"settings_id": self.DOCUMENT_KEY})

        if existing:
            return

        default_settings = {
            "settings_id": self.DOCUMENT_KEY,
            "provider": settings.DEFAULT_LLM_PROVIDER,
            "model": settings.DEFAULT_LLM_MODEL,
            "base_url": settings.OLLAMA_BASE_URL,
            "api_key": settings.OPENAI_API_KEY,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "streaming_enabled": settings.LLM_STREAMING_ENABLED,
            "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
        }

        self.collection.insert_one(default_settings)

    def _get_document(self) -> dict[str, Any]:
        """
        Read the active LLM settings document.
        """

        document = self.collection.find_one({"settings_id": self.DOCUMENT_KEY})
        cleaned = _from_mongo_document(document)

        if cleaned is None:
            self._ensure_default_settings()
            cleaned = _from_mongo_document(
                self.collection.find_one({"settings_id": self.DOCUMENT_KEY})
            )

        return cleaned or {}

    def get_document(self) -> dict[str, Any]:
        """
        Read the whole settings document in exactly one round-trip.

        Prefer this over repeated `store.llm_settings["field"]` accesses when a caller needs
        several fields -- each `__getitem__` call below independently re-fetches the *entire*
        document (there is no per-instance caching), so reading N fields one at a time costs N
        round-trips. This mattered concretely: computing every agent's effective LLM settings
        (5 agents x ~6 fields, plus the global settings) previously took ~30+ separate
        `find_one` calls against MongoDB Atlas (a real, non-local cluster with real per-call
        network latency) -- observed taking 5+ seconds for what should be one cheap read.
        """
        return self._get_document()

    def __getitem__(self, key: str) -> Any:
        """
        Support:
            store.llm_settings["provider"]
        """

        document = self._get_document()
        return document[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """
        Support:
            store.llm_settings["provider"] = "ollama"
        """

        self.collection.update_one(
            {"settings_id": self.DOCUMENT_KEY},
            {"$set": {key: _to_mongo_value(value)}},
            upsert=True,
        )

    def __delitem__(self, key: str) -> None:
        """
        Support deleting one setting field if needed.
        """

        self.collection.update_one(
            {"settings_id": self.DOCUMENT_KEY},
            {"$unset": {key: ""}},
        )

    def __iter__(self) -> Iterator[str]:
        """
        Allows this object to behave like a dictionary.
        """

        document = self._get_document()

        for key in document:
            if key != "settings_id":
                yield key

    def __len__(self) -> int:
        """
        Return number of LLM setting fields.
        """

        return len(list(iter(self)))

    def get(self, key: str, default: Any = None) -> Any:
        """
        Support:
            store.llm_settings.get("model")
        """

        return self._get_document().get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert settings proxy to normal dictionary.

        Useful when returning settings in API response.
        """

        document = self._get_document()
        document.pop("settings_id", None)
        return document


class MongoStore:
    """
    Main MongoDB store used by the application.

    This class replaces the old InMemoryStore.

    Collections:
        projects
        features
        artifacts
        approvals
        llm_settings
        stage_events
        requirement_conversations
    """

    def __init__(self):
        """
        Create MongoDB connection and collection proxies.
        """

        self.client = MongoClient(settings.MONGODB_URI)
        self.database = self.client[settings.MONGODB_DATABASE]

        # Collections are similar to tables in SQL.
        self.projects = MongoCollectionProxy(
            collection=self.database["projects"],
            id_field="project_id",
        )

        self.features = MongoCollectionProxy(
            collection=self.database["features"],
            id_field="feature_id",
        )

        self.artifacts = MongoCollectionProxy(
            collection=self.database["artifacts"],
            id_field="artifact_id",
        )

        self.approvals = MongoCollectionProxy(
            collection=self.database["approvals"],
            id_field="approval_id",
        )

        self.llm_settings = MongoLLMSettingsProxy(
            collection=self.database["llm_settings"],
        )

        # One record per human-initiated run()/revise() request -- the "ask" half of the
        # frontend's per-stage activity timeline (see approvals for the "reviewer decision"
        # half; the artifact's own created_at is the "agent responded" half). Recorded at the
        # API route layer (app/api/routes/agents.py), not deep in each agent, since that's the
        # one place every request's human_comment/revision_comment is already available
        # uniformly, before any agent-specific processing.
        self.stage_events = MongoCollectionProxy(
            collection=self.database["stage_events"],
            id_field="event_id",
        )

        # One document per feature_id, upserted in place each conversational turn -- NOT
        # versioned like artifacts, since a single in-progress turn is not a reviewable output
        # on its own (unlike every other artifact type). Requirement Agent's conversational
        # gap-filling loop reads/writes this directly; see conversation_engine.py.
        self.requirement_conversations = MongoCollectionProxy(
            collection=self.database["requirement_conversations"],
            id_field="feature_id",
        )

        # One record per uploaded per-project domain knowledge document (see
        # knowledge_document_service.py) -- the raw file lives on disk and its chunks live in
        # Chroma; this is just the metadata (filename, status, chunk_count) the UI lists/manages.
        self.knowledge_documents = MongoCollectionProxy(
            collection=self.database["knowledge_documents"],
            id_field="document_id",
        )

        # One document per feature_id, holding the QA Agent's chat turn history (a plain list of
        # {role, content, created_at}) -- same "one document, upserted in place, not versioned
        # like an artifact" shape as requirement_conversations above, since a chat turn is not a
        # reviewable output on its own. See app/api/routes/agents.py's /qa/chat[/stream] routes.
        self.qa_conversations = MongoCollectionProxy(
            collection=self.database["qa_conversations"],
            id_field="feature_id",
        )

        # Same shape as qa_conversations above, for the Security Agent's own chat -- see
        # app/api/routes/agents.py's /security/chat[/stream] routes.
        self.security_conversations = MongoCollectionProxy(
            collection=self.database["security_conversations"],
            id_field="feature_id",
        )

        # One document per registered account (email/password or OAuth). See
        # app/services/auth_service.py for how this is created/read; app/api/deps.py for how a
        # request resolves the current user from a JWT back to a document here.
        self.users = MongoCollectionProxy(
            collection=self.database["users"],
            id_field="user_id",
        )

        self._create_indexes()

    def _create_indexes(self) -> None:
        """
        Create indexes for faster lookups.

        Why indexes:
        Without indexes, MongoDB may scan the full collection.
        With indexes, finding by project_id, feature_id, etc. is faster.
        """

        self.database["projects"].create_index(
            [("project_id", ASCENDING)],
            unique=True,
        )

        self.database["features"].create_index(
            [("feature_id", ASCENDING)],
            unique=True,
        )

        self.database["features"].create_index(
            [("project_id", ASCENDING)]
        )

        self.database["artifacts"].create_index(
            [("artifact_id", ASCENDING)],
            unique=True,
        )

        self.database["artifacts"].create_index(
            [("feature_id", ASCENDING)]
        )

        self.database["artifacts"].create_index(
            [
                ("feature_id", ASCENDING),
                ("agent_name", ASCENDING),
                ("artifact_type", ASCENDING),
                ("version", ASCENDING),
            ]
        )

        self.database["approvals"].create_index(
            [("approval_id", ASCENDING)],
            unique=True,
        )

        self.database["approvals"].create_index(
            [("artifact_id", ASCENDING)]
        )

        self.database["llm_settings"].create_index(
            [("settings_id", ASCENDING)],
            unique=True,
        )

        self.database["stage_events"].create_index(
            [("event_id", ASCENDING)],
            unique=True,
        )

        self.database["stage_events"].create_index(
            [("feature_id", ASCENDING)]
        )

        self.database["requirement_conversations"].create_index(
            [("feature_id", ASCENDING)],
            unique=True,
        )

        self.database["qa_conversations"].create_index(
            [("feature_id", ASCENDING)],
            unique=True,
        )

        self.database["security_conversations"].create_index(
            [("feature_id", ASCENDING)],
            unique=True,
        )

        self.database["knowledge_documents"].create_index(
            [("document_id", ASCENDING)],
            unique=True,
        )

        self.database["knowledge_documents"].create_index(
            [("project_id", ASCENDING)]
        )

        self.database["users"].create_index(
            [("user_id", ASCENDING)],
            unique=True,
        )

        self.database["users"].create_index(
            [("email", ASCENDING)],
            unique=True,
        )

        self.database["projects"].create_index(
            [("user_id", ASCENDING)]
        )

    def reset(self) -> None:
        """
        Clear project-related data from MongoDB.

        Important:
        We do not reset LLM settings because selected provider/model
        should remain available during development.
        """

        self.projects.clear()
        self.features.clear()
        self.artifacts.clear()
        self.approvals.clear()
        self.stage_events.clear()
        self.requirement_conversations.clear()
        self.qa_conversations.clear()
        self.security_conversations.clear()
        self.knowledge_documents.clear()

    def close(self) -> None:
        """
        Close MongoDB connection.

        This is useful when the FastAPI app shuts down.
        """

        self.client.close()


# Global store object used by the whole backend.
# Existing imports will continue to work:
#     from app.services.in_memory_store import store
store = MongoStore()




# """
# Temporary in-memory database.

# Important:
# This is only for the first MVP foundation.

# Later, this will be replaced with PostgreSQL or MongoDB.

# This store now also keeps LLM settings so we can switch between:
# - Ollama
# - OpenAI/API provider
# """

# from typing import Any

# from app.core.config import settings


# class InMemoryStore:
#     """
#     Very simple in-memory storage.

#     Data will be lost when the backend restarts.
#     """

#     def __init__(self):
#         self.projects: dict[str, dict[str, Any]] = {}
#         self.features: dict[str, dict[str, Any]] = {}
#         self.artifacts: dict[str, dict[str, Any]] = {}
#         self.approvals: dict[str, dict[str, Any]] = {}

#         # LLM settings are stored here for MVP.
#         # Later, move this to a database table or collection.
#         self.llm_settings: dict[str, Any] = {
#             "provider": settings.DEFAULT_LLM_PROVIDER,
#             "model": settings.DEFAULT_LLM_MODEL,
#             "base_url": settings.OLLAMA_BASE_URL,
#             "api_key": settings.OPENAI_API_KEY,
#             "temperature": settings.LLM_TEMPERATURE,
#             "max_tokens": settings.LLM_MAX_TOKENS,
#             "streaming_enabled": settings.LLM_STREAMING_ENABLED,
#             "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
#         }

#     def reset(self) -> None:
#         """
#         Clear all in-memory data.

#         We do not reset LLM settings here because the selected model
#         should remain available during local development.
#         """
#         self.projects.clear()
#         self.features.clear()
#         self.artifacts.clear()
#         self.approvals.clear()


# store = InMemoryStore()