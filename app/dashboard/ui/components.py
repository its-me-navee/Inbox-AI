from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from app.dashboard.ui.styles import STATUS_CLASS, TYPE_CLASS, URGENCY_CLASS

TYPE_LABELS = {
    "No Action": "No reply needed",
}

STATUS_LABELS = {
    "Needs Human": "Review",
    "No Action Closed": "Closed",
    "Resolved": "Marked as resolved",
}


def badge(label: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{escape(label)}</span>'


def type_label(request_type: str) -> str:
    return TYPE_LABELS.get(request_type, request_type)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def type_chip(request_type: str) -> str:
    return badge(type_label(request_type), TYPE_CLASS.get(request_type, "type-unknown"))


def urgency_chip(urgency: str) -> str:
    return badge(urgency, URGENCY_CLASS.get(urgency, "status-muted"))


def status_chip(status: str) -> str:
    return badge(status_label(status), STATUS_CLASS.get(status, "status-muted"))


def status_badge_html(label: str, css_class: str) -> str:
    return badge(label, css_class)


def render_empty_state(title: str, message: str) -> None:
    st.info(f"**{title}**  \n{message}")


def render_app_hero(total_cases: int, needs_human: int) -> None:
    pills = [
        f'<span class="hero-pill"><span class="dot"></span>Total cases: {total_cases}</span>',
        f'<span class="hero-pill {"warn" if needs_human else ""}"><span class="dot"></span>Manager review: {needs_human}</span>',
    ]
    st.markdown(
        f"""
        <div class="app-hero">
            <h1>Inbox AI Assistant</h1>
            <p>Classifies incoming warehouse mail, prepares the action plan, and brings manager decisions forward.</p>
            <p class="hero-demo">To test my assistant, send a warehouse-style email to <a href="mailto:navnee4501@gmail.com">navnee4501@gmail.com</a> and watch it classify, route, draft, and log the decision here.</p>
            <div class="hero-pills">{"".join(pills)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metrics_row(records: list[dict[str, Any]]) -> None:
    cols = st.columns(6)
    cols[0].metric("Total", len(records))
    cols[1].metric("Review", sum(1 for r in records if r.get("status") == "Needs Human"))
    cols[2].metric("Routed", sum(1 for r in records if r.get("status") == "Routed"))
    cols[3].metric("Marked as resolved", sum(1 for r in records if r.get("status") == "Resolved"))
    cols[4].metric("Closed", sum(1 for r in records if r.get("status") == "No Action Closed"))
    cols[5].metric("Sent", sum(1 for r in records if r.get("outbound_status") == "sent"))


def render_ops_metrics(records: list[dict[str, Any]], *, case_from_record) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    sla_due = follow_due = 0
    for record in records:
        case = case_from_record(record)
        for value in (case.sla_due_at, case.follow_up_at):
            if not value:
                continue
            try:
                due = datetime.strptime(value, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
                if due <= now:
                    if value == case.sla_due_at:
                        sla_due += 1
                    else:
                        follow_due += 1
            except ValueError:
                continue
    c1, c2, c3 = st.columns(3)
    c1.metric("SLA overdue", sla_due)
    c2.metric("Follow-up overdue", follow_due)
    c3.metric("Open review", sum(1 for r in records if r.get("status") == "Needs Human"))


def render_workflow_diagram() -> None:
    st.markdown("#### Classification flow")
    st.markdown(
        "`Gmail intake` &rarr; `Mail Reader` &rarr; `Classifier` &rarr; `Classification Auditor` &rarr; `Branch Agent` &rarr; `Case Auditor`",
        unsafe_allow_html=True,
    )
    cols = st.columns(6)
    branches = [
        ("Complaint", "type-complaint"),
        ("General Enquiry", "type-general-enquiry"),
        ("Service Request", "type-service-request"),
        ("Escalation", "type-escalation"),
        ("No reply needed", "type-no-action"),
        ("Unknown", "type-unknown"),
    ]
    for col, (label, css) in zip(cols, branches):
        col.markdown(badge(label, css), unsafe_allow_html=True)


def render_remediation_table() -> None:
    st.markdown("#### Manager workflow")
    st.dataframe(
        [
            {"Case": "Complaint", "Manager decision": "Review priority issue and assign owner", "Assistant prepares": "Acknowledgement, escalation note, follow-up timer"},
            {"Case": "General Enquiry", "Manager decision": "Approve or correct the answer when needed", "Assistant prepares": "KB-backed reply and resolution log"},
            {"Case": "Service Request", "Manager decision": "Confirm routing or reassign", "Assistant prepares": "Extracted details, routing note, SLA"},
            {"Case": "Escalation", "Manager decision": "Handle immediately", "Assistant prepares": "Urgent acknowledgement and supervisor alert"},
            {"Case": "No reply needed", "Manager decision": "No follow-up needed", "Assistant prepares": "Reason and close status"},
        ],
        hide_index=True,
        use_container_width=True,
    )
