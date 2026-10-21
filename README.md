# mera.health Take-Home — Diabetic Follow-Up Call List Tool

A zero-dependency local tool for the hospital front desk to identify and call diabetic patients who are overdue for follow-up, while safely separating ambiguous records and excluding deceased, transferred, or non-diabetic (e.g., PCOS) patients.

## Requirements
- **Python 3.8+** (Uses only the Python Standard Library — no `pip install`, database setup, or login required).

## How to Run (1 Command)

Start the Front Desk Web UI:
```bash
python app.py
```
Then open [http://localhost:8000](http://localhost:8000) in your browser.

### Optional CLI Audit Summary
To print the terminal breakdown of buckets and the 3-definition comparison:
```bash
python app.py --summary
```

## Repository Contents
- **`PLAN.md`** — Initial plan committed prior to implementation.
- **`DECISIONS.md`** — Definitions chosen, 3-rule comparison, data anomalies found, manual verification log (18 patients), and limitations.
- **`reply.txt`** — Non-technical response email to Meenakshi (<200 words).
- **`app.py`** — Data pipeline, clinical classification engine, and local web server (Call Now, Check First, Excluded, CSV export, and printable call sheet).
- **`analyze.py`** — Standalone data audit and verification script.
- **`engineering-intern-take-home/`** — Take-home brief, Meenakshi's email, and raw export CSVs.
