from __future__ import annotations

from app.dashboard.ui.case_views import operator_log_line, selected_row_index, sort_records_by_urgency
from app.dashboard.ui.tabs import inbox_resolution_action_label, inbox_table_records


def test_sort_records_by_urgency_orders_highest_priority_first() -> None:
    records = [
        {"subject": "low", "classification": {"urgency": "Low"}},
        {"subject": "critical", "classification": {"urgency": "Critical"}},
        {"subject": "medium", "classification": {"urgency": "Medium"}},
        {"subject": "high", "classification": {"urgency": "High"}},
    ]

    sorted_records = sort_records_by_urgency(records)

    assert [record["subject"] for record in sorted_records] == ["critical", "high", "medium", "low"]


def test_selected_row_index_falls_back_when_selection_is_stale() -> None:
    assert selected_row_index([4], record_count=2) == 0
    assert selected_row_index([-1], record_count=2) == 0
    assert selected_row_index([1], record_count=2) == 1


def test_inbox_table_records_keeps_full_mailbox_history() -> None:
    records = [
        {"id": "needs-human", "status": "Needs Human"},
        {"id": "routed", "status": "Routed"},
        {"id": "marked-resolved", "status": "Resolved"},
        {"id": "closed", "status": "No Action Closed"},
    ]

    assert [record["id"] for record in inbox_table_records(records)] == [
        "needs-human",
        "routed",
        "marked-resolved",
        "closed",
    ]


def test_inbox_resolution_action_label_confirms_already_closed_cases() -> None:
    assert inbox_resolution_action_label("No Action Closed") == "Confirm reviewed"
    assert inbox_resolution_action_label("Resolved") == "Confirm reviewed"
    assert inbox_resolution_action_label("Routed") == "Mark as resolved"
    assert inbox_resolution_action_label("Needs Human") == "Mark as resolved"


def test_operator_log_line_hides_gmail_message_ids() -> None:
    assert operator_log_line("Outbound reply sent: 19f4715e1b246143") == "Outbound reply sent."
    assert (
        operator_log_line("Internal notification sent to Dock planning (dock@example.com): 19f4715e30e98200")
        == "Team forward sent to Dock planning."
    )
