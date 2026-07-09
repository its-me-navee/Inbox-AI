"""Application and production runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.common.environment import load_env

DEFAULT_GMAIL_POLL_QUERY = "in:inbox newer_than:1d"
DEFAULT_API_BASE_URL = "http://localhost:8501"
DEFAULT_OAUTH_SUCCESS_REDIRECT_URL = "http://localhost:8502"
DEFAULT_DATA_DIR = "data"
DEFAULT_MANAGER_EMAIL = "navee4501@gmail.com"
DEFAULT_SUPERVISOR_EMAIL = "navee4501@gmail.com"
DEFAULT_OPS_LEAD_EMAIL = "navee4501@gmail.com"
DEFAULT_DOCK_PLANNING_EMAIL = "navee4501@gmail.com"


def env_str(name: str, default: str = "") -> str:
    load_env()
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip() or default


def env_bool(name: str, default: bool = False) -> bool:
    load_env()
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    load_env()
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    load_env()
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class AppSettings:
    dry_run: bool
    auto_send_enabled: bool
    auto_send_general_enquiry: bool
    auto_send_service_request: bool
    min_send_confidence: float
    gmail_poll_query: str
    poll_interval_seconds: int
    poll_max_results: int
    auto_poll_enabled: bool
    api_base_url: str
    oauth_success_redirect_url: str
    data_dir: str
    db_path: str
    manager_email: str
    supervisor_email: str
    ops_lead_email: str
    dock_planning_email: str


def dry_run_enabled() -> bool:
    return env_bool("INBOX_AI_DRY_RUN", False)


def app_settings() -> AppSettings:
    load_env()
    return AppSettings(
        dry_run=dry_run_enabled(),
        auto_send_enabled=env_bool("AUTO_SEND_ENABLED", False),
        auto_send_general_enquiry=env_bool("AUTO_SEND_GENERAL_ENQUIRY", True),
        auto_send_service_request=env_bool("AUTO_SEND_SERVICE_REQUEST", True),
        min_send_confidence=env_float("MIN_SEND_CONFIDENCE", 0.8),
        gmail_poll_query=env_str("GMAIL_POLL_QUERY", DEFAULT_GMAIL_POLL_QUERY),
        poll_interval_seconds=env_int("GMAIL_POLL_INTERVAL_SECONDS", 60),
        poll_max_results=env_int("GMAIL_POLL_MAX_RESULTS", 10),
        auto_poll_enabled=env_bool("GMAIL_AUTO_POLL_ENABLED", True),
        api_base_url=env_str("INBOX_AI_API_BASE", DEFAULT_API_BASE_URL).rstrip("/"),
        oauth_success_redirect_url=env_str("GMAIL_OAUTH_SUCCESS_REDIRECT_URL", DEFAULT_OAUTH_SUCCESS_REDIRECT_URL),
        data_dir=env_str("INBOX_AI_DATA_DIR", DEFAULT_DATA_DIR),
        db_path=env_str("INBOX_AI_DB_PATH", ""),
        manager_email=env_str("INBOX_AI_MANAGER_EMAIL", DEFAULT_MANAGER_EMAIL),
        supervisor_email=env_str("INBOX_AI_SUPERVISOR_EMAIL", DEFAULT_SUPERVISOR_EMAIL),
        ops_lead_email=env_str("INBOX_AI_OPS_LEAD_EMAIL", DEFAULT_OPS_LEAD_EMAIL),
        dock_planning_email=env_str("INBOX_AI_DOCK_PLANNING_EMAIL", DEFAULT_DOCK_PLANNING_EMAIL),
    )


def public_settings() -> dict[str, object]:
    settings = app_settings()
    return {
        "dry_run": settings.dry_run,
        "auto_send_enabled": settings.auto_send_enabled,
        "auto_send_general_enquiry": settings.auto_send_general_enquiry,
        "auto_send_service_request": settings.auto_send_service_request,
        "min_send_confidence": settings.min_send_confidence,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "poll_max_results": settings.poll_max_results,
        "auto_poll_enabled": settings.auto_poll_enabled,
        "gmail_poll_query": settings.gmail_poll_query,
        "api_base_url": settings.api_base_url,
        "data_dir": settings.data_dir,
        "db_path": settings.db_path,
        "manager_email": settings.manager_email,
        "supervisor_email": settings.supervisor_email,
        "ops_lead_email": settings.ops_lead_email,
        "dock_planning_email": settings.dock_planning_email,
    }
