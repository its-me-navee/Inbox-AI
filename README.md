# Inbox AI

Inbox AI is a warehouse mailbox assistant that reads Gmail messages, classifies the requester intent, routes each case through a LangGraph workflow, and records the result for operator review in Streamlit. The goal is safe mailbox triage: automate low-risk replies and routing, but hold complaints, escalations, unclear cases, and weakly evidenced answers for humans.

## Workflow Design

```text
Gmail inbox
  -> poller duplicate check
  -> mail_reader
  -> Groq structured classifier
  -> deterministic classification auditor
  -> branch agent
  -> case auditor
  -> optional Gmail reply or internal forward
  -> SQLite case log
  -> Streamlit dashboard
```

The classifier proposes `request_type`, urgency, confidence, tags, details, and rationale. The classification auditor then scans the subject/body for deterministic warehouse signals and can correct the route before any branch runs. The branch agent creates the remediation actions, customer draft, internal note, SLA/follow-up markers, and audit trace. The final case auditor verifies the branch produced the minimum required outputs before the case can be stored or sent.

## Classification Logic

Inbox AI supports six branch types:

| Branch | Signal | Urgency | Automation rule |
| --- | --- | --- | --- |
| Complaint | Dissatisfaction, dispute, chargeback, damaged or missing freight, receiving discrepancy | High | Draft acknowledgement and route to operations lead; human review required. |
| General Enquiry | Informational warehouse question about hours, documents, labels, check-in, appointment process, or policy | Low | Search the local KB and answer only when the evidence gate says the facts are sufficient. |
| Service Request | Request to schedule, reschedule, cancel, update, investigate, release, receive, count, repair, reprint, or coordinate warehouse work | Medium | Extract required details, route to dock planning or operations, confirm receipt, and set a 2-hour SLA. |
| Escalation | Active safety, security, legal, regulatory, hazmat, blocked-operations, supervisor, or executive issue | Critical | Pause automation, notify supervisor, and keep the case in human review. |
| No Action | Automated mail, FYI-only note, receipt, delivery/bounce notification, newsletter, promotion, OTP/security alert, or explicit no-action language | Low | Log and close without customer response. |
| Unknown | Low confidence, conflicting signals, or possibly relevant email without enough intent/details | Medium | Hold automation and route to a warehouse operator with a suggested holding reply. |

Route precedence is deterministic: explicit no-action evidence closes the case; critical escalation evidence outranks the remaining operational branches; complaint evidence outranks service and enquiry; service actions outrank informational questions. The word `urgent` alone does not create an Escalation, and unsupported `No Action` classifications are downgraded to `Unknown`.

## Remediation Strategy

| Branch | Remediation output |
| --- | --- |
| Complaint | Acknowledge receipt, prepare operations-lead escalation, log a high-priority case, and set a 2-hour follow-up marker. |
| General Enquiry | Classify the sub-topic, search `app/core/knowledge/catalog.py`, run the evidence gate, answer from KB facts only, or route to human review if facts are missing. |
| Service Request | Extract appointment/ASN/PO/action/time details, validate required references, prepare requester confirmation, forward an internal routing note, and set a 2-hour SLA. |
| Escalation | Draft urgent acknowledgement, prepare supervisor alert, set `auto_resolution_paused`, and keep the case as `Needs Human`. |
| No Action | Record the reason, suppress outbound response, and close as `No Action Closed`. |
| Unknown | Hold automation, route to manager review, and draft a non-committal holding reply for the operator. |

## Tools Used

- **Gmail API + OAuth** for reading messages, replying to requesters, and forwarding internal notifications.
- **LangGraph** for the agent workflow and branch routing.
- **Groq / ChatGroq** for structured classification, evidence checks, extraction, and reply drafting.
- **Deterministic signal scanner** in `app/core/classification/engine.py` for audit corrections and safety precedence.
- **Local warehouse knowledge base** in `app/core/knowledge/catalog.py` for bounded General Enquiry answers.
- **SQLite** for case records, payload JSON, poll errors, and audit history.
- **FastAPI** for health, status, cases, Gmail polling, and OAuth callback endpoints.
- **Streamlit** for the operator dashboard: inbox queue, manager review, assistant replies, metrics, workflow, and setup.
- **Docker Compose** for running the API, dashboard, and poller services.

## End-To-End Examples

| Branch | Example email | Workflow result |
| --- | --- | --- |
| Complaint | "Receiving discrepancy for ASN WHX9021. We delivered 24 pallets, receiving shows 21, and three cartons were damaged. This is creating a chargeback dispute." | Classified `Complaint / High`, acknowledgement drafted, operations lead escalation prepared, 2-hour follow-up set, status `Needs Human`. |
| General Enquiry | "Can you confirm what documents a driver needs at carrier check-in for an inbound load? Are BOL, ASN, PO, and photo ID required?" | Classified `General Enquiry / Low`, KB article `Carrier Check-In Requirements` used, evidence gate passes, response generated, status `Resolved`. |
| Service Request | "Please reschedule inbound appointment FC-NYC9-3812 for ASN WHX3344 and PO 128900 from July 12 at 08:00 to July 13 after 14:00." | Classified `Service Request / Medium`, details extracted, dock planning note created, requester confirmation drafted, 2-hour SLA set, status `Routed`. |
| Escalation | "Active hazmat spill near dock door 4. Two outbound lanes are blocked and supervisor attention is needed immediately." | Classified `Escalation / Critical`, urgent acknowledgement drafted, supervisor notification prepared, automation paused, status `Needs Human`. |
| No Action | "This is an automated notification. Your monthly billing statement is available. No action is required from Warehouse Operations." | Classified `No Action / Low`, response suppressed, case logged and closed as `No Action Closed`. |
| Unknown | "This is urgent, but I do not have the location, appointment reference, or actual request details yet. I will send more context later." | Classified `Unknown / Medium`, automation held, operator review requested, suggested holding reply drafted, status `Needs Human`. |

Run locally with `docker compose up --build -d`, then open the dashboard at `http://localhost:8502` and the API at `http://localhost:8501`.
