"""
MedSafe Sathi — Two-Interface Dashboard (Reviewer view + Doctor view)

This is a SEPARATE, standalone file. It does not modify or depend on
agent.py in any way — it only READS the JSON data files that the existing
ADK agents already save, and writes confirm/reject decisions back to the
same pending_alerts.json file, using the exact same format the agent
already uses. If this file has any problem, your existing ADK project is
completely unaffected.

Run with: streamlit run dashboard.py
"""

import json
import os
from datetime import datetime

import streamlit as st

# ---------------------------------------------------------------------------
# Point this at your existing medsafe_sathi_agent/data folder.
# Adjust the path below if your folder structure is different.
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join("medsafe_sathi_agent", "data")
RECORD_FILE = os.path.join(DATA_DIR, "patient_records.json")
PENDING_ALERTS_FILE = os.path.join(DATA_DIR, "pending_alerts.json")
AUDIT_FILE = os.path.join(DATA_DIR, "audit_log.json")


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


st.set_page_config(page_title="MedSafe Sathi Dashboard", layout="wide")
st.title("MedSafe Sathi")
st.caption("A point-of-care prescription safety pipeline — reviewer and doctor views")

tab1, tab2 = st.tabs(["Reviewer View", "Doctor View"])

# ---------------------------------------------------------------------------
# TAB 1 — Reviewer View: sees ALL pending AI flags, can confirm or reject
# ---------------------------------------------------------------------------
with tab1:
    st.header("Reviewer View")
    st.write("The reviewer (pharmacist / PV staff) sees every AI-generated flag here, before the doctor ever sees anything.")

    alerts = load_json(PENDING_ALERTS_FILE)

    if not alerts:
        st.info("No alerts yet. Run a Visit 1 → Visit 2 sequence in your ADK agent first, then refresh this page.")
    else:
        for patient_id, patient_alerts in alerts.items():
            for alert in patient_alerts:
                with st.container(border=True):
                    st.markdown(f"**Patient ID:** {patient_id}")
                    st.markdown(f"**Alert ID:** {alert['alert_id']}")
                    st.markdown(f"**AI Flag:** {alert['ai_flag_summary']}")
                    st.markdown(f"**Status:** `{alert['status']}`")

                    if alert["status"] == "pending_review":
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button(f"✅ Confirm", key=f"confirm_{alert['alert_id']}"):
                                alert["status"] = "visible_to_doctor"
                                alert["reviewer_note"] = "Confirmed via dashboard"
                                save_json(PENDING_ALERTS_FILE, alerts)

                                logs = load_json(AUDIT_FILE)
                                logs.setdefault(patient_id, []).append({
                                    "ai_flag_summary": alert["ai_flag_summary"],
                                    "human_decision": "confirmed",
                                    "note": "Confirmed via dashboard",
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                })
                                save_json(AUDIT_FILE, logs)
                                st.rerun()
                        with col2:
                            if st.button(f"❌ Reject", key=f"reject_{alert['alert_id']}"):
                                alert["status"] = "rejected"
                                alert["reviewer_note"] = "Rejected via dashboard"
                                save_json(PENDING_ALERTS_FILE, alerts)
                                st.rerun()

# ---------------------------------------------------------------------------
# TAB 2 — Doctor View: ONLY sees alerts a human has already confirmed
# ---------------------------------------------------------------------------
with tab2:
    st.header("Doctor View")
    st.write("The doctor only ever sees alerts that a human reviewer has already confirmed — never raw, unverified AI output.")

    alerts = load_json(PENDING_ALERTS_FILE)
    visible_any = False

    for patient_id, patient_alerts in alerts.items():
        confirmed = [a for a in patient_alerts if a["status"] == "visible_to_doctor"]
        if confirmed:
            visible_any = True
            st.subheader(f"Patient ID: {patient_id}")
            for alert in confirmed:
                st.warning(alert["ai_flag_summary"])

    if not visible_any:
        st.info("Nothing to show yet — no alerts have been confirmed by a reviewer.")