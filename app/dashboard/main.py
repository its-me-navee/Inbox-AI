from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st

from app.common.gmail import credentials_configured, gmail_authorization_url, oauth_token_path
from app.common.polling import poll_gmail_once
from app.common.settings import app_settings
from app.common.storage import list_cases
from app.dashboard.ui.case_views import case_from_record, is_dashboard_visible_case
from app.dashboard.ui.components import render_app_hero
from app.dashboard.ui.styles import APP_CSS
from app.dashboard.ui.tabs import (
    render_inbox_tab,
    render_metrics_tab,
    render_replies_tab,
    render_review_tab,
    render_routed_tab,
    render_setup_tab,
    render_workflow_tab,
)

def gmail_poll_settings() -> tuple[int, str | None, int, bool]:
    settings = app_settings()
    query = settings.gmail_poll_query.strip() or None
    return settings.poll_max_results, query, settings.poll_interval_seconds, settings.auto_poll_enabled


def execute_gmail_poll(*, max_results: int | None = None, query: str | None = None) -> dict[str, Any]:
    default_max, default_query, _, _ = gmail_poll_settings()
    result = poll_gmail_once(
        max_results=max_results if max_results is not None else default_max,
        query=query if query is not None else default_query,
    )
    if result["status"] in {"credentials_required", "authorization_required"} or result.get("failed"):
        st.session_state.last_poll_problem = result
    else:
        st.session_state.pop("last_poll_problem", None)
    return result


def mailbox_ready_for_poll() -> bool:
    return credentials_configured() and oauth_token_path().exists()


def poll_success_message(result: dict[str, Any]) -> str:
    return (
        f"Checked {result.get('fetched', 0)} messages · added {result.get('processed', 0)} new cases · "
        f"already seen {result.get('skipped', 0)}"
    )


def queue_poll_toast(result: dict[str, Any]) -> None:
    st.session_state.poll_toast = result


def render_poll_toast() -> None:
    result = st.session_state.pop("poll_toast", None)
    if not result:
        return
    if result["status"] in {"credentials_required", "authorization_required"}:
        return
    if result.get("failed"):
        return
    if result.get("processed", 0) or result.get("skipped", 0):
        st.toast(poll_success_message(result))
    else:
        st.toast("No new Gmail messages.")


def render_poll_status(result: dict[str, Any] | None) -> None:
    if not result:
        return
    if result["status"] in {"credentials_required", "authorization_required"}:
        st.warning("Connect Gmail before syncing.")
    elif result.get("failed"):
        st.error(f"{result['failed']} message(s) failed.")


@st.fragment(run_every=timedelta(seconds=10))
def auto_poll_fragment() -> None:
    settings = app_settings()
    if not settings.auto_poll_enabled:
        return
    if not mailbox_ready_for_poll():
        return
    interval = max(10, settings.poll_interval_seconds)
    now = time.time()
    if now - st.session_state.get("last_auto_poll_at", 0.0) < interval:
        return
    st.session_state.last_auto_poll_at = now
    max_results, query, _, _ = gmail_poll_settings()
    result = execute_gmail_poll(max_results=max_results, query=query)
    if result.get("processed", 0) > 0:
        st.rerun()


def load_case_records() -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for record in list_cases():
        try:
            case = case_from_record(record)
            if not is_dashboard_visible_case(case):
                continue
            valid.append(record)
        except Exception:
            continue
    return valid


def render_main_poll_action() -> None:
    if mailbox_ready_for_poll():
        if st.button("Poll Gmail", type="primary"):
            with st.spinner("Polling Gmail..."):
                result = execute_gmail_poll()
            queue_poll_toast(result)
            st.session_state.last_auto_poll_at = time.time()
            st.rerun()
    elif credentials_configured():
        try:
            url, _ = gmail_authorization_url()
            st.link_button("Connect Gmail", url, type="primary")
        except Exception as exc:
            st.error(f"OAuth error: {exc.__class__.__name__}")
    else:
        st.warning("OAuth credentials are not configured.")
    render_poll_status(st.session_state.get("last_poll_problem"))


st.set_page_config(page_title="Inbox AI · Manager Assistant", layout="wide", initial_sidebar_state="collapsed")
st.markdown(APP_CSS, unsafe_allow_html=True)
render_poll_toast()

if st.query_params.get("gmail") == "connected":
    try:
        st.query_params.clear()
    except Exception:
        pass

records = load_case_records()
needs_human = sum(1 for r in records if r.get("status") == "Needs Human")

render_app_hero(len(records), needs_human)
render_main_poll_action()

t1, t2, t3, t4, t5, t6, t7 = st.tabs(
    ["Inbox Queue", "Manager Review", "Routed", "Assistant Replies", "Metrics", "Workflow", "Setup"]
)
with t1:
    render_inbox_tab(records)
with t2:
    render_review_tab(records)
with t3:
    render_routed_tab(records)
with t4:
    render_replies_tab(records)
with t5:
    render_metrics_tab(records)
with t6:
    render_workflow_tab()
with t7:
    render_setup_tab()

# Poll after the dashboard has already rendered so the first load isn't
# blocked behind a synchronous Gmail sync + classification pass.
if (
    gmail_poll_settings()[3]
    and mailbox_ready_for_poll()
    and not st.session_state.get("initial_poll_done")
):
    st.session_state.initial_poll_done = True
    with st.spinner("Syncing Gmail inbox…"):
        result = execute_gmail_poll()
    if result.get("processed", 0) or result.get("skipped", 0):
        st.rerun()

auto_poll_fragment()
