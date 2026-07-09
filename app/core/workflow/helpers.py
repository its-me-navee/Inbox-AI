"""Small, dependency-light helpers shared by the graph nodes and response generators."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.classification import SignalProfile, scan_mail_signals
from app.core.workflow.models import Action, AgentTrace, GraphState

__all__ = [
    "action",
    "base_case",
    "clean_customer_response_text",
    "fmt_time",
    "greeting",
    "signal_profile_from_state",
    "trace",
    "utc_now",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC")


def greeting(requester: str) -> str:
    if not requester:
        return "Hello,"
    name = requester.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
    return f"Hello {name},"


def clean_customer_response_text(content: str) -> str:
    lines = content.strip().splitlines()
    while lines and lines[0].strip().lower().startswith("subject:"):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)

    cleaned = "\n".join(lines).strip()
    replacements = {
        "Best regards,\nGeneral Enquiry Response Agent": "Regards,\nWarehouse Operations",
        "Best regards,\nWarehouse Operations": "Regards,\nWarehouse Operations",
        "General Enquiry Response Agent\nAmazon Warehouse Operations": "Warehouse Operations",
        "General Enquiry Response Agent": "Warehouse Operations",
        "Amazon Warehouse Operations": "Warehouse Operations",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)

    cleaned = re.sub(r"(?im)^Regards,\s*Warehouse Operations\.?\s*$", "Regards,\nWarehouse Operations", cleaned)
    lines = [line.rstrip() for line in cleaned.splitlines()]
    while (
        len(lines) >= 2
        and lines[-1].strip().lower().rstrip(".") == "warehouse operations"
        and lines[-2].strip().lower().rstrip(".") == "warehouse operations"
    ):
        lines.pop()
    return "\n".join(lines).strip()


def signal_profile_from_state(state: GraphState) -> SignalProfile:
    return state.get("signal_profile") or scan_mail_signals(state.get("subject", ""), state.get("body", ""), state.get("requester", ""))


def action(step: str, detail: str, owner: str | None = None) -> Action:
    return Action(step=step, detail=detail, owner=owner)


def trace(agent: str, thought: str, action_name: str, observation: str) -> AgentTrace:
    return AgentTrace(agent=agent, thought=thought, action=action_name, observation=observation)


def base_case(state: GraphState) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "created_at": fmt_time(utc_now()),
        "requester": state.get("requester", ""),
        "subject": state.get("subject", ""),
        "body": state.get("body", ""),
        "classification": state["classification"],
        "agent_trace": state.get("agent_trace", []),
    }
