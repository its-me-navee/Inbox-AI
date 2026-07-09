from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any

from app.common.environment import load_env
from app.common.settings import DEFAULT_GMAIL_POLL_QUERY, dry_run_enabled


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


@dataclass(frozen=True)
class GmailAttachment:
    filename: str
    mime_type: str = ""


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    thread_id: str | None
    requester: str
    subject: str
    body: str
    reply_to: str = ""
    rfc_message_id: str = ""
    references: str = ""
    received_at: str = ""
    attachments: list[GmailAttachment] = field(default_factory=list)


def credentials_configured() -> bool:
    load_env()
    auth_mode = os.getenv("GMAIL_AUTH_MODE", "").strip().lower()
    service_account_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    oauth_client_path = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS", "").strip()
    oauth_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    oauth_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    has_service_account_file = bool(service_account_path and Path(service_account_path).exists())
    has_oauth_client_file = bool(oauth_client_path and Path(oauth_client_path).exists())
    has_oauth_client_values = bool(oauth_client_id and oauth_client_secret)
    if auth_mode == "oauth":
        return has_oauth_client_file or has_oauth_client_values
    if auth_mode == "service_account":
        return has_service_account_file
    return has_service_account_file or has_oauth_client_file or has_oauth_client_values


def _build_service_account_gmail_service(credentials_path: str) -> Any:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=GMAIL_SCOPES,
    )
    impersonated_user = os.getenv("GOOGLE_IMPERSONATED_USER_EMAIL", "").strip()
    if impersonated_user:
        credentials = credentials.with_subject(impersonated_user)
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def oauth_token_path() -> Path:
    load_env()
    return Path(os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "data/gmail_token.json"))


def oauth_state_path() -> Path:
    return oauth_token_path().with_name("gmail_oauth_states.json")


def _save_oauth_state(state: str, code_verifier: str | None) -> None:
    if not code_verifier:
        return
    path = oauth_state_path()
    if path.exists():
        states = json.loads(path.read_text(encoding="utf-8") or "{}")
    else:
        states = {}
    states[state] = code_verifier
    if len(states) > 20:
        states = dict(list(states.items())[-20:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(states, indent=2), encoding="utf-8")


def _pop_oauth_code_verifier(state: str | None) -> str | None:
    if not state:
        return None
    path = oauth_state_path()
    if not path.exists():
        return None
    states = json.loads(path.read_text(encoding="utf-8") or "{}")
    code_verifier = states.pop(state, None)
    path.write_text(json.dumps(states, indent=2), encoding="utf-8")
    return code_verifier


def oauth_token_exists() -> bool:
    return oauth_token_path().exists()


def oauth_token_has_required_scopes() -> bool:
    if not oauth_token_exists():
        return False
    try:
        token = json.loads(oauth_token_path().read_text(encoding="utf-8"))
        granted = token.get("scopes") or token.get("scope") or []
        if isinstance(granted, str):
            granted_scopes = set(granted.split())
        else:
            granted_scopes = {str(scope) for scope in granted}
        return set(GMAIL_SCOPES).issubset(granted_scopes)
    except Exception:
        return False


def _oauth_client_config() -> tuple[dict[str, Any], str]:
    load_env()
    client_secrets_path = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS", "").strip()
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()

    if client_secrets_path and Path(client_secrets_path).exists():
        config = json.loads(Path(client_secrets_path).read_text(encoding="utf-8"))
        if "installed" in config:
            return config, "installed"
        if "web" in config:
            return config, "web"
        raise RuntimeError("Google OAuth JSON must contain an installed or web client config")

    if client_id and client_secret:
        return (
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": ["http://localhost"],
                }
            },
            "installed",
        )

    if client_id:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_SECRET is required when GOOGLE_OAUTH_CLIENT_ID is used")
    raise RuntimeError("GOOGLE_OAUTH_CLIENT_SECRETS or GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET is required")


def oauth_redirect_uri() -> str:
    load_env()
    configured = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if configured:
        return configured

    config, client_type = _oauth_client_config()
    redirect_uris = config.get(client_type, {}).get("redirect_uris", [])
    for uri in redirect_uris:
        if "localhost" in uri:
            return str(uri)
    for uri in redirect_uris:
        if "127.0.0.1" in uri:
            return str(uri)
    return "http://localhost:8501/oauth/gmail/callback"


def _allow_local_oauth_http() -> None:
    redirect_uri = oauth_redirect_uri()
    if redirect_uri.startswith("http://localhost") or redirect_uri.startswith("http://127.0.0.1"):
        if not os.environ.get("OAUTHLIB_INSECURE_TRANSPORT"):
            os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def gmail_authorization_url() -> tuple[str, str]:
    from google_auth_oauthlib.flow import Flow

    _allow_local_oauth_http()
    config, _ = _oauth_client_config()
    flow = Flow.from_client_config(config, scopes=GMAIL_SCOPES, redirect_uri=oauth_redirect_uri())
    url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    _save_oauth_state(state, flow.code_verifier)
    return url, state


def save_oauth_token_from_authorization_response(authorization_response: str, state: str | None = None) -> Path:
    from google_auth_oauthlib.flow import Flow

    _allow_local_oauth_http()
    config, _ = _oauth_client_config()
    flow = Flow.from_client_config(
        config,
        scopes=GMAIL_SCOPES,
        redirect_uri=oauth_redirect_uri(),
        state=state,
        code_verifier=_pop_oauth_code_verifier(state),
    )
    flow.fetch_token(authorization_response=authorization_response)
    path = oauth_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(flow.credentials.to_json(), encoding="utf-8")
    return path


def _build_oauth_gmail_service(client_secrets_path: str) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = oauth_token_path()
    credentials = None
    if token_path.exists():
        if not oauth_token_has_required_scopes():
            raise RuntimeError("Gmail OAuth token needs Gmail send permission. Click Connect Gmail again to re-authorize.")
        credentials = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            config, client_type = _oauth_client_config()
            if client_type == "web":
                raise RuntimeError("Gmail OAuth token is missing. Open Streamlit and click Connect Gmail first.")
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, GMAIL_SCOPES)
            credentials = flow.run_local_server(port=0, prompt="consent")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _build_oauth_gmail_service_from_env(client_id: str, client_secret: str) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = Path(os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "data/gmail_token.json"))
    credentials = None
    if token_path.exists():
        if not oauth_token_has_required_scopes():
            raise RuntimeError("Gmail OAuth token needs Gmail send permission. Re-run Gmail authorization.")
        credentials = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": ["http://localhost"],
                    }
                },
                GMAIL_SCOPES,
            )
            credentials = flow.run_local_server(port=0, prompt="consent")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def build_gmail_service() -> Any:
    load_env()
    auth_mode = os.getenv("GMAIL_AUTH_MODE", "").strip().lower()
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    oauth_client_path = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS", "").strip()
    oauth_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    oauth_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()

    if auth_mode == "oauth" or ((oauth_client_path or oauth_client_id) and not credentials_path):
        if oauth_client_path and Path(oauth_client_path).exists():
            return _build_oauth_gmail_service(oauth_client_path)
        if oauth_client_id and oauth_client_secret:
            return _build_oauth_gmail_service_from_env(oauth_client_id, oauth_client_secret)
        if oauth_client_id:
            raise RuntimeError("GOOGLE_OAUTH_CLIENT_SECRET is required when GOOGLE_OAUTH_CLIENT_ID is used")
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_SECRETS or GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET is required for Gmail OAuth polling")

    if not credentials_path:
        raise RuntimeError("Set GOOGLE_OAUTH_CLIENT_SECRETS for personal Gmail or GOOGLE_APPLICATION_CREDENTIALS for Workspace Gmail")

    return _build_service_account_gmail_service(credentials_path)


def _header(headers: list[dict[str, str]], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _decode_part_body(part: dict[str, Any]) -> str:
    data = (part.get("body") or {}).get("data")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


HTML_TAG_PATTERN = re.compile(
    r"(?is)<\s*/?\s*(?:html|head|body|p|br|div|span|a|table|thead|tbody|"
    r"tr|td|th|ul|ol|li|strong|b|em|i|style|script|blockquote|h[1-6]|"
    r"font|meta|link|img|section|article)\b[^>]*>"
)


def _html_to_text(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"(?is)<!--.*?-->", " ", value)
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", value)
    value = re.sub(r"(?i)<\s*li\b[^>]*>", "- ", value)
    value = re.sub(r"(?i)</\s*(p|div|tr|li|h[1-6]|table|section|article|blockquote)\s*>", "\n", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    return unescape(value)


def clean_email_body(value: str) -> str:
    text = unescape(value or "")
    if HTML_TAG_PATTERN.search(text):
        text = _html_to_text(text)
    text = text.replace("<!--", " ").replace("-->", " ")
    text = re.sub(r"[\u200b-\u200f\ufeff]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    quote_patterns = (
        r"\nOn .+ wrote:.*$",
        r"\n[-_]{2,}\s*Original Message\s*[-_]{2,}.*$",
        r"\nFrom:\s.+\nSent:\s.+$",
        r"\n_{5,}.*$",
    )
    for pattern in quote_patterns:
        text = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE | re.DOTALL)[0]
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(">"):
            continue
        line = re.sub(r"\s+", " ", line)
        line = re.sub(r"\s+([.,;:!?])", r"\1", line)
        lines.append(line)
    return "\n".join(lines).strip()


def _extract_body(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/plain":
        return clean_email_body(_decode_part_body(payload))
    if payload.get("mimeType") == "text/html":
        return clean_email_body(_html_to_text(_decode_part_body(payload)))

    plain_chunks: list[str] = []
    html_chunks: list[str] = []
    for part in payload.get("parts") or []:
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain":
            plain_chunks.append(_decode_part_body(part))
        elif mime_type == "text/html":
            html_chunks.append(_html_to_text(_decode_part_body(part)))
        elif part.get("parts"):
            nested = _extract_body(part)
            if nested:
                plain_chunks.append(nested)
    if plain_chunks:
        return clean_email_body("\n".join(chunk for chunk in plain_chunks if chunk))
    if html_chunks:
        return clean_email_body("\n".join(chunk for chunk in html_chunks if chunk))
    return clean_email_body(_decode_part_body(payload))


def _extract_attachments(payload: dict[str, Any]) -> list[GmailAttachment]:
    attachments: list[GmailAttachment] = []
    filename = str(payload.get("filename") or "").strip()
    body = payload.get("body") or {}
    if filename or body.get("attachmentId"):
        attachments.append(GmailAttachment(filename=filename or "(unnamed attachment)", mime_type=str(payload.get("mimeType") or "")))
    for part in payload.get("parts") or []:
        attachments.extend(_extract_attachments(part))
    return attachments


def _received_at(raw: dict[str, Any], headers: list[dict[str, str]]) -> str:
    internal_date = str(raw.get("internalDate") or "").strip()
    if internal_date.isdigit():
        return datetime.fromtimestamp(int(internal_date) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    date_header = _header(headers, "Date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return date_header
    return ""


def normalize_message(raw: dict[str, Any]) -> GmailMessage:
    payload = raw.get("payload") or {}
    headers = payload.get("headers") or []
    _, requester = parseaddr(_header(headers, "From"))
    _, reply_to = parseaddr(_header(headers, "Reply-To"))
    subject = _header(headers, "Subject")
    body = _extract_body(payload) or raw.get("snippet", "")
    attachments = _extract_attachments(payload)
    return GmailMessage(
        message_id=str(raw["id"]),
        thread_id=raw.get("threadId"),
        requester=requester or "",
        subject=subject,
        body=clean_email_body(body),
        reply_to=reply_to or requester or "",
        rfc_message_id=_header(headers, "Message-ID"),
        references=_header(headers, "References"),
        received_at=_received_at(raw, headers),
        attachments=attachments,
    )


def list_recent_message_ids(service: Any, *, max_results: int = 10, query: str | None = None) -> list[str]:
    load_env()
    user_id = os.getenv("GMAIL_USER_ID", "me")
    search_query = query if query is not None else os.getenv("GMAIL_POLL_QUERY", DEFAULT_GMAIL_POLL_QUERY)
    remaining = max(1, max_results)
    ids: list[str] = []
    page_token: str | None = None

    while remaining > 0:
        response = service.users().messages().list(
            userId=user_id,
            q=search_query,
            maxResults=min(remaining, 100),
            pageToken=page_token,
        ).execute()
        for message in response.get("messages", []):
            if message.get("id"):
                ids.append(str(message["id"]))
        remaining = max_results - len(ids)
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return list(dict.fromkeys(ids))[:max_results]


def fetch_message(service: Any, message_id: str) -> GmailMessage:
    load_env()
    user_id = os.getenv("GMAIL_USER_ID", "me")
    raw = service.users().messages().get(userId=user_id, id=message_id, format="full").execute()
    return normalize_message(raw)


def reply_subject(subject: str) -> str:
    clean_subject = subject.strip() or "(no subject)"
    if clean_subject.lower().startswith("re:"):
        return clean_subject
    return f"Re: {clean_subject}"


def validate_gmail_send_content(recipient: str, body: str) -> str:
    if not recipient.strip():
        return "Cannot send Gmail reply without a recipient."
    content = clean_email_body(body)
    if not content:
        return "Cannot send an empty Gmail reply."
    lower = content.lower()
    if any(marker in content for marker in ("{{", "}}", "[[", "]]")) or re.search(r"\b(todo|tbd)\b", lower):
        return "Reply contains unresolved placeholders."
    internal_markers = (
        "internal routing note",
        "human review required",
        "validation hold:",
        "warehouse service request\nrequester:",
        "critical warehouse escalation\nrequester:",
    )
    if any(marker in lower for marker in internal_markers):
        return "Reply appears to contain internal routing text."
    return ""


def build_reply_raw_message(original: GmailMessage, response_body: str) -> str:
    load_env()
    recipient = original.reply_to or original.requester
    validation_error = validate_gmail_send_content(recipient, response_body)
    if validation_error:
        raise ValueError(validation_error)
    message = EmailMessage()
    sender = os.getenv("GMAIL_SEND_FROM", "").strip() or os.getenv("GOOGLE_IMPERSONATED_USER_EMAIL", "").strip()
    if sender:
        message["From"] = sender
    message["To"] = recipient
    message["Subject"] = reply_subject(original.subject)
    if original.rfc_message_id:
        message["In-Reply-To"] = original.rfc_message_id
        references = f"{original.references} {original.rfc_message_id}".strip()
        message["References"] = references
    message.set_content(clean_email_body(response_body))
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")


def send_gmail_reply(service: Any, original: GmailMessage, response_body: str) -> dict[str, str]:
    load_env()
    if dry_run_enabled():
        return {"sent_message_id": "dryrun", "thread_id": original.thread_id or "dryrun"}
    user_id = os.getenv("GMAIL_USER_ID", "me")
    payload: dict[str, str] = {"raw": build_reply_raw_message(original, response_body)}
    if original.thread_id:
        payload["threadId"] = original.thread_id
    response = service.users().messages().send(userId=user_id, body=payload).execute()
    return {
        "sent_message_id": str(response.get("id", "")),
        "thread_id": str(response.get("threadId", original.thread_id or "")),
    }


def build_raw_message(*, to: str, subject: str, body: str, sender: str | None = None) -> str:
    load_env()
    validation_error = validate_gmail_send_content(to, body)
    if validation_error:
        raise ValueError(validation_error)
    message = EmailMessage()
    from_address = sender or os.getenv("GMAIL_SEND_FROM", "").strip() or os.getenv("GOOGLE_IMPERSONATED_USER_EMAIL", "").strip()
    if from_address:
        message["From"] = from_address
    message["To"] = to
    message["Subject"] = subject
    message.set_content(clean_email_body(body))
    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")


def send_gmail_message(service: Any, *, to: str, subject: str, body: str, sender: str | None = None) -> dict[str, str]:
    load_env()
    if dry_run_enabled():
        return {"sent_message_id": "dryrun", "thread_id": "dryrun"}
    user_id = os.getenv("GMAIL_USER_ID", "me")
    response = service.users().messages().send(
        userId=user_id,
        body={"raw": build_raw_message(to=to, subject=subject, body=body, sender=sender)},
    ).execute()
    return {
        "sent_message_id": str(response.get("id", "")),
        "thread_id": str(response.get("threadId", "")),
    }
