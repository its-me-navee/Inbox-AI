"""Graph assembly and the two public entry points: process_request and classify."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.common.logging import get_logger, log_event
from app.core.classification import BRANCH_SPECS, Classification
from app.core.workflow.models import CaseResult, GraphState
from app.core.workflow.audit import case_auditor_node
from app.core.workflow.branch_nodes import (
    complaint_node,
    escalation_node,
    general_enquiry_node,
    no_action_node,
    service_request_node,
    unknown_node,
)
from app.core.workflow.classifier_nodes import (
    classification_auditor_node,
    classification_node,
    mail_reader_node,
)
from app.core.workflow.responses import classify_with_llm

logger = get_logger("workflow")

__all__ = ["build_graph", "classify", "process_request"]


def route_after_classification(state: GraphState) -> str:
    classification = state["classification"]
    if classification.confidence < 0.6:
        return "unknown"
    routes = {request_type: spec.route for request_type, spec in BRANCH_SPECS.items()}
    return routes.get(classification.request_type, "unknown")


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("mail_reader", mail_reader_node)
    graph.add_node("classifier", classification_node)
    graph.add_node("classification_auditor", classification_auditor_node)
    graph.add_node("complaint", complaint_node)
    graph.add_node("general_enquiry", general_enquiry_node)
    graph.add_node("service_request", service_request_node)
    graph.add_node("escalation", escalation_node)
    graph.add_node("no_action", no_action_node)
    graph.add_node("unknown", unknown_node)
    graph.add_node("case_auditor", case_auditor_node)

    graph.add_edge(START, "mail_reader")
    graph.add_edge("mail_reader", "classifier")
    graph.add_edge("classifier", "classification_auditor")
    graph.add_conditional_edges(
        "classification_auditor",
        route_after_classification,
        {
            "complaint": "complaint",
            "general_enquiry": "general_enquiry",
            "service_request": "service_request",
            "escalation": "escalation",
            "no_action": "no_action",
            "unknown": "unknown",
        },
    )
    for node in ["complaint", "general_enquiry", "service_request", "escalation", "no_action", "unknown"]:
        graph.add_edge(node, "case_auditor")
    graph.add_edge("case_auditor", END)
    return graph.compile()


def process_request(requester: str, subject: str, body: str) -> CaseResult:
    log_event(logger, "workflow_request_start", requester=requester, subject=subject)
    state = build_graph().invoke(
        {"requester": requester, "subject": subject, "body": body, "agent_trace": []}
    )
    case = state["result"]
    log_event(
        logger,
        "workflow_request_done",
        case_id=case.id,
        request_type=case.classification.request_type,
        urgency=case.classification.urgency,
        confidence=case.classification.confidence,
        status=case.status,
        outbound_status=case.outbound_status,
    )
    return case


def classify(subject: str, body: str) -> Classification:
    classification, _ = classify_with_llm("", subject, body)
    return classification
