from __future__ import annotations

import base64
from email import message_from_bytes

import pytest
from fastapi.testclient import TestClient

import app.common.polling as polling
import app.dashboard.ui.case_views as case_views
import app.dashboard.ui.tabs as tabs
from app.main import app
from app.common.gmail import (
    GmailAttachment,
    GmailMessage,
    build_raw_message,
    build_reply_raw_message,
    clean_email_body,
    list_recent_message_ids,
    normalize_message,
    send_gmail_reply,
)
from app.common.storage import CaseRepository, append_case, case_exists, list_cases, list_poll_errors, update_case
from app.core.workflow import Action, CaseResult, Classification


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def test_simulate_request_api_is_not_available(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/requests/simulate",
        json={
            "requester": "driver.dispatch@example.com",
            "subject": "Inbound dock hours",
            "body": "Can you confirm inbound dock hours for Saturday?",
        },
    )

    assert response.status_code == 404
    assert client.get("/cases").json()["cases"] == []


def test_gmail_poll_api_reports_missing_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GMAIL_AUTH_MODE", "oauth")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRETS", "")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    client = TestClient(app)

    response = client.post("/gmail/poll", json={"max_results": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "credentials_required"
    assert payload["processed"] == 0


def test_gmail_poll_api_uses_shared_poller(monkeypatch) -> None:
    def fake_poll(*, max_results: int, query: str | None) -> dict[str, object]:
        return {
            "status": "processed",
            "processed": 1,
            "skipped": 0,
            "failed": 0,
            "fetched": max_results,
            "case_ids": ["case-1"],
            "errors": [],
            "query": query,
        }

    monkeypatch.setattr("app.main.poll_gmail_once", fake_poll)
    client = TestClient(app)

    response = client.post("/gmail/poll", json={"max_results": 3, "query": "in:inbox"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 1
    assert payload["fetched"] == 3
    assert payload["query"] == "in:inbox"


def test_production_status_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GMAIL_POLL_QUERY", raising=False)
    client = TestClient(app)

    response = client.get("/production/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["storage"]["backend"] == "sqlite"
    assert "auto_send_enabled" in payload["settings"]
    assert payload["settings"]["gmail_poll_query"] == "in:inbox newer_than:1d"


def test_default_gmail_query_is_one_day(monkeypatch) -> None:
    monkeypatch.delenv("GMAIL_POLL_QUERY", raising=False)

    class FakeList:
        def __init__(self) -> None:
            self.query = ""

        def users(self) -> "FakeList":
            return self

        def messages(self) -> "FakeList":
            return self

        def list(self, *, userId: str, q: str, maxResults: int, pageToken: str | None = None) -> "FakeList":
            self.query = q
            return self

        def execute(self) -> dict[str, object]:
            return {"messages": [{"id": "msg-1"}]}

    service = FakeList()

    assert list_recent_message_ids(service, max_results=1) == ["msg-1"]
    assert service.query == "in:inbox newer_than:1d"


def test_poll_query_respects_requested_window() -> None:
    assert polling.effective_gmail_query("in:inbox newer_than:7d") == "in:inbox newer_than:7d"
    assert polling.effective_gmail_query("in:inbox older_than:30d") == "in:inbox older_than:30d"
    assert polling.effective_gmail_query("  in:inbox   newer_than:30d  ") == "in:inbox newer_than:30d"


def test_normalize_message_cleans_html_and_records_metadata() -> None:
    raw = {
        "id": "msg-1",
        "threadId": "thread-1",
        "internalDate": "1783497600000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Driver <driver@example.com>"},
                {"name": "Reply-To", "value": "ops@example.com"},
                {"name": "Subject", "value": "Inbound dock hours"},
                {"name": "Message-ID", "value": "<msg-1@example.com>"},
                {"name": "References", "value": "<prev@example.com>"},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": encoded("<p>Can you confirm dock hours?</p><br>On Tuesday, someone wrote:<blockquote>old reply</blockquote>")},
                },
                {
                    "filename": "bol.pdf",
                    "mimeType": "application/pdf",
                    "body": {"attachmentId": "att-1"},
                },
            ],
        },
    }

    message = normalize_message(raw)

    assert message.requester == "driver@example.com"
    assert message.reply_to == "ops@example.com"
    assert message.body == "Can you confirm dock hours?"
    assert message.received_at == "2026-07-08 08:00 UTC"
    assert message.attachments == [GmailAttachment(filename="bol.pdf", mime_type="application/pdf")]


def test_clean_email_body_strips_raw_and_escaped_html() -> None:
    body = """
    &lt;div&gt;Hello manager,&lt;/div&gt;
    <p>Please review <strong>door 3</strong>.</p>
    <style>.hidden { display: none; }</style>
    <script>alert("tracking")</script>
    -->
    <br>
    Regards,<br>Dock Team
    """

    cleaned = clean_email_body(body)

    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "-->" not in cleaned
    assert "Hello manager," in cleaned
    assert "Please review door 3." in cleaned
    assert "Regards," in cleaned
    assert "Dock Team" in cleaned
    assert "tracking" not in cleaned


def test_assistant_reply_view_text_is_plain_text_without_subject_header() -> None:
    cleaned = case_views.clean_assistant_reply_view_text(
        "<p>Subject: Re: Dock hours</p><p>Hello,</p><p>Dock hours are 8 AM to 6 PM.</p>"
    )

    assert cleaned == "Hello,\nDock hours are 8 AM to 6 PM."
    assert "<" not in cleaned
    assert ">" not in cleaned


def test_poll_gmail_once_processes_unseen_messages(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(polling, "credentials_configured", lambda: True)
    monkeypatch.setattr(polling, "build_gmail_service", lambda: object())
    monkeypatch.setattr(polling, "list_recent_message_ids", lambda service, max_results, query: ["msg-1"])
    monkeypatch.setattr(
        polling,
        "fetch_message",
        lambda service, message_id: GmailMessage(
            message_id=message_id,
            thread_id="thread-1",
            requester="driver.dispatch@example.com",
            subject="Inbound dock hours",
            body="Can you confirm inbound dock hours for Saturday?",
        ),
    )

    first = polling.poll_gmail_once(max_results=10)
    second = polling.poll_gmail_once(max_results=10)

    assert first["status"] == "processed"
    assert first["processed"] == 1
    assert first["query"] == "in:inbox newer_than:1d"
    assert second["status"] == "idle"
    assert second["skipped"] == 1


def test_poll_gmail_once_persists_gmail_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(polling, "credentials_configured", lambda: True)
    monkeypatch.setattr(polling, "build_gmail_service", lambda: object())
    monkeypatch.setattr(polling, "list_recent_message_ids", lambda service, max_results, query: ["msg-1"])
    monkeypatch.setattr(
        polling,
        "fetch_message",
        lambda service, message_id: GmailMessage(
            message_id=message_id,
            thread_id="thread-1",
            requester="driver.dispatch@example.com",
            subject="Inbound dock hours",
            body="Can you confirm inbound dock hours for Saturday?",
            reply_to="reply@example.com",
            rfc_message_id="<msg-1@example.com>",
            received_at="2026-07-08 00:00 UTC",
            attachments=[GmailAttachment("dock-slip.pdf", "application/pdf")],
        ),
    )

    result = polling.poll_gmail_once(max_results=10)
    stored = list_cases()[0]

    assert result["processed"] == 1
    assert stored["source_message_id"] == "msg-1"
    assert stored["source_thread_id"] == "thread-1"
    assert stored["source_reply_to"] == "reply@example.com"
    assert stored["received_at"] == "2026-07-08 00:00 UTC"
    assert stored["attachment_count"] == 1
    assert stored["attachment_names"] == ["dock-slip.pdf"]


def eligible_general_case() -> CaseResult:
    return CaseResult(
        id="case-1",
        created_at="2026-07-08 00:00 UTC",
        requester="driver.dispatch@example.com",
        subject="Inbound dock hours",
        body="Can you confirm inbound dock hours for Saturday?",
        classification=Classification(
            request_type="General Enquiry",
            urgency="Low",
            confidence=0.95,
            rationale="Safe knowledge-base enquiry.",
            tags=["warehouse_kb"],
        ),
        status="Resolved",
        summary="Answered from knowledge base.",
        actions=[],
        customer_output="Hello,\n\nInbound dock hours are Monday to Saturday.\n\nRegards,\nWarehouse Operations",
        sub_topic="dock_hours",
    )


def eligible_service_case() -> CaseResult:
    case = eligible_general_case()
    case.classification.request_type = "Service Request"
    case.classification.urgency = "Medium"
    case.classification.rationale = "Inbound appointment reschedule request routed to dock planning."
    case.classification.tags = ["service_request", "appointment"]
    case.classification.details = {
        "requested_action": "reschedule inbound appointment",
        "appointment_id": "FC-BLR8-7781",
        "asn": "FBA99887",
        "po": "45001234",
        "requested_date": "July 11, 2026",
        "requested_time": "10:00 AM to 12:00 PM",
    }
    case.status = "Routed"
    case.summary = "Requester asked to reschedule an inbound appointment."
    case.customer_output = (
        "Dear Navee,\n\n"
        "We have received your request to reschedule the inbound appointment. "
        "Our dock planning team will review the details and follow up if additional information is required.\n\n"
        "Regards,\nWarehouse Operations"
    )
    case.internal_output = (
        "Internal routing note\n"
        "Requester: driver.dispatch@example.com\n"
        "Route to dock planning for appointment reschedule review."
    )
    case.actions = [
        Action(
            "Route to relevant department",
            "Dock planning should review the requested appointment change.",
            "dock@example.com",
        )
    ]
    case.sub_topic = ""
    return case


def test_build_reply_raw_message_preserves_thread_headers() -> None:
    original = GmailMessage(
        message_id="msg-1",
        thread_id="thread-1",
        requester="from@example.com",
        reply_to="reply@example.com",
        subject="Inbound dock hours",
        body="Question",
        rfc_message_id="<original@example.com>",
        references="<previous@example.com>",
    )

    raw = build_reply_raw_message(original, "Response body")
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))

    assert parsed["To"] == "reply@example.com"
    assert parsed["Subject"] == "Re: Inbound dock hours"
    assert parsed["In-Reply-To"] == "<original@example.com>"
    assert parsed["References"] == "<previous@example.com> <original@example.com>"
    assert parsed.get_payload().strip() == "Response body"


def test_send_safety_blocks_internal_text() -> None:
    original = GmailMessage(
        message_id="msg-1",
        thread_id="thread-1",
        requester="from@example.com",
        subject="Inbound dock hours",
        body="Question",
    )

    with pytest.raises(ValueError, match="internal routing text"):
        build_reply_raw_message(original, "Internal routing note\nRequester: driver@example.com")


def test_build_raw_message_allows_internal_text_when_explicit() -> None:
    raw = build_raw_message(
        to="dock@example.com",
        subject="Inbox AI routed Service Request",
        body="Internal routing note\nRequester: driver@example.com\nRoute to dock planning.",
        allow_internal=True,
    )
    parsed = message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))

    assert parsed["To"] == "dock@example.com"
    assert parsed["Subject"] == "Inbox AI routed Service Request"
    assert "Internal routing note" in parsed.get_payload()
    assert "Requester: driver@example.com" in parsed.get_payload()


def test_send_gmail_reply_uses_original_thread(monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DRY_RUN", "false")

    class FakeService:
        def __init__(self) -> None:
            self.body: dict[str, str] = {}

        def users(self) -> "FakeService":
            return self

        def messages(self) -> "FakeService":
            return self

        def send(self, *, userId: str, body: dict[str, str]) -> "FakeService":
            self.body = body
            return self

        def execute(self) -> dict[str, str]:
            return {"id": "sent-1", "threadId": self.body["threadId"]}

    service = FakeService()
    original = GmailMessage(
        message_id="msg-1",
        thread_id="thread-1",
        requester="driver.dispatch@example.com",
        subject="Inbound dock hours",
        body="Question",
    )

    result = send_gmail_reply(service, original, "Response body")

    assert result == {"sent_message_id": "sent-1", "thread_id": "thread-1"}
    assert service.body["threadId"] == "thread-1"
    assert service.body["raw"]


def test_dry_run_blocks_outbound_send(monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DRY_RUN", "true")

    class ExplodingService:
        def users(self) -> "ExplodingService":
            raise AssertionError("Gmail API must not be called in dry-run mode")

    original = GmailMessage(
        message_id="msg-1",
        thread_id="thread-1",
        requester="driver.dispatch@example.com",
        subject="Inbound dock hours",
        body="Question",
    )

    result = send_gmail_reply(ExplodingService(), original, "Response body")

    assert result == {"sent_message_id": "dryrun", "thread_id": "thread-1"}


def test_send_policy_allows_safe_general_and_service_cases(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_SEND_ENABLED", "true")
    general = eligible_general_case()
    service = eligible_general_case()
    service.classification.request_type = "Service Request"
    service.classification.urgency = "Medium"
    service.status = "Routed"
    service.sub_topic = ""

    assert polling.send_policy(general)[0] is True
    assert polling.send_policy(service)[0] is True


def test_send_policy_blocks_no_action_and_low_confidence(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_SEND_ENABLED", "true")
    no_action = eligible_general_case()
    no_action.classification.request_type = "No Action"
    no_action.status = "No Action Closed"
    no_action.customer_output = ""
    low_confidence = eligible_general_case()
    low_confidence.classification.confidence = 0.79
    placeholder = eligible_general_case()
    placeholder.customer_output = "Hello {{name}}"

    assert polling.send_policy(no_action)[0] is False
    assert polling.send_policy(low_confidence)[0] is False
    assert polling.send_policy(placeholder)[0] is False


def test_poll_gmail_once_sends_eligible_case(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTO_SEND_ENABLED", "true")
    monkeypatch.setattr(polling, "credentials_configured", lambda: True)
    monkeypatch.setattr(polling, "build_gmail_service", lambda: object())
    monkeypatch.setattr(polling, "list_recent_message_ids", lambda service, max_results, query: ["msg-1"])
    monkeypatch.setattr(
        polling,
        "fetch_message",
        lambda service, message_id: GmailMessage(
            message_id=message_id,
            thread_id="thread-1",
            requester="driver.dispatch@example.com",
            subject="Inbound dock hours",
            body="Can you confirm inbound dock hours for Saturday?",
        ),
    )
    monkeypatch.setattr(polling, "process_request", lambda requester, subject, body: eligible_general_case())
    monkeypatch.setattr(
        polling,
        "send_gmail_reply",
        lambda service, message, response_body: {"sent_message_id": "sent-1", "thread_id": "thread-1"},
    )

    result = polling.poll_gmail_once(max_results=10)
    cases = list_cases()

    assert result["sent"] == 1
    assert result["not_sent"] == 0
    assert result["send_failed"] == 0
    assert cases[0]["outbound_status"] == "sent"
    assert cases[0]["sent_message_id"] == "sent-1"


def test_poll_gmail_once_forwards_service_request_to_internal_team(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTO_SEND_ENABLED", "true")
    monkeypatch.setenv("INBOX_AI_DOCK_PLANNING_EMAIL", "dock@example.com")
    monkeypatch.setattr(polling, "credentials_configured", lambda: True)
    monkeypatch.setattr(polling, "build_gmail_service", lambda: object())
    monkeypatch.setattr(polling, "list_recent_message_ids", lambda service, max_results, query: ["msg-1"])
    monkeypatch.setattr(
        polling,
        "fetch_message",
        lambda service, message_id: GmailMessage(
            message_id=message_id,
            thread_id="thread-1",
            requester="vendor@example.com",
            subject="Reschedule appointment FC-BLR8-7781",
            body="Please reschedule appointment FC-BLR8-7781 for ASN FBA99887.",
            reply_to="vendor.reply@example.com",
            received_at="2026-07-09 08:00 UTC",
        ),
    )

    def fake_process_request(requester: str, subject: str, body: str) -> CaseResult:
        case = eligible_service_case()
        case.requester = requester
        case.subject = subject
        case.body = body
        case.internal_output = (
            "Internal routing note\n"
            f"Requester: {requester}\n"
            "Route to dock planning for appointment reschedule review."
        )
        return case

    monkeypatch.setattr(polling, "process_request", fake_process_request)
    replied: dict[str, object] = {}
    monkeypatch.setattr(
        polling,
        "send_gmail_reply",
        lambda service, message, response_body: replied.update({"message": message, "body": response_body})
        or {"sent_message_id": "reply-1", "thread_id": "thread-1"},
    )
    forwarded: dict[str, object] = {}

    def fake_send_gmail_message(
        service: object,
        *,
        to: str,
        subject: str,
        body: str,
        sender: str | None = None,
        allow_internal: bool = False,
    ) -> dict[str, str]:
        forwarded.update({"to": to, "subject": subject, "body": body, "allow_internal": allow_internal})
        return {"sent_message_id": "internal-1", "thread_id": ""}

    monkeypatch.setattr(polling, "send_gmail_message", fake_send_gmail_message)

    result = polling.poll_gmail_once(max_results=10)
    stored = list_cases()[0]

    assert result["sent"] == 1
    assert result["not_sent"] == 0
    assert result["internal_sent"] == 1
    assert stored["outbound_status"] == "sent"
    assert stored["sent_message_id"] == "reply-1"
    assert stored["internal_notification_status"] == "sent"
    assert stored["internal_notification_to"] == "dock@example.com"
    assert stored["internal_notification_message_id"] == "internal-1"
    assert isinstance(replied["message"], GmailMessage)
    assert "dock planning team will review" in str(replied["body"])
    assert forwarded["to"] == "dock@example.com"
    assert forwarded["allow_internal"] is True
    assert str(forwarded["subject"]) == "Fwd: Reschedule appointment FC-BLR8-7781"
    assert "Hi Dock planning team," in str(forwarded["body"])
    assert "Please look into this matter." in str(forwarded["body"])
    assert "---------- Forwarded message ---------" in str(forwarded["body"])
    assert "From: vendor@example.com" in str(forwarded["body"])
    assert "Subject: Reschedule appointment FC-BLR8-7781" in str(forwarded["body"])
    assert "Please reschedule appointment FC-BLR8-7781 for ASN FBA99887." in str(forwarded["body"])
    assert "What the mail is saying" not in str(forwarded["body"])
    assert "Requester confirmation" not in str(forwarded["body"])
    assert "SLA due" not in str(forwarded["body"])
    assert "Case reference" not in str(forwarded["body"])
    assert "Internal routing note" not in str(forwarded["body"])


def test_poll_gmail_once_records_processing_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(polling, "credentials_configured", lambda: True)
    monkeypatch.setattr(polling, "build_gmail_service", lambda: object())
    monkeypatch.setattr(polling, "list_recent_message_ids", lambda service, max_results, query: ["msg-1"])

    def explode(service: object, message_id: str) -> GmailMessage:
        raise RuntimeError("fetch failed")

    monkeypatch.setattr(polling, "fetch_message", explode)

    result = polling.poll_gmail_once(max_results=10, query="in:inbox newer_than:1d")
    errors = list_poll_errors()

    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert errors[0]["message_id"] == "msg-1"
    assert errors[0]["stage"] == "process"
    assert errors[0]["query"] == "in:inbox newer_than:1d"


def test_sqlite_storage_prevents_duplicate_source_message(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    first = append_case(eligible_general_case(), source="gmail", source_message_id="msg-1")
    duplicate_case = eligible_general_case()
    duplicate_case.id = "case-2"

    second = append_case(duplicate_case, source="gmail", source_message_id="msg-1")

    assert first["id"] == "case-1"
    assert second["id"] == "case-1"
    assert case_exists("gmail", "msg-1") is True
    assert len(list_cases()) == 1


def test_update_case_persists_manual_outbound_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    case = eligible_general_case()
    append_case(case, source="gmail", source_message_id="msg-1")

    case.outbound_status = "sent"
    case.outbound_reason = "Sent manually by operator to navee4501@gmail.com."
    case.sent_message_id = "manual-sent-1"
    update_case(case, source="gmail", source_message_id="msg-1")

    stored = list_cases()[0]
    assert stored["outbound_status"] == "sent"
    assert stored["outbound_reason"] == "Sent manually by operator to navee4501@gmail.com."
    assert stored["sent_message_id"] == "manual-sent-1"


def test_mark_resolved_without_send_discards_unsent_draft(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    case = eligible_general_case()
    case.status = "Needs Human"
    case.outbound_status = "not_sent"
    record = append_case(case, source="gmail", source_message_id="msg-1")

    case_views.mark_case_resolved(case, record, reason="Manager marked as resolved from Inbox Queue")

    stored = list_cases()[0]
    resolved = case_views.case_from_record(stored)
    assert stored["status"] == "Resolved"
    assert stored["customer_output"] == ""
    assert stored["outbound_status"] == "not_sent"
    assert stored["dashboard_hidden"] is True
    assert "without sending the assistant draft" in stored["outbound_reason"]
    assert any("draft discarded" in item.lower() for item in stored["log"])
    assert case_views.is_resolved_without_send(resolved) is True
    assert case_views.is_auto_reply_candidate(resolved) is False
    assert case_views.is_dashboard_visible_case(resolved) is False


def test_mark_resolved_confirms_already_resolved_case_without_clearing_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    case = eligible_general_case()
    case.status = "Resolved"
    case.outbound_status = "not_sent"
    record = append_case(case, source="gmail", source_message_id="msg-resolved")

    case_views.mark_case_resolved(case, record, reason="Manager marked as resolved from Inbox Queue")

    stored = list_cases()[0]
    assert stored["status"] == "Resolved"
    assert stored["customer_output"] == "Hello,\n\nInbound dock hours are Monday to Saturday.\n\nRegards,\nWarehouse Operations"
    assert stored["outbound_status"] == "not_sent"
    assert stored["dashboard_hidden"] is True
    assert "without sending the assistant draft" not in stored["outbound_reason"]
    assert any("manager confirmed resolved" in item.lower() for item in stored["log"])


def test_mark_resolved_confirms_no_action_closed_case_without_status_change(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    case = eligible_general_case()
    case.classification.request_type = "No Action"
    case.status = "No Action Closed"
    case.customer_output = ""
    record = append_case(case, source="gmail", source_message_id="msg-no-action")

    case_views.mark_case_resolved(case, record, reason="Manager marked as resolved from Inbox Queue")

    stored = list_cases()[0]
    assert stored["status"] == "No Action Closed"
    assert stored["customer_output"] == ""
    assert stored["dashboard_hidden"] is True
    assert any("manager confirmed resolved" in item.lower() for item in stored["log"])


def test_old_marked_resolved_case_is_not_reply_candidate() -> None:
    case = eligible_general_case()
    case.status = "Resolved"
    case.outbound_status = "not_sent"
    case.log.append("Manager marked as resolved from Inbox Queue: status changed from Routed to Resolved")

    assert case.customer_output
    assert case_views.is_resolved_without_send(case) is True
    assert case_views.is_auto_reply_candidate(case) is False
    assert case_views.is_dashboard_visible_case(case) is False


def test_routed_service_request_is_requester_reply_candidate() -> None:
    case = eligible_service_case()

    assert case.status == "Routed"
    assert case_views.is_auto_reply_candidate(case) is True


def test_sent_case_is_not_requester_reply_candidate() -> None:
    case = eligible_service_case()
    case.outbound_status = "sent"
    case.sent_message_id = "reply-1"

    assert case_views.is_auto_reply_candidate(case) is False


def test_sent_acknowledgement_is_reply_history_not_sendable_candidate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    case = eligible_service_case()
    case.outbound_status = "sent"
    case.outbound_reason = "Eligible for mailbox auto-reply."
    record = append_case(case, source="gmail", source_message_id="msg-sent-service")

    assert case_views.is_auto_reply_candidate(case_views.case_from_record(record)) is False
    assert tabs.is_sent_reply_record(record) is True
    assert tabs.is_held_reply_record(record) is False


def test_display_outbound_reason_describes_auto_sent_acknowledgement() -> None:
    case = eligible_service_case()
    case.outbound_status = "sent"
    case.outbound_reason = "Eligible for mailbox auto-reply."

    assert case_views.display_outbound_reason(case) == "Acknowledgement was sent automatically during Gmail polling."


def test_send_internal_forward_updates_stored_case(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INBOX_AI_DOCK_PLANNING_EMAIL", "dock@example.com")
    case = eligible_service_case()
    case.requester = "vendor@example.com"
    case.subject = "Reschedule appointment FC-BLR8-7781"
    case.body = "Please reschedule appointment FC-BLR8-7781 for ASN FBA99887."
    record = append_case(case, source="gmail", source_message_id="msg-service-forward")

    monkeypatch.setattr(case_views, "build_gmail_service", lambda: object())
    sent_payload: dict[str, object] = {}

    def fake_send_gmail_message(
        service: object,
        *,
        to: str,
        subject: str,
        body: str,
        sender: str | None = None,
        allow_internal: bool = False,
    ) -> dict[str, str]:
        sent_payload.update({"to": to, "subject": subject, "body": body, "allow_internal": allow_internal})
        return {"sent_message_id": "internal-1", "thread_id": ""}

    monkeypatch.setattr(case_views, "send_gmail_message", fake_send_gmail_message)

    success, message = case_views.send_internal_forward(case, record)
    stored = list_cases()[0]

    assert success is True
    assert message == "Team forward sent to dock@example.com."
    assert stored["internal_notification_status"] == "sent"
    assert stored["internal_notification_to"] == "dock@example.com"
    assert stored["internal_notification_message_id"] == "internal-1"
    assert sent_payload["to"] == "dock@example.com"
    assert sent_payload["allow_internal"] is True
    assert "---------- Forwarded message ---------" in str(sent_payload["body"])
    assert "Please look into this matter" in str(sent_payload["body"])
    assert "Requester confirmation" not in str(sent_payload["body"])
    assert "Case reference" not in str(sent_payload["body"])
    assert "Internal routing note" not in str(sent_payload["body"])


def test_case_repository_wrapper_matches_module_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    repo = CaseRepository()
    case = eligible_general_case()

    repo.append_case(case, source="gmail", source_message_id="msg-1")
    case.outbound_status = "sent"
    repo.update_case(case, source="gmail", source_message_id="msg-1")

    records = repo.list_cases(limit=1)
    assert repo.case_exists("gmail", "msg-1") is True
    assert len(records) == 1
    assert records[0]["outbound_status"] == "sent"
    assert repo.get_case("case-1")["source_message_id"] == "msg-1"
    assert repo.status()["case_count"] == 1


def test_manual_operator_reply_resolves_human_review_general_case(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    case = eligible_general_case()
    case.status = "Needs Human"
    case.outbound_status = "not_sent"
    record = append_case(case, source="gmail", source_message_id="msg-1")

    monkeypatch.setattr(case_views, "build_gmail_service", lambda: object())
    threaded: dict[str, object] = {}
    monkeypatch.setattr(
        case_views,
        "send_gmail_reply",
        lambda service, original, body: threaded.update({"original": original, "body": body})
        or {"sent_message_id": "manual-sent-1", "thread_id": "thread-1"},
    )
    monkeypatch.setattr(
        case_views,
        "send_gmail_message",
        lambda *args, **kwargs: pytest.fail("Gmail records should use threaded replies"),
    )

    success, message = case_views.send_operator_reply(
        case,
        record,
        recipient="navee4501@gmail.com",
        body="Hello,\n\nSharing the requested contact details.\n\nRegards,\nWarehouse Operations",
    )

    stored = list_cases()[0]
    assert success is True
    assert message == "Mail sent to navee4501@gmail.com."
    assert stored["status"] == "Resolved"
    assert stored["outbound_status"] == "sent"
    assert stored["sent_message_id"] == "manual-sent-1"
    assert any("status changed from Needs Human to Resolved" in item for item in stored["log"])
    assert case_views.is_auto_reply_candidate(case_views.case_from_record(stored)) is False
    assert isinstance(threaded["original"], GmailMessage)
    assert threaded["original"].message_id == "msg-1"


def test_manual_operator_reply_completes_complaint_review(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    case = eligible_general_case()
    case.status = "Needs Human"
    case.outbound_status = "not_sent"
    case.classification.request_type = "Complaint"
    case.classification.urgency = "High"
    case.classification.rationale = "Complaint requires manager acknowledgement."
    record = append_case(case, source="gmail", source_message_id="msg-complaint-1")

    monkeypatch.setattr(case_views, "build_gmail_service", lambda: object())
    monkeypatch.setattr(
        case_views,
        "send_gmail_reply",
        lambda service, original, body: {"sent_message_id": "manual-complaint-1", "thread_id": "thread-1"},
    )

    success, message = case_views.send_operator_reply(
        case,
        record,
        recipient="vendor@example.com",
        body="Hello,\n\nThe warehouse operations lead is reviewing this issue.\n\nRegards,\nWarehouse Operations",
    )

    stored = list_cases()[0]
    assert success is True
    assert message == "Mail sent to vendor@example.com."
    assert stored["status"] == "Resolved"
    assert stored["outbound_status"] == "sent"
    assert stored["sent_message_id"] == "manual-complaint-1"
    assert any("status changed from Needs Human to Resolved" in item for item in stored["log"])


def test_manual_operator_reply_resolves_service_request_review(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INBOX_AI_DATA_DIR", str(tmp_path))
    case = eligible_general_case()
    case.status = "Needs Human"
    case.outbound_status = "not_sent"
    case.classification.request_type = "Service Request"
    case.classification.urgency = "Medium"
    case.classification.rationale = "Service request needs manager reply."
    record = append_case(case, source="gmail", source_message_id="msg-service-1")

    monkeypatch.setattr(case_views, "build_gmail_service", lambda: object())
    monkeypatch.setattr(
        case_views,
        "send_gmail_reply",
        lambda service, original, body: {"sent_message_id": "manual-service-1", "thread_id": "thread-1"},
    )

    success, message = case_views.send_operator_reply(
        case,
        record,
        recipient="vendor@example.com",
        body="Hello,\n\nDock planning will review the appointment request.\n\nRegards,\nWarehouse Operations",
    )

    stored = list_cases()[0]
    assert success is True
    assert message == "Mail sent to vendor@example.com."
    assert stored["status"] == "Resolved"
    assert stored["outbound_status"] == "sent"
    assert stored["sent_message_id"] == "manual-service-1"
    assert any("status changed from Needs Human to Resolved" in item for item in stored["log"])
