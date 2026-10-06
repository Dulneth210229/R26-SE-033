"""
Manual end-to-end verification of the Domain Agent RAG pipeline.

This exercises the REAL embedding model and REAL ChromaDB vector store --
no LLM call is needed for this part, since retrieval is deterministic Python.

Usage:
    python scripts/ingest_domain_knowledge.py --path knowledge_base/ecommerce
    python scripts/verify_domain_rag_e2e.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.domain_knowledge_service import domain_knowledge_service

CHECKS = [
    (
        "cart merge login guest checkout stock validation",
        "checkout_and_cart_conventions.txt",
    ),
    (
        "storing raw card numbers payment tokenization PCI compliance",
        "payment_and_pci_basics.txt",
    ),
    (
        "order status pending confirmed paid shipped delivered cancelled",
        "order_lifecycle_states.txt",
    ),
    (
        "account lockout after failed login attempts password reset",
        "user_account_and_authentication.txt",
    ),
]


def main() -> None:
    failures = 0

    for query, expected_source in CHECKS:
        results = domain_knowledge_service.retrieve(query, top_k=3)

        if not results:
            print(f"FAIL: no chunks retrieved for query: {query!r}")
            failures += 1
            continue

        top_sources = [chunk["source_document"] for chunk in results]

        if expected_source in top_sources:
            print(f"PASS: {query!r} -> {top_sources}")
        else:
            print(f"FAIL: {query!r} -> expected {expected_source!r} in {top_sources}")
            failures += 1

    empty_check = domain_knowledge_service.retrieve("", top_k=3)
    if empty_check == []:
        print("PASS: empty query returns no chunks")
    else:
        print(f"FAIL: empty query should return [], got {empty_check}")
        failures += 1

    print()
    if failures:
        print(f"{failures} check(s) failed. Did you run scripts/ingest_domain_knowledge.py first?")
        sys.exit(1)

    print("All Domain Agent RAG retrieval checks passed.")


if __name__ == "__main__":
    main()
