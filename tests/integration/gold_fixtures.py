"""Shared helpers for the integration tests of feature 02 (gold set and results table)."""

from __future__ import annotations

import psycopg


def insert_documents(db: psycopg.Connection, count: int) -> list[str]:
    """Registry rows D-0001… without files: enough for the gold tables' foreign keys."""
    run_id = db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('intake', 't', '{}') RETURNING id"
    ).fetchone()[0]
    ids = []
    for seq in range(1, count + 1):
        doc_id = f"D-{seq:04d}"
        db.execute(
            "INSERT INTO document (id, seq, sha256, original_name, source_path, copy_path, "
            "size_bytes, page_count, intake_run_id) "
            "VALUES (%s, %s, %s, 'x.pdf', 's', 'c', 1, 1, %s)",
            (doc_id, seq, f"{seq:064x}", run_id),
        )
        ids.append(doc_id)
    db.execute("UPDATE document_counter SET last_seq = %s", (count,))
    return ids
