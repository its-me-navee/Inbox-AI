"""LLM-backed classification, evidence checks, extraction, and response generation."""

from __future__ import annotations

from app.core.classification import (
    APPOINTMENT_ACTIONS,
    Classification,
    ClassificationPayload,
    combined_text,
    has_service_signal,
)
from app.core.knowledge.catalog import Article, match_article
from app.core.workflow.helpers import clean_customer_response_text, greeting, trace
from app.core.workflow.models import AgentTrace, EvidenceDecision, EvidencePayload, ServiceRequestDetails
from app.common.llm import invoke_structured, invoke_text, llm_enabled
from app.common.prompts import (
    CLASSIFICATION_PROMPT,
    COMPLAINT_ACK_PROMPT,
    ESCALATION_ACK_PROMPT,
    EVIDENCE_GATE_PROMPT,
    GENERAL_ENQUIRY_RESPONSE_PROMPT,
    HUMAN_REVIEW_REPLY_PROMPT,
    SERVICE_REQUEST_CONFIRMATION_PROMPT,
    SERVICE_REQUEST_EXTRACTION_PROMPT,
)

__all__ = [
    "classify_with_llm",
    "evaluate_kb_answerability",
    "extract_service_request_details",
    "format_service_routing_note",
    "generate_complaint_acknowledgement",
    "generate_escalation_acknowledgement",
    "generate_general_response",
    "generate_human_review_reply",
    "generate_service_request_confirmation",
    "missing_service_information",
    "search_warehouse_kb",
]


def _require_llm() -> None:
    if not llm_enabled():
        raise RuntimeError("Set GROQ_API_KEY or GROQ_API_KEY1/2/3 for LLM-backed workflow processing.")


def _required_text(content: str, *, source: str) -> str:
    cleaned = clean_customer_response_text(content)
    if not cleaned:
        raise RuntimeError(f"{source} returned an empty response.")
    return cleaned


def search_warehouse_kb(subject: str, body: str) -> tuple[Article | None, int, AgentTrace]:
    article, score = match_article(subject, body)
    observation = f"Matched {article.title}; topic={article.topic}; score={score}" if article else "No matching KB article found."
    return article, score, trace(
        "Knowledge Base Tool",
        "Search warehouse knowledge base before any General Enquiry response.",
        "search_warehouse_kb",
        observation,
    )


def missing_service_information(subject: str, body: str, details: ServiceRequestDetails) -> str:
    text = combined_text(subject, body)
    if not has_service_signal(subject, body):
        return "The message does not contain a clear warehouse service action."
    if not details.requested_action:
        return "The requested warehouse action could not be extracted."
    if any(item in text or item in details.requested_action.lower() for item in APPOINTMENT_ACTIONS):
        if not any((details.appointment_id, details.asn, details.po)):
            return "Appointment, ASN, or PO reference is required before routing an appointment request."
    return ""


def classify_with_llm(requester: str, subject: str, body: str) -> tuple[Classification, AgentTrace]:
    _require_llm()
    payload = invoke_structured(
        CLASSIFICATION_PROMPT,
        f"Requester: {requester or 'unknown'}\nSubject: {subject}\n\nEmail body:\n{body}",
        ClassificationPayload,
        temperature=0,
    )
    classification = Classification(
        request_type=payload.request_type,
        urgency=payload.urgency,
        confidence=payload.confidence,
        rationale=payload.rationale,
        tags=payload.tags,
        details=payload.extracted_details,
        source="groq",
    )
    return classification, trace(
        "Classification Agent",
        "Ask Groq to create request_type, urgency, tags, extracted details, confidence, and rationale.",
        "groq_structured_classification",
        f"{classification.request_type} / {classification.urgency}; tags={', '.join(classification.tags)}",
    )


def evaluate_kb_answerability(subject: str, body: str, article: Article | None, score: int) -> tuple[EvidenceDecision, AgentTrace]:
    if not article:
        decision = EvidenceDecision(
            can_answer=False,
            confidence=0.95,
            missing_information="No knowledge-base article matched the requested information.",
            rationale="No KB article matched the request.",
        )
        return decision, trace(
            "Evidence Gate Agent",
            "Check whether retrieved knowledge-base facts can directly answer the request.",
            "kb_evidence_check",
            decision.rationale,
        )

    _require_llm()
    facts = "\n".join(f"- {fact}" for fact in article.facts)
    payload = invoke_structured(
        EVIDENCE_GATE_PROMPT,
        f"Subject: {subject}\nEmail body:\n{body}\n\nRetrieved KB title: {article.title}\nMatch score: {score}\nKB facts:\n{facts}",
        EvidencePayload,
        temperature=0,
    )
    decision = EvidenceDecision(
        can_answer=payload.can_answer,
        confidence=payload.confidence,
        missing_information=payload.missing_information,
        rationale=payload.rationale,
    )
    return decision, trace(
        "Evidence Gate Agent",
        "Ask Groq whether the KB facts are sufficient for the exact request.",
        "groq_evidence_check",
        f"can_answer={decision.can_answer}; confidence={decision.confidence:.2f}; {decision.rationale}",
    )


def generate_general_response(requester: str, subject: str, body: str, article: Article) -> tuple[str, str]:
    _require_llm()
    facts = "\n".join(f"- {fact}" for fact in article.facts)
    content = invoke_text(
        GENERAL_ENQUIRY_RESPONSE_PROMPT,
        f"Greeting to use: {greeting(requester)}\nSubject: {subject}\nBody: {body}\n\nKB topic: {article.title}\nFacts:\n{facts}",
    )
    return _required_text(content, source="General enquiry response generation"), "groq"


def generate_complaint_acknowledgement(requester: str, subject: str, body: str, classification: Classification) -> tuple[str, str]:
    _require_llm()
    content = invoke_text(
        COMPLAINT_ACK_PROMPT,
        f"Requester: {requester or 'unknown'}\nSubject: {subject}\nBody: {body}\nClassification rationale: {classification.rationale}",
    )
    return _required_text(content, source="Complaint acknowledgement generation"), "groq"


def generate_escalation_acknowledgement(requester: str, subject: str, body: str, classification: Classification) -> tuple[str, str]:
    _require_llm()
    content = invoke_text(
        ESCALATION_ACK_PROMPT,
        f"Requester: {requester or 'unknown'}\nSubject: {subject}\nBody: {body}\nClassification rationale: {classification.rationale}",
    )
    return _required_text(content, source="Escalation acknowledgement generation"), "groq"


def extract_service_request_details(subject: str, body: str, classification: Classification) -> tuple[ServiceRequestDetails, str]:
    _require_llm()
    payload = invoke_structured(
        SERVICE_REQUEST_EXTRACTION_PROMPT,
        f"Subject: {subject}\nBody: {body}\nClassification details: {classification.details}",
        ServiceRequestDetails,
        temperature=0,
    )
    return payload, "groq"


def generate_service_request_confirmation(
    requester: str,
    subject: str,
    details: ServiceRequestDetails,
) -> tuple[str, str]:
    _require_llm()
    extracted = "\n".join(
        f"- {key}: {value}"
        for key, value in details.model_dump().items()
        if value
    )
    content = invoke_text(
        SERVICE_REQUEST_CONFIRMATION_PROMPT,
        f"Requester: {requester or 'unknown'}\nSubject: {subject}\nExtracted details:\n{extracted}",
    )
    return _required_text(content, source="Service request confirmation generation"), "groq"


def format_service_routing_note(requester: str, subject: str, details: ServiceRequestDetails) -> str:
    lines = [
        "Warehouse service request",
        f"Requester: {requester}",
        f"Subject: {subject}",
        f"Requested action: {details.requested_action or 'not specified'}",
    ]
    if details.appointment_id:
        lines.append(f"Appointment ID: {details.appointment_id}")
    if details.asn:
        lines.append(f"ASN: {details.asn}")
    if details.po:
        lines.append(f"PO: {details.po}")
    if details.requested_date or details.requested_time:
        lines.append(f"Requested slot: {details.requested_date} {details.requested_time}".strip())
    return "\n".join(lines)


def generate_human_review_reply(
    requester: str,
    subject: str,
    body: str,
    reason: str,
    missing_information: str = "",
) -> tuple[str, str]:
    _require_llm()
    info_needed = (missing_information or "").strip()
    info_line = f"Information needed: {info_needed}" if info_needed else "Information needed: none - this needs operator judgement."
    content = invoke_text(
        HUMAN_REVIEW_REPLY_PROMPT,
        f"Greeting to use: {greeting(requester)}\nRequester: {requester or 'unknown'}\nSubject: {subject}\nBody: {body}\nWhy this is held: {reason}\n{info_line}",
    )
    return _required_text(content, source="Human review reply generation"), "groq"
