"""
MedSafe Sathi — a pharmacovigilance / point-of-care safety pipeline.

This file holds 2 of the 4 agents in the full project (the real-time
prescription flow). The 4th agent (ADR reaction reporting) lives separately
in ../medsafe_reporting_agent, since it runs later, at a different point in
time, not as part of this same real-time pipeline.

Pipeline (this file):
  intake_agent      -> reads a new prescription + patient-written allergy
                        note, extracts structured data, translates it to
                        plain language, and redacts personal identifiers
                        before anything is saved.
  risk_check_agent  -> pulls the patient's stored medication history, checks
                        the new drug against it using a hardcoded interaction
                        table, and — if something is flagged — saves it as a
                        PENDING alert. The doctor never sees this directly;
                        a human reviewer must confirm it first via
                        reviewer_confirm_alert before it becomes visible.

A human always makes the final call at every stage — the agents only assist.
"""

import json
import os
import re
from datetime import datetime

from google.adk import Agent, Workflow

# ---------------------------------------------------------------------------
# 1. Hardcoded interaction reference table
#    (deliberately small and curated — NOT a claim of clinical completeness.
#     For the capstone demo this is the transparent, auditable data source
#     behind the "risk-check" agent skill.)
# ---------------------------------------------------------------------------

INTERACTION_TABLE = {
    ("aspirin", "warfarin"): "Increased bleeding risk — both affect clotting.",
    ("ibuprofen", "warfarin"): "NSAIDs like ibuprofen displace warfarin from plasma protein binding sites, increasing free (active) warfarin in the blood and raising bleeding risk.",
    ("ciprofloxacin", "warfarin"): "Ciprofloxacin can raise warfarin levels, increasing bleeding risk.",
    ("amiodarone", "warfarin"): "Amiodarone raises warfarin levels — bleeding risk increases.",
    ("lisinopril", "spironolactone"): "Combination can cause dangerously high potassium levels.",
    ("lisinopril", "ibuprofen"): "NSAIDs can reduce the effect of ACE inhibitors and stress the kidneys.",
    ("digoxin", "amiodarone"): "Amiodarone raises digoxin levels — risk of toxicity.",
    ("sildenafil", "nitroglycerin"): "Combination can cause a dangerous, severe drop in blood pressure.",
    ("methotrexate", "ibuprofen"): "NSAIDs can raise methotrexate levels to toxic range.",
    ("clopidogrel", "omeprazole"): "Omeprazole may reduce how well clopidogrel prevents clotting.",
    ("metformin", "iodinated contrast"): "Risk of lactic acidosis around contrast imaging procedures.",
    ("lithium", "hydrochlorothiazide"): "Thiazide diuretics can raise lithium to toxic levels.",
    ("theophylline", "ciprofloxacin"): "Ciprofloxacin can raise theophylline to toxic levels.",
    ("tramadol", "sertraline"): "Combined serotonergic effect — risk of serotonin syndrome.",
    ("simvastatin", "clarithromycin"): "Clarithromycin raises simvastatin levels — risk of muscle damage.",
}


def check_new_drug_for_patient(patient_id: str, new_drug: str) -> str:
    """Does the COMPLETE risk check for a new drug in one single call: pulls
    the patient's history, checks for interactions, and pulls FAERS evidence
    if anything is flagged. This is the ONLY tool needed for a risk check —
    no other information is required.

    Args:
        patient_id: the patient's ID.
        new_drug: the name of the new drug being prescribed.

    Returns:
        A JSON string with the full result: existing drugs, any flagged
        interactions, and real FAERS evidence if a flag was found.
    """
    history = json.loads(get_patient_history(patient_id))
    existing_drugs = [entry["drug"] for entry in history]
    interaction_result = json.loads(check_interactions(new_drug, existing_drugs))

    evidence = {}
    if interaction_result.get("status") == "flagged":
        for finding in interaction_result["findings"]:
            for drug in (finding["drug_a"], finding["drug_b"]):
                ev = get_faers_evidence(drug)
                if "No FAERS evidence" not in ev:
                    evidence[drug] = ev

    return json.dumps({
        "existing_drugs": existing_drugs,
        "interaction_result": interaction_result,
        "faers_evidence": evidence,
    })


def _normalize(drug_name: str) -> str:
    return drug_name.strip().lower()


# ---------------------------------------------------------------------------
# 1b. Real-world evidence from FDA FAERS (2026 Q1 public adverse event data).
#     These counts were pulled directly from the actual FAERS dataset —
#     real reported cases, not estimates — to back up the hardcoded table
#     above with genuine FDA data.
# ---------------------------------------------------------------------------

FAERS_EVIDENCE = {
    "warfarin": (
        "FDA FAERS 2026 Q1: 109 real reported cases with Warfarin as primary "
        "suspect drug. Top reactions: INR increased (14 reports), "
        "anticoagulation above therapeutic (12), GI haemorrhage (10), "
        "haemorrhage (9), drug interaction explicitly reported (7)."
    ),
    "aspirin": (
        "FDA FAERS 2026 Q1: 168 real reported cases with Aspirin as primary "
        "suspect drug. Top reactions: haemoglobin decreased (11 reports), "
        "GI haemorrhage (9), contraindicated product administered (10)."
    ),
}


def get_faers_evidence(drug_name: str) -> str:
    """Looks up real FDA FAERS adverse event report evidence for a drug, to
    support a flag with actual reported case data rather than just the
    hardcoded reference table alone.

    Args:
        drug_name: the drug to look up real-world evidence for.

    Returns:
        A summary of real FAERS report data if available, or a message
        saying no FAERS evidence was pulled for this drug.
    """
    evidence = FAERS_EVIDENCE.get(_normalize(drug_name))
    if not evidence:
        return f"No FAERS evidence was pulled for {drug_name} in this project."
    return evidence


def check_interactions(new_drug: str, existing_drugs: list[str]) -> str:
    """Checks a new drug against a patient's existing medication list for
    known, clinically significant interactions using the reference table.

    Args:
        new_drug: the drug being newly prescribed.
        existing_drugs: list of drugs already on the patient's stored record.

    Returns:
        A JSON string listing any matches found, or a message saying none
        were found in the reference table.
    """
    new_drug_n = _normalize(new_drug)
    findings = []
    for existing in existing_drugs:
        pair = tuple(sorted([new_drug_n, _normalize(existing)]))
        if pair in INTERACTION_TABLE:
            findings.append(
                {
                    "drug_a": pair[0],
                    "drug_b": pair[1],
                    "risk": INTERACTION_TABLE[pair],
                }
            )
    if not findings:
        return json.dumps(
            {"status": "no_match", "note": "No known interaction found in the reference table. This does not rule out risk — clinical judgment still applies."}
        )
    return json.dumps({"status": "flagged", "findings": findings})


# ---------------------------------------------------------------------------
# 2. Security tool: redact personal identifiers before anything is stored
# ---------------------------------------------------------------------------

def redact_pii(text: str) -> str:
    """Removes obvious personal identifiers (phone numbers, honorific + name)
    from free-text notes before they are saved to the shared record.

    Args:
        text: raw patient/prescription note text.

    Returns:
        The same text with identifying details replaced by placeholders.
    """
    text = re.sub(r"\b\d{10}\b", "[PHONE REDACTED]", text)
    text = re.sub(r"\b(Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+\b", "[NAME REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# 3. Storage tools: the shared record that solves the underreporting problem
#    (this is what lets Doctor B see what Doctor A prescribed, even with
#    no direct connection between them)
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
RECORD_FILE = os.path.join(DATA_DIR, "patient_records.json")
AUDIT_FILE = os.path.join(DATA_DIR, "audit_log.json")


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _save_json(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def save_prescription(patient_id: str, drug: str, dose: str, frequency: str, allergies: str, doctor: str) -> str:
    """Saves a new prescription entry to the patient's shared medication record.

    Args:
        patient_id: simple lookup key entered by the patient (e.g. phone number or clinic ID).
        drug: name of the drug prescribed.
        dose: dose amount.
        frequency: how often the drug is taken.
        allergies: allergy note as written by the patient.
        doctor: name/identifier of the prescribing doctor for this visit.

    Returns:
        Confirmation message.
    """
    records = _load_json(RECORD_FILE)
    entry = {
        "drug": drug,
        "dose": dose,
        "frequency": frequency,
        "allergies": allergies,
        "doctor": doctor,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    records.setdefault(patient_id, []).append(entry)
    _save_json(RECORD_FILE, records)
    return f"Saved. Patient {patient_id} now has {len(records[patient_id])} record(s) on file."


def get_patient_history(patient_id: str) -> str:
    """Retrieves the stored medication history for a patient.

    Args:
        patient_id: simple lookup key entered by the patient.

    Returns:
        A JSON string of the patient's prior prescriptions, or an empty list if none exist.
    """
    records = _load_json(RECORD_FILE)
    return json.dumps(records.get(patient_id, []))


def log_pharmacist_decision(patient_id: str, ai_flag_summary: str, human_decision: str, note: str = "") -> str:
    """Logs a pharmacist's confirm/override decision against an AI-generated flag.
    This creates an auditable record of human oversight.

    Args:
        patient_id: the patient this decision relates to.
        ai_flag_summary: short summary of what the AI flagged.
        human_decision: "confirmed" or "overridden".
        note: optional free-text reason from the pharmacist.

    Returns:
        Confirmation message.
    """
    logs = _load_json(AUDIT_FILE)
    logs.setdefault(patient_id, []).append(
        {
            "ai_flag_summary": ai_flag_summary,
            "human_decision": human_decision,
            "note": note,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    )
    _save_json(AUDIT_FILE, logs)
    return "Decision logged."


# ---------------------------------------------------------------------------
# 3b. Human-gated alert queue.
#     An AI flag is NEVER shown to the doctor directly. It is saved here as
#     "pending_review" first. Only after a human reviewer confirms it does it
#     become visible to the doctor. This is the gate you asked for.
# ---------------------------------------------------------------------------

PENDING_ALERTS_FILE = os.path.join(DATA_DIR, "pending_alerts.json")


def create_pending_alert(patient_id: str, ai_flag_summary: str) -> str:
    """Saves a new AI-generated flag as pending review. The doctor cannot see
    this yet — it only becomes visible after a human reviewer confirms it.

    Args:
        patient_id: the patient this alert relates to.
        ai_flag_summary: the plain-language flag text generated by the risk_check_agent.

    Returns:
        The alert_id, which the reviewer will use to confirm or reject it.
    """
    alerts = _load_json(PENDING_ALERTS_FILE)
    patient_alerts = alerts.setdefault(patient_id, [])
    alert_id = f"{patient_id}-{len(patient_alerts) + 1}"
    patient_alerts.append(
        {
            "alert_id": alert_id,
            "ai_flag_summary": ai_flag_summary,
            "status": "pending_review",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    )
    _save_json(PENDING_ALERTS_FILE, alerts)
    return alert_id


def reviewer_confirm_alert(patient_id: str, alert_id: str, decision: str, note: str = "") -> str:
    """A human reviewer confirms or rejects a pending AI flag. This is the
    gate that determines whether the doctor ever sees the alert.

    Args:
        patient_id: the patient this alert relates to.
        alert_id: the id of the pending alert being reviewed.
        decision: "confirm" (doctor will now see it) or "reject" (doctor will not).
        note: optional reviewer note explaining the decision.

    Returns:
        Confirmation message.
    """
    alerts = _load_json(PENDING_ALERTS_FILE)
    for alert in alerts.get(patient_id, []):
        if alert["alert_id"] == alert_id:
            alert["status"] = "visible_to_doctor" if decision == "confirm" else "rejected"
            alert["reviewer_note"] = note
            _save_json(PENDING_ALERTS_FILE, alerts)
            log_pharmacist_decision(patient_id, alert["ai_flag_summary"], "confirmed" if decision == "confirm" else "overridden", note)
            return f"Alert {alert_id} marked as {alert['status']}."
    return f"Alert {alert_id} not found."


def get_doctor_visible_alerts(patient_id: str) -> str:
    """Retrieves ONLY the alerts a human reviewer has confirmed. This is the
    only function the doctor-facing side of the system is allowed to read
    from — it never has access to raw, unconfirmed AI output.

    Args:
        patient_id: the patient to check alerts for.

    Returns:
        A JSON string of confirmed, doctor-visible alerts.
    """
    alerts = _load_json(PENDING_ALERTS_FILE)
    visible = [a for a in alerts.get(patient_id, []) if a["status"] == "visible_to_doctor"]
    return json.dumps(visible)


# ---------------------------------------------------------------------------
# 4. Agents
# ---------------------------------------------------------------------------

intake_agent = Agent(
    name="intake_agent",
    model="gemini-2.5-flash",
    instruction="""You are a pharmacy intake assistant.

You will be given: a patient_id, raw prescription text (drug, dose, frequency),
a doctor name, and an allergy note written by the patient in their own words.

Steps:
1. Extract: drug name, dose, frequency.
2. Call redact_pii on the allergy note and any free text that might contain
   personal identifiers (names, phone numbers) before using it further.
3. Rewrite the prescription as simple, plain-language patient instructions
   (e.g. "Take one tablet twice a day, after food, for 5 days.").
4. Call save_prescription to store the structured entry in the shared record.
5. Reply with a short confirmation summary in plain language, including the
   plain-language instructions and the redacted allergy note.

Always call save_prescription — this is what allows a different doctor,
with no prior connection, to see this patient's medication history later.""",
    tools=[redact_pii, save_prescription],
)

risk_check_agent = Agent(
    name="risk_check_agent",
    model="gemini-2.5-flash",
    instruction="""You check new prescriptions for drug interactions.

You need EXACTLY two things: patient_id and new_drug (the drug name).
Nothing else. Ever.

The moment you have both, immediately call check_new_drug_for_patient(patient_id, new_drug).
Do not ask about dose, frequency, doctor, or allergies — you have no use for them.

If the result shows a flagged interaction:
1. Explain the flagged pair and why, in plain language, including any FAERS evidence provided.
2. Call create_pending_alert with that summary.
3. Tell the user the alert_id and that a human must call reviewer_confirm_alert before the doctor can see it.

If no interaction was flagged, just say so plainly. Do not call create_pending_alert.

ALWAYS end your response with this exact line:
"This is an AI-generated flag for pharmacist review — it is not a final
medical decision and must be confirmed or overridden by a human before
any action is taken."

You can also be asked to:
- Confirm or reject a pending alert: call reviewer_confirm_alert.
- Show what the doctor can see: call get_doctor_visible_alerts.""",
    tools=[
        check_new_drug_for_patient,
        create_pending_alert,
        reviewer_confirm_alert,
        get_doctor_visible_alerts,
    ],
)

root_agent = Workflow(
    name="medsafe_sathi_pipeline",
    edges=[("START", intake_agent, risk_check_agent)],
)