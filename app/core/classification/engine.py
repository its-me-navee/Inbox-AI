from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field


RequestType = Literal["Complaint", "General Enquiry", "Service Request", "Escalation", "No Action", "Unknown"]
Urgency = Literal["Low", "Medium", "High", "Critical"]


NO_ACTION_PATTERNS = (
    r"\bout of office\b",
    r"\bautomatic reply\b",
    r"\bauto[- ]?reply\b",
    r"\bdo not reply\b",
    r"\bno action required\b",
    r"\bfyi only\b",
    r"\bfor your information only\b",
    r"\bnotification only\b",
    r"\bautomated\s+(?:message|email|mail|notification)\b",
    r"\bsystem[- ]generated\s+(?:message|email|mail|notification)\b",
    r"\bnewsletter\b",
    r"\bunsubscribe\b",
    r"\bmanage (?:email )?preferences\b",
    r"\bmarketing\b",
    r"\bpromotional\b",
    r"\b(?:authentication|verification|account|login|sign[- ]?in|password|multi[- ]?factor|two[- ]?factor|2fa)\s+(?:code|token|alert|notice|notification)\b",
    r"\bsecurity\s+(?:code|token)\b",
    r"\b(?:one[- ]?time|temporary)\s+(?:password|passcode|code|token)\b",
    r"\b(?:payment|billing|transaction|account)\s+(?:confirmation|notification|notice|alert|receipt|statement)\b",
    r"\b(?:receipt|invoice|statement)\s+(?:available|attached|generated|issued|ready)\b",
    r"\b(?:shipment|delivery|order|package)\s+(?:status|confirmation|notification)\b",
    r"\b(?:shipment|delivery|order|package)\s+(?:was\s+)?successfully\s+delivered\b",
    r"\bdelivery confirmation\b",
    r"\bdelivery status notification\b",
    r"\bundeliverable\b",
    r"\bbounced?\b",
)

COMPLAINT_SIGNALS = (
    "complaint",
    "unhappy",
    "angry",
    "short received",
    "missing pallet",
    "missing pallets",
    "damaged",
    "chargeback",
    "dispute",
    "late unload",
    "receiving discrepancy",
    "shortage",
)

SERVICE_ACTION_PATTERN = r"\b(reschedule|schedule|change|pickup|count|investigate|update|cancel|repair|reprint|receive|coordinate)\b"
SERVICE_RELEASE_PATTERN = r"\brelease\s+(?:the\s+)?(?:(?:inbound|outbound)\s+)?(?:trailer|load|shipment|freight|order|pallets?|inventory|stock|container)\b"
APPOINTMENT_ACTIONS = ("reschedule", "schedule", "update", "cancel", "appointment", "slot")
PO_REFERENCE_PATTERN = r"\b(PO(?:[-\s]?[0-9][A-Z0-9-]*|[-\s]+[A-Z0-9][A-Z0-9-]*))\b"
URGENT_LANGUAGE = ("critical", "urgent", "asap", "immediately")

ESCALATION_PATTERNS = (
    r"\bsafety\b",
    r"\binjur(?:y|ies|ed)\b",
    r"\bincident\b",
    r"\bforklift\b",
    r"\bcollision\b",
    r"\bblocked\s+(?:dock|lane|door|yard|operations?|inbound|outbound)\b",
    r"\bhazmat\b",
    r"\bfire\b",
    r"\btheft\b",
    r"\bsecurity\b",
    r"\blegal\s+(?:issue|matter|hold|notice|claim|action|escalation|review|risk)\b",
    r"\bregulatory\s+(?:issue|matter|hold|notice|inspection|noncompliance|review)\b",
    r"\bsupervisor\b",
    r"\bexecutive\b",
)

INFORMATION_PATTERNS = (
    r"\b(?:question|information|info)\s+(?:about|on|regarding|for)\b",
    r"\bhow do (?:i|we)\b",
    r"\bcan you (?:confirm|tell|advise|share|provide)\b",
    r"\bcould you (?:confirm|tell|advise|share|provide)\b",
    r"\bplease (?:confirm|advise|share|provide)\b",
    r"\bwhat (?:documents?|hours?|process|steps?|time|are|is|should|do|does)\b",
    r"\bwhen (?:is|are|do|does|should|can|will)\b",
    r"\bwhere (?:is|are|do|does|should|can)\b",
    r"\bwhich (?:documents?|forms?|labels?|process|dock|door)\b",
    r"\b(?:dock|receiving|inbound)\s+hours\b",
    r"\bcarrier\s+check[- ]?in\b",
    r"\bcheck[- ]?in\s+(?:documents?|requirements?|process)\b",
    r"\b(?:bol|asn|po|photo id)\s+(?:required|needed|accepted)\b",
    r"\b(?:label|labels|labeling)\s+(?:rules?|requirements?|process)\b",
    r"\b(?:phone number|contact|manager)\b",
)


@dataclass(frozen=True)
class BranchSpec:
    request_type: str
    urgency: str
    route: str
    remediation_steps: tuple[str, ...]
    terminal_status: str


BRANCH_SPECS: dict[str, BranchSpec] = {
    "Complaint": BranchSpec(
        request_type="Complaint",
        urgency="High",
        route="complaint",
        remediation_steps=("Acknowledge receipt", "Escalate to senior handler", "Log priority case", "Set 2-hour follow-up"),
        terminal_status="Needs Human",
    ),
    "General Enquiry": BranchSpec(
        request_type="General Enquiry",
        urgency="Low",
        route="general_enquiry",
        remediation_steps=("Classify sub-topic", "Check KB evidence", "Draft response", "Log resolved"),
        terminal_status="Resolved",
    ),
    "Service Request": BranchSpec(
        request_type="Service Request",
        urgency="Medium",
        route="service_request",
        remediation_steps=("Extract details", "Route department", "Draft confirmation", "Set SLA"),
        terminal_status="Routed",
    ),
    "Escalation": BranchSpec(
        request_type="Escalation",
        urgency="Critical",
        route="escalation",
        remediation_steps=("Flag human review", "Draft urgent acknowledgement", "Notify supervisor", "Pause automation"),
        terminal_status="Needs Human",
    ),
    "No Action": BranchSpec(
        request_type="No Action",
        urgency="Low",
        route="no_action",
        remediation_steps=("Validate no-action signal", "Suppress response", "Close"),
        terminal_status="No Action Closed",
    ),
}


@dataclass
class Classification:
    request_type: str
    urgency: str
    confidence: float
    rationale: str
    tags: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    source: str = "groq"


@dataclass
class SignalProfile:
    no_action: list[str] = field(default_factory=list)
    escalation: list[str] = field(default_factory=list)
    complaint: list[str] = field(default_factory=list)
    service: list[str] = field(default_factory=list)
    information: list[str] = field(default_factory=list)
    urgent_language: list[str] = field(default_factory=list)
    appointment_id: str = ""
    asn: str = ""
    po: str = ""

    def has_request_signal(self) -> bool:
        return any((self.escalation, self.complaint, self.service, self.information))

    def summary(self) -> str:
        parts = []
        for name in ("no_action", "escalation", "complaint", "service", "information", "urgent_language"):
            matches = getattr(self, name)
            if matches:
                parts.append(f"{name}={', '.join(matches[:4])}")
        refs = [value for value in (self.appointment_id, self.asn, self.po) if value]
        if refs:
            parts.append(f"refs={', '.join(refs)}")
        return "; ".join(parts) if parts else "no strong workflow signal"


class ClassificationPayload(BaseModel):
    request_type: RequestType
    urgency: Urgency
    confidence: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    extracted_details: dict[str, Any] = Field(default_factory=dict)
    rationale: str


def combined_text(subject: str, body: str) -> str:
    return f"{subject}\n{body}".lower()


def combined_mail_text(subject: str, body: str, requester: str = "") -> str:
    return f"{requester}\n{subject}\n{body}".lower()


def matched_literal_signals(subject: str, body: str, signals: tuple[str, ...], requester: str = "") -> list[str]:
    text = combined_mail_text(subject, body, requester)
    return [signal for signal in signals if signal in text]


def matched_regex_signals(subject: str, body: str, patterns: tuple[str, ...], requester: str = "") -> list[str]:
    text = combined_mail_text(subject, body, requester)
    return [pattern for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE)]


def match_is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 90) : start].lower()
    return bool(
        re.search(
            r"(?:\bno\b|\bnot\b|\bwithout\b|\bdo not have\b|\bdoes not have\b|\bdon't have\b|\bdoesn't have\b)[\w\s,;:-]{0,80}$",
            prefix,
        )
    )


def matched_contextual_regex_signals(subject: str, body: str, patterns: tuple[str, ...], requester: str = "") -> list[str]:
    text = combined_mail_text(subject, body, requester)
    matches: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match and not match_is_negated(text, match.start()):
            matches.append(pattern)
    return matches


def first_regex_value(subject: str, body: str, pattern: str) -> str:
    match = re.search(pattern, f"{subject}\n{body}", flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def normalize_asn(value: str) -> str:
    return re.sub(r"^ASN\s*", "", value.strip().upper())


def service_actions(text: str) -> list[str]:
    actions = list(re.findall(SERVICE_ACTION_PATTERN, text))
    if re.search(SERVICE_RELEASE_PATTERN, text):
        actions.append("release")
    return list(dict.fromkeys(actions))


def scan_mail_signals(subject: str, body: str, requester: str = "") -> SignalProfile:
    text = combined_text(subject, body)
    asn = first_regex_value(subject, body, r"\b(ASN\s*[A-Z0-9]+|FBA\d+)\b")
    return SignalProfile(
        no_action=matched_regex_signals(subject, body, NO_ACTION_PATTERNS, requester),
        escalation=matched_contextual_regex_signals(subject, body, ESCALATION_PATTERNS),
        complaint=matched_literal_signals(subject, body, COMPLAINT_SIGNALS),
        service=service_actions(text),
        information=matched_regex_signals(subject, body, INFORMATION_PATTERNS, requester),
        urgent_language=matched_literal_signals(subject, body, URGENT_LANGUAGE),
        appointment_id=first_regex_value(subject, body, r"\b(FC-[A-Z0-9-]+|\b[A-Z]{2,}\d{4,})\b"),
        asn=normalize_asn(asn) if asn else "",
        po=first_regex_value(subject, body, PO_REFERENCE_PATTERN),
    )


def has_no_action_signal(subject: str, body: str) -> bool:
    return bool(scan_mail_signals(subject, body).no_action)


def has_escalation_signal(subject: str, body: str) -> bool:
    return bool(scan_mail_signals(subject, body).escalation)


def has_complaint_signal(subject: str, body: str) -> bool:
    return bool(scan_mail_signals(subject, body).complaint)


def has_service_signal(subject: str, body: str) -> bool:
    return bool(scan_mail_signals(subject, body).service)


def has_information_signal(subject: str, body: str) -> bool:
    return bool(scan_mail_signals(subject, body).information)


def audited_classification(
    classification: Classification,
    request_type: str,
    reason: str,
    *,
    confidence: float,
    tags: list[str],
    details: dict[str, Any] | None = None,
) -> Classification:
    spec = BRANCH_SPECS[request_type]
    return Classification(
        request_type=request_type,
        urgency=spec.urgency,
        confidence=max(classification.confidence, confidence),
        rationale=f"{classification.rationale} Classification audit: {reason}",
        tags=list(dict.fromkeys([*classification.tags, *tags, "classification_audited"])),
        details={**classification.details, **(details or {}), "audit_reason": reason},
        source=f"{classification.source}+audit",
    )


def audit_classification_against_signals(classification: Classification, signals: SignalProfile) -> tuple[Classification, str]:
    if signals.no_action:
        if classification.request_type == "No Action":
            return classification, "Accepted No Action from explicit automated, FYI, receipt, marketing, or no-action evidence."
        return audited_classification(
            classification,
            "No Action",
            "explicit automated, FYI, receipt, delivery failure, marketing, or no-action evidence was found",
            confidence=0.93,
            tags=["no_action"],
            details={"reason": "automated_or_fyi"},
        ), "Corrected to No Action from explicit no-action evidence."

    if classification.request_type == "No Action" and not signals.has_request_signal():
        return Classification(
            request_type="Unknown",
            urgency="Medium",
            confidence=min(classification.confidence, 0.55),
            rationale=f"{classification.rationale} Classification audit: no explicit no-action or workflow signal supported automatic closure.",
            tags=list(dict.fromkeys([*classification.tags, "human_review", "classification_audited"])),
            details={
                **classification.details,
                "audit_reason": "No explicit no-action or workflow signal supported automatic closure.",
            },
            source=f"{classification.source}+audit",
        ), "Downgraded to Unknown because No Action lacked explicit no-action evidence."

    if signals.escalation and classification.request_type != "Escalation":
        return audited_classification(
            classification,
            "Escalation",
            "safety, security, legal, supervisor, or blocked-operations evidence outranks the candidate branch",
            confidence=0.9,
            tags=["critical_ops", "supervisor_review"],
            details={"signals": signals.escalation},
        ), "Corrected to Escalation from critical operations evidence."

    if signals.complaint and not signals.escalation and classification.request_type not in {"Complaint"}:
        details = {"sub_topic": "receiving_discrepancy"} if any(item in signals.complaint for item in ("short received", "shortage", "chargeback", "receiving discrepancy")) else {}
        return audited_classification(
            classification,
            "Complaint",
            "complaint or receiving-dispute evidence was stronger than the candidate branch",
            confidence=0.84,
            tags=["warehouse_complaint", "priority_review"],
            details=details,
        ), "Corrected to Complaint from complaint evidence."

    if signals.service and not signals.escalation and not signals.complaint and classification.request_type != "Service Request":
        details = {"requested_action": " ".join(dict.fromkeys(signals.service))}
        if signals.appointment_id:
            details["appointment_id"] = signals.appointment_id
        if signals.asn:
            details["asn"] = signals.asn
        if signals.po:
            details["po"] = signals.po
        return audited_classification(
            classification,
            "Service Request",
            "warehouse action request evidence was found and no critical or complaint evidence outranked it",
            confidence=0.8,
            tags=["warehouse_service_request", "sla_required"],
            details=details,
        ), "Corrected to Service Request from action-request evidence."

    if signals.information and not signals.escalation and not signals.complaint and not signals.service and classification.request_type != "General Enquiry":
        return audited_classification(
            classification,
            "General Enquiry",
            "informational warehouse question evidence was found and no work-request or critical evidence outranked it",
            confidence=0.8,
            tags=["warehouse_kb", "general_enquiry"],
        ), "Corrected to General Enquiry from informational evidence."

    if not signals.has_request_signal() and not signals.no_action and classification.request_type != "Unknown" and classification.confidence < 0.75:
        return Classification(
            request_type="Unknown",
            urgency="Medium",
            confidence=min(classification.confidence, 0.55),
            rationale=f"{classification.rationale} Classification audit: no reliable workflow signal supported the candidate branch.",
            tags=list(dict.fromkeys([*classification.tags, "human_review", "classification_audited"])),
            details={**classification.details, "audit_reason": "No reliable workflow signal supported the candidate branch."},
            source=f"{classification.source}+audit",
        ), "Downgraded to Unknown because no reliable branch signal supported a low-confidence classification."

    return classification, "Classification accepted against signal profile."
