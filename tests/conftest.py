from __future__ import annotations

import re
from typing import Any

import pytest

import app.core.workflow.responses as responses
from app.core.classification import (
    PO_REFERENCE_PATTERN,
    SERVICE_ACTION_PATTERN,
    ClassificationPayload,
    combined_text,
    scan_mail_signals,
)
from app.core.workflow.models import EvidencePayload, ServiceRequestDetails


def _field(prompt: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.*)$", prompt, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _body(prompt: str) -> str:
    match = re.search(r"(?:Email body|Body):\n?(.*)", prompt, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def _classification_payload(prompt: str) -> ClassificationPayload:
    requester = _field(prompt, "Requester")
    subject = _field(prompt, "Subject")
    body = _body(prompt)
    text = combined_text(subject, body)
    signals = scan_mail_signals(subject, body, requester)
    details: dict[str, Any] = {}

    if signals.no_action:
        return ClassificationPayload(
            request_type="No Action",
            urgency="Low",
            confidence=0.93,
            tags=["automated_mail", "no_action", "low_risk"],
            extracted_details={"reason": "automated_or_fyi"},
            rationale="The message is automated, FYI-only, or explicitly says no action is required.",
        )
    if signals.escalation:
        return ClassificationPayload(
            request_type="Escalation",
            urgency="Critical",
            confidence=0.9,
            tags=["critical_ops", "supervisor_review", "auto_resolution_paused"],
            extracted_details={"signals": ["warehouse_escalation"]},
            rationale="The message describes a critical warehouse issue requiring immediate human review.",
        )
    if signals.complaint:
        if any(word in text for word in ("asn", "po", "pallet", "pallets", "chargeback", "receiving", "short")):
            details["sub_topic"] = "receiving_discrepancy"
        if signals.asn:
            details["asn"] = signals.asn
        if signals.po:
            details["po"] = signals.po
        return ClassificationPayload(
            request_type="Complaint",
            urgency="High",
            confidence=0.84,
            tags=["warehouse_complaint", "receiving_dispute", "priority_review"],
            extracted_details=details,
            rationale="The message describes a warehouse receiving complaint or dispute.",
        )
    if signals.service:
        details["requested_action"] = " ".join(dict.fromkeys(signals.service))
        if signals.appointment_id:
            details["appointment_id"] = signals.appointment_id
        if signals.asn:
            details["asn"] = signals.asn
        if signals.po:
            details["po"] = signals.po
        return ClassificationPayload(
            request_type="Service Request",
            urgency="Medium",
            confidence=0.8,
            tags=["warehouse_service_request", "dock_planning", "sla_required"],
            extracted_details=details,
            rationale="The requester is asking the warehouse team to perform operational work.",
        )
    if signals.information:
        return ClassificationPayload(
            request_type="General Enquiry",
            urgency="Low",
            confidence=0.82,
            tags=["warehouse_kb", "general_enquiry", "low_risk"],
            extracted_details={},
            rationale="The message asks a warehouse information question.",
        )
    return ClassificationPayload(
        request_type="Unknown",
        urgency="Medium",
        confidence=0.45,
        tags=["unknown_intent", "human_review"],
        extracted_details={"signals": signals.urgent_language} if signals.urgent_language else {},
        rationale="The request does not clearly match a supported branch.",
    )


def _evidence_payload(prompt: str) -> EvidencePayload:
    text = prompt.lower()
    requested_sensitive_details = ("phone number", "contact number", "email address", "manager", "personal contact", "direct number")
    if any(item in text for item in requested_sensitive_details):
        return EvidencePayload(
            can_answer=False,
            confidence=0.88,
            missing_information="The requester asks for a specific contact/person detail that is not present in the retrieved KB facts.",
            rationale="Retrieved facts do not contain the requested contact detail.",
        )
    return EvidencePayload(can_answer=True, confidence=0.72, missing_information="", rationale="Retrieved KB facts answer the request.")


def _service_details(prompt: str) -> ServiceRequestDetails:
    subject = _field(prompt, "Subject")
    body = _body(prompt)
    combined = f"{subject}\n{body}"
    text = combined.lower()
    appointment_match = re.search(r"\b(FC-[A-Z0-9-]+)\b", combined, re.IGNORECASE)
    asn_match = re.search(r"\b(ASN\s*[A-Z0-9]+|FBA\d+)\b", combined, re.IGNORECASE)
    po_match = re.search(PO_REFERENCE_PATTERN, combined, re.IGNORECASE)
    date_match = re.search(r"\b(?:from|to|on|for)\s+([A-Z][a-z]+\s+\d{1,2}(?:,\s*\d{4})?)\b", combined)
    time_match = re.search(r"\b(?:at|after|before)\s+(\d{1,2}(?::\d{2})?)\b", text)
    verbs = re.findall(SERVICE_ACTION_PATTERN, text)
    return ServiceRequestDetails(
        appointment_id=appointment_match.group(1).upper() if appointment_match else "",
        asn=asn_match.group(1).upper().replace("ASN ", "") if asn_match else "",
        po=po_match.group(1).upper() if po_match else "",
        requested_action=" ".join(dict.fromkeys(verbs)),
        requested_date=date_match.group(1) if date_match else "",
        requested_time=time_match.group(1) if time_match else "",
        notes="",
    )


def _fake_structured(system_prompt: str, human_prompt: str, schema: type[Any], *, temperature: float = 0.0) -> Any:
    if schema is ClassificationPayload:
        return _classification_payload(human_prompt)
    if schema is EvidencePayload:
        return _evidence_payload(human_prompt)
    if schema is ServiceRequestDetails:
        return _service_details(human_prompt)
    raise AssertionError(f"Unhandled structured schema: {schema}")


def _fake_text(system_prompt: str, human_prompt: str, *, temperature: float = 0.2) -> str:
    greeting_match = re.search(r"^Greeting to use:\s*(.*)$", human_prompt, flags=re.MULTILINE)
    greeting = greeting_match.group(1).strip() if greeting_match else "Hello,"
    subject = _field(human_prompt, "Subject") or "your message"

    if "warehouse complaint case" in system_prompt:
        return (
            f"{greeting}\n\n"
            f"We have received your complaint regarding {subject}. The warehouse operations lead will review this case within 2 hours.\n\n"
            "Regards,\nWarehouse Operations"
        )
    if "critical warehouse escalation" in system_prompt:
        return (
            f"{greeting}\n\n"
            "We have received your urgent message. A warehouse supervisor has been notified for immediate human review.\n\n"
            "Regards,\nWarehouse Operations"
        )
    if "confirming receipt of a service request" in system_prompt:
        return (
            f"{greeting}\n\n"
            "We received your warehouse service request. The dock planning team will review and follow up if anything else is needed.\n\n"
            "Regards,\nWarehouse Operations"
        )
    if "suggested reply" in system_prompt:
        info_match = re.search(r"Information needed:\s*(.*)", human_prompt)
        info = info_match.group(1).strip() if info_match else ""
        if info and not info.startswith("none"):
            return (
                f"{greeting}\n\n"
                f"Thanks for contacting warehouse operations regarding {subject}. Could you please share the following: {info}\n\n"
                "Regards,\nWarehouse Operations"
            )
        return (
            f"{greeting}\n\n"
            f"Thanks for contacting warehouse operations regarding {subject}. Our team is reviewing it and will follow up shortly.\n\n"
            "Regards,\nWarehouse Operations"
        )
    return (
        f"{greeting}\n\n"
        "Inbound receiving hours are Monday to Saturday, and drivers should bring the required check-in documents listed in the knowledge base.\n\n"
        "Regards,\nWarehouse Operations"
    )


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(responses, "llm_enabled", lambda: True)
    monkeypatch.setattr(responses, "invoke_structured", _fake_structured)
    monkeypatch.setattr(responses, "invoke_text", _fake_text)
