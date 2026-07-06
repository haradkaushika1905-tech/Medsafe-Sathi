# MedSafe Sathi

**A multi-agent pharmacy safety system that catches dangerous drug interactions across doctors who never talk to each other — and never lets an AI make the final call alone.**

Built for the Vibecoding Agents Capstone Project (Google, Kaggle) — **Agents for Good** track.

---

## The Problem

In many healthcare settings, a patient can see multiple doctors — a cardiologist, a GP, a specialist — with no shared system between them. Doctor B has no way of knowing what Doctor A prescribed last month. This is a real, common cause of dangerous drug interactions and adverse reactions that go undetected until it's too late.

This problem has two names in clinical literature: **polypharmacy** and **underreporting**.

**Polypharmacy** — a patient taking multiple medications simultaneously, often prescribed by different, unconnected providers — is one of the strongest known risk factors for dangerous drug-drug interactions. The more medications a patient accumulates across uncoordinated visits, the higher the risk that two of them interact in ways no single doctor would catch, simply because no one doctor can see the whole list.

**Underreporting** compounds this further. Many adverse drug reactions that do occur are never formally logged anywhere, meaning the same dangerous combination can go unnoticed as a pattern across multiple patients. Both are leading, preventable contributors to avoidable hospitalizations — particularly for patients managing multiple chronic conditions across multiple providers.

At the same time, patients often don't understand their own prescriptions. A note like "Warfarin 5mg once daily" means very little to someone without a medical background, and a hand-written allergy note can contain personal details that shouldn't be stored insecurely.

**MedSafe Sathi** ("Sathi" means "companion" in Hindi) addresses both problems: it gives every doctor visibility into a patient's full medication history regardless of who prescribed what, flags dangerous interactions automatically, translates prescriptions into plain language for patients, and — critically — never lets the AI make a final safety decision alone. A human pharmacist always reviews and confirms every flag before a doctor ever sees it.

## The Solution

MedSafe Sathi is a multi-agent pipeline built on Google's Agent Development Kit (ADK). It has four cooperating pieces of logic, two of which run in real time as part of the prescription workflow, and a separate reporting component that operates independently:

1. **Intake Agent** — reads a new prescription and the patient's own allergy note, extracts structured data (drug, dose, frequency), strips personal identifiers before anything is stored, rewrites the prescription in plain language for the patient, and saves it to a shared patient record.
2. **Risk Check Agent** — the moment a new drug is prescribed, this agent pulls the patient's full medication history (regardless of which doctor entered it), checks the new drug against everything the patient is already taking using a curated drug-interaction reference table, and pulls real-world evidence from the FDA's FAERS adverse event database to back up any flag with actual reported case data.
3. **Human-in-the-loop review gate** — if an interaction is flagged, it is saved as **pending review** only. It is never shown to the doctor directly. A human pharmacist must explicitly confirm or reject the flag. Only a confirmed flag ever becomes visible to the doctor. Every decision — confirmed or overridden — is logged to a permanent audit trail.
4. **ADR Reporting Agent** *(separate module)* — handles adverse drug reaction reporting after the fact, since this happens at a different point in time from the real-time prescription flow above.

## Why This Matters (Agents for Good)

This project targets a real, well-documented healthcare safety gap: fragmented patient records across uncoordinated providers. Rather than trying to replace clinical judgment, the system is deliberately designed around **transparency and human oversight** — every AI-generated flag is explainable (it cites the specific interaction and, where available, real FDA report data), and no flag reaches a doctor without a human pharmacist's sign-off first. This reflects a responsible approach to deploying AI in a domain where mistakes have real consequences.

## Architecture

```
                     ┌────────────────────┐
   New prescription  │   Intake Agent     │
   + allergy note ───▶│  - extract data    │
                     │  - redact PII       │
                     │  - plain-language   │
                     │  - save to record   │
                     └─────────┬──────────┘
                               │
                               ▼
                     ┌────────────────────┐
                     │ Risk Check Agent   │
                     │ - pull history     │
                     │ - check interaction│
                     │ - pull FAERS data  │
                     └─────────┬──────────┘
                               │
                     flagged?  ▼
                     ┌────────────────────┐
                     │  Pending Alert     │
                     │ (hidden from       │
                     │  doctor)           │
                     └─────────┬──────────┘
                               │
                     ┌─────────▼──────────┐
                     │ Human Pharmacist   │
                     │ confirms / rejects │
                     └─────────┬──────────┘
                               │
                     confirmed ▼
                     ┌────────────────────┐
                     │ Visible to Doctor  │
                     └────────────────────┘
```

`![Agent Graph](docs/agent_graph.png)`

## Key Features

- **Shared patient record across providers** — solves the real-world underreporting/fragmentation problem, so any doctor can see a patient's full history via a simple patient ID lookup.
- **Automated interaction detection** — checks new prescriptions against a curated, transparent reference table of known clinically significant drug interactions.
- **Real-world evidence backing** — pulls genuine FDA FAERS adverse event report data to support flags with actual case numbers, not just a static rule.
- **Mandatory human-in-the-loop** — no AI flag ever reaches a doctor without explicit pharmacist confirmation. This is enforced structurally (via `get_doctor_visible_alerts`, which can only ever return confirmed alerts), not just a suggestion.
- **Full audit trail** — every pharmacist decision (confirmed or overridden) is permanently logged with a timestamp and note.
- **PII redaction** — personal identifiers (phone numbers, names) are stripped from free-text notes before anything is saved.
- **Plain-language translation** — technical prescriptions are rewritten into simple instructions patients can actually understand.

## Tech Stack

- **Google Agent Development Kit (ADK)** — multi-agent orchestration (`Agent`, `Workflow`)
- **Gemini 2.5 Flash** — underlying model for both agents
- **Python** — core implementation
- **JSON file storage** — patient records, pending alerts, and audit logs (swappable for a real database in production)
- **FDA FAERS public data** — real-world adverse event evidence

## Setup Instructions

### Prerequisites
- Python 3.10+
- A Google API key with Gemini API access ([get one here](https://aistudio.google.com/apikey))

### Installation

```bash
git clone https://github.com/YOUR-USERNAME/medsafe-sathi.git
cd medsafe-sathi/medsafe_sathi_agent
pip install google-adk
```

### Running the ADK multi-agent version

```bash
# Windows PowerShell
$env:GOOGLE_API_KEY="your-api-key-here"

# Mac/Linux
export GOOGLE_API_KEY="your-api-key-here"

adk web
```

Then open `http://127.0.0.1:8000` in your browser, select the agent, and start a new session.

**Example message to trigger a full flow:**
```
patient_id: 9876543210, doctor: Dr. Rao, new drug: Ibuprofen, dose: 400mg, frequency: twice daily, prescription text: "Take one 400mg tablet twice a day for pain", allergy note: "none"
```

### Running the Lite (terminal) version

```bash
cd medsafe_sathi_lite
python main.py
```

Follow the on-screen menu to add a prescription, trigger a flag, and confirm it as the reviewing pharmacist.

## Project Structure

```
MedSafeSathi/
├── medsafe_sathi_agent/      # Full ADK multi-agent implementation
│   ├── agent.py
│   ├── data/                 # Patient records, alerts, audit log (gitignored)
│   └── __init__.py
├── medsafe_sathi_lite/        # Simplified terminal version for quick demos
│   └── main.py
└── medsafe_reporting_agent/   # Separate ADR reporting module
```

## Limitations & Honest Disclaimers

- The drug-interaction reference table is **deliberately small and curated for demonstration purposes** — it is not a claim of clinical completeness and should never be used as a substitute for a real clinical decision-support system or professional pharmacist judgment.
- Storage is file-based (JSON) for simplicity in this capstone; a production system would need a proper database with encryption at rest.
- This is a prototype built for a hackathon capstone, not a certified medical device.

## License

Submitted under CC-BY 4.0 per competition rules.
# MedSafe Sathi

**A multi-agent pharmacy safety system that catches dangerous drug interactions across doctors who never talk to each other — and never lets an AI make the final call alone.**

Built for the Vibecoding Agents Capstone Project (Google, Kaggle) — **Agents for Good** track.

---

## The Problem

In many healthcare settings, a patient can see multiple doctors — a cardiologist, a GP, a specialist — with no shared system between them. Doctor B has no way of knowing what Doctor A prescribed last month. This is a real, common cause of dangerous drug interactions and adverse reactions that go undetected until it's too late.

This problem has two names in clinical literature: **polypharmacy** and **underreporting**.

**Polypharmacy** — a patient taking multiple medications simultaneously, often prescribed by different, unconnected providers — is one of the strongest known risk factors for dangerous drug-drug interactions. The more medications a patient accumulates across uncoordinated visits, the higher the risk that two of them interact in ways no single doctor would catch, simply because no one doctor can see the whole list.

**Underreporting** compounds this further. Many adverse drug reactions that do occur are never formally logged anywhere, meaning the same dangerous combination can go unnoticed as a pattern across multiple patients. Both are leading, preventable contributors to avoidable hospitalizations — particularly for patients managing multiple chronic conditions across multiple providers.

At the same time, patients often don't understand their own prescriptions. A note like "Warfarin 5mg once daily" means very little to someone without a medical background, and a hand-written allergy note can contain personal details that shouldn't be stored insecurely.

**MedSafe Sathi** ("Sathi" means "companion" in Hindi) addresses both problems: it gives every doctor visibility into a patient's full medication history regardless of who prescribed what, flags dangerous interactions automatically, translates prescriptions into plain language for patients, and — critically — never lets the AI make a final safety decision alone. A human pharmacist always reviews and confirms every flag before a doctor ever sees it.

## The Solution

MedSafe Sathi is a multi-agent pipeline built on Google's Agent Development Kit (ADK). It has four cooperating pieces of logic, two of which run in real time as part of the prescription workflow, and a separate reporting component that operates independently:

1. **Intake Agent** — reads a new prescription and the patient's own allergy note, extracts structured data (drug, dose, frequency), strips personal identifiers before anything is stored, rewrites the prescription in plain language for the patient, and saves it to a shared patient record.
2. **Risk Check Agent** — the moment a new drug is prescribed, this agent pulls the patient's full medication history (regardless of which doctor entered it), checks the new drug against everything the patient is already taking using a curated drug-interaction reference table, and pulls real-world evidence from the FDA's FAERS adverse event database to back up any flag with actual reported case data.
3. **Human-in-the-loop review gate** — if an interaction is flagged, it is saved as **pending review** only. It is never shown to the doctor directly. A human pharmacist must explicitly confirm or reject the flag. Only a confirmed flag ever becomes visible to the doctor. Every decision — confirmed or overridden — is logged to a permanent audit trail.
4. **ADR Reporting Agent** *(separate module)* — handles adverse drug reaction reporting after the fact, since this happens at a different point in time from the real-time prescription flow above.

## Why This Matters (Agents for Good)

This project targets a real, well-documented healthcare safety gap: fragmented patient records across uncoordinated providers. Rather than trying to replace clinical judgment, the system is deliberately designed around **transparency and human oversight** — every AI-generated flag is explainable (it cites the specific interaction and, where available, real FDA report data), and no flag reaches a doctor without a human pharmacist's sign-off first. This reflects a responsible approach to deploying AI in a domain where mistakes have real consequences.

## Architecture

```
                     ┌────────────────────┐
   New prescription  │   Intake Agent     │
   + allergy note ───▶│  - extract data    │
                     │  - redact PII       │
                     │  - plain-language   │
                     │  - save to record   │
                     └─────────┬──────────┘
                               │
                               ▼
                     ┌────────────────────┐
                     │ Risk Check Agent   │
                     │ - pull history     │
                     │ - check interaction│
                     │ - pull FAERS data  │
                     └─────────┬──────────┘
                               │
                     flagged?  ▼
                     ┌────────────────────┐
                     │  Pending Alert     │
                     │ (hidden from       │
                     │  doctor)           │
                     └─────────┬──────────┘
                               │
                     ┌─────────▼──────────┐
                     │ Human Pharmacist   │
                     │ confirms / rejects │
                     └─────────┬──────────┘
                               │
                     confirmed ▼
                     ┌────────────────────┐
                     │ Visible to Doctor  │
                     └────────────────────┘
```

*(Add your actual ADK agent-graph screenshot here in the repo — e.g. `![Agent Graph](docs/agent_graph.png)`)*

## Key Features

- **Shared patient record across providers** — solves the real-world underreporting/fragmentation problem, so any doctor can see a patient's full history via a simple patient ID lookup.
- **Automated interaction detection** — checks new prescriptions against a curated, transparent reference table of known clinically significant drug interactions.
- **Real-world evidence backing** — pulls genuine FDA FAERS adverse event report data to support flags with actual case numbers, not just a static rule.
- **Mandatory human-in-the-loop** — no AI flag ever reaches a doctor without explicit pharmacist confirmation. This is enforced structurally (via `get_doctor_visible_alerts`, which can only ever return confirmed alerts), not just a suggestion.
- **Full audit trail** — every pharmacist decision (confirmed or overridden) is permanently logged with a timestamp and note.
- **PII redaction** — personal identifiers (phone numbers, names) are stripped from free-text notes before anything is saved.
- **Plain-language translation** — technical prescriptions are rewritten into simple instructions patients can actually understand.

## Tech Stack

- **Google Agent Development Kit (ADK)** — multi-agent orchestration (`Agent`, `Workflow`)
- **Gemini 2.5 Flash** — underlying model for both agents
- **Python** — core implementation
- **JSON file storage** — patient records, pending alerts, and audit logs (swappable for a real database in production)
- **FDA FAERS public data** — real-world adverse event evidence

## Setup Instructions

### Prerequisites
- Python 3.10+
- A Google API key with Gemini API access ([get one here](https://aistudio.google.com/apikey))

### Installation

```bash
git clone https://github.com/YOUR-USERNAME/medsafe-sathi.git
cd medsafe-sathi/medsafe_sathi_agent
pip install google-adk
```

### Running the ADK multi-agent version

```bash
# Windows PowerShell
$env:GOOGLE_API_KEY="your-api-key-here"

# Mac/Linux
export GOOGLE_API_KEY="your-api-key-here"

adk web
```

Then open `http://127.0.0.1:8000` in your browser, select the agent, and start a new session.

**Example message to trigger a full flow:**
```
patient_id: 9876543210, doctor: Dr. Rao, new drug: Ibuprofen, dose: 400mg, frequency: twice daily, prescription text: "Take one 400mg tablet twice a day for pain", allergy note: "none"
```

### Running the Lite (terminal) version

```bash
cd medsafe_sathi_lite
python main.py
```

Follow the on-screen menu to add a prescription, trigger a flag, and confirm it as the reviewing pharmacist.

## Project Structure

```
MedSafeSathi/
├── medsafe_sathi_agent/      # Full ADK multi-agent implementation
│   ├── agent.py
│   ├── data/                 # Patient records, alerts, audit log (gitignored)
│   └── __init__.py
├── medsafe_sathi_lite/        # Simplified terminal version for quick demos
│   └── main.py
└── medsafe_reporting_agent/   # Separate ADR reporting module
```

## Limitations & Honest Disclaimers

- The drug-interaction reference table is **deliberately small and curated for demonstration purposes** — it is not a claim of clinical completeness and should never be used as a substitute for a real clinical decision-support system or professional pharmacist judgment.
- Storage is file-based (JSON) for simplicity in this capstone; a production system would need a proper database with encryption at rest.
- This is a prototype built for a hackathon capstone, not a certified medical device.

## License

Submitted under CC-BY 4.0 per competition rules.
