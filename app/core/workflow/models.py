"""Dataclasses, pydantic payloads, and graph-state types shared across the workflow package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from pydantic import BaseModel, Field

from app.core.classification import Classification, SignalProfile

__all__ = [
    "Action",
    "AgentTrace",
    "CaseResult",
    "EvidenceDecision",
    "EvidencePayload",
    "GraphState",
    "ServiceRequestDetails",
]


@dataclass
class Action:
    step: str
    detail: str
    owner: str | None = None


@dataclass
class AgentTrace:
    agent: str
    thought: str
    action: str
    observation: str


@dataclass
class CaseResult:
    id: str
    created_at: str
    requester: str
    subject: str
    body: str
    classification: Classification
    status: str
    summary: str
    actions: list[Action]
    customer_output: str = ""
    internal_output: str = ""
    sub_topic: str = ""
    follow_up_at: str = ""
    sla_due_at: str = ""
    auto_resolution_paused: bool = False
    outbound_status: str = "not_evaluated"
    outbound_reason: str = ""
    sent_at: str = ""
    sent_message_id: str = ""
    send_error: str = ""
    internal_notification_status: str = "not_evaluated"
    internal_notification_reason: str = ""
    internal_notification_to: str = ""
    internal_notification_message_id: str = ""
    internal_notification_error: str = ""
    source_message_id: str = ""
    source_thread_id: str = ""
    source_rfc_message_id: str = ""
    source_reply_to: str = ""
    received_at: str = ""
    attachment_count: int = 0
    attachment_names: list[str] = field(default_factory=list)
    attachment_mime_types: list[str] = field(default_factory=list)
    dashboard_hidden: bool = False
    agent_trace: list[AgentTrace] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


class EvidencePayload(BaseModel):
    can_answer: bool
    confidence: float = Field(ge=0.0, le=1.0)
    missing_information: str = ""
    rationale: str


class ServiceRequestDetails(BaseModel):
    appointment_id: str = ""
    asn: str = ""
    po: str = ""
    requested_action: str = ""
    requested_date: str = ""
    requested_time: str = ""
    notes: str = ""


@dataclass
class EvidenceDecision:
    can_answer: bool
    confidence: float
    rationale: str
    missing_information: str = ""


class GraphState(TypedDict, total=False):
    requester: str
    subject: str
    body: str
    signal_profile: SignalProfile
    classification: Classification
    result: CaseResult
    agent_trace: list[AgentTrace]
