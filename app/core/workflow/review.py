"""Shared human-review and rerouting helpers for workflow nodes."""

from __future__ import annotations

from app.common.settings import app_settings
from app.core.classification import Classification
from app.core.workflow.helpers import action, base_case, trace
from app.core.workflow.models import Action, AgentTrace, CaseResult, GraphState
from app.core.workflow.responses import generate_human_review_reply

__all__ = ["human_review_case", "reroute_to_escalation"]


def human_review_case(
    state: GraphState,
    *,
    summary: str,
    reason: str,
    actions: list[Action] | None = None,
    agent: str = "Human Review Agent",
    traces: list[AgentTrace] | None = None,
    missing_information: str = "",
) -> CaseResult:
    settings = app_settings()
    classification = state["classification"]
    requester = state.get("requester", "")
    subject = state.get("subject", "")
    body = state.get("body", "")
    suggested_reply, reply_source = generate_human_review_reply(
        requester, subject, body, reason, missing_information=missing_information
    )
    info_line = (
        f"Information needed: {missing_information}"
        if missing_information.strip()
        else "Information needed: operator judgement (no specific detail missing)."
    )
    case = CaseResult(
        **base_case(state),
        status="Needs Human",
        summary=summary,
        actions=actions
        or [
            action("Hold automation", "Do not auto-resolve."),
            action(
                "Route to warehouse operator",
                "Human should review the message before any response.",
                settings.manager_email,
            ),
        ],
        customer_output=suggested_reply,
        internal_output=(
            "Human review required\n"
            f"Requester: {requester}\n"
            f"Subject: {subject}\n"
            f"Reason: {reason}\n"
            f"{info_line}"
        ),
        log=[
            "Mail read",
            f"Tags assigned: {', '.join(classification.tags) or 'none'}",
            f"Branch validation held automation: {reason}",
            f"Suggested reply drafted for operator ({reply_source})",
            "Routed to human review",
        ],
    )
    case.agent_trace.extend(traces or [])
    case.agent_trace.append(
        trace(
            agent,
            "Route to human review when branch validation cannot safely complete remediation.",
            "route_human_review",
            reason,
        )
    )
    case.agent_trace.append(
        trace(
            "Assistant Draft Agent",
            "Even when a human must decide, prepare a suggested reply and state what information is needed.",
            "draft_suggested_reply",
            f"source={reply_source}; {info_line}",
        )
    )
    return case


def reroute_to_escalation(state: GraphState, reason: str) -> GraphState:
    previous = state["classification"]
    next_state: GraphState = dict(state)
    next_state["classification"] = Classification(
        request_type="Escalation",
        urgency="Critical",
        confidence=max(previous.confidence, 0.9),
        rationale=f"Branch validation rerouted to Escalation: {reason}",
        tags=list(dict.fromkeys([*previous.tags, "critical_ops", "branch_gate_reroute"])),
        details={**previous.details, "rerouted_from": previous.request_type},
        source=previous.source,
    )
    next_state["agent_trace"] = [
        *state.get("agent_trace", []),
        trace(
            "Branch Gate",
            f"Validate candidate {previous.request_type} branch before acting.",
            "reroute_to_escalation",
            reason,
        ),
    ]
    return next_state
