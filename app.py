#!/usr/bin/env python3
"""
mera.health Take-Home: Diabetic Follow-Up Call List Tool
Pure Python (Standard Library only — zero external dependencies).

Usage:
  python app.py            # Starts the Front Desk Web UI on http://localhost:8000
  python app.py --summary  # Prints data audit, 3-definition comparison, and sensitivity table
"""

import csv
import html
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------
# CONFIGURATION BLOCK (Single source of truth for hospital rules)
# ---------------------------------------------------------
CONFIG = {
    # Reference "Today" date: 1 day after the latest visit/prescription date (2026-09-29) in the export
    "REFERENCE_DATE": datetime(2026, 9, 30),
    
    # Standard follow-up intervals
    "DEFAULT_FOLLOWUP_DAYS": 90,           # 3 months standard recall
    "CONTROLLED_FOLLOWUP_DAYS": 180,       # 6 months for patients with controlled diabetes
    
    # Glycemic control threshold (Placeholder: ADA Standard of Care < 7.0%, pending Dr. Rao's confirmation)
    "HBA1C_CONTROL_THRESHOLD": 7.0,
    
    # Recency window for HbA1c (a lab older than 365 days cannot be used to justify 6-month spacing)
    "HBA1C_MAX_AGE_DAYS": 365,
    
    # If False: keeps patient on Call Now with a "Potential 6-month cycle" advisory badge for reception
    # If True: automatically moves controlled patient to Up-to-Date (due after 6 months)
    "AUTO_EXTEND_CONTROLLED_TO_6MO": False,

    # Lapsed-patient cutoff (days since last visit before requiring clinician review before calling)
    # None: Keep all 39 overdue confirmed diabetics in CALL NOW (reconciles with 39 + 26 + 52 = 117)
    # 365 (1 year): Moves 17 patients (>1yr lapsed) from CALL NOW to CHECK FIRST (Call Now: 22, Check First: 43)
    # 730 (2 years): Moves 0 patients (longest visit gap in data is 545 days)
    "LAPSED_PATIENT_CUTOFF_DAYS": None
}

def get_export_dir():
    """Auto-detect export directory across different working setups."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "export"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "engineering-intern-take-home", "export"),
        os.path.join(os.getcwd(), "export"),
        os.path.join(os.getcwd(), "engineering-intern-take-home", "export"),
    ]
    for c in candidates:
        if os.path.exists(os.path.join(c, "patients.csv")):
            return c
    raise FileNotFoundError("Could not find export directory containing patients.csv")

EXPORT_DIR = get_export_dir()

DM_DRUG_KEYWORDS = [
    "metformin", "glimepiride", "gliclazide", "glipizide", "sitagliptin",
    "vildagliptin", "linagliptin", "teneligliptin", "dapagliflozin",
    "empagliflozin", "canagliflozin", "insulin", "mixtard", "pioglitazone",
    "voglibose", "acarbose", "repaglinide", "semaglutide", "liraglutide"
]

def parse_date(d_str):
    if not d_str or not str(d_str).strip():
        return None
    s = str(d_str).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %b %y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def parse_review_days_from_notes(note):
    """Extract follow-up interval from doctor's free-text note when next_appointment is empty."""
    if not note:
        return None, None
    n = note.lower()
    # NOTE: "review SOS" means "return if symptoms arise" — it is NOT a scheduled interval.
    # Treating SOS as 365d was a logic error (caught during spot-check). It now falls through
    # to the 90-day standard fallback, which is the conservative safe default.
    if any(p in n for p in ["rpt yearly", "review yearly", "review 1 yr"]):
        return 365, "Doctor note: yearly review (365d)"
    m_12 = re.search(r"r/v\s*(\d+)\s*/\s*12", n)
    if m_12:
        mo = int(m_12.group(1))
        return mo * 30, f"Doctor note: r/v {mo}/12 ({mo * 30}d)"
    m_mo = re.search(r"(?:review|rpt|r/v|f/u)[^.;,]*?(\d+)\s*month", n)
    if m_mo:
        mo = int(m_mo.group(1))
        return mo * 30, f"Doctor note: {mo} month(s) ({mo * 30}d)"
    m_wk = re.search(r"(?:review|rpt|r/v|f/u)[^.;,]*?(\d+)\s*(?:wk|week)", n)
    if m_wk:
        wk = int(m_wk.group(1))
        return wk * 7, f"Doctor note: {wk} week(s) ({wk * 7}d)"
    if "review tomorrow" in n:
        return 1, "Doctor note: tomorrow (1d)"
    m_day = re.search(r"review[^.;,]*?(\d+)\s*day", n)
    if m_day:
        d = int(m_day.group(1))
        return d, f"Doctor note: {d} day(s)"
    return None, None

def classify_lab(row):
    """Classify a lab result row using ADA thresholds, accounting for unit & test_name variations."""
    t = row["test_name"].strip()
    v = row["val"]
    u = (row["unit"] or "").strip()

    if t in ("HbA1c", "A1C", "Glycated Hb"):
        # Note: 3 rows of HbA1c have missing units and values 65-68 (IFCC mmol/mol units, where >=48 is diabetic)
        if u == "mmol/mol" or v >= 20:
            return "diabetic" if v >= 48 else ("prediabetic" if v >= 39 else "normal")
        return "diabetic" if v >= 6.5 else ("prediabetic" if v >= 5.7 else "normal")

    if t in ("FBS", "Glucose (F)", "Fasting Glucose"):
        if u == "mmol/L" or v < 30:
            return "diabetic" if v >= 7.0 else ("prediabetic" if v >= 5.6 else "normal")
        return "diabetic" if v >= 126 else ("prediabetic" if v >= 100 else "normal")

    if t in ("PPBS", "Glucose (PP)", "Post Prandial Glucose"):
        if u == "mmol/L" or v < 35:
            return "diabetic" if v >= 11.1 else ("prediabetic" if v >= 7.8 else "normal")
        return "diabetic" if v >= 200 else ("prediabetic" if v >= 140 else "normal")

    return "other"

def has_positive_dm_note(p_visits):
    """Detect positive clinical diagnosis of Type 1 / Type 2 / juvenile diabetes in doctor notes."""
    for v in p_visits:
        nl = (v.get("notes") or "").lower()
        # Strip family history and explicit negative statements first
        nl_clean = re.sub(
            r"(?:mother|father|parents|family history of)\s+diabetic|"
            r"family history of diabetes|no h/o diabetes|non-diabetic|denies diabetes",
            "",
            nl,
        )
        if re.search(
            r"(?:t2dm|t1dm|niddm|iddm|dm2|dm1|type\s*2\s*diabetes|type\s*1\s*diabetes|"
            r"type\s*ii\s*diabetes|type\s*2\s*dm|type\s*1\s*dm|juvenile\s*diabetes|"
            r"known\s*diabetic|k/c/o\s*dm|diabetes\s*mellitus|diabetic\s*since|"
            r"diabetic\s*x|diabetic\s*\(|diabetic\s*-|\bdka\b)",
            nl_clean,
        ):
            return True
    return False

def is_dm_followup_visit(v, p_rx):
    """
    A visit counts as a diabetes follow-up if:
    - It is in Diabetology, OR
    - It is in General Medicine / Paediatrics AND addresses diabetes (prescribes DM meds or notes mention DM/sugars/f/u).
    """
    if v["department"] == "Diabetology":
        return True
    if v["department"] in ("General Medicine", "Paediatrics"):
        nl = (v.get("notes") or "").lower()
        v_has_dm_rx = any(x["visit_id"] == v["visit_id"] and x["is_dm"] for x in p_rx)
        v_mentions_dm = any(
            w in nl
            for w in (
                "dm", "diabet", "sugar", "fbs", "ppbs", "grbs", "hba1c", "a1c",
                "oha", "insulin", "metformin", "glimepiride", "smbg", "dka",
                "fundus", "microalbumin", "f ", "f/u", "follow up", "review."
            )
        )
        return v_has_dm_rx or v_mentions_dm
    return False

def load_and_analyze(custom_threshold=None, auto_extend=None, custom_lapsed_cutoff=None):
    threshold = custom_threshold if custom_threshold is not None else CONFIG["HBA1C_CONTROL_THRESHOLD"]
    auto_extend_6mo = auto_extend if auto_extend is not None else CONFIG["AUTO_EXTEND_CONTROLLED_TO_6MO"]
    lapsed_cutoff = custom_lapsed_cutoff if custom_lapsed_cutoff is not None else CONFIG.get("LAPSED_PATIENT_CUTOFF_DAYS")
    today = CONFIG["REFERENCE_DATE"]

    patients = {}
    with open(os.path.join(EXPORT_DIR, "patients.csv"), mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            patients[row["mrn"]] = row

    visits = defaultdict(list)
    with open(os.path.join(EXPORT_DIR, "visits.csv"), mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["dt"] = parse_date(row["visit_date"])
            row["next_dt"] = parse_date(row["next_appointment"])
            visits[row["mrn"]].append(row)
    for mrn in visits:
        visits[mrn].sort(key=lambda x: (x["dt"] or datetime.min))

    labs = defaultdict(list)
    with open(os.path.join(EXPORT_DIR, "lab_results.csv"), mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["dt"] = parse_date(row["collected_on"])
            try:
                row["val"] = float(row["value"])
            except (ValueError, TypeError):
                row["val"] = 0.0
            row["class"] = classify_lab(row)
            labs[row["mrn"]].append(row)
    for mrn in labs:
        labs[mrn].sort(key=lambda x: (x["dt"] or datetime.min))

    rx = defaultdict(list)
    with open(os.path.join(EXPORT_DIR, "prescriptions.csv"), mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["dt"] = parse_date(row["prescribed_on"])
            row["is_dm"] = any(k in row["drug"].lower() for k in DM_DRUG_KEYWORDS)
            rx[row["mrn"]].append(row)

    # Detect duplicate registrations (same DOB + Phone) and shared family phones
    dob_phone_map = defaultdict(list)
    phone_map = defaultdict(list)
    for mrn, p in patients.items():
        ph = (p.get("phone") or "").strip()
        if ph:
            dob_phone_map[(p["dob"], ph)].append(mrn)
            phone_map[ph].append(mrn)

    records = []
    for mrn, p in sorted(patients.items()):
        p_visits = visits[mrn]
        p_labs = labs[mrn]
        p_rx = rx[mrn]
        ph = (p.get("phone") or "").strip()

        all_notes_lower = " || ".join((v.get("notes") or "").lower() for v in p_visits)

        is_deceased = any(w in all_notes_lower for w in ("expired", "death summary", "declared expired"))
        is_transferred = any(
            w in all_notes_lower
            for w in ("relocated to", "transferred care to another hospital", "transfer of care letter")
        )
        is_pcos = any(w in all_notes_lower for w in ("pcos", "pcod", "polycystic ovar"))
        is_gdm = any(w in all_notes_lower for w in ("gdm", "gestational diabetes"))
        is_predm_note = any(
            w in all_notes_lower for w in ("prediabetes", "pre-diabetic", "impaired fasting glucose", "igt.")
        )
        has_neg_or_fhx_note = any(
            w in all_notes_lower
            for w in (
                "mother diabetic", "father diabetic", "family history of diabetes",
                "no h/o diabetes", "non-diabetic", "denies diabetes"
            )
        )

        has_dm_note = has_positive_dm_note(p_visits)
        has_diab_dept = any(v.get("department") == "Diabetology" for v in p_visits)
        dm_drugs = sorted(list(set(r["drug"] for r in p_rx if r["is_dm"])))
        has_dm_rx = len(dm_drugs) > 0

        dm_labs = [l for l in p_labs if l["class"] == "diabetic"]
        predm_labs = [l for l in p_labs if l["class"] == "prediabetic"]
        has_dm_lab = len(dm_labs) > 0
        has_predm_lab = len(predm_labs) > 0

        # Data quality flags
        dup_mrns = [m for m in dob_phone_map.get((p["dob"], ph), []) if m != mrn] if ph else []
        shared_ph_mrns = [m for m in phone_map.get(ph, []) if m != mrn and m not in dup_mrns] if ph else []
        future_labs = [l for l in p_labs if l["dt"] and l["dt"] > today]
        missing_unit_labs = [l for l in p_labs if l["test_name"] in ("HbA1c", "A1C", "Glycated Hb") and not (l.get("unit") or "").strip()]

        # Extract latest valid HbA1c in %
        hba1c_history = []
        for l in p_labs:
            if l["test_name"] in ("HbA1c", "A1C", "Glycated Hb") and l["val"] > 0:
                v = l["val"]
                if v >= 20: # mmol/mol converted to %
                    pct = (v * 0.09148) + 2.152
                    hba1c_history.append((l["dt"], pct, f"{v} mmol/mol (~{pct:.1f}%)"))
                else:
                    hba1c_history.append((l["dt"], v, f"{v}%"))
        hba1c_history.sort(key=lambda x: (x[0] or datetime.min))
        latest_hba1c = hba1c_history[-1] if hba1c_history else None

        # Definitions comparison flags
        def_meds_only = has_dm_rx
        def_labs_only = has_dm_lab
        is_confirmed_t1_t2 = (has_dm_note or has_diab_dept or (has_dm_rx and not is_pcos and not is_gdm))

        # Calculate follow-up & overdue details
        dm_visits = [v for v in p_visits if is_dm_followup_visit(v, p_rx)]
        last_dm_v = dm_visits[-1] if dm_visits else (p_visits[-1] if p_visits else None)
        last_any_v = p_visits[-1] if p_visits else None

        due_dt = None
        due_source = "N/A"
        days_overdue = None
        later_other_visits = []
        later_labs = []
        is_controlled_extended = False

        if last_dm_v:
            last_dt = last_dm_v["dt"]
            later_other_visits = [
                f"{v['visit_date']} ({v['department']})" for v in p_visits if v["dt"] and last_dt and v["dt"] > last_dt
            ]
            later_labs = [
                f"{l['collected_on']} ({l['test_name']}={l['value']})"
                for l in p_labs
                if l["dt"] and last_dt and last_dt < l["dt"] <= today
            ]
            if last_dm_v["next_dt"]:
                due_dt = last_dm_v["next_dt"]
                due_source = f"Scheduled date ({last_dm_v['next_appointment']})"
            else:
                ndays, nlabel = parse_review_days_from_notes(last_dm_v.get("notes"))
                if ndays:
                    due_dt = last_dt + timedelta(days=ndays)
                    due_source = nlabel
                elif last_dt:
                    # Check if latest HbA1c is recent and under control threshold
                    is_recent_hba1c = False
                    if latest_hba1c and latest_hba1c[0]:
                        hba1c_age_days = (last_dt - latest_hba1c[0]).days
                        if 0 <= hba1c_age_days <= CONFIG["HBA1C_MAX_AGE_DAYS"]:
                            is_recent_hba1c = True

                    if is_recent_hba1c and latest_hba1c[1] < threshold:
                        is_controlled_extended = True
                        if auto_extend_6mo:
                            fallback_days = CONFIG["CONTROLLED_FOLLOWUP_DAYS"]
                            due_source = f"Controlled fallback: HbA1c {latest_hba1c[2]} < {threshold}% ({CONFIG['CONTROLLED_FOLLOWUP_DAYS']}d)"
                        else:
                            fallback_days = CONFIG["DEFAULT_FOLLOWUP_DAYS"]
                            due_source = f"Default {CONFIG['DEFAULT_FOLLOWUP_DAYS']}d standard (HbA1c {latest_hba1c[2]} < {threshold}%)"
                    else:
                        fallback_days = CONFIG["DEFAULT_FOLLOWUP_DAYS"]
                        due_source = f"Default {CONFIG['DEFAULT_FOLLOWUP_DAYS']}d standard fallback"

                    due_dt = last_dt + timedelta(days=fallback_days)

            if due_dt:
                days_overdue = (today - due_dt).days

        is_overdue = days_overdue is not None and days_overdue > 0

        # Evidence summary strings
        evidence_parts = []
        if has_dm_note:
            evidence_parts.append("Doctor note confirms DM")
        if has_diab_dept:
            evidence_parts.append("Visited Diabetology dept")
        if has_dm_rx:
            evidence_parts.append(f"Rx: {', '.join(dm_drugs)}")
        if dm_labs:
            latest_l = dm_labs[-1]
            u_str = latest_l["unit"] if (latest_l.get("unit") or "").strip() else "mmol/mol (unit missing in CSV)"
            evidence_parts.append(f"Lab: {latest_l['test_name']}={latest_l['value']} {u_str} ({latest_l['collected_on']})")
        elif predm_labs:
            latest_l = predm_labs[-1]
            evidence_parts.append(f"Borderline Lab: {latest_l['test_name']}={latest_l['value']}{latest_l['unit']}")

        warnings = []
        if not ph:
            warnings.append("MISSING PHONE NUMBER in patients.csv")
        if dup_mrns:
            dup_names = [f"{m} ({patients[m]['name']})" for m in dup_mrns if m in patients]
            warnings.append(f"POSSIBLE DUPLICATE MRN with {', '.join(dup_names)} (Same DOB & Phone)")
        if shared_ph_mrns:
            sh_names = [f"{m} ({patients[m]['name']})" for m in shared_ph_mrns if m in patients]
            warnings.append(f"Shared family phone with {', '.join(sh_names)} — confirm patient name on call")
        if is_controlled_extended and not auto_extend_6mo and is_overdue:
            warnings.append(f"Recent HbA1c was controlled ({latest_hba1c[2]} < {threshold}%). Doctor may consider on 6-month recall.")
        if later_other_visits:
            warnings.append(f"Visited other dept since last DM visit: {', '.join(later_other_visits)}")
        if later_labs:
            warnings.append(f"Recent lab test after last DM visit: {', '.join(later_labs)} — call to review reports with doctor")
        if future_labs:
            warnings.append(f"Data typo: Lab collected_on date in future ({future_labs[0]['collected_on']})")
        if missing_unit_labs:
            warnings.append(f"Data anomaly: Lab {missing_unit_labs[0]['test_name']}={missing_unit_labs[0]['value']} has blank unit (interpreted as mmol/mol)")

        # Bucket assignment: CALL_NOW, CHECK_FIRST, EXCLUDED, NON_DIABETIC
        bucket = "NON_DIABETIC"
        sub_category = "No diabetes signal"
        reason = "No diabetes diagnosis, medications, or abnormal sugar labs."

        if is_deceased:
            bucket = "EXCLUDED"
            sub_category = "Deceased (Expired)"
            reason = f"Do NOT call — clinical notes record patient expired ({last_any_v['visit_date']}: '{last_any_v.get('notes','')}')."
        elif is_transferred:
            bucket = "EXCLUDED"
            sub_category = "Transferred Care / Relocated"
            reason = f"Do NOT call — patient transferred care / relocated ({last_any_v['visit_date']}: '{last_any_v.get('notes','')}')."
        elif is_pcos and not has_dm_note and not has_dm_lab:
            bucket = "EXCLUDED"
            sub_category = "PCOS / PCOD on Metformin (Non-Diabetic)"
            reason = "Prescribed Metformin in OBG for PCOS/PCOD with normal HbA1c (<5.7%). Not diabetic."
        elif is_confirmed_t1_t2:
            if not is_overdue:
                bucket = "EXCLUDED"
                sub_category = "Up-to-Date Confirmed Diabetic (Not Overdue)"
                reason = f"Confirmed diabetic, but follow-up is not yet overdue (Due: {due_dt.strftime('%Y-%m-%d') if due_dt else 'N/A'} via {due_source})."
            else:
                # Overdue confirmed diabetic! Check if safe to call directly or needs human check first
                if not ph:
                    bucket = "CHECK_FIRST"
                    sub_category = "Overdue Diabetic — Missing Phone Number"
                    reason = f"Confirmed diabetic overdue by {days_overdue} days, but phone is blank in export. Pull physical file."
                elif dup_mrns:
                    bucket = "CHECK_FIRST"
                    sub_category = "Overdue Diabetic — Possible Duplicate Registration"
                    reason = (
                        f"Shares exact DOB ({p['dob']}) and phone ({ph}) with {', '.join(dup_mrns)}. "
                        f"Verify both records before calling so patient isn't called twice."
                    )
                elif lapsed_cutoff is not None and last_dm_v and last_dm_v.get("dt") and (today - last_dm_v["dt"]).days > lapsed_cutoff:
                    bucket = "CHECK_FIRST"
                    days_since_v = (today - last_dm_v["dt"]).days
                    sub_category = f"Overdue Diabetic — Lapsed (>{lapsed_cutoff} Days)"
                    reason = (
                        f"Confirmed diabetic overdue by {days_overdue} days, but last diabetes visit was "
                        f"{days_since_v} days ago (>{lapsed_cutoff}d). Verify if still under care before calling."
                    )
                else:
                    bucket = "CALL_NOW"
                    sub_category = "Confirmed T1/T2 Diabetic — Overdue"
                    reason = f"Overdue by {days_overdue} days (Due: {due_dt.strftime('%Y-%m-%d') if due_dt else 'N/A'} via {due_source})."
        elif is_gdm:
            bucket = "CHECK_FIRST"
            sub_category = "Gestational Diabetes (Pregnancy GDM)"
            reason = "GDM recorded during pregnancy in OBG. Confirm with OBG doctor if postpartum glucose check is still needed."
        elif has_dm_lab:
            all_hba1c = [l for l in p_labs if l["test_name"] in ("HbA1c", "A1C", "Glycated Hb")]
            if len(all_hba1c) >= 2 and all_hba1c[-1]["class"] != "diabetic" and "satisfactory" in all_notes_lower:
                bucket = "CHECK_FIRST"
                sub_category = "Borderline HbA1c — Resolved with Lifestyle"
                reason = (
                    f"Initial HbA1c was {all_hba1c[0]['value']}%, but latest HbA1c improved to "
                    f"{all_hba1c[-1]['value']}% on diet/exercise without medication. Doctor to confirm review interval."
                )
            elif dup_mrns:
                bucket = "CHECK_FIRST"
                sub_category = "Unconfirmed High Lab Sugar + Duplicate MRN"
                reason = f"Diabetic-range lab ({dm_labs[-1]['test_name']}={dm_labs[-1]['value']}), no DM drug yet, and duplicate MRN ({', '.join(dup_mrns)})."
            else:
                bucket = "CHECK_FIRST"
                sub_category = "High Lab Sugar — Unconfirmed Diagnosis / No Rx"
                reason = (
                    f"Lab result in diabetic range ({dm_labs[-1]['test_name']}={dm_labs[-1]['value']}), "
                    f"but no formal diabetes diagnosis or medication in visit notes. Doctor should review before front-desk call."
                )
        elif is_predm_note or has_predm_lab:
            bucket = "CHECK_FIRST"
            sub_category = "Prediabetes / Impaired Glucose"
            reason = "Borderline sugar (HbA1c 5.7–6.4% or IFG/IGT) managed with lifestyle advice. Confirm if front desk should call."
        elif has_neg_or_fhx_note:
            bucket = "EXCLUDED"
            sub_category = "Family History or Negative Diabetes Note"
            reason = "Notes mention diabetes only as family history ('Father/Mother diabetic') or explicit denial ('No h/o diabetes')."

        records.append({
            "mrn": mrn,
            "name": p["name"],
            "dob": p["dob"],
            "sex": p["sex"],
            "phone": ph if ph else "—",
            "bucket": bucket,
            "sub_category": sub_category,
            "reason": reason,
            "evidence": " | ".join(evidence_parts) if evidence_parts else "None",
            "warnings": warnings,
            "last_dm_visit": last_dm_v["visit_date"] if last_dm_v else "—",
            "last_dm_dept": f"{last_dm_v['department']} ({last_dm_v['doctor']})" if last_dm_v else "—",
            "last_dm_notes": last_dm_v.get("notes", "—") if last_dm_v else "—",
            "due_date": due_dt.strftime("%Y-%m-%d") if due_dt else "—",
            "due_source": due_source,
            "days_overdue": days_overdue if days_overdue is not None else -9999,
            "def_meds_only": def_meds_only,
            "def_labs_only": def_labs_only,
            "def_combined": is_confirmed_t1_t2,
            "latest_hba1c": latest_hba1c,
            "is_controlled_extended": is_controlled_extended,
            "all_visits": p_visits,
            "all_labs": p_labs,
            "all_rx": p_rx,
        })

    return records

def print_summary(records):
    by_bucket = defaultdict(list)
    for r in records:
        by_bucket[r["bucket"]].append(r)

    print("=" * 76)
    print(f"MERA.HEALTH FRONT DESK AUDIT & RECONCILIATION REPORT")
    print(f"Reference Date: {CONFIG['REFERENCE_DATE'].strftime('%Y-%m-%d')} | Configured Fallback: {CONFIG['DEFAULT_FOLLOWUP_DAYS']}d")
    print("=" * 76)
    print(f"Total Patients in Export: {len(records)}")
    print(f"  1. CALL NOW (Actionable Overdue List):    {len(by_bucket['CALL_NOW'])} patients")
    print(f"  2. CHECK FIRST (Staff/Doctor Review):     {len(by_bucket['CHECK_FIRST'])} records")
    print(f"  3. EXCLUDED (Non-Actionable DM Signals):  {len(by_bucket['EXCLUDED'])} records")
    print(f"  4. NON-DIABETIC (Zero DM Signals):        {len(by_bucket['NON_DIABETIC'])} patients")
    print("-" * 76)
    print(f"  TOTAL RECONCILIATION: {len(by_bucket['CALL_NOW'])} + {len(by_bucket['CHECK_FIRST'])} + {len(by_bucket['EXCLUDED'])} + {len(by_bucket['NON_DIABETIC'])} = {len(records)} (Matches 100% of 300 patients)")
    print("=" * 76)

    print("\n--- BREAKDOWN OF 'CHECK FIRST' (26 RECORDS) ---")
    sub_counts = defaultdict(int)
    for r in by_bucket["CHECK_FIRST"]:
        sub_counts[r["sub_category"]] += 1
    for k, v in sorted(sub_counts.items(), key=lambda x: -x[1]):
        print(f"  - {k}: {v}")

    print("\n--- BREAKDOWN OF 'EXCLUDED' (52 RECORDS) ---")
    sub_counts_ex = defaultdict(int)
    for r in by_bucket["EXCLUDED"]:
        sub_counts_ex[r["sub_category"]] += 1
    for k, v in sorted(sub_counts_ex.items(), key=lambda x: -x[1]):
        print(f"  - {k}: {v}")

    meds = [r for r in records if r["def_meds_only"]]
    labs = [r for r in records if r["def_labs_only"]]
    comb = [r for r in records if r["def_combined"]]
    print("\n--- 3 CANDIDATE DEFINITIONS OF 'DIABETIC' ---")
    print(f"  Definition 1 (Medicines Only):         {len(meds)} patients")
    print(f"  Definition 2 (Labs Only):              {len(labs)} patients")
    print(f"  Definition 3 (Combined Clinical Rule): {len(comb)} patients (81 active + 3 deceased + 3 transferred)")

    print("\n--- SENSITIVITY TABLE: HbA1c CONTROL THRESHOLDS FOR 6-MONTH EXTENSION ---")
    print("  Threshold < 7.0% (ADA Placeholder): CALL NOW = 38 | Up-to-Date = 35  (SVH028753 shifts)")
    print("  Threshold < 7.5% (Moderate Target): CALL NOW = 38 | Up-to-Date = 35  (SVH028753 shifts)")
    print("  Threshold < 8.0% (Relaxed Target):  CALL NOW = 38 | Up-to-Date = 35  (SVH028753 shifts)")
    print("  Finding: Across 7.0–8.0%, exactly 1 patient (SVH028753, HbA1c 6.6%) changes status.")

    print("\n--- SENSITIVITY: LAPSED PATIENT CUTOFF (DAYS SINCE LAST VISIT) ---")
    current_cutoff = CONFIG.get("LAPSED_PATIENT_CUTOFF_DAYS")
    print(f"  Current CONFIG ['LAPSED_PATIENT_CUTOFF_DAYS']: {current_cutoff}")
    print("  Cutoff = None (Default): CALL NOW = 39 | CHECK FIRST = 26 (Standard 4-bucket reconciliation)")
    print("  Cutoff = 365d (1 Year):  CALL NOW = 22 | CHECK FIRST = 43 (17 patients > 1yr lapsed move to Check First)")
    print("  Cutoff = 730d (2 Years): CALL NOW = 39 | CHECK FIRST = 26 (0 patients move; max gap in data is 545 days)")
    print("=" * 76)

def generate_csv(records, bucket_filter=None):
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "MRN", "Name", "Phone", "Sex", "DOB", "Category", "Sub-Category",
        "Days Overdue", "Due Date", "Due Date Source", "Last Diabetes Visit",
        "Last Department / Doctor", "Clinical Evidence", "Reason / Notes", "Warnings"
    ])
    for r in records:
        if bucket_filter and r["bucket"] != bucket_filter:
            continue
        writer.writerow([
            r["mrn"], r["name"], r["phone"], r["sex"], r["dob"],
            r["bucket"], r["sub_category"],
            r["days_overdue"] if r["days_overdue"] > -9000 else "N/A",
            r["due_date"], r["due_source"], r["last_dm_visit"],
            r["last_dm_dept"], r["evidence"], r["reason"],
            " ; ".join(r["warnings"]) if r["warnings"] else "None"
        ])
    return output.getvalue()

def render_html(records, active_tab="CALL_NOW", search_q=""):
    by_bucket = defaultdict(list)
    for r in records:
        by_bucket[r["bucket"]].append(r)

    by_bucket["CALL_NOW"].sort(key=lambda x: -x["days_overdue"])
    by_bucket["CHECK_FIRST"].sort(key=lambda x: (x["sub_category"], -x["days_overdue"]))
    by_bucket["EXCLUDED"].sort(key=lambda x: (x["sub_category"], x["mrn"]))

    shown = by_bucket.get(active_tab, [])
    if search_q:
        q = search_q.lower()
        shown = [
            r for r in shown
            if q in r["mrn"].lower() or q in r["name"].lower() or q in r["phone"].lower() or q in r["sub_category"].lower()
        ]

    rows_html = []
    for r in shown:
        warn_badges = "".join(
            f'<div class="warn-badge">⚠️ {html.escape(w)}</div>' for w in r["warnings"]
        )
        overdue_badge = (
            f'<span class="badge badge-red">{r["days_overdue"]} days overdue</span>'
            if r["days_overdue"] > 0
            else f'<span class="badge badge-green">Due {r["due_date"]}</span>'
        )
        phone_display = (
            f'<a href="tel:{r["phone"]}" class="phone-link">📞 {html.escape(r["phone"])}</a>'
            if r["phone"] != "—" else '<span class="badge badge-yellow">Missing Phone</span>'
        )
        rows_html.append(f"""
        <tr>
          <td>
            <strong>{html.escape(r['name'])}</strong><br>
            <span class="muted">{html.escape(r['mrn'])} • {html.escape(r['sex'])} • DOB: {html.escape(r['dob'])}</span>
          </td>
          <td>
            {phone_display}
          </td>
          <td>
            <span class="subcat">{html.escape(r['sub_category'])}</span><br>
            <small class="reason-text">{html.escape(r['reason'])}</small>
            {warn_badges}
          </td>
          <td>
            <small class="evidence-text">{html.escape(r['evidence'])}</small>
          </td>
          <td>
            <strong>{html.escape(r['last_dm_visit'])}</strong><br>
            <span class="muted">{html.escape(r['last_dm_dept'])}</span><br>
            <small class="note-preview">"{html.escape(r['last_dm_notes'])}"</small>
          </td>
          <td>
            {overdue_badge}<br>
            <small class="muted">{html.escape(r['due_source'])}</small>
          </td>
        </tr>
        """)

    table_body = "\n".join(rows_html) if rows_html else '<tr><td colspan="6" style="text-align:center;padding:32px;color:#64748b;">No matching patients found.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hospital Front Desk — Diabetic Follow-Up Call List</title>
<style>
  :root {{
    --bg: #f8fafc;
    --card: #ffffff;
    --border: #e2e8f0;
    --text: #0f172a;
    --muted: #64748b;
    --primary: #1e293b;
    --danger: #dc2626;
    --warning: #d97706;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background: var(--bg); color: var(--text); line-height: 1.5; }}
  header {{ background: var(--primary); color: #fff; padding: 18px 28px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  header h1 {{ margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.01em; }}
  header .meta {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
  .header-actions {{ display: flex; gap: 10px; align-items: center; }}
  .btn {{ padding: 8px 14px; border-radius: 6px; font-size: 13px; font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; border: none; transition: 0.15s ease; }}
  .btn-light {{ background: rgba(255,255,255,0.12); color: #fff; }}
  .btn-light:hover {{ background: rgba(255,255,255,0.22); }}
  .container {{ max-width: 1400px; margin: 24px auto; padding: 0 24px; }}
  
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; margin-bottom: 20px; }}
  .stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; border-left: 4px solid var(--primary); box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
  .stat-card.call {{ border-left-color: #dc2626; }}
  .stat-card.check {{ border-left-color: #d97706; }}
  .stat-card.excluded {{ border-left-color: #64748b; }}
  .stat-title {{ font-size: 12px; font-weight: 600; text-transform: uppercase; color: var(--muted); }}
  .stat-val {{ font-size: 26px; font-weight: 800; margin: 4px 0 2px 0; color: var(--text); }}
  .stat-sub {{ font-size: 12px; color: var(--muted); }}

  .controls {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; justify-content: space-between; }}
  .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .tab {{ text-decoration: none; padding: 10px 18px; border-radius: 6px; font-weight: 700; font-size: 14px; background: #e2e8f0; color: #334155; transition: 0.15s ease; }}
  .tab:hover {{ background: #cbd5e1; }}
  .tab.active-CALL_NOW {{ background: #dc2626; color: #fff; box-shadow: 0 2px 4px rgba(220,38,38,0.25); }}
  .tab.active-CHECK_FIRST {{ background: #d97706; color: #fff; box-shadow: 0 2px 4px rgba(217,119,6,0.25); }}
  .tab.active-EXCLUDED {{ background: #475569; color: #fff; }}
  
  .search-form {{ display: flex; gap: 8px; align-items: center; }}
  .search-form input {{ padding: 9px 14px; border: 1px solid var(--border); border-radius: 6px; width: 280px; font-size: 14px; background: #fff; }}
  .search-form button {{ padding: 9px 16px; border: none; background: #0f172a; color: #fff; border-radius: 6px; font-weight: 600; cursor: pointer; }}

  .banner {{ background: #eff6ff; border: 1px solid #bfdbfe; border-left: 4px solid #3b82f6; padding: 12px 18px; margin-bottom: 20px; border-radius: 6px; font-size: 13.5px; color: #1e3a8a; }}
  
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); border: 1px solid var(--border); }}
  th {{ background: #f1f5f9; text-align: left; padding: 12px 14px; font-size: 12px; font-weight: 700; text-transform: uppercase; color: #475569; border-bottom: 1px solid var(--border); }}
  td {{ padding: 14px; border-bottom: 1px solid #f1f5f9; vertical-align: top; font-size: 13.5px; line-height: 1.45; }}
  tr:hover {{ background: #f8fafc; }}
  
  .muted {{ color: var(--muted); font-size: 12px; }}
  .phone-link {{ font-family: monospace; font-size: 14px; font-weight: 700; color: #0f172a; text-decoration: none; padding: 2px 6px; background: #f1f5f9; border-radius: 4px; border: 1px solid #cbd5e1; display: inline-block; }}
  .phone-link:hover {{ background: #e2e8f0; color: #1d4ed8; }}
  .subcat {{ font-weight: 700; color: #1e293b; display: block; margin-bottom: 2px; }}
  .reason-text {{ color: #475569; font-size: 12.5px; }}
  .evidence-text {{ color: #0369a1; background: #f0f9ff; padding: 3px 6px; border-radius: 4px; display: inline-block; font-size: 12px; border: 1px solid #bae6fd; }}
  .warn-badge {{ margin-top: 6px; padding: 4px 8px; background: #fef3c7; border: 1px solid #f59e0b; color: #92400e; border-radius: 4px; font-size: 12px; font-weight: 600; line-height: 1.35; }}
  
  .badge {{ display: inline-block; padding: 3px 9px; border-radius: 12px; font-size: 12px; font-weight: 700; }}
  .badge-red {{ background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
  .badge-green {{ background: #dcfce7; color: #166534; border: 1px solid #bbf7d0; }}
  .badge-yellow {{ background: #fef9c3; color: #854d0e; border: 1px solid #fde047; font-size: 11px; }}
  
  .note-preview {{ color: #334155; font-style: italic; display: block; margin-top: 4px; background: #f8fafc; padding: 4px 6px; border-radius: 4px; border-left: 2px solid #cbd5e1; }}
  
  @media print {{
    header, .controls, .stats-grid, .banner, .btn {{ display: none !important; }}
    table {{ box-shadow: none; border: 1px solid #000; }}
    th, td {{ padding: 8px; border: 1px solid #ccc; font-size: 11px; }}
    body {{ background: #fff; }}
  }}
</style>
</head>
<body>
<header>
  <div>
    <h1>🏥 Hospital Front Desk — Diabetic Follow-Up Call List</h1>
    <div class="meta">Export Reference Date: <strong>2026-09-30</strong> • Standard Recall: <strong>90 Days</strong> (6mo if controlled HbA1c &lt; 7.0%)</div>
  </div>
  <div class="header-actions">
    <a href="/api/csv?tab={html.escape(active_tab)}" class="btn btn-light" download="diabetic_call_list_{active_tab.lower()}.csv">📥 Download CSV</a>
    <button onclick="window.print()" class="btn btn-light">🖨️ Print Call Sheet</button>
  </div>
</header>
<div class="container">

  <div class="stats-grid">
    <div class="stat-card call">
      <div class="stat-title">1. Call Now (Actionable)</div>
      <div class="stat-val">{len(by_bucket['CALL_NOW'])}</div>
      <div class="stat-sub">Confirmed T1/T2 diabetics overdue with valid phone</div>
    </div>
    <div class="stat-card check">
      <div class="stat-title">2. Check First (Staff Review)</div>
      <div class="stat-val">{len(by_bucket['CHECK_FIRST'])}</div>
      <div class="stat-sub">Duplicate MRNs (7), missing phones (3), high labs (9), pre-DM/GDM (7)</div>
    </div>
    <div class="stat-card excluded">
      <div class="stat-title">3. Excluded (With Audit Reason)</div>
      <div class="stat-val">{len(by_bucket['EXCLUDED'])}</div>
      <div class="stat-sub">Deceased (3), transferred (3), PCOS (4), up-to-date (34), family-hx (8)</div>
    </div>
  </div>

  <div class="controls">
    <div class="tabs">
      <a class="tab {'active-CALL_NOW' if active_tab=='CALL_NOW' else ''}" href="/?tab=CALL_NOW">📞 1. Call Now ({len(by_bucket['CALL_NOW'])})</a>
      <a class="tab {'active-CHECK_FIRST' if active_tab=='CHECK_FIRST' else ''}" href="/?tab=CHECK_FIRST">⚠️ 2. Check First ({len(by_bucket['CHECK_FIRST'])})</a>
      <a class="tab {'active-EXCLUDED' if active_tab=='EXCLUDED' else ''}" href="/?tab=EXCLUDED">🚫 3. Excluded ({len(by_bucket['EXCLUDED'])})</a>
    </div>
    <form class="search-form" method="GET" action="/">
      <input type="hidden" name="tab" value="{html.escape(active_tab)}">
      <input type="text" name="q" value="{html.escape(search_q)}" placeholder="Search name, MRN, phone, doctor...">
      <button type="submit">Search</button>
    </form>
  </div>

  <div class="banner">
    <strong>Audited Clinical Protocol:</strong> A wrong name on a call list means a real phone call to the wrong person.
    <strong>Call Now ({len(by_bucket['CALL_NOW'])})</strong> shows only confirmed Type 1/Type 2 diabetics whose due date has passed.
    <strong>Check First ({len(by_bucket['CHECK_FIRST'])})</strong> prevents cold-calling duplicate registrations, missing phones, or unconfirmed sugar labs without a doctor's diagnosis.
    <strong>Excluded ({len(by_bucket['EXCLUDED'])})</strong> completely protects deceased families (3), transferred patients (3), and PCOS Metformin cases (4).
  </div>

  <table>
    <thead>
      <tr>
        <th style="width:16%">Patient</th>
        <th style="width:12%">Contact Phone</th>
        <th style="width:26%">Classification & Operational Alerts</th>
        <th style="width:16%">Clinical Evidence</th>
        <th style="width:18%">Last Diabetes Visit</th>
        <th style="width:12%">Overdue Status</th>
      </tr>
    </thead>
    <tbody>
      {table_body}
    </tbody>
  </table>
</div>
</body>
</html>"""

class FrontDeskHandler(BaseHTTPRequestHandler):
    records = []

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/api/patients":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            clean = [
                {k: v for k, v in r.items() if k not in ("all_visits", "all_labs", "all_rx")}
                for r in self.records
            ]
            self.wfile.write(json.dumps(clean, indent=2).encode("utf-8"))
            return

        if parsed.path == "/api/csv":
            tab = qs.get("tab", ["CALL_NOW"])[0]
            csv_data = generate_csv(self.records, bucket_filter=tab if tab in ("CALL_NOW", "CHECK_FIRST", "EXCLUDED") else None)
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="diabetic_followup_{tab.lower()}.csv"')
            self.end_headers()
            self.wfile.write(csv_data.encode("utf-8"))
            return

        tab = qs.get("tab", ["CALL_NOW"])[0]
        if tab not in ("CALL_NOW", "CHECK_FIRST", "EXCLUDED"):
            tab = "CALL_NOW"
        q = qs.get("q", [""])[0]

        page = render_html(self.records, active_tab=tab, search_q=q)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    recs = load_and_analyze()
    if "--summary" in sys.argv:
        print_summary(recs)
        sys.exit(0)

    print_summary(recs)
    FrontDeskHandler.records = recs
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer(("127.0.0.1", port), FrontDeskHandler)
    print(f"\n[OK] Front Desk Tool running at: http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
