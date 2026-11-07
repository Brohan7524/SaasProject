# DECISIONS

Log of choices made where SPEC.md was ambiguous.

- P1: `data/raw/events.csv` and `data/workplace.db` are gitignored (large, fully regenerable with seed 42). Smaller CSVs and ground_truth.json are committed.
- P1: Power BI file (`dashboard/adoption.pbix`) is built manually by the user; this repo provides tidy CSVs in `outputs/powerbi/`.

## P2: data generation
- Window is calendar year 2025 (Diwali 20 Oct 2025, Christmas 24-31 Dec). Go-live dates run Nov 2024 - May 2025, so some clients are already mature on 1 Jan.
- Feature enabled in an office = the first `offices_enabled` offices of that client (by office_id). `offices_enabled` is stored in client_config.
- `client_config` columns beyond the spec: `offices_enabled`, `policy_max_days_per_week` (only on the Attendance Policy row). Scanner/calendar/parking flags live on `offices`, as in the spec.
- QR Check-in is its own feature whose only action is `check_in`. Other bookable features also emit `check_in` when a booking is attended. Attendance Policy has no check-in or no-show.
- Gap planting (10 gaps, one per client, distinct clients): 2 QR-no-scanners, 2 rooms-not-synced, 2 strict-policy, 1 bad-rollout, 1 parking-zero-spots, 2 silent-churn.
  - QR: usage x0.04 starting 30 days after enabling, in offices with no scanner (at most 1 office has one).
  - Rooms: employees using rooms x0.45 and no-show probability 0.35 (normal 0.08) in unsynced offices.
  - Strict policy: cap 1 day/week and desk view->book probability 0.15 (normal 0.75).
  - Bad rollout: Desk Booking switched on in 1 office of a client with >=4 offices.
  - Parking: 0 spots at every office; view->book probability 0.02.
  - Silent churn: usage slides to 30% by 31 Dec from 1 Oct, plus 40-55 extra tickets in that period.
- `ground_truth.json` also lists `decoys_not_gaps`: look-alike setups that are NOT planted gaps (1 office without scanners, 1 unsynced office, phased 50% rollout, cap of 2 days but normal booking, 1 office with zero parking, 4 naturally low-engagement clients, 1 mild ~25% decline). They exist so the P6 detector can have false positives; the detector must not read this file.
- Normal clients get no config problems at all (all scanners present, all calendars synced). Only planted gaps and decoys deviate. This is a simplification of real life.
- Ticket categories: how_to, bug, access, feature_request, integration, configuration, hardware, policy_restriction. Gap clients get ~25-45 extra tickets skewed to the category that matches the gap.
- Event volume was tuned (feature `rate` values) until the total was ~1M: 996,776 rows with seed 42.

## P3: SQLite load
- Tables are created with explicit DDL (PKs, foreign keys, CHECK constraints), then filled from the CSVs. Indexes are built after loading because that is faster.
- Dates and timestamps are stored as ISO text, since SQLite has no date type. ISO text sorts correctly and works with `date()` and `strftime()`.
- Indexes: `events(client_id, feature, ts)` as the spec asks, plus `events(employee_id, feature, ts)` for the cohort-retention query, and small indexes on the join keys.
- Booleans are 0/1 integers with CHECK constraints. Empty `enabled_date`, `policy_max_days_per_week` and `resolved_at` become NULL.
- `data/workplace.db` is 159 MB, so it stays gitignored. `python load_db.py` rebuilds it in seconds.

## P4: SQL 01-03 and run_queries.py
- **"Use" definition:** a `book` or `check_in` event. A `view` alone is browsing, not adoption. This is why Parking at a zero-spot client shows as low adoption even though people open the page.
- **Funnel stages (employee level):** eligible employees (in offices where the feature is on) -> ever used -> habitual (used in >= 3 of the last 4 weeks). "Last 4 weeks" = the 28 days ending 2025-12-31, as 7-day blocks counted backwards. These weeks include the Christmas dip, so the habitual numbers are a little conservative, especially for US/UK clients.
- **SQL file format:** a file may hold several queries. A line `-- @result name` starts a query that `run_queries.py` saves as `outputs/<file>__<name>.csv`. Text before the first marker is setup (temp tables). This keeps "one question per file" while allowing a few related result sets.
- **Resume number X (QR no repeat use):** per QR-enabled client, compare check-ins in month 1 (the 30 days from `enabled_date`) with the average 30-day rate after that. "No repeat use" = month 1 had no check-ins, or the later rate is below 25% of month 1. The 0.25 threshold was written before looking at the results. In the output the ratios are clearly split: 0.07 and 0.09 versus 1.78 and above, so the choice of threshold does not change the answer.
- **Known limitation of X:** `enabled_date` before 2025-01-01 (client C002, enabled Dec 2024) makes month 1 partly invisible, because events only start on 1 Jan. Its ratio (10.05) is inflated, but it is not flagged either way.
- **Cohort retention:** cohort = month of first `book` event, activity = any booking in a month. There is one table for any feature and one per feature. Later cohorts have fewer months of history and are cut off at Dec 2025.
- **DAU/WAU/MAU:** DAU is averaged over weekdays only (Mon-Fri), with zero-activity weekdays counted as 0 via a calendar table. Weekends are excluded because hybrid offices are nearly empty then. Weeks run Mon-Sun and belong to the month they start in.

## P5: SQL 04-06
- **Dependency:** `04_feature_matrix.sql` builds the temp table `feature_matrix`; 05 and 06 reuse it. `run_queries.py` runs the files in order on one connection, so run them through it.
- **Matrix metric (04):** adoption = employees with a book/check-in in the last 90 days (2025-10-03..2025-12-31) / ALL client employees. Dividing by all employees, not only eligible ones, makes partial rollouts look weak. `adoption_pct_of_eligible` and `coverage_pct` are included as well. Disabled features are NULL, not 0.
- **Low adopter (05):** the lowest quartile of adoption per feature (`NTILE(4) = 1`), so each feature is compared with its own peers. Quartiles were chosen over a fixed % because "good" adoption differs a lot by feature (Visitor ~7%, Desk ~31%).
- **Finding worth knowing:** adoption % alone does NOT expose every gap. Strict-policy clients still have many employees who book now and then, so they are not in the lowest desk quartile even though most of their views never become bookings. That is why the gap detector (P6) looks at behaviour (view-to-book, no-shows), not only adoption %.

### Health score (06) - weights and why
`health = 0.30 * breadth + 0.30 * depth + 0.25 * trend + 0.15 * (100 - ticket_load)`, all components 0-100.
- **Breadth, 30%:** is the client using many features, or only Desk Booking? Breadth is what makes a client sticky and is the central product-adoption question. A feature counts as "in use" if >= 5% of employees were active in the last 90 days.
- **Depth, 30%:** how well does the client use the features it has? It is the client's average percent rank against peers on each enabled feature. Peer-relative on purpose: there is no objective "good" adoption level, and this avoids picking arbitrary targets. Side effect: the score is relative, not absolute.
- **Trend, 25%:** is usage rising or falling? It gets less weight than breadth and depth because 60-day windows are noisy and holidays distort them for everyone.
- **Ticket load, 15%, subtracted:** a high ticket rate is a warning sign but also a sign of engagement, so it has the lowest weight. Percent rank of tickets per 100 employees in the last 90 days.
- **Two changes made after seeing the first run (both disclosed):**
  1. *Trend window.* The first draft compared Oct-Dec with Jul-Sep. That diluted a decline concentrated at year end, and the two clients with the sharpest recent drop scored as healthy as everyone else. It now compares the last 60 days with the previous 60. Across all 40 clients this ratio is around 0.8 for normal clients (the Diwali/Christmas dip) and 0.44-0.48 for the two sharpest decliners.
  2. *Red band.* The first draft used Red < 45, but no client scored below 48 (the peer-percentile components pull scores to the middle), so Red was empty and useless. Bands are now Green >= 65, Amber 55 to < 65, Red < 55 (the bottom quartile is ~55). The bands are a relative ranking, not an absolute judgement.
- **Limitation:** a coarse health band does not tell you the cause. Use the `weakest_component` column and the gap report (P6) for that.

## P6: gap detector
- **Inputs:** the detector reads the raw CSVs (config, offices, employees, events, tickets) with pandas, not the SQLite database. It never reads `ground_truth.json` inside a rule. The evaluation function at the bottom is the only reader, and it runs after `gap_report.csv` is written.
- **Thresholds were fixed before the first run and not changed since.** Each rule needs a config signal AND a usage signal, so a clean config with normal usage is never flagged, and a config oddity alone is not enough:
  1. QR: no scanners at >= 50% of offices AND later usage < 0.5x month-1 usage.
  2. Rooms: calendar not synced at >= 50% of offices AND no-show rate in those offices >= 2x the portfolio median (the median is computed from data).
  3. Policy: cap <= 2 days/week AND desk view-to-book conversion < 0.5x the portfolio median.
  4. Rollout: a feature is on in <= 25% of offices, for clients with >= 3 offices (config only).
  5. Parking: zero spots at >= 50% of the offices where parking is on (config only; the view-to-book rate is shown as evidence).
  6. Churn: usage in the last 30 days vs the 30 days ending 90 days earlier, divided by the portfolio median ratio (removes the shared holiday dip), is < 0.5 AND tickets in the last 90 days >= 1.25x the previous 90 days. A client needs >= 200 baseline events to be judged.
- **Unit of evaluation:** a (client, gap type) pair. Employees affected comes from the rule, not from ground truth.
- **Result of the single run:** 10 detected, 10 planted, 10 true positives, 0 false positives, 0 misses.
- **Why 100% is weak evidence, and what to say about it in an interview:** I wrote both the data generator and the rules, and the planted effects are large (e.g. view-to-book 0.15 vs 0.75). The decoys (a 1-in-3 unsynced office, a 50% phased rollout, a cap of 2 with normal booking, a ~25% decline) did test the thresholds, and none were flagged. Real data would be noisier. The thin margins in this run are:
  - Rollout: C031 sits exactly on the 25% limit (1 of 4 offices). A stricter limit of 20% would miss it.
  - Churn: the two flagged clients have seasonally adjusted drops of 56% and 60% against a 50% threshold. The decoy "mild decline" is not flagged.

## P7: Excel tracker and Power BI tables
- **No real PivotTable:** openpyxl cannot create one. The "Feature Matrix" sheet is the already-pivoted client x feature grid with conditional formatting. `fact_feature_adoption.csv` is the long-format version for pivoting in Excel or Power BI.
- **Heat map colour scale is per feature column** (red = lowest, yellow = median, green = highest among clients using that feature). A single global scale would paint Visitor Management (about 7% average adoption) red everywhere and hide differences between clients.
- **Two supporting SQL changes:** `sql/07_client_monthly_usage.sql` (monthly client x feature usage, for trend visuals) and a new result `all_enabled` in `05_why_not.sql` (all enabled client x features, not only low adopters). The six core question files are unchanged.
- **Power BI tables are a star schema:** `dim_clients` and `dim_feature` connect to the fact tables on `client_id` and `feature`. Months are exported as first-of-month dates. Blank cells are intentional: a disabled feature has no adoption %, and QR has no "view" step so view-without-book is blank. `outputs/powerbi/README.md` lists relationships, page layouts and DAX measures.
- **Not verified visually:** I checked the workbook structure with openpyxl (sheets, conditional-format ranges, values), but there is no Excel or LibreOffice on this machine to render it. Open the file once to check the colours.

## P8: Streamlit dashboard
- **Data source:** the dashboard reads `outputs/powerbi/*.csv`, the same tables Power BI uses, so both tools show the same numbers. Nothing is recomputed in the app.
- **Heat map colour:** sequential single-hue blue, kept light so the number printed in each cell stays readable. A toggle switches between absolute % and a per-feature relative rank, matching the Excel heat map. Blank cells are features that are not enabled.
- **Health bands:** green, amber and red are used because the bands are statuses, and every colour is paired with the band name and a count, never colour alone.
- **Testing:** I ran the app with Streamlit's `AppTest` harness. All three pages, the filters, the colour-scale toggle, the funnel feature selector and four client drill-downs (C011, C019, C031, C001) ran with no exceptions. I also started the server headless and checked it answered, then stopped it. I could not view it in a browser from here, so the layout and colours have not been looked at. Run `streamlit run dashboard/app.py` once and check it.

## P9: docs
- **Blockers are ranked by the sum of `employees_affected` from `gap_report.csv`** (silent churn 1,155; rooms not synced 773; strict policy 608; then QR 471, rollout 444, parking 404). Silent churn is an outcome rather than a configuration cause, but it is the largest group by the spec's ranking, so it is included with a note that the data cannot say why usage fell.
- **"3,855 employees directly affected" is the sum over gaps; "4,362 employees" is everyone at the 10 flagged clients.** Both are stated so neither is mistaken for the other.
- **No impact estimates:** the brief proposes one product change per blocker and says each is a hypothesis. It gives no uplift numbers because nothing in this data can support them.
- **Client guide:** benchmarks come from the synthetic portfolio (Desk Booking clients: average 31% adoption, 75% median view-to-book, 9.9% cancelled, 5.5% no-show, 69% of bookings made Tue-Thu). The guide says this at the top. Practices and message templates are labelled as recommendations. Thresholds such as "fewer than about 4 in 10" are half the median conversion, the same line used by the detector.
