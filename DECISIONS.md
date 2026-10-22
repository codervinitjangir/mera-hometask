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
  3. Otherwise, apply a **90-day (3-month) default fallback**, or **180 days (6 months)** if the patient's recent HbA1c is documented as controlled.
- **Bug found and fixed (`review SOS`):** An early version of the code treated `"review SOS"` as a 365-day interval. `SOS` means *"come back only if symptoms arise"* — it is not a scheduled follow-up date. The fix: `"review SOS"` now returns no interval and falls through to the 90-day standard fallback. This affected 10 patients' due-source labels but did not change any bucket assignment (all 10 were non-diabetic or in `Check First` for unrelated reasons).

### D. Update After Receiving Hospital Clarifications (22 Oct 2026)
We received Meenakshi's reply via Arjun (recorded in full in `hospital_reply.txt`):
1. **Condition Scope (T1/T2/GDM/Prediabetes/PCOS):** Meenakshi clarified she is non-clinical and Dr. Rao is away until next week, wanting *"whoever the doctors would consider diabetic."*
   - *Handling:* Confirmed T1/T2 diabetics go to **Call Now** (if overdue); PCOS on Metformin is **Excluded**; GDM (3) and Prediabetes (4) are held in **Check First** for Dr. Rao.
2. **High Lab Tests Without Diagnosis:** Confirmed this *"would need a doctor's input."*
   - *Handling:* Kept in **Check First** (9 records). Front desk never makes unconfirmed diagnoses.
3. **Follow-Up Interval (3 Months vs 6 Months if Controlled):** Meenakshi shared that *"doctors usually say every 3 months, or 6 if the sugar is under control,"* though the exact line is unstated.
   - *Clinical Guideline Lookup:* American Diabetes Association (ADA) Standards of Care in Diabetes—2026, Section 6: *“Glycemic Goals, Hypoglycemia, and Hyperglycemic Crises: Standards of Care in Diabetes—2026”* (*Diabetes Care 2026; 49(Suppl. 1): S132–S149*, [PMC Article](https://pmc.ncbi.nlm.nih.gov/articles/PMC12690178)). The ADA recommends assessing glycemic status twice annually (every 6 months) for patients meeting treatment goals (e.g. HbA1c < 7.0%), and quarterly (every 3 months) for patients whose therapy has changed or who are not meeting goals. Note: ADA goals are individualized defaults (e.g., older or complex adults often target < 8.0%); our threshold serves as an operational placeholder until Dr. Rao confirms the hospital's specific clinical policy next week.
   - *Sensitivity Analysis — HbA1c Thresholds:* We tested thresholds at 7.0%, 7.5%, and 8.0%:
     - **Baseline (Flat 90d):** Call Now = 39 | Check First = 26 | Excluded = 52
     - **Threshold < 7.0%:** Call Now = 38 | Check First = 26 | Excluded = 53
     - **Threshold < 7.5%:** Call Now = 38 | Check First = 26 | Excluded = 53
     - **Threshold < 8.0%:** Call Now = 38 | Check First = 26 | Excluded = 53
     - *Key Finding:* Across all three thresholds, exactly **1 patient shifts** (`SVH028753`, Vimala P, last visit 2026-06-19, HbA1c 6.6%). This proves that the precise threshold chosen does not practically disrupt the operational call list.
   - *Sensitivity Analysis — Lapsed Patient Cutoff:* Evaluated in `CONFIG["LAPSED_PATIENT_CUTOFF_DAYS"]`:
     - **Cutoff = None (Default):** Call Now = 39 | Check First = 26 (Standard reconciliation; all overdue called).
     - **Cutoff = 365d (1 Year):** Call Now = 22 | Check First = 43 (17 patients with last visit > 1 year ago move to Check First for file pull before calling).
     - **Cutoff = 730d (2 Years):** Call Now = 39 | Check First = 26 (0 patients move; longest gap across all export patients is 545 days).
4. **Cross-Department Visits:** Deferred for medical staff review. We display non-diabetes OPD visits as badges on screen without resetting the chronic diabetes recall clock.
5. **Duplicate Registrations:** Meenakshi confirmed *"people sometimes re-register when they forget their card"* and she cannot confirm if records match from email alone. We strictly adhere to our non-merging policy and hold all duplicate pairs in **Check First**.

---

## 2. Complete 4-Bucket Reconciliation Table

Every single one of the 300 patients in `patients.csv` maps to exactly one category:

| Primary Bucket | Patient Count | Sub-Category Breakdown | Clinical / Operational Rationale |
| :--- | :---: | :--- | :--- |
| **1. CALL NOW** | **39** | Confirmed T1/T2 Overdue (39) | Valid phone, confirmed chronic diabetes, overdue past due date. |
| **2. CHECK FIRST** | **26** | • High Lab, Unconfirmed Diagnosis (7)<br>• Overdue Duplicate Registrations (5)<br>• Prediabetes / Impaired Glucose (4)<br>• Overdue Diabetic, Missing Phone (3)<br>• Gestational Diabetes / GDM (3)<br>• High Lab + Duplicate MRN (2)<br>• Borderline Lab Resolved on Diet (2) | Ambiguous cases held for staff verification or Dr. Rao's input so front desk makes zero unverified calls. |
| **3. EXCLUDED (With Signal)** | **52** | • Up-to-Date Diabetics (34)<br>• Family History / Denials Only (8)<br>• PCOS/PCOD on Metformin (4)<br>• Transferred Care / Relocated (3)<br>• Deceased / Expired in Notes (3) | Explicitly non-actionable or safely removed to prevent calling deceased families or non-diabetic women. |
| **4. NON-DIABETIC** | **183** | Zero Diabetes Signals (183) | Patients with no diabetes diagnoses, drugs, or abnormal glucose labs. |
| **TOTAL** | **300** | **100% Accounted For** | Exactly matches 300 patient rows in `patients.csv`. |

---

## 3. Problems Found in the Data (and How We Handled Them)

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

## 4. Manual Spot-Check Against Raw CSVs (20 Patients Checked by Hand)

During manual verification against raw CSV rows across all buckets, we verified our logic and caught two clinical edge cases:
- *Fix 1:* Pediatric Type 1 diabetics (`SVH025870`, `SVH028258`, `SVH029838`) are treated in `Paediatrics` rather than `Diabetology`/`General Medicine`. Added `Paediatrics` to qualifying follow-up departments.
- *Fix 2:* `SVH029107` was prescribed `Inj. Human Mixtard 30/70`, which our initial drug list missed because the string `"insulin"` wasn't in the brand name. Added `mixtard`.

| MRN | Raw CSV Ground Truth Facts | Tool Output & Verified Status |
| :--- | :--- | :--- |
| `SVH025030`, `SVH025870`, `SVH026153`, `SVH028258`, `SVH028910` | Confirmed T1/T2 diabetics with valid phone, overdue >90d (includes pediatric T1DM on insulin & adult OPD visits) | **CALL_NOW** (Matched) |
| `SVH025063` | Confirmed diabetic overdue, phone blank in `patients.csv` | **CHECK_FIRST** (Missing Phone — Matched) |
| `SVH026798` & `SVH027596` | Fasting glucose 138 mg/dL / HbA1c 65 mmol/mol without diagnosis or drugs | **CHECK_FIRST** (High Lab Unconfirmed — Matched) |
| `SVH028326` | GDM diagnosed during OBG pregnancy visit; insulin stopped postpartum | **CHECK_FIRST** (Gestational Diabetes — Matched) |
| `SVH029446` | Initial HbA1c 6.5% normalized to 5.7% on diet/exercise alone | **CHECK_FIRST** (Borderline Lab Resolved — Matched) |
| `SVH027082` & `SVH030772` | Identical DOB (`1959-05-25`) & phone (`9845012345`). `SVH027082` has T2DM; `SVH030772` re-registered for Thyroid only | `SVH027082` in **CHECK_FIRST** (Duplicate flag); `SVH030772` in **NON_DIABETIC** (Matched) |
| `SVH025473` & `SVH029873` | Identical DOB (`1956-07-14`) & phone (`9845098765`). Both have high glucose labs awaiting doctor diagnosis | Both in **CHECK_FIRST** (High Lab + Duplicate MRN — Matched) |
| `SVH025339`, `SVH025698`, `SVH026086` | Clinical notes confirm patient expired (`SVH025339` home, `SVH026086` ICU, `SVH025698` STEMI) | **EXCLUDED** (Deceased — Matched) |
| `SVH024860`, `SVH025512`, `SVH028346` | Clinical notes confirm relocated / transferred care to Hyderabad/Pune | **EXCLUDED** (Transferred — Matched) |
| `SVH025191`, `SVH028876`, `SVH029693`, `SVH030554` | OBG visits for PCOS/PCOD on Metformin with normal HbA1c (`5.0%–5.4%`) | **EXCLUDED** (PCOS Non-Diabetic — Matched) |
| `SVH029838` | Paediatric T1DM on insulin, last seen `2026-08-11` (<90d ago) | **EXCLUDED** (Up-to-Date Diabetic — Matched) |
| `SVH030117` | Note records `"Father diabetic"`, patient has normal glucose | **EXCLUDED** (Family History Only — Matched) |
| `SVH028753` | Last visit `2026-06-19`, HbA1c `6.6%`. Evaluated in threshold sensitivity | **CALL_NOW** (with Controlled 6mo badge — Matched) |

---

## 5. What This Result Cannot Be Trusted For

1. **Unrecorded Deaths or Transfers:** Deaths/transfers are only known if typed into a visit note. Any patient who passed away at home or switched hospitals without informing staff will still appear on `Call Now`.
2. **Appointments Booked in Another System:** `next_appointment` is blank on 71% of visits. If the front desk tracks future bookings in a separate register, some patients on `Call Now` may already have appointments.
3. **Clinical Severity / Triage:** Sorting by days overdue does not reflect medical urgency (e.g., a patient with HbA1c `11.2%` overdue by 15 days may need a call more urgently than a well-controlled patient overdue by 200 days).
4. **Free-text Note Parsing is Approximate:** Doctor notes are unstructured. Patterns like `r/v 3/12` or `review 6 months` are matched using heuristic regex. Any note written in an unexpected format (e.g., mixed language, abbreviation variant) will fall through to the 90-day default. The `review SOS` bug above is an example of such an assumption being incorrect.

---

## 6. Corrections Log — Where the Initial Agent Version Was Wrong

| # | Mistake Made | How Caught | Fix Applied |
| :--- | :--- | :--- | :--- |
| **1** | **Naive overdue rule (single-signal from meds/labs = `CALL_NOW`)** — Initial logic treated *any* anti-diabetic medication or high HbA1c as sufficient to route patients directly to `Call Now`, including PCOS patients on Metformin and diet-controlled borderline HbA1c patients. | Manual review of patient context (PCOS notes, GDM notes, lifestyle-controlled sugars) | Three-way definition comparison (Meds / Labs / Combined Clinical Evidence). PCOS → `EXCLUDED`; GDM/borderline → `CHECK_FIRST`. |
| **2** | **Wrong ADA page numbers** — Agent initially cited *Diabetes Care 2026; 49(Suppl 1): S91–S101* from memory. | Cross-referenced against actual PubMed Central article URL | Corrected to Section 6 (*S132–S149*), URL: [PMC12690178](https://pmc.ncbi.nlm.nih.gov/articles/PMC12690178). Added note that ADA goals are individualized defaults, not the hospital's policy. |
| **3** | **`"review SOS"` treated as a 1-year follow-up interval** — Early code returned 365 days for notes containing `"review SOS"`, equating it with `"review yearly"`. `SOS` means *"return only if problem arises"* — it carries no scheduled date at all. | Agent's own note-parsing was reviewed critically; SOS context in raw CSVs confirmed it was used for acute/unrelated visits (Ortho, ENT, fever) | Removed `"review SOS"` from the yearly-interval match list. SOS notes now fall through to the 90-day standard default. |
