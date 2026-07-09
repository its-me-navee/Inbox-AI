"""Tab renderers for the manager dashboard."""

from __future__ import annotations

import os
import re
import time
from html import escape
from typing import Any

import streamlit as st

from app.common.settings import app_settings
from app.dashboard.ui.case_views import (
    case_from_record,
    compact_subject,
    filtered_records,
    is_auto_reply_candidate,
    is_human_review_case,
    mark_case_resolved,
    render_branch_output_summary,
    render_case_detail,
    render_reply_workspace,
    render_review_workspace,
    sort_records_by_urgency,
)
from app.dashboard.ui.components import (
    render_empty_state,
    render_metrics_row,
    render_ops_metrics,
    render_remediation_table,
    render_workflow_diagram,
    status_label,
    type_label,
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROUTING_ENV_KEYS = {
    "manager_email": "INBOX_AI_MANAGER_EMAIL",
    "supervisor_email": "INBOX_AI_SUPERVISOR_EMAIL",
    "ops_lead_email": "INBOX_AI_OPS_LEAD_EMAIL",
    "dock_planning_email": "INBOX_AI_DOCK_PLANNING_EMAIL",
}
ACTIVE_REVIEW_KEY = "active_review_case_id"
REVIEW_SEND_RESULT_KEY = "review_send_result"
ACTIVE_INBOX_KEY = "active_inbox_case_id"
INBOX_RESOLVE_RESULT_KEY = "inbox_resolve_result"
ACTIVE_REPLY_KEY = "active_reply_case_id"
FLASH_TTL_SECONDS = 3.0
RESOLVED_STATUS = "Resolved"


def render_requester_email(column: Any, requester: str) -> None:
    safe_value = escape(requester.strip() or "unknown")
    column.markdown(f'<span class="requester-email">{safe_value}</span>', unsafe_allow_html=True)


def set_flash(key: str, payload: Any) -> None:
    st.session_state[key] = {"payload": payload, "expires_at": time.time() + FLASH_TTL_SECONDS}


def pop_flash(key: str) -> Any | None:
    value = st.session_state.get(key)
    if not isinstance(value, dict) or "expires_at" not in value:
        return st.session_state.pop(key, None)
    if time.time() >= float(value["expires_at"]):
        st.session_state.pop(key, None)
        return None
    return value.get("payload")


def clear_flash_after_delay(key: str) -> None:
    time.sleep(FLASH_TTL_SECONDS)
    st.session_state.pop(key, None)
    st.rerun()


def close_inbox_dialog() -> None:
    st.session_state.pop(ACTIVE_INBOX_KEY, None)


def close_review_dialog() -> None:
    st.session_state.pop(ACTIVE_REVIEW_KEY, None)


def close_reply_dialog() -> None:
    st.session_state.pop(ACTIVE_REPLY_KEY, None)


def render_inbox_case_dialog(record: dict[str, Any]) -> None:
    @st.dialog("Inbox case details", width="large", on_dismiss=close_inbox_dialog)
    def _dialog() -> None:
        case = case_from_record(record)
        st.markdown(f"### {compact_subject(case.subject, 90)}")
        st.divider()
        render_case_detail(case, record, show_title=False)

    _dialog()


def render_review_case_dialog(record: dict[str, Any]) -> None:
    @st.dialog("Manager review", width="large", on_dismiss=close_review_dialog)
    def _dialog() -> None:
        case = case_from_record(record)
        st.markdown(f"### {compact_subject(case.subject, 90)}")
        st.divider()
        render_review_workspace(case, record, show_title=False, return_to_queue_on_send=True)

    _dialog()


def render_reply_case_dialog(record: dict[str, Any]) -> None:
    @st.dialog("Assistant reply", width="large", on_dismiss=close_reply_dialog)
    def _dialog() -> None:
        case = case_from_record(record)
        st.markdown(f"### {compact_subject(case.subject, 90)}")
        render_branch_output_summary(case)
        st.caption(case.outbound_reason or "Eligible for mailbox auto-reply when policy allows.")
        st.divider()
        render_case_detail(case, record, show_summary=False, show_title=False)
        st.divider()
        st.markdown("#### Assistant reply")
        render_reply_workspace(case, record)

    _dialog()


def inbox_table_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("status") != RESOLVED_STATUS]


def render_inbox_tab(records: list[dict[str, Any]]) -> None:
    render_metrics_row(records)
    st.divider()
    active_records = inbox_table_records(records)
    fc = st.columns([0.25, 0.25, 0.4, 0.1])
    statuses = sorted({str(r.get("status")) for r in active_records if r.get("status")})
    types = sorted({str((r.get("classification") or {}).get("request_type")) for r in active_records if (r.get("classification") or {}).get("request_type")})
    sel_status = fc[0].multiselect("Status", statuses, placeholder="All", format_func=status_label)
    sel_type = fc[1].multiselect("Type", types, placeholder="All", format_func=type_label)
    search = fc[2].text_input("Search", placeholder="Subject, requester, body…")
    if fc[3].button("Refresh", use_container_width=True):
        st.rerun()

    visible = filtered_records(active_records, statuses=sel_status, request_types=sel_type, search=search)
    if not records:
        render_empty_state("No cases yet", "Sync Gmail to let the assistant classify incoming requests.")
        return

    resolve_result = pop_flash(INBOX_RESOLVE_RESULT_KEY)
    if resolve_result:
        st.success(resolve_result)
        clear_flash_after_delay(INBOX_RESOLVE_RESULT_KEY)

    resolved_count = len(records) - len(active_records)
    st.caption(f"{len(visible)} of {len(active_records)} active cases. {resolved_count} marked as resolved counted above.")
    if not active_records:
        render_empty_state("Inbox queue clear", "Marked-as-resolved cases are counted in the dashboard metrics.")
    elif not visible:
        st.caption("No cases match the current filters.")
    else:
        render_inbox_queue(visible)

    active_case_id = st.session_state.get(ACTIVE_INBOX_KEY)
    if active_case_id:
        active_record = next((record for record in active_records if record.get("id") == active_case_id), None)
        if active_record:
            render_inbox_case_dialog(active_record)
        else:
            close_inbox_dialog()


def render_inbox_queue(records: list[dict[str, Any]]) -> None:
    header = st.columns([0.09, 0.18, 0.12, 0.12, 0.29, 0.12, 0.08])
    header[0].markdown("**Open**")
    header[1].markdown("**Resolution**")
    header[2].markdown("**Urgency**")
    header[3].markdown("**Type**")
    header[4].markdown("**Subject**")
    header[5].markdown("**Requester**")
    header[6].markdown("**Status**")

    for record in sort_records_by_urgency(records):
        if record.get("status") == RESOLVED_STATUS:
            continue
        case = case_from_record(record)
        cols = st.columns([0.09, 0.18, 0.12, 0.12, 0.29, 0.12, 0.08])
        if cols[0].button("Open", key=f"inbox-open-{case.id}", use_container_width=True):
            st.session_state[ACTIVE_INBOX_KEY] = case.id
            st.rerun()
        if cols[1].button("Mark as resolved", key=f"inbox-resolve-{case.id}", use_container_width=True):
            mark_case_resolved(case, record, reason="Manager marked as resolved from Inbox Queue")
            close_inbox_dialog()
            set_flash(INBOX_RESOLVE_RESULT_KEY, "Marked as resolved.")
            st.rerun()
        cols[2].write(case.classification.urgency)
        cols[3].write(type_label(case.classification.request_type))
        cols[4].write(compact_subject(case.subject, 78))
        render_requester_email(cols[5], case.requester)
        cols[6].write(status_label(case.status))


def render_review_tab(records: list[dict[str, Any]]) -> None:
    review = [r for r in records if is_human_review_case(case_from_record(r))]
    drafts = sum(1 for r in review if case_from_record(r).customer_output.strip())
    c1, c2, c3 = st.columns(3)
    c1.metric("Manager review", len(review))
    c2.metric("Drafts ready", drafts)
    c3.metric("Needs routing", len(review) - drafts)
    st.divider()

    send_result = pop_flash(REVIEW_SEND_RESULT_KEY)
    if send_result:
        ok, text = send_result
        (st.success if ok else st.error)(text)
        clear_flash_after_delay(REVIEW_SEND_RESULT_KEY)

    if not review:
        render_empty_state("Review queue clear", "Cases needing manager judgement appear here.")
        return

    view = st.radio("Filter", ["All", "With draft", "No draft"], horizontal=True, key="review-filter")
    if view == "With draft":
        visible = [r for r in review if case_from_record(r).customer_output.strip()]
    elif view == "No draft":
        visible = [r for r in review if not case_from_record(r).customer_output.strip()]
    else:
        visible = review

    if not visible:
        st.caption("No cases match this filter.")
        return

    render_review_queue(visible)

    active_case_id = st.session_state.get(ACTIVE_REVIEW_KEY)
    if active_case_id:
        selected = next((record for record in review if record.get("id") == active_case_id), None)
        if selected:
            render_review_case_dialog(selected)
        else:
            close_review_dialog()


def render_review_queue(records: list[dict[str, Any]]) -> None:
    st.caption(f"{len(records)} case(s) waiting. Choose one to review.")
    header = st.columns([0.12, 0.12, 0.16, 0.14, 0.32, 0.14])
    header[0].markdown("**Action**")
    header[1].markdown("**Urgency**")
    header[2].markdown("**Type**")
    header[3].markdown("**Status**")
    header[4].markdown("**Subject**")
    header[5].markdown("**Requester**")

    for record in sort_records_by_urgency(records):
        case = case_from_record(record)
        cols = st.columns([0.12, 0.12, 0.16, 0.14, 0.32, 0.14])
        if cols[0].button("Let's review", key=f"review-open-{case.id}", use_container_width=True):
            st.session_state[ACTIVE_REVIEW_KEY] = case.id
            st.rerun()
        cols[1].write(case.classification.urgency)
        cols[2].write(type_label(case.classification.request_type))
        cols[3].write(status_label(case.status))
        cols[4].write(compact_subject(case.subject, 70))
        render_requester_email(cols[5], case.requester)


def render_replies_tab(records: list[dict[str, Any]]) -> None:
    candidates = [r for r in records if is_auto_reply_candidate(case_from_record(r))]
    active_case_id = st.session_state.get(ACTIVE_REPLY_KEY)
    active_record = next((record for record in records if record.get("id") == active_case_id), None)
    if active_case_id and not active_record:
        close_reply_dialog()

    c1, c2, c3 = st.columns(3)
    c1.metric("Ready replies", len(candidates))
    c2.metric("Sent", sum(1 for r in candidates if r.get("outbound_status") == "sent"))
    c3.metric("Held", sum(1 for r in candidates if r.get("outbound_status") == "not_sent"))
    st.caption("Assistant replies prepared for safe outbound handling when mail sending is enabled.")
    st.divider()
    if not candidates and not active_record:
        render_empty_state("No assistant replies", "Resolved enquiries and routed service requests with generated replies appear here.")
        return

    if candidates:
        render_replies_queue(candidates)
    if active_record:
        render_reply_case_dialog(active_record)


def render_replies_queue(records: list[dict[str, Any]]) -> None:
    st.caption(f"{len(records)} assistant repl{'y' if len(records) == 1 else 'ies'} ready. Open one to inspect or send.")
    header = st.columns([0.09, 0.12, 0.16, 0.34, 0.17, 0.12])
    header[0].markdown("**Open**")
    header[1].markdown("**Urgency**")
    header[2].markdown("**Type**")
    header[3].markdown("**Subject**")
    header[4].markdown("**Requester**")
    header[5].markdown("**Status**")

    for record in sort_records_by_urgency(records):
        case = case_from_record(record)
        cols = st.columns([0.09, 0.12, 0.16, 0.34, 0.17, 0.12])
        if cols[0].button("Open", key=f"reply-open-{case.id}", use_container_width=True):
            st.session_state[ACTIVE_REPLY_KEY] = case.id
            st.rerun()
        cols[1].write(case.classification.urgency)
        cols[2].write(type_label(case.classification.request_type))
        cols[3].write(compact_subject(case.subject, 78))
        render_requester_email(cols[4], case.requester)
        cols[5].write(status_label(case.status))


def render_metrics_tab(records: list[dict[str, Any]]) -> None:
    render_ops_metrics(records, case_from_record=case_from_record)
    st.divider()
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_urgency: dict[str, int] = {}
    for record in records:
        case = case_from_record(record)
        status = status_label(case.status)
        request_type = type_label(case.classification.request_type)
        by_status[status] = by_status.get(status, 0) + 1
        by_type[request_type] = by_type.get(request_type, 0) + 1
        by_urgency[case.classification.urgency] = by_urgency.get(case.classification.urgency, 0) + 1
    cl, cr = st.columns(2)
    with cl:
        st.markdown("##### Volume by request type")
        if by_type:
            st.bar_chart(by_type, use_container_width=True)
    with cr:
        st.markdown("##### Volume by status")
        if by_status:
            st.bar_chart(by_status, use_container_width=True)
    st.dataframe(
        [{"Urgency": key, "Cases": value} for key, value in sorted(by_urgency.items())],
        hide_index=True,
        use_container_width=True,
    )

def render_workflow_tab() -> None:
    render_workflow_diagram()
    render_remediation_table()
    st.caption("The assistant follows this workflow for each synced Gmail message.")


def _valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match(value.strip()))


def render_setup_tab() -> None:
    settings = app_settings()
    st.markdown("#### Routing setup")
    st.caption("These addresses are used for new cases created during this dashboard session.")
    with st.form("routing-setup-form"):
        manager_email = st.text_input("Manager review inbox", value=settings.manager_email)
        supervisor_email = st.text_input("Supervisor escalation inbox", value=settings.supervisor_email)
        ops_lead_email = st.text_input("Operations lead inbox", value=settings.ops_lead_email)
        dock_planning_email = st.text_input("Dock planning inbox", value=settings.dock_planning_email)
        c1, c2 = st.columns([0.5, 0.5])
        save = c1.form_submit_button("Save setup", use_container_width=True, type="primary")
        reset = c2.form_submit_button("Reset session setup", use_container_width=True)

    if reset:
        for key in ROUTING_ENV_KEYS.values():
            os.environ.pop(key, None)
        st.success("Routing setup reset to .env/default values.")
        st.rerun()

    if save:
        values = {
            "manager_email": manager_email.strip(),
            "supervisor_email": supervisor_email.strip(),
            "ops_lead_email": ops_lead_email.strip(),
            "dock_planning_email": dock_planning_email.strip(),
        }
        invalid = [label.replace("_", " ") for label, value in values.items() if not _valid_email(value)]
        if invalid:
            st.error("Enter valid email addresses for: " + ", ".join(invalid))
            return
        for key, value in values.items():
            os.environ[ROUTING_ENV_KEYS[key]] = value
        st.success("Routing setup saved for this dashboard session.")
        st.rerun()

    current = app_settings()
    st.divider()
    st.markdown("##### Current routing")
    rows = [
        ("Manager review", current.manager_email, "Human review and failed workflow checks"),
        ("Supervisor escalation", current.supervisor_email, "Critical escalation notifications"),
        ("Operations lead", current.ops_lead_email, "Complaint escalation owner"),
        ("Dock planning", current.dock_planning_email, "Service request routing"),
    ]
    for role, email, purpose in rows:
        st.markdown(f"**{role}**  \n`{email}`  \n{purpose}")
