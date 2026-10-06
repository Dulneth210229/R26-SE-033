"""
Ingest domain knowledge files (PDF/DOCX/TXT/MD) into the Domain Agent's
vector store.

Usage:
    python scripts/ingest_domain_knowledge.py
    python scripts/ingest_domain_knowledge.py --path knowledge_base/ecommerce
    python scripts/ingest_domain_knowledge.py --path C:\\path\\to\\my_own_docs

Run this once before exercising the Domain Agent for real, and again any
time new domain documents are added -- ingestion is idempotent (chunk IDs
are deterministic per source file, so re-running just overwrites existing
vectors instead of duplicating them).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.domain_knowledge_service import domain_knowledge_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest domain knowledge files into the vector store.")
    parser.add_argument(
        "--path",
        default=settings.DOMAIN_KNOWLEDGE_BASE_DIR,
        help="File or directory to ingest (default: settings.DOMAIN_KNOWLEDGE_BASE_DIR).",
    )
    args = parser.parse_args()

    print(f"Ingesting domain knowledge from: {args.path}")
    summary = domain_knowledge_service.ingest_path(args.path)

    print(f"Files ingested:  {summary['files_ingested']}")
    print(f"Chunks created:  {summary['chunks_created']}")
    print(f"Files skipped:   {summary['files_skipped']}")


if __name__ == "__main__":
    main()
