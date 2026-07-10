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
    display_outbound_reason,
    display_internal_forward_status,
    filtered_records,
    is_auto_reply_candidate,
    is_human_review_case,
    mark_case_resolved,
    render_branch_output_summary,
    render_case_detail,
    render_reply_workspace,
    render_review_workspace,
    sort_records_by_recent,
    sort_records_by_urgency,
    team_forward_target,
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
ACTIVE_ROUTED_KEY = "active_routed_case_id"
REVIEW_SEND_RESULT_KEY = "review_send_result"
ACTIVE_INBOX_KEY = "active_inbox_case_id"
INBOX_RESOLVE_RESULT_KEY = "inbox_resolve_result"
ACTIVE_REPLY_KEY = "active_reply_case_id"
ACTIVE_SENT_REPLY_KEY = "active_sent_reply_case_id"
FLASH_TTL_SECONDS = 3.0
ROUTED_STATUS = "Routed"
CONFIRM_REVIEW_STATUSES = {"Resolved", "No Action Closed"}
INBOX_SORT_RECENT = "Recent first"
INBOX_SORT_URGENCY = "Urgency first"
INBOX_SORT_OPTIONS = (INBOX_SORT_RECENT, INBOX_SORT_URGENCY)


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


def close_routed_dialog() -> None:
    st.session_state.pop(ACTIVE_ROUTED_KEY, None)


def close_reply_dialog() -> None:
    st.session_state.pop(ACTIVE_REPLY_KEY, None)


def close_sent_reply_dialog() -> None:
    st.session_state.pop(ACTIVE_SENT_REPLY_KEY, None)


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


def render_routed_case_dialog(record: dict[str, Any]) -> None:
    @st.dialog("Routed case", width="large", on_dismiss=close_routed_dialog)
    def _dialog() -> None:
        case = case_from_record(record)
        st.markdown(f"### {compact_subject(case.subject, 90)}")
        st.divider()
        render_case_detail(case, record, show_title=False)

    _dialog()


def render_reply_case_dialog(record: dict[str, Any]) -> None:
    @st.dialog("Assistant reply", width="large", on_dismiss=close_reply_dialog)
    def _dialog() -> None:
        case = case_from_record(record)
        st.markdown(f"### {compact_subject(case.subject, 90)}")
        render_branch_output_summary(case)
        st.caption(display_outbound_reason(case) or "Acknowledgement is ready for review.")
        st.divider()
        render_case_detail(case, record, show_summary=False, show_title=False)
        st.divider()
        st.markdown("#### Assistant reply")
        render_reply_workspace(case, record)

    _dialog()


def render_sent_reply_case_dialog(record: dict[str, Any]) -> None:
    @st.dialog("Sent acknowledgement", width="large", on_dismiss=close_sent_reply_dialog)
    def _dialog() -> None:
        case = case_from_record(record)
        st.markdown(f"### {compact_subject(case.subject, 90)}")
        render_branch_output_summary(case)
        st.caption(display_outbound_reason(case) or "Acknowledgement was sent.")
        st.divider()
        render_case_detail(case, record, show_summary=False, show_title=False)

    _dialog()


def inbox_table_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return records


def sort_inbox_records(records: list[dict[str, Any]], sort_mode: str) -> list[dict[str, Any]]:
    if sort_mode == INBOX_SORT_URGENCY:
        return sort_records_by_urgency(records)
    return sort_records_by_recent(records)


def render_inbox_tab(records: list[dict[str, Any]]) -> None:
    render_metrics_row(records)
    st.divider()
    inbox_records = inbox_table_records(records)
    fc = st.columns([0.21, 0.21, 0.32, 0.16, 0.1])
    statuses = sorted({str(r.get("status")) for r in inbox_records if r.get("status")})
    types = sorted({str((r.get("classification") or {}).get("request_type")) for r in inbox_records if (r.get("classification") or {}).get("request_type")})
    sel_status = fc[0].multiselect("Status", statuses, placeholder="All", format_func=status_label)
    sel_type = fc[1].multiselect("Type", types, placeholder="All", format_func=type_label)
    search = fc[2].text_input("Search", placeholder="Subject, requester, body…")
    sort_mode = fc[3].selectbox("Sort", INBOX_SORT_OPTIONS)
    if fc[4].button("Refresh", width="stretch"):
        st.rerun()

    visible = sort_inbox_records(
        filtered_records(inbox_records, statuses=sel_status, request_types=sel_type, search=search),
        sort_mode,
    )
    if not records:
        render_empty_state("No cases yet", "Sync Gmail to let the assistant classify incoming requests.")
        return

    resolve_result = pop_flash(INBOX_RESOLVE_RESULT_KEY)
    if resolve_result:
        st.success(resolve_result)
        clear_flash_after_delay(INBOX_RESOLVE_RESULT_KEY)

    st.caption(f"{len(visible)} of {len(inbox_records)} inbox cases. Manager-confirmed cases leave this dashboard.")
    if not inbox_records:
        render_empty_state("Inbox queue clear", "Synced mailbox cases appear here.")
    elif not visible:
        st.caption("No cases match the current filters.")
    else:
        render_inbox_queue(visible)

    active_case_id = st.session_state.get(ACTIVE_INBOX_KEY)
    if active_case_id:
        active_record = next((record for record in inbox_records if record.get("id") == active_case_id), None)
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

    for record in records:
        case = case_from_record(record)
        cols = st.columns([0.09, 0.18, 0.12, 0.12, 0.29, 0.12, 0.08])
        if cols[0].button("Open", key=f"inbox-open-{case.id}", width="stretch"):
            st.session_state[ACTIVE_INBOX_KEY] = case.id
            st.rerun()
        button_label = inbox_resolution_action_label(case.status)
        confirming_review = button_label == "Confirm reviewed"
        if cols[1].button(button_label, key=f"inbox-resolve-{case.id}", width="stretch"):
            reason = "Manager confirmed review from Inbox Queue" if confirming_review else "Manager marked as resolved from Inbox Queue"
            mark_case_resolved(case, record, reason=reason)
            close_inbox_dialog()
            message = "Review confirmed. Mail history was kept." if confirming_review else "Marked as resolved. No mail was sent."
            set_flash(INBOX_RESOLVE_RESULT_KEY, message)
            st.rerun()
        cols[2].write(case.classification.urgency)
        cols[3].write(type_label(case.classification.request_type))
        cols[4].write(compact_subject(case.subject, 78))
        render_requester_email(cols[5], case.requester)
        cols[6].write(status_label(case.status))


def inbox_resolution_action_label(status: str) -> str:
    return "Confirm reviewed" if status in CONFIRM_REVIEW_STATUSES else "Mark as resolved"


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
        if cols[0].button("Let's review", key=f"review-open-{case.id}", width="stretch"):
            st.session_state[ACTIVE_REVIEW_KEY] = case.id
            st.rerun()
        cols[1].write(case.classification.urgency)
        cols[2].write(type_label(case.classification.request_type))
        cols[3].write(status_label(case.status))
        cols[4].write(compact_subject(case.subject, 70))
        render_requester_email(cols[5], case.requester)


def render_routed_tab(records: list[dict[str, Any]]) -> None:
    routed = [record for record in records if record.get("status") == ROUTED_STATUS]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Routed", len(routed))
    c2.metric("Team forward sent", sum(1 for r in routed if case_from_record(r).internal_notification_status == "sent"))
    c3.metric("Needs team forward", sum(1 for r in routed if case_from_record(r).internal_notification_status != "sent"))
    c4.metric("SLA tracked", sum(1 for r in routed if case_from_record(r).sla_due_at))
    st.divider()

    if not routed:
        render_empty_state("No routed cases", "Service requests routed to operations teams appear here.")
        return

    fc = st.columns([0.42, 0.18, 0.18, 0.12])
    search = fc[0].text_input("Search routed", placeholder="Subject, requester, body…")
    forward_filter = fc[1].selectbox("Team forward", ["All", "Sent", "Needs send"], key="routed-forward-filter")
    sla_filter = fc[2].selectbox("SLA", ["All", "With SLA", "Missing SLA"], key="routed-sla-filter")
    if fc[3].button("Refresh", width="stretch", key="routed-refresh"):
        st.rerun()

    visible = filtered_records(routed, statuses=[], request_types=[], search=search)
    if forward_filter == "Sent":
        visible = [r for r in visible if case_from_record(r).internal_notification_status == "sent"]
    elif forward_filter == "Needs send":
        visible = [r for r in visible if case_from_record(r).internal_notification_status != "sent"]
    if sla_filter == "With SLA":
        visible = [r for r in visible if case_from_record(r).sla_due_at]
    elif sla_filter == "Missing SLA":
        visible = [r for r in visible if not case_from_record(r).sla_due_at]

    if not visible:
        st.caption("No routed cases match the current filters.")
    else:
        render_routed_queue(visible)

    active_case_id = st.session_state.get(ACTIVE_ROUTED_KEY)
    if active_case_id:
        selected = next((record for record in routed if record.get("id") == active_case_id), None)
        if selected:
            render_routed_case_dialog(selected)
        else:
            close_routed_dialog()


def render_routed_queue(records: list[dict[str, Any]]) -> None:
    st.caption(f"{len(records)} routed case(s). Open one to monitor SLA and team-forward delivery.")
    header = st.columns([0.09, 0.14, 0.16, 0.16, 0.30, 0.15])
    header[0].markdown("**Open**")
    header[1].markdown("**SLA due**")
    header[2].markdown("**Team**")
    header[3].markdown("**Forward**")
    header[4].markdown("**Subject**")
    header[5].markdown("**Requester**")

    for record in sort_records_by_urgency(records):
        case = case_from_record(record)
        target = team_forward_target(case)
        team_label = target[1] if target else "-"
        cols = st.columns([0.09, 0.14, 0.16, 0.16, 0.30, 0.15])
        if cols[0].button("Open", key=f"routed-open-{case.id}", width="stretch"):
            st.session_state[ACTIVE_ROUTED_KEY] = case.id
            st.rerun()
        cols[1].write(case.sla_due_at or "-")
        cols[2].write(team_label)
        cols[3].write(display_internal_forward_status(case))
        cols[4].write(compact_subject(case.subject, 70))
        render_requester_email(cols[5], case.requester)


def is_sent_reply_record(record: dict[str, Any]) -> bool:
    case = case_from_record(record)
    return bool(case.customer_output.strip()) and case.outbound_status == "sent"


def is_held_reply_record(record: dict[str, Any]) -> bool:
    case = case_from_record(record)
    return bool(case.customer_output.strip()) and case.outbound_status == "not_sent" and not is_auto_reply_candidate(case)


def render_replies_tab(records: list[dict[str, Any]]) -> None:
    candidates = [r for r in records if is_auto_reply_candidate(case_from_record(r))]
    sent_records = [r for r in records if is_sent_reply_record(r)]
    held_records = [r for r in records if is_held_reply_record(r)]
    active_case_id = st.session_state.get(ACTIVE_REPLY_KEY)
    active_record = next((record for record in records if record.get("id") == active_case_id), None)
    if active_record and not is_auto_reply_candidate(case_from_record(active_record)):
        active_record = None
    if active_case_id and not active_record:
        close_reply_dialog()
    active_sent_id = st.session_state.get(ACTIVE_SENT_REPLY_KEY)
    active_sent_record = next((record for record in sent_records if record.get("id") == active_sent_id), None)
    if active_sent_id and not active_sent_record:
        close_sent_reply_dialog()

    c1, c2, c3 = st.columns(3)
    c1.metric("Ready replies", len(candidates))
    c2.metric("Sent", len(sent_records))
    c3.metric("Held", len(held_records))
    st.caption("Assistant acknowledgements prepared, sent, or held for safe outbound handling.")
    st.divider()
    if not candidates and not sent_records and not active_record and not active_sent_record:
        render_empty_state("No assistant replies", "Resolved enquiries and routed service requests with generated replies appear here.")
        return

    if candidates:
        st.markdown("#### Ready to send")
        render_replies_queue(candidates)
    if sent_records:
        st.markdown("#### Sent acknowledgements")
        render_sent_replies_queue(sent_records)
    if active_record:
        render_reply_case_dialog(active_record)
    if active_sent_record:
        render_sent_reply_case_dialog(active_sent_record)


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
        if cols[0].button("Open", key=f"reply-open-{case.id}", width="stretch"):
            st.session_state[ACTIVE_REPLY_KEY] = case.id
            st.rerun()
        cols[1].write(case.classification.urgency)
        cols[2].write(type_label(case.classification.request_type))
        cols[3].write(compact_subject(case.subject, 78))
        render_requester_email(cols[4], case.requester)
        cols[5].write(status_label(case.status))


def render_sent_replies_queue(records: list[dict[str, Any]]) -> None:
    st.caption(f"{len(records)} sent acknowledgement{'s' if len(records) != 1 else ''}. Open one to verify the sent mail history.")
    header = st.columns([0.09, 0.12, 0.16, 0.34, 0.17, 0.12])
    header[0].markdown("**Open**")
    header[1].markdown("**Urgency**")
    header[2].markdown("**Type**")
    header[3].markdown("**Subject**")
    header[4].markdown("**Requester**")
    header[5].markdown("**Mail**")

    for record in sort_records_by_urgency(records):
        case = case_from_record(record)
        cols = st.columns([0.09, 0.12, 0.16, 0.34, 0.17, 0.12])
        if cols[0].button("Open", key=f"sent-reply-open-{case.id}", width="stretch"):
            st.session_state[ACTIVE_SENT_REPLY_KEY] = case.id
            st.rerun()
        cols[1].write(case.classification.urgency)
        cols[2].write(type_label(case.classification.request_type))
        cols[3].write(compact_subject(case.subject, 78))
        render_requester_email(cols[4], case.requester)
        cols[5].write("Sent")


def render_count_table(title: str, counts: dict[str, int]) -> None:
    st.markdown(f"##### {title}")
    rows = [{"Label": key, "Cases": value} for key, value in sorted(counts.items()) if value > 0]
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption("No data yet.")


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
        render_count_table("Volume by request type", by_type)
    with cr:
        render_count_table("Volume by status", by_status)
    st.dataframe(
        [{"Urgency": key, "Cases": value} for key, value in sorted(by_urgency.items())],
        hide_index=True,
        width="stretch",
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
        save = c1.form_submit_button("Save setup", width="stretch", type="primary")
        reset = c2.form_submit_button("Reset session setup", width="stretch")

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
