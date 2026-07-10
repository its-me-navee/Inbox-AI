from __future__ import annotations

import time
from dataclasses import fields
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import escape
from typing import Any

import streamlit as st

from app.common.gmail import (
    GmailMessage,
    build_gmail_service,
    clean_email_body,
    send_gmail_message,
    send_gmail_reply,
    validate_gmail_send_content,
)
from app.common.polling import internal_notification_body, internal_notification_subject, internal_notification_target
from app.common.storage import update_case
from app.dashboard.ui.components import status_chip, status_label, type_chip, type_label, urgency_chip
from app.core.workflow import (
    Action,
    AgentTrace,
    CaseResult,
    Classification,
    clean_customer_response_text,
    fmt_time,
    utc_now,
)

CASE_FIELDS = {field.name for field in fields(CaseResult)}
URGENCY_PRIORITY = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
MANAGER_CONFIRMABLE_STATUSES = {"Resolved", "No Action Closed"}


def case_from_record(record: dict[str, Any]) -> CaseResult:
    payload = {key: value for key, value in record.items() if key in CASE_FIELDS}
    payload["classification"] = Classification(**payload["classification"])
    payload["actions"] = [Action(**item) for item in payload.get("actions", [])]
    payload["agent_trace"] = [AgentTrace(**item) for item in payload.get("agent_trace", [])]
    return CaseResult(**payload)


def record_source(record: dict[str, Any]) -> str:
    return str(record.get("source") or "manual")


def record_source_message_id(record: dict[str, Any]) -> str | None:
    value = record.get("source_message_id")
    return str(value) if value else None


def save_case(case: CaseResult, record: dict[str, Any]) -> None:
    update_case(case, source=record_source(record), source_message_id=record_source_message_id(record))


def compact_subject(value: str, limit: int = 74) -> str:
    value = value.strip() or "(no subject)"
    return value if len(value) <= limit else f"{value[: limit - 1]}..."


def format_confidence(value: float) -> str:
    return f"{value:.0%}"


def queue_status_label(value: str) -> str:
    return status_label(value)


def reply_subject_text(subject: str) -> str:
    clean_subject = subject.strip() or "(no subject)"
    return clean_subject if clean_subject.lower().startswith("re:") else f"Re: {clean_subject}"


def clean_mail_view_text(value: str) -> str:
    return clean_email_body(value)


def clean_assistant_reply_view_text(value: str) -> str:
    return clean_customer_response_text(clean_email_body(value))


def render_readonly_mail_box(label: str, value: str, *, clean_text: bool = False, value_class: str = "") -> None:
    safe_label = escape(label)
    display_value = clean_mail_view_text(value) if clean_text else value.strip()
    safe_value = escape(display_value or "-")
    class_attr = f' class="{value_class}"' if value_class else ""
    st.markdown(
        f'<div class="mail-readonly"><div class="mail-readonly-label">{safe_label}</div>'
        f'<pre{class_attr}>{safe_value}</pre></div>',
        unsafe_allow_html=True,
    )


def urgency_rank(record: dict[str, Any]) -> int:
    classification = record.get("classification") or {}
    return URGENCY_PRIORITY.get(str(classification.get("urgency", "")), 99)


def sort_records_by_urgency(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=urgency_rank)


def record_received_text(record: dict[str, Any]) -> str:
    return str(record.get("received_at") or record.get("created_at") or "").strip()


def record_time_sort_key(record: dict[str, Any]) -> float:
    value = record_received_text(record)
    if not value:
        return float("-inf")
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return float("-inf")


def sort_records_by_recent(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=record_time_sort_key, reverse=True)


def selected_row_index(selected_rows: list[int], record_count: int) -> int:
    if not selected_rows:
        return 0
    index = selected_rows[0]
    return index if 0 <= index < record_count else 0


def select_record(records: list[dict[str, Any]], *, key: str, default_to_first: bool = True) -> dict[str, Any] | None:
    if not records:
        return None
    records = sort_records_by_urgency(records)
    rows = []
    for record in records:
        classification = record.get("classification") or {}
        rows.append(
            {
                "Status": queue_status_label(str(record.get("status", ""))),
                "Type": type_label(str(classification.get("request_type", ""))),
                "Urgency": classification.get("urgency", ""),
                "Subject": compact_subject(str(record.get("subject", "")), 56),
                "Requester": str(record.get("requester", "")),
            }
        )
    event = st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=key,
    )
    selected = list(event.selection["rows"]) if event and event.selection else []
    if not selected and not default_to_first:
        return None
    index = selected_row_index(selected, len(records))
    return records[index]


def manager_next_action(case: CaseResult) -> str:
    request_type = case.classification.request_type
    if case.status == "Needs Human":
        if request_type == "Escalation":
            return "Take ownership now. Review the supervisor alert and decide the immediate next step."
        if request_type == "Complaint":
            return "Review the complaint, assign an owner, and approve the acknowledgement."
        if case.customer_output.strip():
            return "Review the assistant draft, edit if needed, then send."
        return "Review the message and choose the correct branch."
    if request_type == "Service Request":
        return "Confirm the route and monitor the SLA."
    if request_type == "General Enquiry":
        return "No manager action needed unless the answer should be corrected."
    if request_type == "No Action":
        return "No manager action needed."
    return case.summary


def action_label(action: Action) -> str:
    if action.owner:
        return f"{action.step} ({action.owner})"
    return action.step


def render_branch_output_summary(case: CaseResult) -> None:
    col1, col2, col3 = st.columns([0.34, 0.34, 0.32])
    with col1:
        st.markdown("**Assistant decision**")
        chips = (
            type_chip(case.classification.request_type)
            + urgency_chip(case.classification.urgency)
            + status_chip(case.status)
        )
        st.markdown(chips, unsafe_allow_html=True)
        st.caption(f"Confidence {format_confidence(case.classification.confidence)}")
    with col2:
        st.markdown("**Manager focus**")
        st.write(manager_next_action(case))
        if case.follow_up_at:
            st.caption(f"Follow-up due: {case.follow_up_at}")
        if case.sla_due_at:
            st.caption(f"SLA due: {case.sla_due_at}")
        target = team_forward_target(case)
        if target:
            status = display_internal_forward_status(case)
            st.caption(f"Team forward: {status} -> {target[0]}")
    with col3:
        st.markdown("**Action plan**")
        if case.actions:
            for index, act in enumerate(case.actions, start=1):
                st.markdown(f"{index}. {action_label(act)}")
        else:
            st.caption("No action plan recorded.")


def operator_log_line(value: str) -> str:
    lower = value.lower()
    if lower.startswith("outbound reply sent:"):
        return "Outbound reply sent."
    if lower.startswith("internal notification sent to "):
        team_part = value.split("(", 1)[0].replace("Internal notification", "Team forward").strip()
        return f"{team_part}."
    for old, new in {
        "LLM/classifier produced tags:": "Tags assigned:",
        "Response sent in simulation": "Response recorded",
        "Outbound Gmail reply sent:": "Outbound reply sent:",
        "Gmail": "mailbox",
    }.items():
        value = value.replace(old, new)
    return value


def render_audit_timeline(case: CaseResult) -> None:
    rows: list[dict[str, str]] = []
    for item in case.log:
        rows.append({"Source": "Case log", "Detail": operator_log_line(item)})
    for step in case.agent_trace:
        detail = operator_log_line(step.observation)
        rows.append({"Source": step.agent, "Detail": f"{step.action} — {detail}" if detail else step.action})
    if not rows:
        st.caption("No audit entries recorded.")
        return
    st.dataframe(rows, hide_index=True, width="stretch")


def requester_recipient(case: CaseResult) -> str:
    return case.source_reply_to or case.requester or "requester"


def original_gmail_message(case: CaseResult, record: dict[str, Any]) -> GmailMessage:
    return GmailMessage(
        message_id=case.source_message_id or str(record.get("source_message_id") or ""),
        thread_id=case.source_thread_id or str(record.get("source_thread_id") or "") or None,
        requester=case.requester,
        subject=case.subject,
        body=case.body,
        reply_to=case.source_reply_to or case.requester,
        rfc_message_id=case.source_rfc_message_id,
        received_at=case.received_at,
    )


def team_forward_target(case: CaseResult) -> tuple[str, str] | None:
    target = internal_notification_target(case)
    if target:
        recipient, team = target
        return case.internal_notification_to or recipient, team
    if case.internal_notification_to:
        return case.internal_notification_to, "Internal team"
    return None


def display_internal_forward_status(case: CaseResult) -> str:
    status = case.internal_notification_status or "not_evaluated"
    if status == "not_evaluated":
        return "not sent yet"
    if status == "not_applicable":
        return "not required"
    return status


def send_internal_forward(case: CaseResult, record: dict[str, Any]) -> tuple[bool, str]:
    target = team_forward_target(case)
    if not target:
        return False, "No internal team route is configured for this case."
    recipient, team = target
    if not recipient.strip():
        return False, f"No {team} email is configured."

    message = original_gmail_message(case, record)
    body = internal_notification_body(case, message, team)
    validation_error = validate_gmail_send_content(recipient, body, allow_internal=True)
    if validation_error:
        return False, validation_error

    try:
        service = build_gmail_service()
        sent = send_gmail_message(
            service,
            to=recipient,
            subject=internal_notification_subject(case, team),
            body=body,
            allow_internal=True,
        )
        case.internal_notification_status = "sent"
        case.internal_notification_to = recipient
        case.internal_notification_message_id = sent.get("sent_message_id", "")
        case.internal_notification_reason = f"Team forward sent to {team}."
        case.internal_notification_error = ""
        case.log.append(f"Internal notification sent to {team} ({recipient}).")
        save_case(case, record)
        return True, f"Team forward sent to {recipient}."
    except Exception as exc:
        case.internal_notification_status = "failed"
        case.internal_notification_to = recipient
        case.internal_notification_error = exc.__class__.__name__
        case.internal_notification_reason = f"Team forward failed for {team}."
        case.log.append(f"Internal notification failed: {case.internal_notification_error}")
        save_case(case, record)
        return False, f"Team forward failed: {case.internal_notification_error}"


def display_outbound_reason(case: CaseResult) -> str:
    reason = case.outbound_reason.strip()
    if case.outbound_status == "sent" and "eligible for mailbox auto-reply" in reason.lower():
        return "Acknowledgement was sent automatically during Gmail polling."
    return reason


def display_internal_forward_reason(case: CaseResult, team: str | None = None) -> str:
    reason = case.internal_notification_reason.strip()
    team_name = team or "team"
    if case.internal_notification_status == "sent":
        return f"Team forward sent to {team_name}."
    if case.internal_notification_status == "failed":
        return f"Team forward failed for {team_name}."
    return reason


def render_mail_flow(case: CaseResult, record: dict[str, Any]) -> None:
    has_requester_mail = bool(case.customer_output.strip())
    target = team_forward_target(case)
    if not has_requester_mail and not target:
        return

    st.markdown("**Mail flow**")
    if has_requester_mail:
        label = "Acknowledgement sent to requester" if case.outbound_status == "sent" else "Acknowledgement draft"
        st.write(f"{label}: {case.outbound_status} -> {requester_recipient(case)}")
        outbound_reason = display_outbound_reason(case)
        if outbound_reason:
            st.caption(outbound_reason)
        if case.send_error:
            st.caption(f"Error: {case.send_error}")
        box_label = "Acknowledgement sent to requester" if case.outbound_status == "sent" else "Acknowledgement draft for requester"
        render_readonly_mail_box(box_label, case.customer_output, clean_text=True)

    if target:
        recipient, team = target
        status = display_internal_forward_status(case)
        label = "Mail forwarded to team" if case.internal_notification_status == "sent" else "Team mail"
        st.write(f"{label}: {status} -> {recipient}")
        internal_reason = display_internal_forward_reason(case, team)
        if internal_reason:
            st.caption(internal_reason)
        if case.internal_notification_error:
            st.caption(f"Error: {case.internal_notification_error}")
        body = internal_notification_body(case, original_gmail_message(case, record), team)
        box_label = "Mail forwarded to team" if case.internal_notification_status == "sent" else "Team mail content"
        render_readonly_mail_box(box_label, body, clean_text=False)
        if case.internal_notification_status != "sent":
            st.caption("Team forwards are sent automatically when Gmail polling routes a case.")


def render_case_meta_strip(case: CaseResult) -> None:
    cols = st.columns(4)
    cols[0].markdown("Type  \n" + type_chip(case.classification.request_type), unsafe_allow_html=True)
    cols[1].markdown("Urgency  \n" + urgency_chip(case.classification.urgency), unsafe_allow_html=True)
    cols[2].markdown("Status  \n" + status_chip(case.status), unsafe_allow_html=True)
    cols[3].metric("Confidence", format_confidence(case.classification.confidence))


def manual_reply_status(case: CaseResult) -> str:
    if case.status != "Needs Human":
        return case.status
    return "Resolved"


def is_resolved_without_send(case: CaseResult) -> bool:
    if case.status != "Resolved" or case.outbound_status == "sent":
        return False
    reason = case.outbound_reason.lower()
    if "resolved without sending" in reason or "without sending the assistant draft" in reason:
        return True
    return any("marked as resolved" in item.lower() for item in case.log)


def manager_closed_case(case: CaseResult) -> bool:
    if case.dashboard_hidden:
        return True
    manager_markers = (
        "manager confirmed resolved",
        "manager marked as resolved from inbox queue",
    )
    return any(any(marker in item.lower() for marker in manager_markers) for item in case.log)


def is_dashboard_visible_case(case: CaseResult) -> bool:
    return not manager_closed_case(case)


def mark_case_resolved(case: CaseResult, record: dict[str, Any], *, reason: str = "Manager marked as resolved") -> None:
    previous_status = case.status
    if previous_status in MANAGER_CONFIRMABLE_STATUSES:
        case.dashboard_hidden = True
        case.log.append(f"{reason}: manager confirmed resolved")
        save_case(case, record)
        return

    if case.customer_output.strip() and case.outbound_status != "sent":
        case.customer_output = ""
        case.outbound_status = "not_sent"
        case.outbound_reason = "Manager resolved this case without sending the assistant draft."
        case.send_error = ""
        case.log.append("Assistant draft discarded because the manager resolved the case without sending mail")
    case.status = "Resolved"
    case.dashboard_hidden = True
    case.log.append(f"{reason}: status changed from {previous_status} to Resolved")
    save_case(case, record)


def send_operator_reply(
    case: CaseResult,
    record: dict[str, Any],
    *,
    recipient: str,
    body: str,
) -> tuple[bool, str]:
    recipient = recipient.strip()
    body = clean_assistant_reply_view_text(body)
    validation_error = validate_gmail_send_content(recipient, body)
    if validation_error:
        return False, validation_error
    try:
        service = build_gmail_service()
        source_message_id = case.source_message_id or str(record.get("source_message_id") or "")
        if record_source(record) == "gmail" and source_message_id:
            original = GmailMessage(
                message_id=source_message_id,
                thread_id=case.source_thread_id or str(record.get("source_thread_id") or "") or None,
                requester=case.requester,
                subject=case.subject,
                body=case.body,
                reply_to=case.source_reply_to or recipient,
                rfc_message_id=case.source_rfc_message_id,
            )
            result = send_gmail_reply(service, original, body)
        else:
            result = send_gmail_message(service, to=recipient, subject=reply_subject_text(case.subject), body=body)
        case.customer_output = body
        case.outbound_status = "sent"
        case.outbound_reason = f"Sent manually by operator to {recipient}."
        case.sent_at = fmt_time(utc_now())
        case.sent_message_id = result.get("sent_message_id", "")
        case.send_error = ""
        case.log.append(f"Manual outbound reply sent to {recipient}")
        previous_status = case.status
        next_status = manual_reply_status(case)
        if next_status != previous_status:
            case.status = next_status
            case.log.append(f"Manual review completed: status changed from {previous_status} to {next_status}")
        elif case.status == "Needs Human":
            case.log.append("Manual reply sent; case remains in human review for operational follow-up")
        save_case(case, record)
        return True, f"Mail sent to {recipient}."
    except Exception as exc:
        case.outbound_status = "failed"
        case.send_error = exc.__class__.__name__
        case.log.append(f"Manual send failed: {case.send_error}")
        save_case(case, record)
        return False, f"Send failed: {case.send_error}"


def render_reply_workspace(
    case: CaseResult,
    record: dict[str, Any],
    *,
    draft_mode: bool = False,
    return_to_queue_on_send: bool = False,
) -> None:
    if draft_mode:
        st.info("Review the assistant draft, edit it if needed, then send.")
    recipient = st.text_input("To", value=(case.requester or "").strip(), key=f"reply-to-{case.id}")
    if record_source(record) == "gmail" and (case.source_thread_id or record.get("source_message_id")):
        st.caption("Reply will be sent in the original Gmail thread. Subject is handled by the backend.")
    else:
        st.caption(f"Subject is handled by the backend: {reply_subject_text(case.subject)}")
    body = st.text_area("Message", value=clean_assistant_reply_view_text(case.customer_output), height=220, key=f"reply-body-{case.id}")
    msg_key = f"send-result-{case.id}"
    if msg_key in st.session_state:
        ok, text = st.session_state[msg_key]
        (st.success if ok else st.error)(text)
    if st.button("Send mail", type="primary", width="stretch", key=f"send-{case.id}"):
        success, text = send_operator_reply(case, record, recipient=recipient, body=body)
        if return_to_queue_on_send:
            st.session_state["review_send_result"] = {
                "payload": (success, text),
                "expires_at": time.time() + 3.0,
            }
            st.session_state.pop("active_review_case_id", None)
        else:
            st.session_state[msg_key] = (success, text)
        st.rerun()


def render_review_workspace(
    case: CaseResult,
    record: dict[str, Any],
    *,
    show_title: bool = True,
    return_to_queue_on_send: bool = False,
) -> None:
    render_case_detail(case, record, show_title=show_title)
    st.divider()
    st.markdown("#### Manager reply")
    if not case.customer_output.strip():
        st.caption("No assistant draft was created. Write a reply here only if this case needs an outbound message.")
    render_reply_workspace(case, record, draft_mode=True, return_to_queue_on_send=return_to_queue_on_send)


def render_case_detail(case: CaseResult, record: dict[str, Any], *, show_summary: bool = True, show_title: bool = True) -> None:
    if show_title:
        st.subheader(compact_subject(case.subject))
    render_case_meta_strip(case)
    if show_summary:
        render_branch_output_summary(case)
    render_mail_flow(case, record)

    tab_email, tab_decision, tab_audit = st.tabs(["Email", "Assistant plan", "Audit"])
    with tab_email:
        c1, c2 = st.columns(2)
        with c1:
            render_readonly_mail_box("Requester", case.requester or "unknown", value_class="requester-email requester-email-detail")
            render_readonly_mail_box("Received", case.received_at or case.created_at)
            render_readonly_mail_box("Mail body", case.body, clean_text=True)
        with c2:
            st.markdown("**Why this matters**")
            st.write(case.summary)
            if case.attachment_count:
                st.warning(f"{case.attachment_count} attachment(s) detected. Attachments are listed but not parsed by automation.")
                st.write(", ".join(case.attachment_names))
            if case.follow_up_at:
                st.metric("Follow-up due", case.follow_up_at)
            if case.sla_due_at:
                st.metric("SLA due", case.sla_due_at)
            if case.auto_resolution_paused:
                st.error("Auto-resolution paused")
    with tab_decision:
        st.markdown("**Manager focus**")
        st.write(manager_next_action(case))
        st.markdown("**Action plan**")
        if case.actions:
            for index, act in enumerate(case.actions, start=1):
                st.markdown(f"{index}. **{act.step}**")
        else:
            st.caption("No action plan recorded.")
        st.markdown("**Classification rationale**")
        st.write(case.classification.rationale)
        if case.internal_output.strip():
            st.markdown("**Routing summary**")
            st.text(case.internal_output)
        if case.internal_notification_status not in {"", "not_evaluated", "not_applicable"}:
            st.markdown("**Forwarded to team**")
            target = case.internal_notification_to or "team inbox not configured"
            st.write(f"{case.internal_notification_status} -> {target}")
            forward_reason = display_internal_forward_reason(case)
            if forward_reason:
                st.caption(forward_reason)
            if case.internal_notification_error:
                st.caption(f"Error: {case.internal_notification_error}")
        if case.classification.details:
            with st.expander("Extracted details", expanded=False):
                st.json(case.classification.details)
    with tab_audit:
        render_audit_timeline(case)
        with st.expander("Agent trace"):
            for index, step in enumerate(case.agent_trace, start=1):
                st.markdown(f"**{index}. {step.agent}** — `{step.action}`")
                st.caption(step.observation)


def filtered_records(
    records: list[dict[str, Any]],
    *,
    statuses: list[str],
    request_types: list[str],
    search: str,
) -> list[dict[str, Any]]:
    out = records
    if statuses:
        out = [r for r in out if r.get("status") in statuses]
    if request_types:
        out = [r for r in out if (r.get("classification") or {}).get("request_type") in request_types]
    query = search.strip().lower()
    if query:
        out = [
            r
            for r in out
            if query in str(r.get("subject", "")).lower()
            or query in str(r.get("requester", "")).lower()
            or query in str(r.get("body", "")).lower()
        ]
    return out


def is_auto_reply_candidate(case: CaseResult) -> bool:
    if not case.customer_output.strip():
        return False
    if case.outbound_status == "sent":
        return False
    if is_resolved_without_send(case):
        return False
    if case.status == "Needs Human" or case.auto_resolution_paused:
        return False
    if case.outbound_status == "sent" and (
        case.outbound_reason.lower().startswith("sent manually by operator")
        or any("manual outbound reply sent" in item.lower() for item in case.log)
    ):
        return False
    return case.classification.request_type in {"General Enquiry", "Service Request"}


def is_human_review_case(case: CaseResult) -> bool:
    return case.status == "Needs Human"
