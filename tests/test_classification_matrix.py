from __future__ import annotations

import pytest

from app.core.workflow import classify, process_request


FULL_TEXT_MAIL_CASES = [
    {
        "id": "complaint_receiving_dispute",
        "requester": "carrier-escalations@example.com",
        "subject": "Receiving discrepancy for ASN WHX9021",
        "body": """Hello Warehouse Operations,

Our carrier delivered 24 pallets for ASN WHX9021 against PO 784512 this morning.
The receiving record now shows only 21 pallets, and three cartons were marked damaged.
This discrepancy is creating a chargeback dispute with the vendor. Please review the receiving record and advise next steps.

Regards,
Carrier Escalations""",
        "request_type": "Complaint",
        "urgency": "High",
        "status": "Needs Human",
    },
    {
        "id": "general_enquiry_kb_answerable",
        "requester": "dispatch@example.com",
        "subject": "Carrier check-in document question",
        "body": """Hello,

Can you confirm what documents a driver needs at carrier check-in for an inbound load?
We need to know whether the BOL, ASN, PO, and photo ID are required before we release the driver to the site.

Thank you,
Dispatch""",
        "request_type": "General Enquiry",
        "urgency": "Low",
        "status": "Resolved",
    },
    {
        "id": "service_request_appointment_change",
        "requester": "vendor-planning@example.com",
        "subject": "Please reschedule inbound appointment FC-NYC9-3812",
        "body": """Hello Dock Planning,

Please reschedule appointment FC-NYC9-3812 for ASN WHX3344 and PO 128900.
The current slot is July 12 at 08:00, and we need to move it to July 13 after 14:00 because the trailer will miss the original departure.

Regards,
Vendor Planning""",
        "request_type": "Service Request",
        "urgency": "Medium",
        "status": "Routed",
    },
    {
        "id": "escalation_active_hazmat_block",
        "requester": "yard-lead@example.com",
        "subject": "Active hazmat spill blocking outbound lane",
        "body": """Supervisor team,

There is an active hazmat spill near dock door 4.
Two outbound lanes are blocked, drivers are waiting in the yard, and supervisor attention is needed immediately.
Please pause automated handling and route this to the on-site lead.

Yard Lead""",
        "request_type": "Escalation",
        "urgency": "Critical",
        "status": "Needs Human",
    },
    {
        "id": "no_action_automated_notification",
        "requester": "notifications@example.com",
        "subject": "System notification: billing statement available",
        "body": """This is an automated notification from the account system.

Your monthly billing statement is available for download. This mailbox is not monitored.
No action is required from Warehouse Operations.

Notification Service""",
        "request_type": "No Action",
        "urgency": "Low",
        "status": "No Action Closed",
    },
    {
        "id": "unknown_insufficient_intent",
        "requester": "sender@example.com",
        "subject": "Urgent follow up",
        "body": """Hello team,

This is urgent, but I do not have the location, appointment reference, or actual request details yet.
Please review when possible and I will send more context later.

Thanks""",
        "request_type": "Unknown",
        "urgency": "Medium",
        "status": "Needs Human",
    },
]


@pytest.mark.parametrize("mail", FULL_TEXT_MAIL_CASES, ids=[case["id"] for case in FULL_TEXT_MAIL_CASES])
def test_full_text_mail_classification_matrix(mail: dict[str, str]) -> None:
    case = process_request(mail["requester"], mail["subject"], mail["body"])

    assert case.classification.request_type == mail["request_type"]
    assert case.classification.urgency == mail["urgency"]
    assert case.status == mail["status"]
    assert case.classification.rationale
    assert case.classification.tags


def test_urgent_language_without_operational_evidence_is_not_escalation() -> None:
    classification = classify(
        "Urgent follow up",
        "This is urgent, but I do not have a warehouse location, appointment reference, incident, or requested action yet.",
    )

    assert classification.request_type == "Unknown"
    assert classification.urgency == "Medium"
