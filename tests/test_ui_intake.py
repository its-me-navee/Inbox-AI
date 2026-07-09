from __future__ import annotations

from app.dashboard.ui.case_views import selected_row_index, sort_records_by_urgency
from app.dashboard.ui.tabs import inbox_table_records


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


def test_inbox_table_records_hide_marked_resolved_cases() -> None:
    records = [
        {"id": "needs-human", "status": "Needs Human"},
        {"id": "marked-resolved", "status": "Resolved"},
        {"id": "closed", "status": "No Action Closed"},
    ]

    assert [record["id"] for record in inbox_table_records(records)] == ["needs-human", "closed"]
