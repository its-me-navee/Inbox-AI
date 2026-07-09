from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Article:
    topic: str
    title: str
    keywords: tuple[str, ...]
    facts: tuple[str, ...]


ARTICLES = [
    Article(
        topic="dock_hours",
        title="Inbound Dock Hours And Check-In",
        keywords=(
            "dock hours",
            "inbound hours",
            "receiving hours",
            "weekend",
            "gate hours",
            "appointment hours",
            "documents",
            "driver",
            "check-in",
            "check in",
        ),
        facts=(
            "Standard inbound receiving runs Monday to Saturday from 06:00 to 18:00 local warehouse time.",
            "Carriers should arrive within the confirmed appointment window and check in at the guard gate first.",
            "Drivers should bring the appointment ID, ASN or PO reference, BOL, and a valid photo ID.",
            "Unscheduled arrivals may be held until the dock team confirms capacity.",
        ),
    ),
    Article(
        topic="carrier_check_in",
        title="Carrier Check-In Requirements",
        keywords=("check in", "check-in", "documents", "bol", "asn", "po", "carrier", "guard gate", "id"),
        facts=(
            "Drivers should bring the appointment ID, ASN or PO reference, BOL, and a valid photo ID.",
            "The guard gate verifies the appointment before assigning a dock door.",
            "Loads with missing ASN, PO, or BOL details may require operations review before unloading.",
        ),
    ),
    Article(
        topic="labeling_requirements",
        title="Pallet And Carton Labeling",
        keywords=("label", "labels", "carton", "pallet", "barcode", "scan", "prep"),
        facts=(
            "Each pallet and carton should have a scannable barcode label facing outward.",
            "Mixed-SKU pallets should be clearly marked and separated where possible.",
            "Unreadable or missing labels can delay receiving and may require manual reconciliation.",
        ),
    ),
    Article(
        topic="appointment_changes",
        title="Inbound Appointment Changes",
        keywords=("reschedule", "appointment", "slot", "schedule", "truck delay", "late truck", "cancel appointment"),
        facts=(
            "Appointment changes require the current appointment ID, ASN or PO reference, requested new date, and requested time window.",
            "The dock planning team confirms the new slot only after checking capacity.",
            "Late truck notices should be sent before the appointment window when possible.",
        ),
    ),
    Article(
        topic="late_arrival_policy",
        title="Late Arrival And Missed Appointment Handling",
        keywords=(
            "late arrival",
            "arriving late",
            "missed appointment",
            "missed slot",
            "late for appointment",
            "grace period",
            "driver delayed",
        ),
        facts=(
            "Drivers who expect to miss the appointment window should notify the dock team before arrival when possible.",
            "The requester should provide the appointment ID, ASN or PO reference, estimated arrival time, and reason for the delay.",
            "Late arrivals are worked in only after dock planning confirms capacity; otherwise a new appointment may be required.",
            "The warehouse should not promise a new slot until dock planning has confirmed capacity.",
        ),
    ),
    Article(
        topic="outbound_pickup_requirements",
        title="Outbound Pickup Requirements",
        keywords=(
            "outbound pickup",
            "pickup requirements",
            "pickup appointment",
            "release number",
            "trailer pickup",
            "load pickup",
            "pick up load",
            "driver pickup",
        ),
        facts=(
            "Outbound pickups require a confirmed pickup appointment or release reference before the driver is dispatched.",
            "Drivers should bring the pickup number or release reference, carrier name, trailer number when available, and a valid photo ID.",
            "The outbound team releases freight only after the load is staged, verified, and assigned to the carrier.",
            "If the pickup number or release reference is missing, the case should be routed to warehouse operations for review.",
        ),
    ),
    Article(
        topic="yard_trailer_drop",
        title="Yard Arrival, Trailer Drop, And Live Unload",
        keywords=(
            "drop trailer",
            "trailer drop",
            "live unload",
            "live load",
            "yard check-in",
            "yard check in",
            "empty trailer",
            "trailer number",
        ),
        facts=(
            "Drivers should check in at the guard gate before dropping a trailer, live unloading, or live loading.",
            "The requester should provide the carrier name, trailer number, appointment ID, ASN or PO reference, and whether the move is drop trailer or live unload.",
            "Dropped trailers should be parked only in the assigned yard location after guard gate confirmation.",
            "Empty trailer requests require operations confirmation before the driver is released.",
        ),
    ),
    Article(
        topic="pallet_limits",
        title="Pallet Dimensions, Stacking, And Weight Limits",
        keywords=(
            "pallet height",
            "pallet weight",
            "pallet dimensions",
            "overhang",
            "stack height",
            "mixed sku",
            "double stacked",
            "floor loaded",
        ),
        facts=(
            "Pallets should be stable, shrink-wrapped, and safe to unload with standard warehouse equipment.",
            "Cartons should not overhang the pallet edge because overhang can delay receiving or require manual handling.",
            "Mixed-SKU pallets should be clearly marked and separated where possible.",
            "Floor-loaded freight or unstable pallets may require manual review before receiving can proceed.",
        ),
    ),
    Article(
        topic="temperature_controlled_loads",
        title="Temperature-Controlled Load Requirements",
        keywords=(
            "temperature controlled",
            "temperature-controlled",
            "reefer",
            "refrigerated",
            "frozen load",
            "chilled load",
            "temperature log",
            "trailer temperature",
        ),
        facts=(
            "Temperature-controlled loads should arrive with the trailer set to the required temperature range before check-in.",
            "Drivers should provide the appointment ID, ASN or PO reference, trailer number, seal number, and temperature record when requested.",
            "The guard gate or receiving team may record trailer temperature at arrival.",
            "Temperature exceptions should be routed to warehouse operations for review before unloading continues.",
        ),
    ),
    Article(
        topic="detention_wait_time",
        title="Carrier Wait Time And Detention Requests",
        keywords=(
            "detention",
            "wait time",
            "waiting time",
            "driver waiting",
            "dwell time",
            "layover",
            "accessorial",
            "unload delay",
        ),
        facts=(
            "Carrier detention or wait-time requests should include appointment ID, ASN or PO reference, carrier name, and driver check-in and check-out times.",
            "Warehouse operations reviews detention requests against gate and dock timestamps before approval.",
            "Accessorial charges should not be approved automatically from email alone.",
            "If timestamps or references are missing, the requester should provide the missing details before review can proceed.",
        ),
    ),
    Article(
        topic="receiving_discrepancy_process",
        title="Receiving Discrepancy Documentation",
        keywords=(
            "receiving discrepancy",
            "short received",
            "shortage",
            "overage",
            "damaged carton",
            "damaged pallet",
            "os&d",
            "osd",
            "missing pallet",
        ),
        facts=(
            "Receiving discrepancies should include ASN or PO reference, appointment ID when available, SKU or item details, and the counted quantity.",
            "Damage reports should include photos, carton or pallet identifiers, and a short description of the damage.",
            "Missing, overage, or damaged freight should be reviewed by warehouse operations before a final disposition is sent.",
            "Complaint or chargeback language should remain in human review rather than being auto-resolved.",
        ),
    ),
    Article(
        topic="proof_of_delivery",
        title="Proof Of Delivery And Receiving Confirmation",
        keywords=(
            "proof of delivery",
            "pod",
            "delivery confirmation",
            "receiving confirmation",
            "received confirmation",
            "unload confirmation",
            "signed bol",
            "bol copy",
        ),
        facts=(
            "Proof-of-delivery requests should include the ASN, PO, BOL, appointment ID, or carrier tracking reference.",
            "Receiving confirmation can be checked only after the warehouse has completed unload and system receipt steps.",
            "Signed BOL or POD copies may require operations review if the document is not already attached to the case.",
            "The assistant should not claim freight was received unless the case or knowledge source provides confirmation.",
        ),
    ),
]


def keyword_matches(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower())
    pattern = escaped.replace(r"\ ", r"\s+").replace(r"\-", r"[-\s]?")
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text) is not None


def match_article(subject: str, body: str) -> tuple[Article | None, int]:
    text = f"{subject}\n{body}".lower()
    ranked = sorted(
        ((article, sum(1 for keyword in article.keywords if keyword_matches(text, keyword))) for article in ARTICLES),
        key=lambda item: item[1],
        reverse=True,
    )
    article, score = ranked[0]
    if score == 0:
        return None, 0
    return article, score
