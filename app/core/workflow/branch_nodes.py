"""Workflow branch nodes for complaint, enquiry, service, escalation, and no-action cases."""

from __future__ import annotations

from datetime import timedelta

from app.common.settings import app_settings
from app.core.workflow.helpers import action, base_case, fmt_time, signal_profile_from_state, trace, utc_now
from app.core.workflow.models import CaseResult, GraphState
from app.core.workflow.responses import (
    evaluate_kb_answerability,
    extract_service_request_details,
    format_service_routing_note,
    generate_complaint_acknowledgement,
    generate_escalation_acknowledgement,
    generate_general_response,
    generate_human_review_reply,
    generate_service_request_confirmation,
    missing_service_information,
    search_warehouse_kb,
)
from app.core.workflow.review import human_review_case, reroute_to_escalation

__all__ = [
    "complaint_node",
    "escalation_node",
    "general_enquiry_node",
    "no_action_node",
    "service_request_node",
    "unknown_node",
]


def complaint_node(state: GraphState) -> GraphState:
    settings = app_settings()
    now = utc_now()
    follow_up = now + timedelta(hours=2)
    requester = state.get("requester", "")
    subject = state.get("subject", "")
    body = state.get("body", "")
    classification = state["classification"]
    signals = signal_profile_from_state(state)
    if signals.escalation:
        return escalation_node(
            reroute_to_escalation(
                state,
                "Critical safety, legal, blocked-operations, or supervisor signal is stronger than complaint handling.",
            )
        )
    if not signals.complaint:
        case = human_review_case(
            state,
            summary="Complaint branch held because complaint evidence is insufficient.",
            reason="No clear complaint, dispute, damaged/missing goods, chargeback, or carrier dissatisfaction signal was found.",
            actions=[
                action("Hold complaint workflow", "Do not log a priority complaint without complaint evidence."),
                action(
                    "Route to warehouse operator",
                    "Human should review the classification before remediation.",
                    settings.manager_email,
                ),
            ],
            agent="Complaint Gate",
            traces=[
                trace(
                    "Complaint Gate",
                    "Validate the Complaint branch before acknowledging, escalating, logging priority, or setting follow-up.",
                    "validate_complaint_evidence",
                    "Complaint evidence was insufficient.",
                )
            ],
        )
        return {"result": case}
    draft_ack, ack_source = generate_complaint_acknowledgement(requester, subject, body, classification)
    case = CaseResult(
        **base_case(state),
        status="Needs Human",
        summary="High-priority warehouse complaint logged for operations lead review.",
        actions=[
            action("Acknowledge receipt", "Draft acknowledgement prepared for human review."),
            action(
                "Escalate to senior handler",
                "Prepare warehouse operations lead escalation note.",
                settings.ops_lead_email,
            ),
            action("Log case with priority flag", "Mark the receiving or dock complaint as high priority."),
            action("Set 2-hour follow-up reminder", "Set 2-hour follow-up reminder."),
        ],
        customer_output=draft_ack,
        internal_output=f"High-priority warehouse complaint\nRequester: {requester}\nSubject: {subject}\nReason: {classification.rationale}",
        follow_up_at=fmt_time(follow_up),
        log=[
            "Mail read",
            f"Tags assigned: {', '.join(classification.tags) or 'none'}",
            "Complaint branch executed",
            f"Draft acknowledgement prepared ({ack_source})",
            "Priority warehouse complaint logged; operations review required",
        ],
    )
    case.agent_trace.append(
        trace(
            "Complaint Gate",
            "Validate complaint evidence before executing the documented remediation workflow.",
            "validate_complaint_evidence",
            "Complaint/dispute evidence found.",
        )
    )
    case.agent_trace.append(
        trace(
            "Complaint Agent",
            "Execute complaint remediation: acknowledge, escalate, log priority, set follow-up.",
            "execute_complaint_branch",
            case.summary,
        )
    )
    case.agent_trace.append(
        trace("Complaint Agent", "Draft acknowledgement for human review.", "draft_acknowledgement", f"source={ack_source}")
    )
    return {"result": case}


def general_enquiry_node(state: GraphState) -> GraphState:
    settings = app_settings()
    requester = state.get("requester", "")
    subject = state.get("subject", "")
    body = state.get("body", "")
    classification = state["classification"]
    signals = signal_profile_from_state(state)
    if signals.escalation:
        return escalation_node(reroute_to_escalation(state, "Critical signal found while validating a General Enquiry candidate."))
    if not signals.information:
        case = human_review_case(
            state,
            summary="General enquiry branch held because the email is not clearly informational.",
            reason="No clear informational question or knowledge-base topic was found.",
            actions=[
                action("Classify sub-topic", "No safe general enquiry sub-topic identified."),
                action("Route to warehouse operator", "Human should classify and answer manually.", settings.manager_email),
                action("Hold response", "No customer response generated by automation."),
            ],
            agent="General Enquiry Gate",
            traces=[
                trace(
                    "General Enquiry Gate",
                    "Validate the email is an informational request before searching the KB.",
                    "validate_informational_request",
                    "Informational request evidence was insufficient.",
                )
            ],
        )
        return {"result": case}

    tool_decision = trace(
        "General Enquiry Agent",
        "Need verified warehouse facts before answering a low-risk informational request.",
        "decide_tool_search",
        "Use search_warehouse_kb, then evidence gate.",
    )
    article, score, kb_search_step = search_warehouse_kb(subject, body)
    if not article:
        evidence, evidence_step = evaluate_kb_answerability(subject, body, article, score)
        case = human_review_case(
            state,
            summary="Knowledge base does not contain enough evidence to answer this enquiry.",
            reason=evidence.missing_information or evidence.rationale,
            actions=[
                action("Classify sub-topic", "No safe knowledge-base sub-topic matched."),
                action("Check knowledge base", evidence.missing_information or "No matching KB evidence found."),
                action(
                    "Route to warehouse operator",
                    "Human should answer manually because the KB does not contain the requested detail.",
                    settings.manager_email,
                ),
                action("Hold response", "No customer response generated by automation."),
            ],
            agent="General Enquiry Agent",
            traces=[tool_decision, kb_search_step, evidence_step],
        )
        case.internal_output = (
            f"General enquiry needs review\nRequester: {requester}\nSubject: {subject}\n"
            f"Reason: {evidence.missing_information or evidence.rationale}"
        )
        case.agent_trace.append(
            trace("General Enquiry Agent", "Hold the case when no KB article can answer the request.", "route_human_review", case.summary)
        )
        return {"result": case}

    evidence, evidence_step = evaluate_kb_answerability(subject, body, article, score)
    if not evidence.can_answer or evidence.confidence < 0.6:
        case = human_review_case(
            state,
            summary="Knowledge base match is insufficient to answer this enquiry.",
            reason=evidence.missing_information or evidence.rationale,
            actions=[
                action("Classify sub-topic", f"Candidate sub-topic: {article.topic}."),
                action("Check knowledge base", evidence.missing_information or evidence.rationale),
                action(
                    "Route to warehouse operator",
                    "Human should answer manually because retrieved KB facts are not sufficient.",
                    settings.manager_email,
                ),
                action("Hold response", "No customer response generated by automation."),
            ],
            agent="General Enquiry Agent",
            traces=[tool_decision, kb_search_step, evidence_step],
        )
        case.internal_output = (
            f"General enquiry needs review\nRequester: {requester}\nSubject: {subject}\n"
            f"Candidate KB: {article.title}\nReason: {evidence.missing_information or evidence.rationale}"
        )
        case.sub_topic = article.topic
        case.agent_trace.append(
            trace(
                "General Enquiry Agent",
                "Do not answer unless retrieved KB facts directly answer the request.",
                "route_human_review",
                case.summary,
            )
        )
        return {"result": case}

    response, response_source = generate_general_response(requester, subject, body, article)
    case = CaseResult(
        **base_case(state),
        status="Resolved",
        summary=f"Answered from knowledge base: {article.title}.",
        actions=[
            action("Classify sub-topic", f"Sub-topic: {article.topic}."),
            action("Generate AI response from knowledge base", f"Used KB article: {article.title}."),
            action("Send response", "Response ready for outbound delivery.", requester or "requester"),
            action("Log as resolved", "Marked case resolved after response."),
        ],
        customer_output=response,
        sub_topic=article.topic,
        log=[
            "Mail read",
            f"Tags assigned: {', '.join(classification.tags) or 'none'}",
            f"Generated response from KB score {score} using {response_source}",
            "Response recorded",
            "Logged as resolved",
        ],
    )
    case.agent_trace.append(tool_decision)
    case.agent_trace.append(kb_search_step)
    case.agent_trace.append(evidence_step)
    case.agent_trace.append(
        trace(
            "KB Response Agent",
            "Generate customer response from verified KB facts.",
            "kb_answer_ready",
            f"Resolved with {article.topic}; response_source={response_source}",
        )
    )
    case.agent_trace.append(
        trace(
            "General Enquiry Agent",
            "Use warehouse KB facts to answer and close low-risk enquiries.",
            "close_resolved",
            case.summary,
        )
    )
    return {"result": case}


def service_request_node(state: GraphState) -> GraphState:
    settings = app_settings()
    now = utc_now()
    sla = now + timedelta(hours=24)
    requester = state.get("requester", "")
    subject = state.get("subject", "")
    body = state.get("body", "")
    classification = state["classification"]
    details, extraction_source = extract_service_request_details(subject, body, classification)
    signals = signal_profile_from_state(state)
    if signals.escalation:
        return escalation_node(reroute_to_escalation(state, "Critical signal found while validating a Service Request candidate."))
    missing = missing_service_information(subject, body, details)
    if missing:
        case = human_review_case(
            state,
            summary="Service request needs human review before routing.",
            reason=missing,
            actions=[
                action("Extract required details", f"Missing or ambiguous detail: {missing}"),
                action(
                    "Route to warehouse operator",
                    "Human should request missing details or choose the correct department.",
                    settings.manager_email,
                ),
                action("Hold confirmation", "No confirmation generated by automation."),
            ],
            agent="Service Request Gate",
            traces=[
                trace(
                    "Service Request Gate",
                    "Validate service action and required routing references before confirmation or SLA.",
                    "validate_service_request_details",
                    f"{missing}; extraction_source={extraction_source}",
                )
            ],
            missing_information=missing,
        )
        case.internal_output = f"{format_service_routing_note(requester, subject, details)}\nValidation hold: {missing}"
        return {"result": case}
    confirmation, confirmation_source = generate_service_request_confirmation(requester, subject, details)
    routing_note = format_service_routing_note(requester, subject, details)
    case = CaseResult(
        **base_case(state),
        status="Routed",
        summary="Warehouse service request routed to the relevant operations team with SLA timer.",
        actions=[
            action("Extract required details", f"Requested action: {details.requested_action or 'warehouse service request'}."),
            action("Route to relevant department", "Route to dock planning or warehouse operations.", settings.dock_planning_email),
            action("Generate confirmation to requester", "Create confirmation for carrier/vendor requester."),
            action("Set SLA timer", "Set 24-hour SLA timer."),
        ],
        customer_output=confirmation,
        internal_output=routing_note,
        sla_due_at=fmt_time(sla),
        log=[
            "Mail read",
            f"Tags assigned: {', '.join(classification.tags) or 'none'}",
            f"Extracted service details ({extraction_source})",
            "Service request branch executed",
            f"Confirmation prepared ({confirmation_source})",
            "Routed to dock planning",
            "SLA timer set",
        ],
    )
    case.agent_trace.append(
        trace(
            "Service Request Gate",
            "Validate service action and required details before routing.",
            "validate_service_request_details",
            f"Service request details sufficient; extraction_source={extraction_source}",
        )
    )
    case.agent_trace.append(
        trace("Service Request Agent", "Extract warehouse request details and route the work.", "extract_and_route", f"extraction_source={extraction_source}")
    )
    case.agent_trace.append(trace("Service Request Agent", "Generate confirmation and set SLA.", "route_with_sla", case.summary))
    return {"result": case}


def escalation_node(state: GraphState) -> GraphState:
    settings = app_settings()
    requester = state.get("requester", "")
    subject = state.get("subject", "")
    body = state.get("body", "")
    classification = state["classification"]
    signals = signal_profile_from_state(state)
    if not signals.escalation:
        case = human_review_case(
            state,
            summary="Escalation branch held because critical evidence is insufficient.",
            reason="No safety, injury, blocked-operations, legal, security, supervisor, or executive escalation signal was found.",
            actions=[
                action("Hold escalation workflow", "Do not send supervisor alert without critical evidence."),
                action(
                    "Route to warehouse operator",
                    "Human should review the urgent or ambiguous request.",
                    settings.manager_email,
                ),
                action("Pause auto-resolution", "Do not auto-close this case."),
            ],
            agent="Escalation Gate",
            traces=[
                trace(
                    "Escalation Gate",
                    "Validate critical escalation evidence before supervisor notification.",
                    "validate_escalation_evidence",
                    "Critical escalation evidence was insufficient.",
                )
            ],
        )
        case.auto_resolution_paused = True
        return {"result": case}
    draft_ack, ack_source = generate_escalation_acknowledgement(requester, subject, body, classification)
    case = CaseResult(
        **base_case(state),
        status="Needs Human",
        summary="Critical escalation flagged for immediate human review.",
        actions=[
            action("Immediately flag for human review", "Immediate warehouse supervisor review required."),
            action("Draft urgent acknowledgement", "Draft urgent acknowledgement prepared for human review."),
            action("Notify supervisor", "Prepare warehouse supervisor alert.", settings.supervisor_email),
            action("Pause auto-resolution", "Do not auto-close this case."),
        ],
        customer_output=draft_ack,
        internal_output=f"Critical warehouse escalation\nRequester: {requester}\nSubject: {subject}\nAuto-resolution paused.",
        auto_resolution_paused=True,
        log=[
            "Mail read",
            f"Tags assigned: {', '.join(classification.tags) or 'none'}",
            "Escalation branch executed",
            f"Draft urgent acknowledgement prepared ({ack_source})",
            "Supervisor alert prepared",
            "Auto-resolution paused",
        ],
    )
    case.agent_trace.append(
        trace(
            "Escalation Gate",
            "Validate critical escalation evidence before supervisor notification.",
            "validate_escalation_evidence",
            "Critical escalation evidence found.",
        )
    )
    case.agent_trace.append(
        trace("Escalation Agent", "Warehouse escalations require immediate human-in-the-loop handling.", "pause_and_notify", case.summary)
    )
    case.agent_trace.append(
        trace("Escalation Agent", "Draft urgent acknowledgement for human review.", "draft_urgent_acknowledgement", f"source={ack_source}")
    )
    return {"result": case}


def no_action_node(state: GraphState) -> GraphState:
    settings = app_settings()
    classification = state["classification"]
    reason = classification.details.get("reason", "no_action_required")
    signals = signal_profile_from_state(state)
    if not signals.no_action:
        case = human_review_case(
            state,
            summary="No Action branch held because the no-action signal is unclear.",
            reason="No explicit auto-reply, FYI-only, receipt, delivery failure, or no-action signal was found.",
            actions=[
                action("Hold no-action close", "Do not close the case without a clear no-action signal."),
                action("Route to warehouse operator", "Human should confirm whether work is required.", settings.manager_email),
            ],
            agent="No Action Gate",
            traces=[
                trace(
                    "No Action Gate",
                    "Validate clear no-action evidence before suppressing response and closing.",
                    "validate_no_action_evidence",
                    "No-action evidence was insufficient.",
                )
            ],
        )
        return {"result": case}
    case = CaseResult(
        **base_case(state),
        status="No Action Closed",
        summary="Message closed without outbound response.",
        actions=[
            action("Record reason", f"Reason: {reason}."),
            action("Suppress response", "No customer response generated."),
            action("Close", "Case closed as no-action."),
        ],
        log=[
            "Mail read",
            f"Tags assigned: {', '.join(classification.tags) or 'none'}",
            f"Closed as no-action because: {reason}",
        ],
    )
    case.agent_trace.append(
        trace(
            "No Action Gate",
            "Validate clear no-action evidence before suppressing response and closing.",
            "validate_no_action_evidence",
            f"Clear no-action signal found: {reason}.",
        )
    )
    case.agent_trace.append(trace("No Action Agent", "Suppress outbound work for automated or no-action mail.", "close_no_action", case.summary))
    return {"result": case}


def unknown_node(state: GraphState) -> GraphState:
    settings = app_settings()
    requester = state.get("requester", "")
    subject = state.get("subject", "")
    body = state.get("body", "")
    suggested_reply, reply_source = generate_human_review_reply(
        requester, subject, body, "Classification uncertain; needs operator judgement."
    )
    case = CaseResult(
        **base_case(state),
        status="Needs Human",
        summary="Could not safely choose a workflow branch.",
        actions=[
            action("Hold automation", "Do not auto-resolve."),
            action("Route to warehouse operator", "Human should classify this request.", settings.manager_email),
            action("Suggest reply", "Draft holding acknowledgement prepared for operator review."),
        ],
        customer_output=suggested_reply,
        log=["Mail read", "Classification uncertain", f"Suggested reply drafted for operator ({reply_source})", "Routed to human review"],
    )
    case.agent_trace.append(
        trace("Human Review Agent", "Unknown or low-confidence messages should not be automated.", "route_human_review", case.summary)
    )
    case.agent_trace.append(
        trace(
            "Assistant Draft Agent",
            "Prepare a suggested holding reply so the operator has a starting point.",
            "draft_suggested_reply",
            f"source={reply_source}",
        )
    )
    return {"result": case}
