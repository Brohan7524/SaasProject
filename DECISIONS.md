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
