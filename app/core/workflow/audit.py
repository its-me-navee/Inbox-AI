"""Final workflow output-contract checks."""

from __future__ import annotations

import logging

from app.common.settings import app_settings
from app.core.workflow.helpers import action, clean_customer_response_text, trace
from app.core.workflow.models import CaseResult, GraphState
from app.core.workflow.review import human_review_case
from app.common.logging import get_logger, log_event

__all__ = ["case_auditor_node", "case_contract_issues"]


logger = get_logger("workflow")


def case_contract_issues(case: CaseResult) -> list[str]:
    issues: list[str] = []
    request_type = case.classification.request_type
    if not case.actions:
        issues.append("No remediation actions were produced.")
    if case.status in {"Resolved", "Routed"} and not clean_customer_response_text(case.customer_output):
        issues.append("Customer-facing output is missing for an automated branch.")
    if request_type == "General Enquiry" and case.status == "Resolved" and not case.sub_topic:
        issues.append("General Enquiry was resolved without a verified knowledge-base sub-topic.")
    if request_type == "Service Request" and case.status == "Routed":
        if not case.internal_output.strip():
            issues.append("Service Request was routed without an internal routing note.")
        if not case.sla_due_at:
            issues.append("Service Request was routed without an SLA timer.")
    if request_type == "Complaint" and not case.follow_up_at and case.status != "Needs Human":
        issues.append("Complaint workflow did not create the required follow-up marker.")
    if request_type == "Escalation" and not case.auto_resolution_paused:
        issues.append("Escalation workflow did not pause auto-resolution.")
    if request_type == "No Action" and case.status != "Needs Human" and case.customer_output.strip():
        issues.append("No Action branch produced a customer response.")
    return issues


def case_auditor_node(state: GraphState) -> GraphState:
    case = state["result"]
    issues = case_contract_issues(case)
    if issues:
        settings = app_settings()
        reason = " ".join(issues)
        log_event(
            logger,
            "workflow_case_audit_failed",
            level=logging.WARNING,
            case_id=case.id,
            request_type=case.classification.request_type,
            status=case.status,
            issues=issues,
        )
        held = human_review_case(
            state,
            summary="Workflow output contract failed; operator review required.",
            reason=reason,
            actions=[
                action("Hold automation", "Do not send or close this case until the workflow output is repaired."),
                action(
                    "Route to warehouse operator",
                    "Human should review the failed workflow contract.",
                    settings.manager_email,
                ),
            ],
            agent="Case Auditor Agent",
            traces=case.agent_trace,
        )
        held.agent_trace.append(
            trace(
                "Case Auditor Agent",
                "Verify every branch produced the minimum required outputs before completion.",
                "fail_output_contract",
                reason,
            )
        )
        return {"result": held}

    log_event(
        logger,
        "workflow_case_audit_passed",
        case_id=case.id,
        request_type=case.classification.request_type,
        status=case.status,
        actions=len(case.actions),
    )
    case.agent_trace.append(
        trace(
            "Case Auditor Agent",
            "Verify every branch produced the minimum required outputs before completion.",
            "pass_output_contract",
            f"{case.classification.request_type} -> {case.status}; actions={len(case.actions)}",
        )
    )
    return {"result": case}
