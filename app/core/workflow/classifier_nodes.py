"""Graph nodes that read mail, classify, and audit the route."""

from __future__ import annotations

from app.core.classification import audit_classification_against_signals
from app.core.workflow.helpers import signal_profile_from_state, trace
from app.core.workflow.models import GraphState
from app.core.workflow.responses import classify_with_llm
from app.common.logging import get_logger, log_event

__all__ = [
    "classification_auditor_node",
    "classification_node",
    "mail_reader_node",
]


logger = get_logger("workflow")


def mail_reader_node(state: GraphState) -> GraphState:
    current_trace = state.get("agent_trace", [])
    return {
        "agent_trace": [
            *current_trace,
            trace(
                "Mail Reader Agent",
                "Read the incoming Gmail/PubSub-style message and prepare it for classification.",
                "read_mail",
                f"Requester={state.get('requester') or 'unknown'}; subject={state.get('subject') or '(no subject)'}",
            ),
        ]
    }


def classification_node(state: GraphState) -> GraphState:
    classification, step = classify_with_llm(
        state.get("requester", ""),
        state.get("subject", ""),
        state.get("body", ""),
    )
    log_event(
        logger,
        "workflow_classified",
        source=classification.source,
        request_type=classification.request_type,
        urgency=classification.urgency,
        confidence=classification.confidence,
    )
    return {
        "classification": classification,
        "agent_trace": [*state.get("agent_trace", []), step],
    }


def classification_auditor_node(state: GraphState) -> GraphState:
    classification = state["classification"]
    signals = signal_profile_from_state(state)
    audited, observation = audit_classification_against_signals(classification, signals)
    action_name = "accept_classification" if audited == classification else "correct_classification"
    log_event(
        logger,
        "workflow_classification_audit",
        action=action_name,
        original_type=classification.request_type,
        audited_type=audited.request_type,
        urgency=audited.urgency,
        confidence=audited.confidence,
        observation=observation,
    )
    return {
        "classification": audited,
        "signal_profile": signals,
        "agent_trace": [
            *state.get("agent_trace", []),
            trace(
                "Classification Auditor Agent",
                "Compare the classifier hypothesis against deterministic workflow evidence before routing.",
                action_name,
                f"{observation} Signals: {signals.summary()}",
            ),
        ],
    }
