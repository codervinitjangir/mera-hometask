# DECISIONS.md — Definitions, Data Anomalies, and Limitations

## 1. Definitions Chosen (and Why)

### A. Reference Date ("Today"): `2026-09-30`
- **Why:** The export has no metadata timestamp. Across `visits.csv` and `prescriptions.csv`, the latest clinical activity is `2026-09-29`. We anchored "today" to `2026-09-30` (the following morning).
- *(Note: `lab_results.csv` contains two future dates—`19/12/2026` for `SVH027355` and `27/02/2027` for `SVH030138`—which we identified as data entry typos rather than the export date, since both patients have visit timelines ending in 2026).*

### B. Who Counts as "Diabetic"?
We compared three candidate definitions across all 300 patients (117 of whom have some glucose/diabetes signal):

1. **Medicines Only (`93 patients`):** Anyone prescribed an anti-diabetic drug (`Metformin`, `Glimepiride`, `Gliclazide`, `Sitagliptin`, `Vildagliptin`, `Dapagliflozin`, `Voglibose`, `Insulin`, or `Human Mixtard 30/70`).
   - *Who it wrongly includes:* **4 PCOS/PCOD patients** (`SVH025191`, `SVH028876`, `SVH029693`, `SVH030554`) prescribed Metformin in OBG with normal HbA1c (`5.0%–5.4%`), and **1 resolved Gestational Diabetes (GDM)** patient (`SVH028326`) whose insulin was stopped post-delivery.
   - *Who it leaves out:* Patients with diabetic-range labs (`HbA1c >= 6.5%`) managed on diet or awaiting medication start (`SVH026798`, `SVH027221`, `SVH027596`, `SVH029597`, `SVH029830`).

2. **Labs Only (`88 patients`):** Anyone with ADA diabetic-range labs (`HbA1c >= 6.5%` or `>= 48 mmol/mol`, fasting glucose `>= 126 mg/dL` or `>= 7.0 mmol/L`, post-prandial `>= 200 mg/dL` or `>= 11.1 mmol/L`).
   - *Who it wrongly includes:* **3 borderline patients** (`SVH025442`, `SVH029446`, `SVH029638`) whose initial HbA1c (`6.5%–6.6%`) normalized (`5.7%–5.9%`) with lifestyle changes alone.
   - *Who it leaves out:* **19 known diabetics on treatment** whose blood sugars are well-controlled (`HbA1c < 6.5%`, e.g., `SVH025811`, `SVH026193`, `SVH029490`) or whose external labs are only recorded inside doctor notes (`SVH026927`, `SVH027999`, `SVH030327`).

3. **Our Chosen Rule — Combined Clinical Evidence (`87 Confirmed T1/T2 Diabetics`):**
   - A patient is a **Confirmed Chronic Diabetic (Type 1 / Type 2)** if they have a positive clinical diagnosis in `visits.notes` (`T2DM`, `T1DM`, `NIDDM`, `juvenile diabetes`, `known diabetic`, etc., excluding family history/denials), **OR** visited the `Diabetology` department, **OR** take anti-diabetic medication without a conflicting PCOS/GDM indication.
   - *Why:* Separates confirmed chronic diabetics (`87`, of whom `81` are active after excluding `3` deceased and `3` transferred) from ambiguous cases (`26` placed in **Check First**).

### C. What Counts as a "Follow-Up" and "Overdue"?
- **Qualifying Follow-Up Visit:** A visit to `Diabetology`, or a visit to `General Medicine` / `Paediatrics` (where 3 Type 1 DM children are treated) that addresses diabetes (prescribes DM drugs or reviews sugars/DM in notes). Acute visits for unrelated illnesses (e.g., `SVH030487` visiting General Medicine for a 2-day cold/cough, or visits to `Dental`, `Orthopaedics`, `ENT`, `Dermatology`) do **not** reset the diabetes follow-up clock, though we display recent non-diabetes visits on screen for context.
- **Due Date & Overdue Calculation:**
  1. Use `next_appointment` from the last qualifying diabetes visit if recorded.
  2. Otherwise, parse the doctor's explicit interval from `notes` (e.g., `r/v 3/12` = 90d, `r/v 6/12` = 180d, `review 6 wks` = 42d, `review 2 months` = 60d).
  3. Otherwise, apply a **90-day (3-month) default fallback**.
- A patient is **overdue** if `Due Date < 2026-09-30`. (Comparing parsed note intervals vs. a flat 90-day fallback changes the exact due date for 5 active patients—`SVH025313`, `SVH026153`, `SVH026167`, `SVH027348`, `SVH027925`—but all 5 remain overdue under both methods).

---

## 2. Problems Found in the Data (and How We Handled Them)

| Problem Found | Evidence / Affected Records | Action Taken |
| :--- | :--- | :--- |
| **1. Deceased patients still in export** | No `status` column in `patients.csv`, but `visits.notes` state `pt expired` for **3 diabetic patients**: `SVH025339` (expired at home), `SVH026086` (DKA/sepsis in ICU), `SVH025698` (STEMI in Emergency). | **Excluded** from call list with prominent warning so the front desk never calls a bereaved family. |
| **2. Transferred / relocated patients** | `visits.notes` record care transfer for **3 patients**: `SVH024860` (Hyderabad), `SVH025512` (native place), `SVH028346` (Pune). | **Excluded** from call list with reason shown. |
| **3. Duplicate patient registrations (2 MRNs per person)** | **4 pairs (8 MRNs)** share identical DOB, sex, and phone with minor name variations: `SVH025473`/`SVH029873` (Md./Mohammed Rafiq), `SVH027082`/`SVH030772` (Padmavathi/Padma Reddy), `SVH027925`/`SVH029107` (Shivakumar), `SVH027863`/`SVH029322` (Joseph Dsouza/D'Souza). | Did **not** silently merge or delete rows. Placed in **Check First** with cross-referenced MRNs so staff verify both files before calling once. |
| **4. Missing phone numbers** | `8` patients total have blank phones (`NaN`), including **3 overdue diabetics**: `SVH025063`, `SVH028319`, `SVH028414`. | Placed in **Check First** (`Overdue Diabetic — Missing Phone Number`) so staff pull paper files. |
| **5. Shared family phone numbers** | `3` phones are shared across distinct relatives (e.g., `9000043929` shared by `SVH026167 Revathi Pandian`, `SVH029084 Meena P`, `SVH030711 Shanthi Biradar`). | Added a warning badge on the call list reminding staff to ask for the specific patient by name and DOB. |
| **6. Inconsistent lab names & missing units** | HbA1c appears as `HbA1c`, `A1C`, and `Glycated Hb`. Units mix `%` and `mmol/mol` (`3` rows—`SVH027596`, `SVH029625`, `SVH029659`—have values `65.0–68.0` with blank `unit`, which are IFCC `mmol/mol` values `>= 48`). Glucose mixes `mg/dL` and `mmol/L`. | Standardized lab classification using unit-aware thresholds without altering raw CSV values. |
| **7. Mixed date formats & typos** | `lab_results.collected_on` mixes `DD Mon YY` (`2 Oct 23`) and `DD/MM/YYYY`. Two labs have future dates (`19/12/2026`, `27/02/2027`), and `V042486` (`SVH029560`) has visit date `2015-03-28` (registered `2025`). | Parsed all date formats safely and flagged future lab dates on the patient card. |
| **8. Drug naming variations** | Prefixes (`Tab.`, `T.`, `Inj.`) and `Human Mixtard 30/70` (biphasic insulin lacking the word "Insulin"). | Included `mixtard` and normalized prefixes during matching. |
| **9. Family history & negative note mentions** | `8` non-diabetic patients have notes like `"Father diabetic"` (`SVH030117`), `"Mother diabetic"` (`SVH025378`), or `"No h/o diabetes"` (`SVH025407`, `SVH026328`, `SVH028557`, `SVH030471`). | Stripped family-history and denial phrases before matching; placed in **Excluded**. |

---

## 3. Where We Flagged for Human Check (`Check First` — 26 Records)

Instead of guessing on clinical or administrative edge cases, we routed 26 records to the **Check First** tab:

1. **Overdue Diabetics with Missing Phone (`3`):** `SVH025063`, `SVH028319`, `SVH028414`.
2. **Overdue Diabetics with Duplicate MRNs (`5`):** `SVH027082` (visited recently under duplicate `SVH030772` for thyroid), `SVH027863`/`SVH029322`, and `SVH027925`/`SVH029107`.
3. **High Lab Sugar (`HbA1c >= 6.5%`) Without Diagnosis/Rx (`8`, including `2` duplicate MRNs):** `SVH025473`/`SVH029873` (Rafiq duplicate pair), `SVH026798`, `SVH027221`, `SVH027596`, `SVH029597`, `SVH029659`, `SVH029830`. Front desk should not tell a patient they are diabetic before a doctor confirms.
4. **Borderline HbA1c Resolved with Lifestyle (`3`):** `SVH025442`, `SVH029446`, `SVH029638`.
5. **Prediabetes / IGT (`4`):** `SVH024560`, `SVH024742`, `SVH025926`, `SVH028864`.
6. **Gestational Diabetes (`3`):** `SVH027966`, `SVH028068`, `SVH028326`.

---

## 4. Manual Spot-Check Against Raw CSVs (18 Patients Checked by Hand)

During manual verification against raw CSV rows, we caught two issues in our initial logic and fixed them:
- *Fix 1:* Pediatric Type 1 diabetics (`SVH025870`, `SVH028258`, `SVH029838`) are seen in `Paediatrics`, not `Diabetology`/`General Medicine`. Added `Paediatrics` to qualifying follow-up departments.
- *Fix 2:* `SVH029107` was prescribed `Inj. Human Mixtard 30/70`, which our initial drug list missed because the string `"insulin"` wasn't in the drug name. Added `mixtard`.

| MRN | Raw CSV Ground Truth | Tool Output Verified |
| :--- | :--- | :--- |
| `SVH025339`, `SVH025698`, `SVH026086` | Notes confirm patient expired | `EXCLUDED` (Deceased) |
| `SVH024860`, `SVH025512`, `SVH028346` | Notes confirm relocated / transferred care | `EXCLUDED` (Transferred) |
| `SVH025191`, `SVH028876`, `SVH029693`, `SVH030554` | OBG visits for PCOS/PCOD on Metformin, HbA1c 5.0–5.4% | `EXCLUDED` (PCOS Non-Diabetic) |
| `SVH027082` & `SVH030772` | Same DOB (`1959-05-25`) & phone; DM on `SVH027082`, thyroid on `SVH030772` | `CHECK_FIRST` (Duplicate Flag) |
| `SVH027596` | HbA1c `65.0` with blank unit, polyuria note, awaiting report review | `CHECK_FIRST` (Unconfirmed Lab + Unit Warning) |
| `SVH025870` & `SVH028258` | Paediatric T1DM on insulin, last seen Dec 2025 (>90d ago) | `CALL_NOW` (Overdue T1DM) |
| `SVH029838` | Paediatric T1DM on insulin, last seen `2026-08-11` (<90d ago) | `EXCLUDED` (Up-to-Date Diabetic) |
| `SVH026153` & `SVH028910` | Overdue for DM, but visited ENT (`2026-08-14`) / Ortho (`2026-09-05`) | `CALL_NOW` (with Other-Dept Visit badge) |

---

## 5. What This Result Cannot Be Trusted For

1. **Unrecorded Deaths or Transfers:** Deaths/transfers are only known if typed into a visit note. Any patient who passed away at home or switched hospitals without informing staff will still appear on `Call Now`.
2. **Appointments Booked in Another System:** `next_appointment` is blank on 71% of visits. If the front desk tracks future bookings in a separate register, some patients on `Call Now` may already have appointments.
3. **Clinical Severity / Triage:** Sorting by days overdue does not reflect medical urgency (e.g., a patient with HbA1c `11.2%` overdue by 15 days may need a call more urgently than a well-controlled patient overdue by 200 days).
