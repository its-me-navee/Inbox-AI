"""Design tokens and CSS for the Streamlit ops console."""

APP_CSS = """
<style>
:root {
    --ink: #17130f;
    --muted: #5f5a52;
    --paper: #f4f4ef;
    --sheet: #fffdf3;
    --cyan: #00a6b2;
    --red: #d23f31;
    --blue: #243c8f;
    --green: #24714f;
    --yellow: #f3c74f;
    --line: #17130f;
    --shadow: 6px 6px 0 #17130f;
}

html, body, [class*="css"] {
    color: var(--ink);
    font-family: Georgia, "Times New Roman", Times, serif;
}

body, .stApp {
    background:
        linear-gradient(90deg, rgba(23, 19, 15, 0.035) 1px, transparent 1px) 0 0 / 28px 28px,
        linear-gradient(rgba(23, 19, 15, 0.03) 1px, transparent 1px) 0 0 / 28px 28px,
        var(--paper);
}

.stApp::before {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    background-image: radial-gradient(rgba(23, 19, 15, 0.08) 0.7px, transparent 0.7px);
    background-size: 5px 5px;
    opacity: 0.45;
}

.block-container {
    padding-top: 0.6rem;
    padding-bottom: 2.5rem;
    max-width: 1440px;
}
header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
.stDeployButton,
#MainMenu,
footer {
    visibility: hidden !important;
    height: 0 !important;
    min-height: 0 !important;
}

header[data-testid="stHeader"] {
    background: transparent !important;
}

h1, h2, h3, h4, h5, h6 {
    color: var(--ink) !important;
    font-family: Georgia, "Times New Roman", Times, serif !important;
    letter-spacing: 0 !important;
}

p, li, label, span, div {
    letter-spacing: 0 !important;
}

a {
    color: var(--blue) !important;
    text-decoration-thickness: 2px !important;
    text-underline-offset: 0.18em !important;
}

.app-hero {
    position: relative;
    background: var(--sheet);
    border: 3px double var(--line);
    border-radius: 0;
    padding: 1.35rem 1.5rem;
    margin: 0 0 1.2rem 0;
    color: var(--ink);
    box-shadow: var(--shadow);
}
.app-hero h1 {
    color: var(--ink) !important;
    font-size: clamp(2.1rem, 4vw, 4rem) !important;
    font-weight: 700 !important;
    line-height: 0.95 !important;
    margin: 0 0 0.35rem 0 !important;
}
.app-hero p {
    color: #2f2a24;
    margin: 0;
    font-size: 1rem;
}
.app-hero .hero-demo {
    max-width: 58rem;
    margin-top: 0.45rem;
    color: var(--muted);
    font-family: "Courier New", Courier, monospace;
    font-size: 0.88rem;
    line-height: 1.35;
}
.hero-pills { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 0.9rem; }
.hero-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 34px;
    padding: 5px 10px;
    border: 2px solid var(--line);
    border-radius: 0;
    color: var(--ink);
    background: var(--sheet);
    box-shadow: 3px 3px 0 var(--line);
    font-family: "Courier New", Courier, monospace;
    font-size: 0.78rem;
    font-weight: 700;
}
.hero-pill .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); border: 1px solid var(--line); }
.hero-pill.warn { background: #f9f0ca; }
.hero-pill.warn .dot { background: var(--yellow); }
.hero-pill.off { background: #fff7f4; }
.hero-pill.off .dot { background: var(--red); }
.hero-pill.dry { background: var(--yellow); }

.stButton > button,
.stDownloadButton > button,
[data-testid="baseButton-secondary"],
[data-testid="baseButton-primary"] {
    min-height: 42px;
    border: 2px solid var(--line) !important;
    border-radius: 0 !important;
    color: var(--ink) !important;
    background: var(--sheet) !important;
    box-shadow: 3px 3px 0 var(--line) !important;
    font-family: "Courier New", Courier, monospace !important;
    font-weight: 700 !important;
    transition: transform 120ms ease, box-shadow 120ms ease, background-color 120ms ease;
}

.stButton > button:hover,
.stDownloadButton > button:hover,
[data-testid="baseButton-secondary"]:hover,
[data-testid="baseButton-primary"]:hover {
    color: var(--ink) !important;
    background: var(--yellow) !important;
    transform: translate(2px, 2px);
    box-shadow: 1px 1px 0 var(--line) !important;
}

.badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 8px;
    margin: 0 4px 5px 0;
    border-radius: 0;
    font-family: "Courier New", Courier, monospace;
    font-size: 0.76rem;
    font-weight: 700;
    border: 2px solid var(--line);
    box-shadow: 2px 2px 0 var(--line);
    white-space: nowrap;
}

.status-ok { color: var(--ink); background: #ecf6dd; }
.status-route { color: var(--ink); background: #d7eef0; }
.status-human { color: var(--sheet); background: var(--red); }
.status-muted { color: var(--ink); background: var(--sheet); }
.status-warn { color: var(--ink); background: #f9f0ca; }

.type-complaint { color: var(--ink); background: #f9f0ca; }
.type-general-enquiry { color: var(--ink); background: #ecf6dd; }
.type-service-request { color: var(--ink); background: #d7eef0; }
.type-escalation { color: var(--sheet); background: var(--red); }
.type-no-action { color: var(--ink); background: var(--sheet); }
.type-unknown { color: var(--sheet); background: var(--blue); }

.urgency-critical { color: var(--sheet); background: var(--red); }
.urgency-high { color: var(--ink); background: var(--yellow); }
.urgency-medium { color: var(--sheet); background: var(--blue); }
.urgency-low { color: var(--ink); background: #ecf6dd; }

div[data-testid="stMetric"] {
    border: 3px solid var(--line);
    border-radius: 0;
    padding: 0.65rem 0.85rem;
    background: var(--sheet);
    box-shadow: 4px 4px 0 var(--line);
}

div[data-testid="stMetric"] label,
div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
    color: var(--red) !important;
    font-family: "Courier New", Courier, monospace !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    overflow: visible !important;
    white-space: normal !important;
    line-height: 1.15 !important;
}

div[data-testid="stMetric"] [data-testid="stMetricLabel"] > div {
    overflow: visible !important;
    text-overflow: unset !important;
    white-space: normal !important;
}

.stMarkdown h4,
.stMarkdown h5 {
    font-family: "Courier New", Courier, monospace !important;
    color: var(--red) !important;
    font-weight: 700 !important;
    text-transform: uppercase;
}

[data-testid="stDataFrame"],
[data-testid="stTable"],
.stAlert,
div[data-testid="stExpander"],
div[data-testid="stForm"] {
    border: 3px solid var(--line) !important;
    border-radius: 0 !important;
    background: var(--sheet) !important;
    box-shadow: 4px 4px 0 var(--line);
}

.mail-readonly {
    border: 2px solid var(--line);
    background: var(--sheet);
    padding: 0.75rem;
    margin-bottom: 0.75rem;
    color: var(--ink);
}

.mail-readonly-label {
    font-family: "Courier New", Courier, monospace;
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--red);
    text-transform: uppercase;
    margin-bottom: 0.35rem;
}

.mail-readonly pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--ink);
    font-family: Georgia, "Times New Roman", Times, serif;
    font-size: 0.96rem;
    line-height: 1.45;
}

.requester-email {
    display: inline-block;
    max-width: 100%;
    color: var(--muted);
    font-family: "Courier New", Courier, monospace !important;
    font-size: 0.74rem !important;
    line-height: 1.2;
    overflow-wrap: anywhere;
    word-break: break-word;
}

.mail-readonly pre.requester-email-detail {
    font-size: 0.78rem !important;
}

.stAlert {
    color: var(--ink) !important;
}

div[data-baseweb="tab-list"] {
    gap: 0.45rem;
    border-bottom: 3px solid var(--line);
}

button[data-baseweb="tab"] {
    border: 2px solid var(--line);
    border-bottom: 0;
    border-radius: 0 !important;
    color: var(--ink) !important;
    background: var(--sheet) !important;
    font-family: "Courier New", Courier, monospace !important;
    font-weight: 700 !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    background: var(--yellow) !important;
}

input,
textarea,
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
div[data-baseweb="textarea"] > div {
    border-radius: 0 !important;
    border-color: var(--line) !important;
    background: var(--sheet) !important;
}

hr {
    border-color: var(--line) !important;
    border-width: 2px 0 0 0 !important;
}
</style>
"""

TYPE_CLASS = {
    "Complaint": "type-complaint",
    "General Enquiry": "type-general-enquiry",
    "Service Request": "type-service-request",
    "Escalation": "type-escalation",
    "No Action": "type-no-action",
    "Unknown": "type-unknown",
}

URGENCY_CLASS = {
    "Critical": "urgency-critical",
    "High": "urgency-high",
    "Medium": "urgency-medium",
    "Low": "urgency-low",
}

STATUS_CLASS = {
    "Needs Human": "status-human",
    "Review": "status-human",
    "Resolved": "status-ok",
    "Routed": "status-route",
    "No Action Closed": "status-muted",
    "No Action": "status-muted",
}
