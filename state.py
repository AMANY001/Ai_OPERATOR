"""SQLite persistence for tasks, steps, approvals, tool runs, and audit events."""
from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from config import get_settings

STATUSES = {"pending", "running", "awaiting_approval", "done", "failed", "skipped", "blocked", "paused", "verified", "rejected", "completed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_path(db_path=None) -> Path:
    path = Path(db_path) if db_path is not None else get_settings().database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(db_path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path=None) -> None:
    with connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, goal TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            plan_json TEXT NOT NULL DEFAULT '{}', result_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS steps (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            step_key TEXT NOT NULL, name TEXT NOT NULL, tool_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(task_id, step_key)
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            status TEXT NOT NULL, proposed_action_json TEXT NOT NULL,
            created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT '', decision_note TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_approvals_task ON approvals(task_id, created_at);
        CREATE TABLE IF NOT EXISTS tool_runs (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            step_id TEXT REFERENCES steps(id) ON DELETE SET NULL, tool_name TEXT NOT NULL,
            attempt INTEGER NOT NULL, started_at TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            timestamp TEXT NOT NULL, event TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id, id);
        """)


def create_task(goal: str, plan: dict | None = None, db_path=None) -> str:
    init_db(db_path)
    task_id, now = str(uuid.uuid4()), _now()
    with connect(db_path) as conn:
        conn.execute("INSERT INTO tasks(id,goal,status,created_at,updated_at,plan_json,result_json) VALUES(?,?,?,?,?,?,?)",
                     (task_id, goal, "running", now, now, json.dumps(plan or {}, ensure_ascii=False), "{}"))
    append_audit(task_id, "task_created", {"goal": goal}, db_path)
    return task_id


def _decode_row(row, json_fields=()):
    if row is None:
        return None
    out = dict(row)
    for key in json_fields:
        try:
            out[key] = json.loads(out.get(key) or "{}")
        except (json.JSONDecodeError, TypeError):
            out[key] = {}
    return out


def get_task(task_id: str, db_path=None) -> dict | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _decode_row(row, ("plan_json", "result_json"))


def list_tasks(limit: int = 50, db_path=None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
    return [_decode_row(row, ("plan_json", "result_json")) for row in rows]


def set_task_status(task_id: str, status: str, result: dict | None = None, db_path=None) -> None:
    if status not in STATUSES:
        raise ValueError(f"Invalid task status: {status}")
    init_db(db_path)
    with connect(db_path) as conn:
        if result is None:
            conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", (status, _now(), task_id))
        else:
            conn.execute("UPDATE tasks SET status=?, result_json=?, updated_at=? WHERE id=?",
                         (status, json.dumps(result, ensure_ascii=False), _now(), task_id))
    append_audit(task_id, "task_status_changed", {"status": status}, db_path)


def upsert_step(task_id: str, step_key: str, name: str, tool_name: str = "", status: str = "pending",
                result: dict | None = None, db_path=None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"Invalid step status: {status}")
    init_db(db_path)
    now, step_id = _now(), str(uuid.uuid4())
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO steps(id,task_id,step_key,name,tool_name,status,result_json,attempts,error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (step_id, task_id, step_key, name, tool_name, status, json.dumps(result or {}, ensure_ascii=False), 0, "", now, now))
        row = conn.execute("SELECT * FROM steps WHERE task_id=? AND step_key=?", (task_id, step_key)).fetchone()
    return _decode_row(row, ("result_json",))


def get_step(task_id: str, step_key: str, db_path=None) -> dict | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM steps WHERE task_id=? AND step_key=?", (task_id, step_key)).fetchone()
    return _decode_row(row, ("result_json",))


def list_steps(task_id: str, db_path=None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM steps WHERE task_id=? ORDER BY created_at, id", (task_id,)).fetchall()
    return [_decode_row(row, ("result_json",)) for row in rows]


def update_step(task_id: str, step_key: str, status: str, result: dict | None = None, error: str | None = None,
                increment_attempts: bool = False, db_path=None) -> None:
    if status not in STATUSES:
        raise ValueError(f"Invalid step status: {status}")
    init_db(db_path)
    assignments = ["status=?", "updated_at=?"]
    params: list[Any] = [status, _now()]
    if result is not None:
        assignments.append("result_json=?")
        params.append(json.dumps(result, ensure_ascii=False))
    if error is not None:
        assignments.append("error=?")
        params.append(error[:4000])
    if increment_attempts:
        assignments.append("attempts=attempts+1")
    params.extend([task_id, step_key])
    with connect(db_path) as conn:
        conn.execute(f"UPDATE steps SET {', '.join(assignments)} WHERE task_id=? AND step_key=?", params)


def create_approval(task_id: str, proposed_action: dict, db_path=None) -> str:
    init_db(db_path)
    approval_id, now = str(uuid.uuid4()), _now()
    with connect(db_path) as conn:
        conn.execute("INSERT INTO approvals(id,task_id,status,proposed_action_json,created_at) VALUES(?,?,?,?,?)",
                     (approval_id, task_id, "pending", json.dumps(proposed_action, ensure_ascii=False), now))
    append_audit(task_id, "approval_requested", {"approval_id": approval_id, "proposed_action": proposed_action}, db_path)
    return approval_id


def get_approval(task_id: str, db_path=None) -> dict | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM approvals WHERE task_id=? ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
    return _decode_row(row, ("proposed_action_json",))


def decide_approval(task_id: str, status: str, note: str = "", db_path=None) -> None:
    if status not in {"approved", "rejected"}:
        raise ValueError("Approval status must be approved or rejected")
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT id,status FROM approvals WHERE task_id=? ORDER BY created_at DESC LIMIT 1", (task_id,)).fetchone()
        if row is None:
            raise ValueError("No approval request exists for this task")
        if row["status"] != "pending":
            raise ValueError("This approval was already decided; prepare a new action for changed details")
        conn.execute("UPDATE approvals SET status=?, decided_at=?, decision_note=? WHERE id=?",
                     (status, _now(), note[:2000], row["id"]))
    append_audit(task_id, "approval_decided", {"approval_id": row["id"], "status": status, "note": note}, db_path)


def add_tool_run(task_id: str, step_key: str, tool_name: str, attempt: int, status: str,
                 result: dict | None = None, error: str = "", completed_at: str | None = None, db_path=None) -> str:
    init_db(db_path)
    step = get_step(task_id, step_key, db_path)
    run_id, now = str(uuid.uuid4()), _now()
    with connect(db_path) as conn:
        conn.execute("INSERT INTO tool_runs(id,task_id,step_id,tool_name,attempt,started_at,completed_at,status,result_json,error) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (run_id, task_id, step["id"] if step else None, tool_name, attempt, now, completed_at or _now(), status,
                      json.dumps(result or {}, ensure_ascii=False), error[:4000]))
    append_audit(task_id, "tool_run", {"tool": tool_name, "attempt": attempt, "status": status, "error": error}, db_path)
    return run_id


def append_audit(task_id: str | None, event: str, details: dict | None = None, db_path=None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO audit_log(task_id,timestamp,event,details_json) VALUES(?,?,?,?)",
                     (task_id, _now(), event, json.dumps(details or {}, ensure_ascii=False, default=str)))


def get_audit_log(task_id: str | None = None, limit: int = 200, db_path=None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as conn:
        if task_id:
            rows = conn.execute("SELECT * FROM audit_log WHERE task_id=? ORDER BY id DESC LIMIT ?", (task_id, max(1, min(limit, 1000)))).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
    return [_decode_row(row, ("details_json",)) for row in rows]


def get_approval_by_id(approval_id: str, db_path=None) -> dict | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    return _decode_row(row, ("proposed_action_json",))


def set_task_plan(task_id: str, plan: dict, db_path=None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("UPDATE tasks SET plan_json=?, updated_at=? WHERE id=?",
                     (json.dumps(plan, ensure_ascii=False), _now(), task_id))
    append_audit(task_id, "task_plan_persisted", {"workflow": (plan.get("decision") or {}).get("workflow", "unknown")}, db_path)
