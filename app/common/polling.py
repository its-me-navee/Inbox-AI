from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.common.settings import DEFAULT_GMAIL_POLL_QUERY, app_settings
from app.core.workflow import CaseResult, clean_customer_response_text, fmt_time, process_request, utc_now
from app.common.gmail import (
    GmailMessage,
    build_gmail_service,
    credentials_configured,
    fetch_message,
    list_recent_message_ids,
    send_gmail_reply,
    validate_gmail_send_content,
)
from app.common.storage import append_case, append_poll_error, case_exists, resolve_poll_errors_for_message
from app.common.logging import get_logger, log_event


logger = get_logger("polling")


@dataclass
class PollCounters:
    sent: int = 0
    not_sent: int = 0
    send_failed: int = 0

    def record_send_result(self, *, sent: bool, failed: bool) -> None:
        if sent:
            self.sent += 1
        elif failed:
            self.send_failed += 1
        else:
            self.not_sent += 1

    def add(self, other: "PollCounters") -> None:
        self.sent += other.sent
        self.not_sent += other.not_sent
        self.send_failed += other.send_failed

    def as_dict(self) -> dict[str, int]:
        return {
            "sent": self.sent,
            "not_sent": self.not_sent,
            "send_failed": self.send_failed,
        }


def _empty_result(status: str, note: str) -> dict[str, Any]:
    return {
        "status": status,
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "sent": 0,
        "not_sent": 0,
        "send_failed": 0,
        "case_ids": [],
        "errors": [],
        "note": note,
    }


def _poll_status(processed_count: int, error_count: int) -> str:
    if error_count and processed_count:
        return "partial"
    if error_count:
        return "failed"
    return "processed" if processed_count else "idle"


def _stored_error_summary(stored_error: dict[str, Any], message_id: str, stage: str, exc: Exception) -> dict[str, str]:
    return {
        "message_id": message_id,
        "stage": stage,
        "error": exc.__class__.__name__,
        "id": str(stored_error.get("id", "")),
    }


def _poll_result(
    *,
    status: str,
    processed_cases: list[dict[str, Any]],
    skipped: int,
    failed: int,
    fetched: int,
    counters: PollCounters,
    errors: list[dict[str, str]],
    query: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "processed": len(processed_cases),
        "skipped": skipped,
        "failed": failed,
        **counters.as_dict(),
        "fetched": fetched,
        "case_ids": [case["id"] for case in processed_cases],
        "errors": errors,
        "query": query,
    }


def effective_gmail_query(query: str | None = None) -> str:
    raw = query if query is not None else app_settings().gmail_poll_query
    cleaned = (raw or DEFAULT_GMAIL_POLL_QUERY).strip() or DEFAULT_GMAIL_POLL_QUERY
    return " ".join(cleaned.split())


def send_policy(case: CaseResult) -> tuple[bool, str]:
    settings = app_settings()
    request_type = case.classification.request_type
    if not settings.auto_send_enabled:
        return False, "Auto-send is disabled by production safety settings."
    if case.status == "Needs Human" or case.auto_resolution_paused:
        return False, "Human review required."
    if request_type in {"No Action", "Complaint", "Escalation", "Unknown"}:
        return False, f"{request_type} cases are not eligible for auto-send."
    if request_type not in {"General Enquiry", "Service Request"}:
        return False, f"{request_type} is not an auto-send branch."
    if request_type == "General Enquiry" and not settings.auto_send_general_enquiry:
        return False, "General Enquiry auto-send is disabled."
    if request_type == "Service Request" and not settings.auto_send_service_request:
        return False, "Service Request auto-send is disabled."
    response = clean_customer_response_text(case.customer_output)
    if not response:
        return False, "No customer response was generated."
    validation_error = validate_gmail_send_content("requester@example.com", response)
    if validation_error:
        return False, validation_error
    if case.classification.confidence < settings.min_send_confidence:
        return False, f"Classification confidence below {settings.min_send_confidence:.2f}."
    if request_type == "General Enquiry" and (case.status != "Resolved" or not case.sub_topic):
        return False, "General enquiry is not safely resolved from the knowledge base."
    if request_type == "Service Request" and case.status != "Routed":
        return False, "Service request has not been routed."
    return True, "Eligible for mailbox auto-reply."


def apply_send_policy(service: Any, message: GmailMessage, case: CaseResult) -> tuple[bool, bool]:
    allowed, reason = send_policy(case)
    case.outbound_reason = reason
    if not allowed:
        log_event(
            logger,
            "gmail_send_skipped",
            message_id=message.message_id,
            case_id=case.id,
            request_type=case.classification.request_type,
            status=case.status,
            reason=reason,
        )
        case.outbound_status = "not_sent"
        case.log.append(f"Outbound reply skipped: {reason}")
        return False, False
    recipient = message.reply_to or message.requester
    validation_error = validate_gmail_send_content(recipient, case.customer_output)
    if validation_error:
        log_event(
            logger,
            "gmail_send_validation_blocked",
            level=logging.WARNING,
            message_id=message.message_id,
            case_id=case.id,
            reason=validation_error,
        )
        case.outbound_status = "not_sent"
        case.outbound_reason = validation_error
        case.log.append(f"Outbound reply skipped: {validation_error}")
        return False, False

    try:
        sent = send_gmail_reply(service, message, case.customer_output)
        case.outbound_status = "sent"
        case.sent_at = fmt_time(utc_now())
        case.sent_message_id = sent.get("sent_message_id", "")
        log_event(
            logger,
            "gmail_send_success",
            message_id=message.message_id,
            case_id=case.id,
            sent_message_id=case.sent_message_id or "unknown",
        )
        case.log.append(f"Outbound reply sent: {case.sent_message_id or 'unknown message id'}")
        return True, False
    except Exception as exc:
        case.outbound_status = "failed"
        case.send_error = exc.__class__.__name__
        logger.exception("gmail_send_failed message_id=%s case_id=%s", message.message_id, case.id)
        case.log.append(f"Outbound reply failed: {case.send_error}")
        return False, True


def attach_gmail_metadata(case: CaseResult, message: GmailMessage) -> None:
    case.source_message_id = message.message_id
    case.source_thread_id = message.thread_id or ""
    case.source_rfc_message_id = message.rfc_message_id
    case.source_reply_to = message.reply_to
    case.received_at = message.received_at
    case.attachment_count = len(message.attachments)
    case.attachment_names = [attachment.filename for attachment in message.attachments]
    case.attachment_mime_types = [attachment.mime_type for attachment in message.attachments]
    if message.attachments:
        names = ", ".join(case.attachment_names)
        case.log.append(f"Gmail attachments detected: {names}")
        if case.status != "Needs Human":
            case.log.append("Attachment review note: attachments are listed but not parsed by automation.")


def record_poll_error(message_id: str, stage: str, exc: Exception, query: str | None) -> dict[str, Any]:
    log_event(
        logger,
        "gmail_poll_error",
        level=logging.ERROR,
        message_id=message_id,
        stage=stage,
        error=exc.__class__.__name__,
        detail=str(exc)[:500],
        query=query or "",
    )
    return append_poll_error(
        {
            "message_id": message_id,
            "stage": stage,
            "error": exc.__class__.__name__,
            "detail": str(exc)[:500],
            "query": query or "",
        }
    )


def process_gmail_message(service: Any, message_id: str, *, query: str | None = None) -> tuple[dict[str, Any] | None, PollCounters]:
    counters = PollCounters()
    had_operational_error = False
    log_event(logger, "gmail_message_start", message_id=message_id, query=query or "")
    message = fetch_message(service, message_id)
    log_event(
        logger,
        "gmail_message_fetched",
        message_id=message_id,
        requester=message.requester,
        subject=message.subject,
        attachments=len(message.attachments),
    )
    case = process_request(message.requester, message.subject, message.body)
    attach_gmail_metadata(case, message)
    log_event(
        logger,
        "workflow_case_created",
        message_id=message_id,
        case_id=case.id,
        request_type=case.classification.request_type,
        urgency=case.classification.urgency,
        confidence=case.classification.confidence,
        status=case.status,
        summary=case.summary,
    )
    sent, failed = apply_send_policy(service, message, case)
    counters.record_send_result(sent=sent, failed=failed)
    if failed:
        had_operational_error = True
        record_poll_error(message_id, "send", RuntimeError(case.send_error or "send_failed"), query)

    record = append_case(case, source="gmail", source_message_id=message.message_id)
    log_event(
        logger,
        "gmail_message_done",
        message_id=message_id,
        case_id=record.get("id") if record else case.id,
        status=case.status,
        outbound_status=case.outbound_status,
        sent=counters.sent,
        not_sent=counters.not_sent,
        send_failed=counters.send_failed,
    )
    if not had_operational_error:
        resolve_poll_errors_for_message(message_id)
    return record, counters


def poll_gmail_once(*, max_results: int = 10, query: str | None = None) -> dict[str, Any]:
    effective_query = effective_gmail_query(query)
    log_event(logger, "gmail_poll_start", max_results=max_results, query=effective_query)
    if not credentials_configured():
        log_event(logger, "gmail_poll_credentials_required", level=logging.WARNING, query=effective_query)
        return {
            **_empty_result(
                "credentials_required",
                "For personal Gmail, set OAuth credentials, open Streamlit, and click Connect Gmail before polling.",
            ),
            "query": effective_query,
        }

    try:
        service = build_gmail_service()
    except RuntimeError as exc:
        log_event(logger, "gmail_poll_authorization_required", level=logging.WARNING, error=str(exc), query=effective_query)
        return {**_empty_result("authorization_required", str(exc)), "query": effective_query}

    message_ids = list_recent_message_ids(service, max_results=max_results, query=effective_query)
    log_event(logger, "gmail_poll_fetched_ids", fetched=len(message_ids), query=effective_query)
    processed_cases: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    skipped = 0
    counters = PollCounters()

    for message_id in message_ids:
        if case_exists("gmail", message_id):
            log_event(logger, "gmail_message_skipped_duplicate", message_id=message_id)
            skipped += 1
            continue
        try:
            record, message_counters = process_gmail_message(service, message_id, query=effective_query)
            if record:
                processed_cases.append(record)
            counters.add(message_counters)
        except Exception as exc:
            logger.exception("gmail_message_process_failed message_id=%s", message_id)
            stored_error = record_poll_error(message_id, "process", exc, effective_query)
            errors.append(_stored_error_summary(stored_error, message_id, "process", exc))

    status = _poll_status(len(processed_cases), len(errors))
    result = _poll_result(
        status=status,
        processed_cases=processed_cases,
        skipped=skipped,
        failed=len(errors),
        fetched=len(message_ids),
        counters=counters,
        errors=errors,
        query=effective_query,
    )
    log_event(
        logger,
        "gmail_poll_done",
        status=status,
        fetched=len(message_ids),
        processed=len(processed_cases),
        skipped=skipped,
        failed=len(errors),
        sent=counters.sent,
        not_sent=counters.not_sent,
        send_failed=counters.send_failed,
    )
    return result


def retry_gmail_message(message_id: str, *, query: str | None = None) -> dict[str, Any]:
    effective_query = effective_gmail_query(query)
    log_event(logger, "gmail_retry_start", message_id=message_id, query=effective_query)
    if not credentials_configured():
        log_event(logger, "gmail_retry_credentials_required", level=logging.WARNING, message_id=message_id)
        return {**_empty_result("credentials_required", "Gmail credentials are not configured."), "query": effective_query}
    if case_exists("gmail", message_id):
        resolve_poll_errors_for_message(message_id)
        log_event(logger, "gmail_retry_skipped_duplicate", message_id=message_id)
        return {
            **_empty_result("skipped_duplicate", "Message already has a stored case."),
            "skipped": 1,
            "fetched": 1,
            "query": effective_query,
        }
    try:
        service = build_gmail_service()
        record, counters = process_gmail_message(service, message_id, query=effective_query)
    except Exception as exc:
        logger.exception("gmail_retry_failed message_id=%s", message_id)
        stored_error = record_poll_error(message_id, "retry", exc, effective_query)
        return {
            **_empty_result("failed", f"Retry failed: {exc.__class__.__name__}"),
            "failed": 1,
            "fetched": 1,
            "errors": [_stored_error_summary(stored_error, message_id, "retry", exc)],
            "query": effective_query,
        }
    processed_cases = [record] if record else []
    result = _poll_result(
        status="processed",
        processed_cases=processed_cases,
        skipped=0,
        failed=0,
        fetched=1,
        counters=counters,
        errors=[],
        query=effective_query,
    )
    log_event(
        logger,
        "gmail_retry_done",
        message_id=message_id,
        processed=result["processed"],
        sent=result["sent"],
        send_failed=result["send_failed"],
    )
    return result
