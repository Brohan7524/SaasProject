# Hybrid-Workplace SaaS: Feature Adoption & Gap Analysis

An analytics project for a hybrid-workplace product (desk, meeting room and parking booking, QR check-in, attendance policy, visitor management). It measures who uses which feature, finds client setups that hold adoption back, and turns that into a PM brief and a client guide.

> **The data is SYNTHETIC.** It was generated with a fixed random seed (42), and **about 10 implementation gaps were planted on purpose** so the gap detector can be scored honestly. Nothing here describes a real company or real clients. Every number below comes from a query or script in this repo.

## The problem

Clients buy a platform with many features, but many only get value from one or two. Support sees tickets, not the pattern. Which features are used, by whom, and which setup mistakes (missing scanners, calendar not connected, a very tight policy) quietly hold clients back?

## The dataset (synthetic)

| Table | Rows |
|---|---|
| clients | 40 |
| client_config (40 clients x 6 features) | 240 |
| offices | 89 |
| employees | 20,000 |
| events (view, book, check_in, cancel, no_show) | 996,776 |
| support_tickets | 1,552 |

12 months (calendar 2025), with a slow ramp after go-live, weekday-heavy usage (Tue-Thu peak), and Diwali and Christmas dips. Six gap types were planted in 10 clients, plus 9 look-alike "decoy" clients that are not gaps. Details are in `DECISIONS.md`.

## Questions answered

1. How far down the funnel do employees get: enabled, first use, habitual use? (`sql/01`)
2. Do employees keep booking after their first booking? (`sql/02`)
3. How sticky is each feature (DAU/WAU/MAU)? (`sql/03`)
4. Which clients use which features, and how much? (`sql/04`)
5. For low adopters, why: views without booking, cancellations, no-shows, tickets? (`sql/05`)
6. Which clients are healthy and which need attention? (`sql/06`)
7. Which setup mistakes can we detect automatically, and how accurate is that? (`gap_detector.py`)

## Key findings

All from `outputs/`. A "use" is a booking or check-in, because a view alone is not adoption.

**Feature adoption.** Where enabled, the average share of employees active in the last 90 days is highest for Desk Booking (31.0%, enabled at 39 of 40 clients) and QR Check-in (29.9%, 23 clients), and lowest for Visitor Management (7.0%, 22 clients). Parking is on at only 17 clients (42.5%).

| Feature | Clients enabled | Employees who ever used it | Habitual (>=3 of last 4 weeks) | DAU/MAU (Sep) |
|---|---|---|---|---|
| QR Check-in | 23 | 43.7% | 11.6% | 0.218 |
| Desk Booking | 39 | 49.1% | 6.5% | 0.150 |
| Parking | 17 | 22.3% | 3.9% | 0.162 |
| Meeting Room Booking | 32 | 28.5% | 1.4% | 0.096 |
| Visitor Management | 22 | 9.7% | 0.2% | 0.081 |
| Attendance Policy | 26 | 39.1% | 0.2% | 0.063 |

The habitual figures are low partly by construction: the window includes the Christmas dip, and Visitor Management and Attendance Policy are rarely used by design.

**Retention.** Of employees whose first booking was in January 2025, 85.1% booked again the next month and 71.9% six months later. For the June cohort the figures are 82.6% and 59.9%.

**QR check-in repeat use.** 2 of 23 clients with QR enabled show no repeat use after month 1: **8.7%**. Both are in the planted "no scanners" group. Their later usage is 0.07 and 0.09 of month 1, while every other client is at 1.78 or higher.

**Why low adopters are low** (lowest quartile per feature vs the rest):
- QR check-in low adopters raise 8.13 tickets per 100 employees, against 1.84 for others.
- Meeting Room low adopters have a 12.0% no-show rate, against 7.4%.
- Parking low adopters see 32.1% of views not turn into a booking, against 20.1%.
- Hardware tickets are 9.8% of low adopters' tickets (2.3% for others); integration tickets are 14.1% (6.5%).
- **Adoption % alone hides some problems:** Desk low adopters show 28.0% of views without a booking, the same as other clients (27.8%), although the strict-policy clients convert only about 15% of desk views.

**Health score.** 15 clients Green, 14 Amber, 11 Red (weights and caveats in `DECISIONS.md`). The bands are relative rankings, and the Red cutoff was set from the score distribution.

## Gap detector: precision and recall

Six rules, one per gap type, each combining a config signal with a usage signal. The rules never read the ground truth. They ran once with thresholds fixed in advance.

| Result | Value |
|---|---|
| Planted gaps | 10 |
| Detected | 10 |
| True positives | 10 |
| False positives | 0 |
| Misses | 0 |
| **Precision** | **100% (10/10)** |
| **Recall** | **100% (10/10)** |

**How much this proves is limited.** I wrote both the generator and the rules, and the planted effects are large. The 9 decoys were not flagged, which shows the thresholds separate look-alikes from real gaps, but real data would be noisier and the thresholds would need calibration. Two results are close to their limits: the bad-rollout client sits exactly on the 25% rule limit (1 of 4 offices), and the two churn clients show seasonally adjusted drops of 56% and 60% against a 50% threshold. The health score alone did not clearly catch the churn clients (C011 is Amber at 55.6). Details are in `DECISIONS.md`.

## Deliverables

- `outputs/client_adoption_tracker.xlsx`: feature-matrix heat map, health scores, gap report.
- `outputs/powerbi/`: tidy CSVs and a README with the model and page layouts for Power BI (built separately in Power BI Desktop).
- `dashboard/app.py`: Streamlit fallback with 3 pages.
- `docs/pm_insights_brief.md`: top 3 blockers ranked by employees affected.
- `docs/client_walkthrough_desk_booking.md`: best-practice guide for a client's office admin.

## Screenshots

*(placeholders; add after running the dashboard and building Power BI)*

- `docs/img/powerbi_overview.png`
- `docs/img/powerbi_heatmap.png`
- `docs/img/powerbi_client_drilldown.png`
- `docs/img/streamlit_heatmap.png`

## How to run

```bash
pip install -r requirements.txt
python generate_data.py      # data/raw/*.csv + data/ground_truth.json
python load_db.py            # data/workplace.db (SQLite, ~160 MB, gitignored)
python run_queries.py        # runs sql/*.sql -> outputs/*.csv
python gap_detector.py       # outputs/gap_report.csv + evaluation
python export_excel.py       # Excel tracker + outputs/powerbi/*.csv
streamlit run dashboard/app.py
```

Everything is reproducible with seed 42: a full re-run produced identical results (only the Excel file's internal timestamp differs). Built and tested with Python 3.10.

## Repo layout

```
generate_data.py  load_db.py  run_queries.py  gap_detector.py  export_excel.py
sql/01..07_*.sql        data/raw/*.csv, data/ground_truth.json
outputs/                dashboard/app.py        docs/
SPEC.md  DECISIONS.md  (every judgement call, with reasons)
```

## Limitations

- Synthetic data: effects are cleaner and larger than real life. Normal clients have no config problems at all.
- One author wrote the data generator and the detector, so the detector's 100% is not independent validation.
- The health score is peer-relative, and its bands were set after viewing the score distribution (disclosed in `DECISIONS.md`).
- The Excel file and Streamlit app were checked structurally and by automated runs, not by eye on this machine.
