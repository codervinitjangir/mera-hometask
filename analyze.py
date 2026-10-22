import csv
import os
import re
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# ---------------------------------------------------------
# CONFIGURATION BLOCK
# ---------------------------------------------------------
CONFIG = {
    "REFERENCE_DATE": datetime(2026, 9, 30),
    "DEFAULT_FOLLOWUP_DAYS": 90,
    "CONTROLLED_FOLLOWUP_DAYS": 180,
    "HBA1C_CONTROL_THRESHOLD": 7.0,
    "HBA1C_MAX_AGE_DAYS": 365,
    "AUTO_EXTEND_CONTROLLED_TO_6MO": False,
    "LAPSED_PATIENT_CUTOFF_DAYS": None
}

def find_export_dir():
    candidates = [
        'export',
        'engineering-intern-take-home/export',
        '../export',
        './'
    ]
    for c in candidates:
        if os.path.exists(os.path.join(c, 'patients.csv')):
            return c
    raise FileNotFoundError("Could not locate export directory containing patients.csv")

def parse_date(d_str):
    if not d_str or not str(d_str).strip():
        return None
    s = str(d_str).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d %b %y', '%d %b %Y'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

def parse_review_days_from_notes(note):
    if not note:
        return None, None
    n = note.lower()
    if any(p in n for p in ["review sos", "rpt yearly", "review yearly", "review 1 yr"]):
        return 365, "Doctor note: yearly / SOS (365d)"
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

def run_audit():
    # Import logic from app.py to ensure 100% synchronization
    import app
    records = app.load_and_analyze()
    app.print_summary(records)

if __name__ == '__main__':
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    run_audit()
