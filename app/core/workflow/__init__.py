"""Public entry point for the warehouse mail workflow.

The implementation is split across small, single-purpose modules:
- models.py:    dataclasses, pydantic payloads, and the LangGraph state type
- helpers.py:   small utilities shared by response and node modules
- responses.py: classification, evidence gate, and reply/generation logic
- classifier_nodes.py: mail reading, classification, and route audit nodes
- branch_nodes.py:     workflow branch nodes
- review.py:           shared human-review and rerouting helpers
- audit.py:            final output-contract checks
- graph.py:     graph assembly and the process_request/classify entry points

Everything below is re-exported here so existing `from app.core.workflow import
...` call sites keep working unchanged.
"""

from __future__ import annotations

from app.core.classification import Classification, SignalProfile, scan_mail_signals
from app.common.environment import load_env
from app.common.llm import llm_enabled
from app.core.workflow.graph import classify, process_request
from app.core.workflow.helpers import clean_customer_response_text, fmt_time, utc_now
from app.core.workflow.models import Action, AgentTrace, CaseResult
from app.core.workflow.audit import case_auditor_node
from app.core.workflow.branch_nodes import no_action_node
from app.core.workflow.classifier_nodes import classification_auditor_node

__all__ = [
    "Action",
    "AgentTrace",
    "CaseResult",
    "Classification",
    "SignalProfile",
    "case_auditor_node",
    "classification_auditor_node",
    "classify",
    "clean_customer_response_text",
    "fmt_time",
    "llm_enabled",
    "load_env",
    "no_action_node",
    "process_request",
    "scan_mail_signals",
    "utc_now",
]
