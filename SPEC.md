# SPEC — Hybrid-Workplace SaaS: Feature Adoption & Gap Analysis

**Goal:** A 3-day portfolio project for a Product Analyst role at a hybrid-workplace SaaS company (desk / room / parking booking, attendance, QR check-in).
It shows I can: track who uses which feature, figure out *why* some clients don't, spot client setups that hold the product back, and explain it to PMs and clients.

Repo name: `workplace-adoption-analytics`
Stack: Python (Pandas, Faker, NumPy) → **SQLite** → **SQL** → **Power BI** (+ an Excel export). No ML needed.

> Rule for Claude Code: build one phase at a time, commit after each, and never make up a number in the README — every figure must come from a query result.

---

## 1. The synthetic dataset (Day 1 morning)

`generate_data.py` writes CSVs with a fixed random seed (42) so the results can be reproduced.

| Table | Rows (approx.) | Key columns |
|---|---|---|
| `clients` | 40 | client_id, name (fake), industry, region (India/US/UK/SG), plan (Basic/Pro/Enterprise), go_live_date, seats |
| `client_config` | 40 × 6 | client_id, feature, enabled (bool), enabled_date, config flags (see gaps below) |
| `employees` | 20,000 | employee_id, client_id, office_id, department, join_date |
| `offices` | ~90 | office_id, client_id, city, desks, rooms, parking_spots, has_qr_scanners, calendar_synced |
| `events` | ~1,000,000 | event_id, employee_id, client_id, feature, action (view / book / check_in / cancel / no_show), ts |
| `support_tickets` | ~1,500 | ticket_id, client_id, feature, category, created_at, resolved_at |

**6 features:** Desk Booking, Meeting Room Booking, Parking, QR Check-in, Attendance Policy (hybrid rules), Visitor Management.
**Time span:** 12 months.

### Plant the ground truth (this is what makes the project honest)
Write `ground_truth.json` listing, per client, which adoption gap was planted. Plant ~10 gaps of these 6 types:

1. **QR check-in enabled, no scanners** — `enabled=True` but `has_qr_scanners=False` at most offices → check-ins collapse after month 1.
2. **Rooms not synced to calendar** — `calendar_synced=False` → room bookings low, high no-show rate.
3. **Over-strict policy** — attendance policy caps bookings (e.g. 1 day/week) → many `view` events with no `book`.
4. **Bad rollout** — feature enabled for only 1 of many offices.
5. **Parking enabled, zero spots configured.**
6. **Silent churn** — healthy usage that drops >50% over the last 3 months with rising support tickets.

The other ~30 clients follow normal adoption curves (slow ramp, steady state, some seasonality, Diwali/Christmas dips).

---

## 2. SQL analysis (Day 1 afternoon → Day 2 morning)

Folder `sql/`, one file per question. Each query runs on SQLite via `run_queries.py`, and its output is saved to `outputs/*.csv`.

1. `01_adoption_funnel.sql` — per feature and per client: enabled → first use → used in ≥3 of the last 4 weeks. Use CTEs.
2. `02_cohort_retention.sql` — monthly employee cohorts by first booking month and retention by month N (window functions).
3. `03_dau_wau_mau.sql` — stickiness (DAU/MAU) per feature.
4. `04_feature_matrix.sql` — client × feature adoption % (feeds the heat map).
5. `05_why_not.sql` — for low adopters, break down view-without-book, cancellations, no-shows, and tickets by category.
6. `06_client_health.sql` — health score = weighted adoption breadth + depth + trend − ticket load; banded Green / Amber / Red.

**This is where the resume numbers come from:**
- `X%` = share of QR-check-in-enabled clients with no repeat use after month 1 (query 01).
- `N` = clients flagged by the gap detector (section 3).

---

## 3. Implementation-gap detector (Day 2)

`gap_detector.py` runs 6 plain, readable rules (one per gap type above) against config plus usage. Output `outputs/gap_report.csv`: client, gap type, evidence (the numbers that fired the rule), employees affected, **suggested fix** (e.g. "Install QR scanners at 4 offices or switch to geofenced check-in").

**Evaluate it against `ground_truth.json`:** precision and recall. Report the true result in the README even if it is not perfect. Interviewers trust "caught 9/10, missed the slow-churn case because…" more than "100%".

---

## 4. Dashboard and write-ups (Day 3)

- **Power BI** (`dashboard/adoption.pbix`) — 3 pages:
  1. Portfolio overview: health-score bands, adoption trend, top features.
  2. Feature heat map (client × feature) plus a funnel per feature.
  3. Client drill-down: the gaps, evidence and suggested fix.
  Take screenshots for the README. *(Power BI Desktop runs on Windows only. If that's a problem, use Streamlit with Plotly as a fallback and keep the Excel export.)*
- **Excel** `outputs/client_adoption_tracker.xlsx`: a pivot of the feature matrix with conditional formatting. This proves the "SQL, Excel, or a BI tool" line.
- **`docs/pm_insights_brief.md`** (1 page): top 3 adoption blockers ranked by employees affected, with evidence and one product change each (e.g. "make the check-in fallback self-serve").
- **`docs/client_walkthrough_desk_booking.md`**: a short best-practice guide written for a client admin. It shows the JD's "walkthroughs, nudges" skill.

---

## 5. README (end of Day 3)
Problem → dataset (state clearly that it is **synthetic, with planted gaps**) → questions → key findings with real numbers → gap detector precision/recall → screenshots → how to run it (`pip install -r requirements.txt && python generate_data.py && python run_queries.py && python gap_detector.py`).

## Schedule

| Day | Deliverable |
|---|---|
| 1 | Data generator plus ground truth, load to SQLite, queries 01–03 |
| 2 | Queries 04–06, gap detector plus evaluation, Excel tracker |
| 3 | Power BI dashboard, PM brief, client walkthrough, README; update `X%` and `N` on the resume |

**Never cut:** the planted ground truth, the gap detector evaluation, or the PM brief. They are what set this apart from a generic dashboard project.
