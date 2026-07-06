"""
MedSafe Sathi — Reaction Reporting Agent (4th agent).

This agent runs separately, later in time, from the intake/risk-check
pipeline. It's used when a patient actually experiences a suspected adverse
drug reaction. Instead of relying purely on the patient's memory of what
they took, when, and how much, it pulls the REAL stored prescription record
(saved by intake_agent, in medsafe_sathi_agent) and drafts a structured
report from that — this is the core fix for underreporting: the data
already exists, even if the patient can't recall the details themselves.

The report is a DRAFT for a human (pharmacist / PV staff) to review and
submit — it is never auto-submitted.
"""

import json
import os
from datetime import datetime

from google.adk import Agent

# Reuse the same shared record used by the main pipeline, so this agent sees
# the real prescription history, not a separate copy of the data.
SHARED_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "medsafe_sathi_agent", "data")
RECORD_FILE = os.path.join(SHARED_DATA_DIR, "patient_records.json")
REPORT_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(REPORT_DIR, exist_ok=True)
REPORT_FILE = os.path.join(REPORT_DIR, "adr_reports.json")


def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_drug_record(patient_id: str, suspected_drug: str) -> str:
    """Looks up the real, stored prescription details for a suspected drug —
    used so the report is built from actual records, not patient memory.

    Args:
        patient_id: the patient reporting the reaction.
        suspected_drug: the drug the patient/pharmacist suspects caused it.

    Returns:
        A JSON string with the stored dose, frequency, doctor, and date this
        drug was prescribed, or a message saying no record was found.
    """
    records = _load_json(RECORD_FILE)
    patient_records = records.get(patient_id, [])
    matches = [r for r in patient_records if r["drug"].strip().lower() == suspected_drug.strip().lower()]
    if not matches:
        return json.dumps({"found": False, "note": "No stored record for this drug — report will rely on patient-reported details only."})
    return json.dumps({"found": True, "record": matches[-1]})


def save_draft_report(patient_id: str, report_text: str) -> str:
    """Saves the drafted ADR report for a human to review before submission.
    This report is NEVER auto-submitted to any real regulatory system.

    Args:
        patient_id: the patient this report is about.
        report_text: the drafted report content.

    Returns:
        Confirmation message.
    """
    reports = _load_json(REPORT_FILE)
    reports.setdefault(patient_id, []).append(
        {
            "report_text": report_text,
            "status": "draft_pending_human_review",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    )
    _save_json(REPORT_FILE, reports)
    return "Draft report saved, pending human review before any submission."


# ---------------------------------------------------------------------------
# Real-world evidence from FDA FAERS (2026 Q1 public adverse event data).
# Pulled directly from the actual FAERS dataset — distinct from the pairs
# used by risk_check_agent in medsafe_sathi_agent, since this agent's job is
# reporting real reactions, not predicting interaction risk.
# ---------------------------------------------------------------------------

FAERS_REACTION_EVIDENCE = {
    "metformin": (
        "FDA FAERS 2026 Q1: 1,293 real reported cases with Metformin as "
        "primary suspect drug. Top reactions: lactic acidosis (372 reports), "
        "acute kidney injury (194), hypoglycaemia (88), drug interaction "
        "explicitly reported (84), nausea (78)."
    ),
}


def get_reaction_evidence(drug_name: str) -> str:
    """Looks up real FDA FAERS report evidence for a drug's known reactions,
    to show the reporting pharmacist how this suspected reaction compares to
    real historical reports for the same drug.

    Args:
        drug_name: the suspected drug to look up real-world evidence for.

    Returns:
        A summary of real FAERS reaction data if available, or a message
        saying no FAERS evidence was pulled for this drug.
    """
    evidence = FAERS_REACTION_EVIDENCE.get(drug_name.strip().lower())
    if not evidence:
        return f"No FAERS reaction evidence was pulled for {drug_name} in this project."
    return evidence


root_agent = Agent(
    name="reporting_agent",
    model="gemini-2.5-flash",
    instruction="""You are an adverse drug reaction (ADR) report drafting
assistant. A patient or pharmacist is reporting a suspected reaction.

You will be given: patient_id, suspected_drug, a description of the
reaction, and roughly when it started.

Steps:
1. Call get_drug_record to pull the REAL stored prescription details for
   that drug (dose, frequency, prescribing doctor, date prescribed) — do
   not rely on what the user tells you about the drug if a stored record
   exists; the stored record is more reliable than memory.
2. Call get_reaction_evidence for the suspected drug to check if this
   reaction pattern has real FDA FAERS report history — include this in
   the report if available.
3. Draft a structured report combining the real record data, the FAERS
   evidence if available, and the reaction description, in a format similar
   to a standard ADR report:
   Patient ID, Suspected Drug, Dose, Frequency, Prescribing Doctor,
   Date Prescribed, Reaction Description, Reaction Onset, Report Date,
   Real-World Evidence (FAERS).
4. Call save_draft_report to save it.
5. Clearly tell the user this is a DRAFT that a human (pharmacist / PV
   staff) must review, edit if needed, and submit through the proper
   channel — you are not submitting anything yourself.

Always mention explicitly if a stored prescription record was found or not,
since that's the whole point: even if the patient doesn't fully remember
the details, the system may already have them on file.""",
    tools=[get_drug_record, get_reaction_evidence, save_draft_report],
)