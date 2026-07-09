from __future__ import annotations

import pytest

from app.core.knowledge.catalog import keyword_matches, match_article


def test_keyword_matching_does_not_match_inside_words() -> None:
    assert keyword_matches("please provide contact details", "id") is False
    assert keyword_matches("bring a valid photo id", "id") is True


def test_contact_request_does_not_match_unrelated_check_in_article() -> None:
    article, score = match_article(
        "Looking for Contact details",
        "Can you provide me the phone number of the warehouse manager?",
    )

    assert article is None
    assert score == 0


@pytest.mark.parametrize(
    ("subject", "body", "topic"),
    [
        (
            "Late arrival grace period",
            "Our driver is arriving late and may miss the appointment slot. What details do you need?",
            "late_arrival_policy",
        ),
        (
            "Outbound pickup requirements",
            "Can you confirm pickup requirements for a driver pickup with a release number?",
            "outbound_pickup_requirements",
        ),
        (
            "Drop trailer yard check-in",
            "What information is needed for a drop trailer and yard check-in?",
            "yard_trailer_drop",
        ),
        (
            "Pallet height and overhang",
            "What are the rules for pallet height, overhang, and double stacked freight?",
            "pallet_limits",
        ),
        (
            "Reefer temperature log",
            "Do refrigerated loads need a temperature log and trailer temperature at arrival?",
            "temperature_controlled_loads",
        ),
        (
            "Carrier detention wait time",
            "What details are required for detention or driver waiting time review?",
            "detention_wait_time",
        ),
        (
            "Receiving discrepancy documentation",
            "What should we send for a damaged carton, OS&D, or short received shipment?",
            "receiving_discrepancy_process",
        ),
        (
            "Proof of delivery",
            "Can you share the POD, signed BOL, or receiving confirmation requirements?",
            "proof_of_delivery",
        ),
    ],
)
def test_expanded_knowledge_base_matches_operational_topics(subject: str, body: str, topic: str) -> None:
    article, score = match_article(subject, body)

    assert article is not None
    assert article.topic == topic
    assert score > 0
