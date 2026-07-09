from __future__ import annotations

from app.core.workflow import (
    Action,
    CaseResult,
    Classification,
    case_auditor_node,
    classification_auditor_node,
    clean_customer_response_text,
    classify,
    no_action_node,
    process_request,
    scan_mail_signals,
)


def test_warehouse_receiving_dispute_is_complaint() -> None:
    case = process_request(
        "carrier.ops@example.com",
        "Short received pallets for ASN FBA12345",
        "We delivered 18 pallets for ASN FBA12345, but receiving shows only 16. This chargeback dispute needs urgent investigation.",
    )

    assert case.classification.request_type == "Complaint"
    assert case.classification.urgency == "High"
    assert case.status == "Needs Human"
    assert case.customer_output
    assert "operations lead" in case.customer_output.lower() or "received" in case.customer_output.lower()
    assert case.internal_output
    assert case.follow_up_at
    assert "warehouse" in case.summary.lower()
    assert [action.step for action in case.actions] == [
        "Acknowledge receipt",
        "Escalate to senior handler",
        "Log case with priority flag",
        "Set 2-hour follow-up reminder",
    ]


def test_urgent_receiving_dispute_does_not_become_escalation() -> None:
    classification = classify(
        "Urgent chargeback dispute",
        "ASN FBA12345 was short received and the missing pallets are causing a chargeback dispute.",
    )

    assert classification.request_type == "Complaint"
    assert classification.urgency == "High"


def test_warehouse_general_enquiry_resolves_from_knowledge_base() -> None:
    case = process_request(
        "driver.dispatch@example.com",
        "Inbound dock hours and check-in documents",
        "Can you confirm the inbound dock hours for Saturday and what documents the driver needs at check-in?",
    )

    assert case.classification.request_type == "General Enquiry"
    assert case.status == "Resolved"
    assert case.sub_topic == "dock_hours"
    assert case.customer_output
    assert any(action.step == "Generate AI response from knowledge base" for action in case.actions)
    assert case.classification.tags
    assert "Response recorded" in case.log
    assert any(step.action == "search_warehouse_kb" for step in case.agent_trace)
    assert any(step.action == "validate_informational_request" or step.action == "decide_tool_search" for step in case.agent_trace)
    assert any(step.agent == "Classification Auditor Agent" for step in case.agent_trace)
    assert any(step.agent == "Case Auditor Agent" and step.action == "pass_output_contract" for step in case.agent_trace)


def test_classification_auditor_corrects_urgent_service_request() -> None:
    subject = "Urgent reschedule inbound appointment FC-BLR8-7781"
    body = "Please urgently reschedule appointment FC-BLR8-7781 for ASN FBA99887 from July 8 to July 9."
    result = classification_auditor_node(
        {
            "requester": "vendor.appointments@example.com",
            "subject": subject,
            "body": body,
            "signal_profile": scan_mail_signals(subject, body),
            "classification": Classification(
                request_type="Escalation",
                urgency="Critical",
                confidence=0.92,
                rationale="Model over-weighted the word urgent.",
                tags=["urgent_review"],
            ),
            "agent_trace": [],
        }
    )

    audited = result["classification"]

    assert audited.request_type == "Service Request"
    assert audited.urgency == "Medium"
    assert audited.details["appointment_id"] == "FC-BLR8-7781"
    assert audited.details["asn"] == "FBA99887"
    assert any(step.action == "correct_classification" for step in result["agent_trace"])


def test_classification_auditor_recognizes_release_service_request() -> None:
    subject = "Release inbound trailer for PO 128900"
    body = "Please release the inbound trailer for PO 128900 once receiving is complete."
    result = classification_auditor_node(
        {
            "requester": "vendor.ops@example.com",
            "subject": subject,
            "body": body,
            "signal_profile": scan_mail_signals(subject, body),
            "classification": Classification(
                request_type="General Enquiry",
                urgency="Low",
                confidence=0.78,
                rationale="Model treated the request as informational.",
                tags=["warehouse_kb"],
            ),
            "agent_trace": [],
        }
    )

    audited = result["classification"]
    assert audited.request_type == "Service Request"
    assert audited.details["requested_action"] == "release"
    assert audited.details["po"] == "PO 128900"


def test_classification_auditor_downgrades_unsupported_no_action_to_unknown() -> None:
    subject = "Hello"
    body = "Thanks"
    result = classification_auditor_node(
        {
            "requester": "sender@example.com",
            "subject": subject,
            "body": body,
            "signal_profile": scan_mail_signals(subject, body),
            "classification": Classification(
                request_type="No Action",
                urgency="Low",
                confidence=0.93,
                rationale="Model considered the message non-actionable.",
                tags=["no_action"],
            ),
            "agent_trace": [],
        }
    )

    audited = result["classification"]
    assert audited.request_type == "Unknown"
    assert audited.confidence < 0.6
    assert any(step.action == "correct_classification" for step in result["agent_trace"])


def test_case_auditor_holds_invalid_automated_output() -> None:
    classification = Classification(
        request_type="General Enquiry",
        urgency="Low",
        confidence=0.9,
        rationale="Informational request.",
        tags=["warehouse_kb"],
    )
    broken_case = CaseResult(
        id="case-1",
        created_at="2026-07-08 00:00 UTC",
        requester="driver.dispatch@example.com",
        subject="Dock hours",
        body="Can you confirm dock hours?",
        classification=classification,
        status="Resolved",
        summary="Answered from knowledge base.",
        actions=[Action("Log as resolved", "Incorrectly marked resolved.")],
        customer_output="",
        sub_topic="dock_hours",
    )

    result = case_auditor_node(
        {
            "requester": broken_case.requester,
            "subject": broken_case.subject,
            "body": broken_case.body,
            "classification": classification,
            "result": broken_case,
            "agent_trace": [],
        }
    )
    held = result["result"]

    assert held.status == "Needs Human"
    assert "Workflow output contract failed" in held.summary
    assert any(step.action == "fail_output_contract" for step in held.agent_trace)


def test_case_auditor_allows_human_review_draft_for_no_action() -> None:
    classification = Classification(
        request_type="No Action",
        urgency="Low",
        confidence=0.8,
        rationale="Likely automated mail, but evidence is unclear.",
        tags=["no_action"],
    )
    held_case = CaseResult(
        id="case-1",
        created_at="2026-07-08 00:00 UTC",
        requester="notifications@example.com",
        subject="Delivery update",
        body="Please review the attached update.",
        classification=classification,
        status="Needs Human",
        summary="No Action branch held because the no-action signal is unclear.",
        actions=[Action("Route to warehouse operator", "Human should confirm whether work is required.")],
        customer_output="Hello,\n\nWe are reviewing this message.\n\nRegards,\nWarehouse Operations",
    )

    result = case_auditor_node(
        {
            "requester": held_case.requester,
            "subject": held_case.subject,
            "body": held_case.body,
            "classification": classification,
            "result": held_case,
            "agent_trace": [],
        }
    )

    audited = result["result"]
    assert audited.status == "Needs Human"
    assert audited.summary == held_case.summary
    assert any(step.action == "pass_output_contract" for step in audited.agent_trace)


def test_contact_request_without_kb_evidence_routes_to_human() -> None:
    case = process_request(
        "navee4501@gmail.com",
        "Looking for Contact details",
        "Hey team can you provide me the phone number of the warehouse manager.",
    )

    assert case.classification.request_type == "General Enquiry"
    assert case.status == "Needs Human"
    assert case.sub_topic == ""
    assert case.customer_output
    assert "Knowledge base does not contain enough evidence" in case.summary
    assert case.internal_output
    assert "Carrier Check-In Requirements" not in case.summary


def test_warehouse_service_request_routes_to_dock_planning() -> None:
    case = process_request(
        "vendor.appointments@example.com",
        "Reschedule inbound appointment FC-BLR8-7781",
        "Please reschedule appointment FC-BLR8-7781 for ASN FBA99887 from July 8 at 10:00 to July 9 after 14:00.",
    )

    assert case.classification.request_type == "Service Request"
    assert case.classification.urgency == "Medium"
    assert case.status == "Routed"
    assert case.customer_output
    assert case.internal_output
    assert "FC-BLR8-7781" in case.internal_output
    assert "FBA99887" in case.internal_output
    assert case.sla_due_at
    assert any(action.owner == "navee4501@gmail.com" for action in case.actions)
    assert [action.step for action in case.actions] == [
        "Extract required details",
        "Route to relevant department",
        "Generate confirmation to requester",
        "Set SLA timer",
    ]


def test_service_request_uses_configured_dock_planning_email(monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DOCK_PLANNING_EMAIL", "tester.dock@example.com")

    case = process_request(
        "vendor.appointments@example.com",
        "Reschedule inbound appointment FC-BLR8-7781",
        "Please reschedule appointment FC-BLR8-7781 for ASN FBA99887 from July 8 at 10:00 to July 9 after 14:00.",
    )

    assert any(action.owner == "tester.dock@example.com" for action in case.actions)


def test_service_request_missing_reference_routes_to_human() -> None:
    case = process_request(
        "vendor.appointments@example.com",
        "Reschedule inbound appointment",
        "Please reschedule my inbound appointment tomorrow.",
    )

    assert case.classification.request_type == "Service Request"
    assert case.status == "Needs Human"
    assert case.customer_output
    assert "Appointment, ASN, or PO reference" in case.internal_output
    assert any(action.step == "Hold confirmation" for action in case.actions)


def test_warehouse_safety_incident_is_escalation() -> None:
    case = process_request(
        "safety.lead@example.com",
        "Critical safety incident at dock door 12",
        "Critical safety incident at dock door 12. A forklift collision has blocked the inbound lane and supervisor attention is needed immediately.",
    )

    assert case.classification.request_type == "Escalation"
    assert case.classification.urgency == "Critical"
    assert case.status == "Needs Human"
    assert case.customer_output
    assert "supervisor" in case.customer_output.lower() or "urgent" in case.customer_output.lower()
    assert case.internal_output
    assert case.auto_resolution_paused is True
    assert any(action.step == "Draft urgent acknowledgement" for action in case.actions)


def test_no_action_branch_suppresses_response() -> None:
    case = process_request(
        "mailer@example.com",
        "Automatic reply: out of office",
        "This is an automatic reply. No action required.",
    )

    assert case.classification.request_type == "No Action"
    assert case.classification.urgency == "Low"
    assert case.status == "No Action Closed"
    assert case.customer_output == ""
    assert case.internal_output == ""
    assert any(action.step == "Suppress response" for action in case.actions)


def test_marketing_sender_closes_as_no_action() -> None:
    case = process_request(
        "info@emails.candy.ai",
        "Get ready. This is just the start",
        "Promotional update. You can unsubscribe or review legal terms at the bottom of this email.",
    )

    assert case.classification.request_type == "No Action"
    assert case.status == "No Action Closed"
    assert case.customer_output == ""


def test_marketing_credits_email_closes_as_no_action() -> None:
    case = process_request(
        "aws-marketing-email-replies@amazon.com",
        "Build your first serverless API and earn $20 in credits",
        "This marketing email shares a promotional credit offer.",
    )

    assert case.classification.request_type == "No Action"
    assert case.status == "No Action Closed"


def test_otp_security_message_closes_as_no_action() -> None:
    case = process_request(
        "onlinesbicard@sbicard.com",
        "One Time Password (OTP) for your online transaction",
        "Dear Cardholder, the One Time Password for your card transaction is valid for 10 minutes. Please do not share it.",
    )

    assert case.classification.request_type == "No Action"
    assert case.status == "No Action Closed"
    assert case.customer_output == ""


def test_delivery_notification_closes_as_no_action() -> None:
    case = process_request(
        "noreply@instamart.in",
        "Your Instamart order was successfully delivered",
        "Your order was successfully delivered. This is an automated notification.",
    )

    assert case.classification.request_type == "No Action"
    assert case.status == "No Action Closed"


def test_standalone_legal_footer_does_not_escalate() -> None:
    classification = classify(
        "Legal terms footer",
        "This email includes legal terms and privacy policy footer text.",
    )

    assert classification.request_type != "Escalation"


def test_portfolio_is_not_extracted_as_po_reference() -> None:
    signals = scan_mail_signals(
        "Portfolio update",
        "The portfolio example is ready for review.",
    )

    assert signals.po == ""


def test_unclear_no_action_classification_routes_to_human() -> None:
    result = no_action_node(
        {
            "requester": "mailer@example.com",
            "subject": "Please review",
            "body": "Please review this warehouse note when possible.",
            "classification": Classification(
                request_type="No Action",
                urgency="Low",
                confidence=0.9,
                rationale="Incorrect no-action classification.",
                tags=["no_action"],
            ),
            "agent_trace": [],
        }
    )
    case = result["result"]

    assert case.status == "Needs Human"
    assert case.customer_output
    assert "no-action signal is unclear" in case.summary.lower()


def test_low_confidence_unknown_routes_to_human() -> None:
    case = process_request("sender@example.com", "Hello", "Thanks")

    assert case.classification.request_type == "Unknown"
    assert case.status == "Needs Human"
    assert any(action.step == "Hold automation" for action in case.actions)


def test_urgent_reschedule_is_service_request_not_escalation() -> None:
    classification = classify(
        "Urgent reschedule inbound appointment FC-BLR8-7781",
        "Please urgently reschedule appointment FC-BLR8-7781 for ASN FBA99887 from July 8 to July 9.",
    )

    assert classification.request_type == "Service Request"
    assert classification.urgency == "Medium"


def test_service_request_extracts_appointment_details() -> None:
    case = process_request(
        "vendor.appointments@example.com",
        "Reschedule inbound appointment FC-BLR8-7781",
        "Please reschedule appointment FC-BLR8-7781 for ASN FBA99887 from July 8 at 10:00 to July 9 after 14:00.",
    )

    assert "FC-BLR8-7781" in case.internal_output
    assert "FBA99887" in case.internal_output


def test_customer_response_cleanup_removes_duplicate_signature_and_subject() -> None:
    cleaned = clean_customer_response_text(
        "Subject: Re: Inbound dock hours\n\n"
        "Dear Driver Dispatch,\n\n"
        "Our standard inbound receiving hours are Monday to Saturday from 06:00 to 18:00 local warehouse time.\n\n"
        "Regards,\n"
        "Warehouse Operations\n"
        "Warehouse Operations"
    )

    assert not cleaned.startswith("Subject:")
    assert cleaned.endswith("Regards,\nWarehouse Operations")
    assert cleaned.count("Warehouse Operations") == 1
