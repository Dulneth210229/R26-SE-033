"""
One-time migration: register the specified pre-existing account and associate every project
that doesn't already have an owner with it.

This is a DATABASE-level operation against the real, shared MongoDB Atlas cluster configured in
.env -- it is independent of any one machine's local outputs/workspaces directories, and never
deletes, renames, or overwrites any existing project field other than adding user_id where it's
missing.

Usage:
    python scripts/migrate_existing_projects_to_user.py

Safe to re-run: the user is only created if the email doesn't already exist, and the project
update only ever targets projects with no user_id at all (an already-migrated or newly-created
project is left untouched).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import auth_service
from app.services.in_memory_store import store

MIGRATION_EMAIL = "dulneth.sa@gmail.com"
MIGRATION_PASSWORD = "Ds#210229"


def main() -> None:
    existing = auth_service.get_user_by_email(MIGRATION_EMAIL)

    if existing:
        user = existing
        print(f"Account already exists: {MIGRATION_EMAIL} (user_id={user['user_id']}) -- reusing it.")
    else:
        user = auth_service.create_user(email=MIGRATION_EMAIL, password=MIGRATION_PASSWORD)
        print(f"Created account: {MIGRATION_EMAIL} (user_id={user['user_id']}).")

    result = store.projects.collection.update_many(
        {"user_id": {"$exists": False}},
        {"$set": {"user_id": user["user_id"]}},
    )

    total_projects = store.projects.collection.count_documents({})
    already_owned = total_projects - result.matched_count

    print(f"Projects newly associated with this account: {result.modified_count}")
    print(f"Projects that already had an owner (untouched): {already_owned}")
    print(f"Total projects in the database: {total_projects}")


if __name__ == "__main__":
    main()
