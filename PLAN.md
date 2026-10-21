# Plan — Diabetic Follow-Up Call List for Front Desk

## 1. Understanding the Goal
Meenakshi needs a practical front-desk tool to call diabetic patients overdue for follow-up. A wrong name means a real phone call to a real person, so precision, auditability, and transparency matter much more than UI.

## 2. What I Need to Find Out First (Data & Domain)
- **Cutoff date**: What is the latest date in the export to anchor "today" / overdue calculations?
- **"Diabetic" definition**: How is diabetes recorded across tables (notes, Diabetology dept, anti-diabetic drugs, HbA1c/glucose labs)? How do we avoid false positives like Metformin for PCOS?
- **"Overdue" definition**: Is `next_appointment` always present, or do notes specify review intervals? What fallback threshold applies when missing?
- **Data anomalies**: Missing phones, duplicate MRNs, or inconsistent test names/formats.

## 3. Questions for the Hospital
I am sending 5 targeted questions to Meenakshi (covering cutoff date, fallback overdue threshold, handling PCOS/pre-diabetes, and cross-department visits), each paired with a default assumption. Crucially, the export lacks death and transfer records, so I will ask how the hospital tracks these and document this absence as a known limitation.

## 4. Planned Execution Steps
1. Commit this PLAN.md before any code is written.
2. Look at the raw CSVs by hand first, then write down my definitions.
3. Send the hospital my questions, each with a default assumption, and keep working while I wait.
4. Ask the agent to list its assumptions about "diabetic" and "overdue" before it writes any code, and keep what I disagree with.
5. Try three definitions of "diabetic" (medicines only, labs only, all signals combined), compare who each wrongly includes or misses, and pick one with reasons.
6. Build a one-command local tool with three lists: Call now, Check first, Excluded. Every patient shows why they are on a list.
7. Check 15-20 patients by hand against the raw CSVs and record where the output was wrong.
8. Write DECISIONS.md and reply.txt. The export has no deceased/transferred field, so I can't exclude those patients; I'll ask and state it as a limit. If I reach 4 hours, I stop and write down what I'd do next.
