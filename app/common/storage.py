from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.common.settings import env_str
from app.core.workflow.models import CaseResult
from app.common.logging import get_logger, log_event


logger = get_logger("storage")


def data_dir() -> Path:
    path = Path(env_str("INBOX_AI_DATA_DIR", "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def case_log_path() -> Path:
    return data_dir() / "cases.jsonl"


def database_path() -> Path:
    configured = env_str("INBOX_AI_DB_PATH", "")
    return Path(configured) if configured else data_dir() / "app.sqlite3"


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    log_event(logger, "storage_init_db", level=logging.DEBUG, database=str(database_path()))
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_message_id TEXT,
                requester TEXT,
                subject TEXT,
                status TEXT,
                request_type TEXT,
                urgency TEXT,
                confidence REAL,
                outbound_status TEXT,
                created_at TEXT,
                inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                payload TEXT NOT NULL,
                UNIQUE(source, source_message_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_inserted_at ON cases(inserted_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_request_type ON cases(request_type)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS poll_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT,
                stage TEXT NOT NULL,
                error TEXT NOT NULL,
                detail TEXT,
                query TEXT,
                resolved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_poll_errors_resolved ON poll_errors(resolved, created_at DESC)")
    migrate_jsonl_once()


def case_to_dict(case: CaseResult, *, source: str = "manual", source_message_id: str | None = None) -> dict[str, Any]:
    payload = asdict(case)
    payload["source"] = source
    payload["source_message_id"] = source_message_id
    return payload


def _insert_case_payload(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    classification = payload.get("classification") or {}
    conn.execute(
        """
        INSERT OR IGNORE INTO cases (
            id, source, source_message_id, requester, subject, status, request_type,
            urgency, confidence, outbound_status, created_at, payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["id"],
            payload.get("source") or "manual",
            payload.get("source_message_id"),
            payload.get("requester"),
            payload.get("subject"),
            payload.get("status"),
            classification.get("request_type"),
            classification.get("urgency"),
            classification.get("confidence"),
            payload.get("outbound_status"),
            payload.get("created_at"),
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def migrate_jsonl_once() -> None:
    marker = data_dir() / ".jsonl_migrated"
    path = case_log_path()
    if marker.exists() or not path.exists():
        return
    with connect() as conn:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                _insert_case_payload(conn, json.loads(line))
    marker.write_text("ok\n", encoding="utf-8")


def append_case(case: CaseResult, *, source: str = "manual", source_message_id: str | None = None) -> dict[str, Any]:
    init_db()
    payload = case_to_dict(case, source=source, source_message_id=source_message_id)
    with connect() as conn:
        _insert_case_payload(conn, payload)
        row = conn.execute("SELECT payload FROM cases WHERE id = ?", (payload["id"],)).fetchone()
        if not row and source_message_id:
            row = conn.execute(
                "SELECT payload FROM cases WHERE source = ? AND source_message_id = ?",
                (source, source_message_id),
            ).fetchone()
    stored = json.loads(row["payload"]) if row else payload
    log_event(
        logger,
        "storage_append_case",
        case_id=stored.get("id", payload["id"]),
        source=source,
        source_message_id=source_message_id or "",
        request_type=(stored.get("classification") or {}).get("request_type", ""),
        status=stored.get("status", ""),
        duplicate=stored.get("id") != payload["id"],
    )
    return stored


def update_case(case: CaseResult, *, source: str = "manual", source_message_id: str | None = None) -> dict[str, Any]:
    init_db()
    payload = case_to_dict(case, source=source, source_message_id=source_message_id)
    classification = payload.get("classification") or {}
    with connect() as conn:
        conn.execute(
            """
            UPDATE cases
            SET source = ?,
                source_message_id = ?,
                requester = ?,
                subject = ?,
                status = ?,
                request_type = ?,
                urgency = ?,
                confidence = ?,
                outbound_status = ?,
                created_at = ?,
                payload = ?
            WHERE id = ?
            """,
            (
                payload.get("source") or "manual",
                payload.get("source_message_id"),
                payload.get("requester"),
                payload.get("subject"),
                payload.get("status"),
                classification.get("request_type"),
                classification.get("urgency"),
                classification.get("confidence"),
                payload.get("outbound_status"),
                payload.get("created_at"),
                json.dumps(payload, ensure_ascii=False),
                payload["id"],
            ),
        )
        row = conn.execute("SELECT payload FROM cases WHERE id = ?", (payload["id"],)).fetchone()
    stored = json.loads(row["payload"]) if row else payload
    log_event(
        logger,
        "storage_update_case",
        case_id=stored.get("id", payload["id"]),
        source=source,
        source_message_id=source_message_id or "",
        request_type=(stored.get("classification") or {}).get("request_type", ""),
        status=stored.get("status", ""),
        outbound_status=stored.get("outbound_status", ""),
    )
    return stored


def list_cases(*, limit: int | None = None) -> list[dict[str, Any]]:
    init_db()
    sql = "SELECT payload FROM cases ORDER BY inserted_at DESC, created_at DESC"
    params: tuple[int, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def get_case(case_id: str) -> dict[str, Any] | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT payload FROM cases WHERE id = ?", (case_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


def case_exists(source: str, source_message_id: str) -> bool:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM cases WHERE source = ? AND source_message_id = ? LIMIT 1",
            (source, source_message_id),
        ).fetchone()
    return row is not None


def append_poll_error(error: dict[str, Any]) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO poll_errors (message_id, stage, error, detail, query)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                error.get("message_id"),
                error.get("stage") or "unknown",
                error.get("error") or "UnknownError",
                error.get("detail") or "",
                error.get("query") or "",
            ),
        )
        row = conn.execute("SELECT * FROM poll_errors WHERE id = ?", (cursor.lastrowid,)).fetchone()
    stored = dict(row) if row else error
    log_event(
        logger,
        "storage_append_poll_error",
        id=stored.get("id", ""),
        message_id=stored.get("message_id", ""),
        stage=stored.get("stage", ""),
        error=stored.get("error", ""),
    )
    return stored


def list_poll_errors(*, limit: int = 50, unresolved_only: bool = True) -> list[dict[str, Any]]:
    init_db()
    where = "WHERE resolved = 0" if unresolved_only else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM poll_errors {where} ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def resolve_poll_errors_for_message(message_id: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute("UPDATE poll_errors SET resolved = 1 WHERE message_id = ?", (message_id,))
    log_event(logger, "storage_resolve_poll_errors", message_id=message_id)


def storage_status() -> dict[str, Any]:
    init_db()
    path = database_path()
    with connect() as conn:
        case_count = conn.execute("SELECT COUNT(*) AS count FROM cases").fetchone()["count"]
        error_count = conn.execute("SELECT COUNT(*) AS count FROM poll_errors WHERE resolved = 0").fetchone()["count"]
    return {
        "backend": "sqlite",
        "path": str(path),
        "case_count": int(case_count),
        "open_poll_errors": int(error_count),
    }


class CaseRepository:
    """SQLite-backed persistence for processed mailbox cases and poll errors."""

    def append_case(self, case: CaseResult, *, source: str = "gmail", source_message_id: str | None = None) -> dict[str, Any]:
        return append_case(case, source=source, source_message_id=source_message_id)

    def update_case(self, case: CaseResult, *, source: str = "gmail", source_message_id: str | None = None) -> dict[str, Any]:
        return update_case(case, source=source, source_message_id=source_message_id)

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        return get_case(case_id)

    def list_cases(self, *, limit: int | None = 200) -> list[dict[str, Any]]:
        return list_cases(limit=limit)

    def case_exists(self, source: str, source_message_id: str) -> bool:
        return case_exists(source, source_message_id)

    def append_poll_error(self, error: dict[str, Any]) -> dict[str, Any]:
        return append_poll_error(error)

    def list_poll_errors(self, *, limit: int = 50, unresolved_only: bool = True) -> list[dict[str, Any]]:
        return list_poll_errors(limit=limit, unresolved_only=unresolved_only)

    def resolve_poll_errors_for_message(self, message_id: str) -> None:
        resolve_poll_errors_for_message(message_id)

    def status(self) -> dict[str, Any]:
        return storage_status()
