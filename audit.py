"""Thin audit helper backed by SQLite state."""
from state import append_audit


def record(task_id: str | None, event: str, details: dict | None = None, db_path=None) -> None:
    append_audit(task_id, event, details or {}, db_path=db_path)
