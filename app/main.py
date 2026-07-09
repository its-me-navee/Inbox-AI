from __future__ import annotations

from html import escape
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.api.schemas import GmailPollRequest
from app.common.settings import app_settings, public_settings
from app.common.gmail import save_oauth_token_from_authorization_response
from app.common.storage import get_case, list_cases, storage_status
from app.common.polling import poll_gmail_once


def create_app() -> FastAPI:
    application = FastAPI(
        title="Inbox AI API",
        description="Gmail polling, reply sending, and intake API for the warehouse mail workflow.",
        version="0.4.0",
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/production/status")
    def production_status() -> dict[str, Any]:
        return {
            "status": "ok",
            "settings": public_settings(),
            "storage": storage_status(),
        }

    @application.get("/cases")
    def cases() -> dict[str, Any]:
        return {"cases": list_cases()}

    @application.get("/cases/{case_id}")
    def case_detail(case_id: str) -> dict[str, Any]:
        case = get_case(case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        return case

    @application.post("/gmail/poll")
    def gmail_poll(payload: GmailPollRequest | None = None) -> dict[str, Any]:
        request = payload or GmailPollRequest()
        return poll_gmail_once(max_results=request.max_results, query=request.query)

    @application.get("/oauth/gmail/callback")
    def gmail_oauth_callback(request: Request) -> Response:
        try:
            save_oauth_token_from_authorization_response(
                str(request.url),
                state=request.query_params.get("state"),
            )
        except Exception as exc:
            return HTMLResponse(
                f"""
                <!DOCTYPE html>
                <html lang="en">
                  <head>
                    <meta charset="utf-8" />
                    <meta name="viewport" content="width=device-width, initial-scale=1" />
                    <title>Gmail authorization failed</title>
                    <style>
                      body {{
                        font-family: Inter, system-ui, sans-serif;
                        background: #f8fafc;
                        color: #0f172a;
                        margin: 0;
                        min-height: 100vh;
                        display: grid;
                        place-items: center;
                      }}
                      .card {{
                        background: #fff;
                        border: 1px solid #e2e8f0;
                        border-radius: 12px;
                        padding: 2rem;
                        max-width: 480px;
                        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
                      }}
                      h1 {{ font-size: 1.25rem; margin: 0 0 0.75rem; }}
                      p {{ color: #64748b; line-height: 1.5; }}
                      code {{ background: #f1f5f9; padding: 0.15rem 0.35rem; border-radius: 4px; }}
                    </style>
                  </head>
                  <body>
                    <div class="card">
                      <h1>Gmail authorization failed</h1>
                      <p>{escape(str(exc))}</p>
                      <p>Close this tab and click <code>Connect Gmail</code> in the dashboard to try again.</p>
                    </div>
                  </body>
                </html>
                """,
                status_code=400,
            )

        redirect_to = app_settings().oauth_success_redirect_url
        return RedirectResponse(f"{redirect_to}?gmail=connected", status_code=303)

    return application


app = create_app()
