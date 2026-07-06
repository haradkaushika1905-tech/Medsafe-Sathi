"""
MedSafe Sathi Lite — backup version.

Same idea, same 3 required concepts (agent skill, security feature, and a
working AI-assisted pipeline with human review), but built as one simple
script that calls the Gemini API directly. No framework setup required —
just Python and one package. Use this if the ADK version isn't working in
time for your deadline.

Run it with:  python main.py
"""

import json
import os
import re
from datetime import datetime

import google.generativeai as genai

# ---------------------------------------------------------------------------
# Setup — reads your API key from the environment variable
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("GOOGLE_API_KEY")
if not API_KEY:
    print("ERROR: GOOGLE_API_KEY is not set.")
    print('Set it first, e.g. (Mac/Linux): export GOOGLE_API_KEY="your-key-here"')
    print('Or (Windows PowerShell): $env:GOOGLE_API_KEY="your-key-here"')
    raise SystemExit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
RECORD_FILE = os.path.join(DATA_DIR, "patient_records.json")
AUDIT_FILE = os.path.join(DATA_DIR, "audit_log.json")

# ---------------------------------------------------------------------------
# Hardcoded interaction reference table (same as the full version)
# ---------------------------------------------------------------------------

INTERACTION_TABLE = {
    ("aspirin", "warfarin"): "Increased bleeding risk — both affect clotting.",
    ("ibuprofen", "warfarin"): "NSAIDs raise bleeding risk when combined with warfarin.",
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


# ---------------------------------------------------------------------------
# 1. Security tool: redact PII (no AI call, pure Python — instant, reliable)
# ---------------------------------------------------------------------------

def redact_pii(text: str) -> str:
    text = re.sub(r"\b\d{10}\b", "[PHONE REDACTED]", text)
    text = re.sub(r"\b(Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+\b", "[NAME REDACTED]", text)
    return text


# ---------------------------------------------------------------------------
# 2. Storage
# ---------------------------------------------------------------------------

def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def save_prescription(patient_id, drug, dose, frequency, allergies, doctor, plain_instructions):
    records = _load_json(RECORD_FILE)
    entry = {
        "drug": drug,
        "dose": dose,
        "frequency": frequency,
        "allergies": redact_pii(allergies),
        "doctor": doctor,
        "plain_instructions": plain_instructions,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    records.setdefault(patient_id, []).append(entry)
    _save_json(RECORD_FILE, records)
    return entry


def get_patient_history(patient_id):
    records = _load_json(RECORD_FILE)
    return records.get(patient_id, [])


def log_pharmacist_decision(patient_id, ai_flag_summary, human_decision, note=""):
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


# ---------------------------------------------------------------------------
# 3. Agent skill #1 — Intake & translate (1 Gemini API call)
# ---------------------------------------------------------------------------

def intake_agent(raw_text: str) -> dict:
    prompt = f"""You are a pharmacy intake assistant. Read this prescription note
and extract structured data. Respond with ONLY valid JSON, no other text,
in exactly this format:
{{"drug": "...", "dose": "...", "frequency": "...", "plain_instructions": "..."}}

The plain_instructions field should rewrite the prescription in simple,
everyday language a patient can understand.

Prescription note:
{raw_text}"""
    response = model.generate_content(prompt)
    cleaned = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# 4. Agent skill #2 — Risk check
#    (deterministic table lookup — no AI needed for the actual detection,
#     which makes this part 100% reliable; Gemini is used only to phrase
#     the result in plain language for the pharmacist)
# ---------------------------------------------------------------------------

def _normalize(name):
    return name.strip().lower()


def check_interactions(new_drug, existing_drugs):
    new_drug_n = _normalize(new_drug)
    findings = []
    for existing in existing_drugs:
        pair = tuple(sorted([new_drug_n, _normalize(existing)]))
        if pair in INTERACTION_TABLE:
            findings.append({"pair": pair, "risk": INTERACTION_TABLE[pair]})
    return findings


def risk_check_agent(patient_id, new_drug):
    history = get_patient_history(patient_id)
    existing_drugs = [entry["drug"] for entry in history]
    findings = check_interactions(new_drug, existing_drugs)

    if not findings:
        summary = f"No known interaction found between {new_drug} and this patient's recorded history."
    else:
        prompt = f"""You are a medication safety assistant. A pharmacist is
about to review this AI-generated flag. Explain these findings in 2-3 plain,
clear sentences for the pharmacist:

New drug: {new_drug}
Patient's recorded medications: {existing_drugs}
Matched risks: {json.dumps(findings)}

Do not make a final medical judgment — you are surfacing information only."""
        response = model.generate_content(prompt)
        summary = response.text.strip()

    summary += (
        "\n\nThis is an AI-generated flag for pharmacist review — it is not a "
        "final medical decision and must be confirmed or overridden by a "
        "human before any action is taken."
    )
    return summary, findings


# ---------------------------------------------------------------------------
# 5. Simple menu-driven demo — safe to run live on camera
# ---------------------------------------------------------------------------

def run_visit():
    print("\n--- New prescription (Visit) ---")
    patient_id = input("Patient ID (e.g. phone number): ").strip()
    doctor = input("Doctor name: ").strip()
    raw_text = input("Prescription note (drug, dose, frequency): ").strip()
    allergies = input("Patient's allergy note (in their own words): ").strip()

    print("\n[intake_agent running — calling Gemini...]")
    extracted = intake_agent(raw_text)
    print("Extracted:", json.dumps(extracted, indent=2))

    entry = save_prescription(
        patient_id,
        extracted["drug"],
        extracted["dose"],
        extracted["frequency"],
        allergies,
        doctor,
        extracted["plain_instructions"],
    )
    print(f"\nSaved to shared record. Patient now has {len(get_patient_history(patient_id))} record(s).")
    print("Plain-language instructions for patient:", entry["plain_instructions"])

    if len(get_patient_history(patient_id)) > 1:
        print("\n[risk_check_agent running — checking against patient history...]")
        summary, findings = risk_check_agent(patient_id, extracted["drug"])
        print("\n--- SAFETY FLAG FOR PHARMACIST REVIEW ---")
        print(summary)

        decision = input("\nAs the reviewing pharmacist, confirm this flag? (y/n): ").strip().lower()
        log_pharmacist_decision(
            patient_id,
            ai_flag_summary=summary,
            human_decision="confirmed" if decision == "y" else "overridden",
        )
        print("Decision logged to audit trail.")


def main():
    print("=== MedSafe Sathi Lite ===")
    while True:
        print("\n1. New prescription visit")
        print("2. View a patient's stored history")
        print("3. Exit")
        choice = input("Choose: ").strip()
        if choice == "1":
            run_visit()
        elif choice == "2":
            pid = input("Patient ID: ").strip()
            print(json.dumps(get_patient_history(pid), indent=2))
        elif choice == "3":
            break
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()