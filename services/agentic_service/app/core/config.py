"""
Application configuration file.

This file loads environment variables from the .env file.

Important:
The .env file must control the default LLM model.
llm_schema.py should only define API request/response shapes.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# This finds the backend root folder:
# services/agentic_service/
BASE_DIR = Path(__file__).resolve().parents[2]

# This points directly to:
# services/agentic_service/.env
ENV_FILE_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    APP_NAME: str = "AutoForge Agentic SDLC Backend"
    APP_ENV: str = "development"
    APP_VERSION: str = "0.1.0"

    API_PREFIX: str = "/api/v1"
    OUTPUT_DIR: str = "outputs"

    # LLM settings
    DEFAULT_LLM_PROVIDER: str = "ollama"
    DEFAULT_LLM_MODEL: str = "llama4"  # This is just a placeholder. The real default model must come from .env.
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"

    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    ANTHROPIC_MODEL: str = "claude-sonnet-5"

    # Model used specifically by agentic (tool-calling) nodes such as the Coder Agent,
    # via init_chat_model. Kept separate from DEFAULT_LLM_MODEL because the one-shot
    # prose-generation agents (Requirement/Domain/Architecture/UI-UX) and the agentic
    # coding loop have different model-quality tradeoffs.
    AGENTIC_MODEL_OVERRIDE: str = "qwen3-coder:latest"

    # Ollama's own server-side default context window is much smaller than most
    # models' real capability and gets silently exceeded by tool results containing
    # real file contents. Only applied when the agentic provider is "ollama".
    AGENTIC_OLLAMA_NUM_CTX: int = 32768

    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT_SECONDS: int = 320
    LLM_STREAMING_ENABLED: bool = True

    # Root folder for persistent per-project git repositories (the actual generated Next.js app).
    WORKSPACE_DIR: str = "workspaces"

    # MongoDB connection URI.
    # For local MongoDB: mongodb://localhost:27017
    # For MongoDB Atlas: mongodb+srv://username:password@cluster.mongodb.net
    MONGODB_URI: str = "mongodb://localhost:27017"

    # MongoDB database name used by AutoForge MAS.
    MONGODB_DATABASE: str = "autoforge_mas"
    # PlantUML configuration.
    # This is used by Architecture Agent to render use case diagrams.
    PLANTUML_JAR_PATH: str = "tools/plantuml.jar"

        # -----------------------------
    # Domain Agent RAG Settings
    # -----------------------------

    # Folder where domain knowledge files are stored.
    # Example:
    # knowledge_base/ecommerce/authentication.md
    # knowledge_base/lms/enrollment.md
    DOMAIN_KNOWLEDGE_BASE_DIR: str = "knowledge_base"

    # Folder where ChromaDB stores vector data.
    CHROMA_PERSIST_DIR: str = "vector_db/chroma"

    # Embedding model used to convert chunks into vectors.
    DOMAIN_EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Size of each text chunk.
    DOMAIN_CHUNK_SIZE: int = 900

    # Overlap between chunks so meaning is not lost between chunk boundaries.
    DOMAIN_CHUNK_OVERLAP: int = 150

    # Number of chunks retrieved for each Domain Agent run.
    DOMAIN_TOP_K: int = 6

    # Maximum size (bytes) accepted for a per-project domain knowledge document upload.
    DOMAIN_MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024

    # -----------------------------
    # Authentication Settings
    # -----------------------------

    # Signs/verifies JWT access tokens. Must be overridden in .env for any real deployment --
    # this placeholder is intentionally obvious so it's never mistaken for a real secret.
    SECRET_KEY: str = "insecure-development-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # OAuth (Google/GitHub) -- both None by default so the corresponding "Continue with X" flow
    # can be cleanly disabled/hidden until real credentials are configured, rather than crashing.
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GITHUB_CLIENT_ID: str | None = None
    GITHUB_CLIENT_SECRET: str | None = None

    # The frontend origin OAuth callbacks redirect back to after a successful provider login.
    OAUTH_REDIRECT_BASE_URL: str = "http://localhost:5174"

    # This backend's own externally-reachable base URL -- used to build the exact
    # redirect_uri Google/GitHub send the user back to, which must match what's registered in
    # each provider's OAuth app console byte-for-byte.
    BACKEND_BASE_URL: str = "http://localhost:8000"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8"
    )


settings = Settings()