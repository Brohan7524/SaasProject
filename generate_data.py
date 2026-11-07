"""
generate_data.py  -  builds the SYNTHETIC dataset for the adoption-analytics project.

Writes:
    data/raw/clients.csv, client_config.csv, offices.csv, employees.csv,
    data/raw/events.csv, support_tickets.csv
    data/ground_truth.json   (which implementation gaps were planted, and where)

Everything is driven by one random generator seeded with 42, so every run
produces identical files.

Big picture of how events are made:
  For every (client, feature, office) "stream" we pick which employees use the
  feature, when each one starts (slow ramp after go-live), and then roll a dice
  for every employee-day.  A "session" then turns into view / book / cancel /
  no_show / check_in events.  Planted gaps are just parameter changes on
  specific streams (e.g. QR usage x0.04 after month 1 at offices with no scanners).
"""
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
START = date(2025, 1, 1)          # simulated window = calendar year 2025
N_DAYS = 365
END = START + timedelta(days=N_DAYS)

RAW_DIR = Path("data/raw")
GROUND_TRUTH_PATH = Path("data/ground_truth.json")

N_CLIENTS = 40
N_EMPLOYEES = 20_000
N_OFFICES_TARGET = 90

FEATURES = ["Desk Booking", "Meeting Room Booking", "Parking",
            "QR Check-in", "Attendance Policy", "Visitor Management"]

# Per-feature behaviour.
#   share    : fraction of an office's employees who ever use the feature
#   rate     : chance an active employee uses it on a normal weekday-ish day
#   p_book   : chance a session that starts with a "view" turns into a booking
#   p_cancel / p_no_show / p_check_in : what happens to a booking afterwards
#   ramp     : average days an employee takes to start after the feature is enabled
FEATURE_PARAMS = {
    "Desk Booking":         dict(share=0.55, rate=0.17, p_book=0.75, p_cancel=0.10, p_no_show=0.06, p_check_in=0.75, ramp=45),
    "Meeting Room Booking": dict(share=0.35, rate=0.10, p_book=0.65, p_cancel=0.12, p_no_show=0.08, p_check_in=0.70, ramp=50),
    "Parking":              dict(share=0.25, rate=0.17, p_book=0.80, p_cancel=0.08, p_no_show=0.05, p_check_in=0.75, ramp=40),
    "QR Check-in":          dict(share=0.45, rate=0.20, p_book=0.00, p_cancel=0.00, p_no_show=0.00, p_check_in=1.00, ramp=30),
    "Attendance Policy":    dict(share=0.50, rate=0.05, p_book=0.50, p_cancel=0.10, p_no_show=0.00, p_check_in=0.00, ramp=60),
    "Visitor Management":   dict(share=0.12, rate=0.05, p_book=0.85, p_cancel=0.08, p_no_show=0.05, p_check_in=0.90, ramp=70),
}

# Chance a client has the feature enabled, by plan.
ENABLE_PROB = {
    "Desk Booking":         {"Basic": 0.97, "Pro": 0.97, "Enterprise": 0.97},
    "Meeting Room Booking": {"Basic": 0.55, "Pro": 0.80, "Enterprise": 0.95},
    "Parking":              {"Basic": 0.45, "Pro": 0.45, "Enterprise": 0.45},
    "QR Check-in":          {"Basic": 0.45, "Pro": 0.65, "Enterprise": 0.80},
    "Attendance Policy":    {"Basic": 0.30, "Pro": 0.70, "Enterprise": 0.90},
    "Visitor Management":   {"Basic": 0.20, "Pro": 0.45, "Enterprise": 0.70},
}
# Days after go-live that a feature is switched on (min, max).
ENABLE_DELAY = {
    "Desk Booking": (0, 14), "Meeting Room Booking": (0, 45), "Parking": (14, 90),
    "QR Check-in": (14, 120), "Attendance Policy": (0, 60), "Visitor Management": (30, 120),
}

REGIONS = {"India": 0.40, "US": 0.25, "UK": 0.20, "SG": 0.15}
CITIES = {
    "India": ["Bengaluru", "Pune", "Hyderabad", "Gurugram", "Chennai", "Mumbai"],
    "US": ["New York", "Austin", "San Francisco", "Chicago", "Seattle"],
    "UK": ["London", "Manchester", "Edinburgh", "Bristol"],
    "SG": ["Singapore"],
}
INDUSTRIES = ["IT Services", "Banking", "Consulting", "Pharma", "Manufacturing",
              "Retail", "Telecom", "Insurance", "Media"]
DEPARTMENTS = ["Engineering", "Sales", "HR", "Finance", "Operations", "Marketing", "Support", "Product"]

# Day-of-week multipliers (Mon..Sun): hybrid offices peak Tue-Thu, weekends almost empty.
WEEKDAY_MULT = np.array([0.90, 1.15, 1.20, 1.10, 0.55, 0.05, 0.04])
# Hour-of-day weights for when sessions happen (hours 6..20).
HOURS = np.arange(6, 21)
HOUR_WEIGHTS = np.array([1, 4, 9, 10, 7, 5, 6, 8, 8, 6, 4, 3, 2, 1, 1], dtype=float)
HOUR_WEIGHTS = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()

TICKET_CATEGORIES = ["how_to", "bug", "access", "feature_request", "integration",
                     "configuration", "hardware", "policy_restriction"]
TICKET_BASE_WEIGHTS = [0.33, 0.20, 0.15, 0.10, 0.08, 0.08, 0.03, 0.03]


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def day_index(d):
    """Days since START (can be negative for dates before the window)."""
    return (d - START).days


def season_multiplier(region):
    """Per-day multiplier (length N_DAYS) with festival / holiday dips for a region."""
    mult = np.ones(N_DAYS)

    def dip(start, end, factor):
        for i in range(N_DAYS):
            if start <= START + timedelta(days=i) <= end:
                mult[i] = min(mult[i], factor)

    dip(date(2025, 12, 24), date(2025, 12, 31), {"India": 0.75, "US": 0.35, "UK": 0.35, "SG": 0.60}[region])
    dip(date(2025, 1, 1), date(2025, 1, 1), 0.50)                    # New Year's Day
    if region == "India":
        dip(date(2025, 10, 17), date(2025, 10, 17), 0.80)            # Diwali 2025 is 20 Oct
        dip(date(2025, 10, 18), date(2025, 10, 23), 0.45)
        dip(date(2025, 1, 26), date(2025, 1, 26), 0.30)              # Republic Day
        dip(date(2025, 8, 15), date(2025, 8, 15), 0.30)              # Independence Day
    if region == "SG":
        dip(date(2025, 10, 20), date(2025, 10, 20), 0.70)            # Deepavali
    if region in ("US", "UK"):
        dip(date(2025, 12, 20), date(2025, 12, 23), 0.80)
    if region == "US":
        dip(date(2025, 7, 4), date(2025, 7, 4), 0.30)
    if region == "UK":
        dip(date(2025, 8, 1), date(2025, 8, 31), 0.85)               # summer holidays
    return mult


def churn_trend(final_level):
    """1.0 until 1 Oct, then slides smoothly down to `final_level` by 31 Dec."""
    trend = np.ones(N_DAYS)
    oct1 = day_index(date(2025, 10, 1))
    for i in range(oct1, N_DAYS):
        progress = (i - oct1) / (N_DAYS - 1 - oct1)
        trend[i] = 1.0 - (1.0 - final_level) * progress
    return trend


# --------------------------------------------------------------------------
# Step 1: clients, office counts, employees per client
# --------------------------------------------------------------------------
def make_clients(rng, fake):
    regions = rng.choice(list(REGIONS), size=N_CLIENTS, p=list(REGIONS.values()))
    plans = rng.choice(["Basic", "Pro", "Enterprise"], size=N_CLIENTS, p=[0.30, 0.45, 0.25])

    # Employees per client: lognormal sizes scaled so the total is ~20,000.
    raw_sizes = rng.lognormal(mean=6.0, sigma=0.7, size=N_CLIENTS)
    sizes = np.maximum(80, raw_sizes / raw_sizes.sum() * N_EMPLOYEES).astype(int)
    # Fix rounding drift by adjusting the largest client.
    sizes[np.argmax(sizes)] += N_EMPLOYEES - sizes.sum()

    go_live_start = date(2024, 11, 1)
    go_live_span = (date(2025, 5, 31) - go_live_start).days
    rows = []
    for i in range(N_CLIENTS):
        rows.append(dict(
            client_id=f"C{i + 1:03d}",
            name=fake.company(),
            industry=str(rng.choice(INDUSTRIES)),
            region=str(regions[i]),
            plan=str(plans[i]),
            go_live_date=go_live_start + timedelta(days=int(rng.integers(0, go_live_span + 1))),
            seats=int(sizes[i] * rng.uniform(1.0, 1.3)),
            n_employees=int(sizes[i]),            # helper column, dropped before saving
        ))
    clients = pd.DataFrame(rows)

    # Office counts: bigger clients get more offices; total lands near 90.
    weights = clients["n_employees"] ** 0.7
    n_offices = np.maximum(1, np.round(weights / weights.sum() * N_OFFICES_TARGET)).astype(int)
    clients["n_offices"] = n_offices
    return clients


# --------------------------------------------------------------------------
# Step 2: decide which clients get which planted gap (or decoy)
# --------------------------------------------------------------------------
def pick_clients(rng, eligible_ids, how_many, used):
    """Pick `how_many` unused clients from eligible_ids."""
    pool = [c for c in eligible_ids if c not in used]
    assert len(pool) >= how_many, "not enough eligible clients for this gap type"
    chosen = [str(c) for c in rng.choice(pool, size=how_many, replace=False)]
    used.update(chosen)
    return chosen


def plan_gaps_and_decoys(rng, clients):
    """
    Returns a dict client_id -> profile.  profile['gap'] is one of the 6 gap types
    (or None).  profile['decoy'] marks look-alike clients that are NOT real gaps.
    Most constrained gap types are assigned first.
    """
    profile = {c: dict(gap=None, decoy=None, engagement=None) for c in clients["client_id"]}
    used = set()
    big_office = clients.loc[clients["n_offices"] >= 4, "client_id"].tolist()
    mid_office = clients.loc[clients["n_offices"] >= 3, "client_id"].tolist()
    big_staff = clients.loc[clients["n_employees"] >= 300, "client_id"].tolist()
    everyone = clients["client_id"].tolist()

    # (gap_type, how many, eligible clients)
    gap_plan = [
        ("bad_rollout", 1, big_office),
        ("silent_churn", 2, big_staff),
        ("qr_no_scanners", 2, everyone),
        ("room_not_synced", 2, everyone),
        ("strict_policy", 2, everyone),
        ("parking_zero_spots", 1, everyone),
    ]
    for gap_type, how_many, eligible in gap_plan:
        for cid in pick_clients(rng, eligible, how_many, used):
            profile[cid]["gap"] = gap_type

    # Decoys: realistic-looking setups that are NOT planted gaps.
    decoy_plan = [
        ("partial_scanners", 1, mid_office),     # 1 office lacks scanners, rest fine
        ("one_room_unsynced", 1, mid_office),    # 1 office unsynced, rest fine
        ("phased_rollout", 1, big_office),       # desk live in half the offices
        ("mild_policy_cap", 1, everyone),        # cap of 2 days but people still book
        ("parking_one_office_zero", 1, mid_office),
        ("low_engagement", 4, everyone),         # naturally low adopters, no config problem
        ("mild_decline", 1, big_staff),          # usage drops ~25%, not >50%
    ]
    for decoy_type, how_many, eligible in decoy_plan:
        for cid in pick_clients(rng, eligible, how_many, used):
            profile[cid]["decoy"] = decoy_type

    # Overall engagement multiplier per client.
    for cid, p in profile.items():
        if p["decoy"] == "low_engagement":
            p["engagement"] = float(rng.uniform(0.35, 0.5))
        elif p["gap"] == "silent_churn":
            p["engagement"] = 1.15          # churn clients start out healthy
        else:
            p["engagement"] = float(np.clip(rng.lognormal(0, 0.2), 0.7, 1.4))
    return profile


# --------------------------------------------------------------------------
# Step 3: client_config (which features are on, plus config flags)
# --------------------------------------------------------------------------
def make_client_config(rng, clients, profile):
    # Gap clients need specific go-live windows so the gap is visible in the data.
    for idx, row in clients.iterrows():
        gap = profile[row["client_id"]]["gap"]
        if gap == "silent_churn":
            clients.at[idx, "go_live_date"] = date(2025, 1, 1) + timedelta(days=int(rng.integers(0, 30)))
        if gap == "qr_no_scanners":
            clients.at[idx, "go_live_date"] = date(2025, 1, 1) + timedelta(days=int(rng.integers(0, 45)))

    rows = []
    last_enable_date = date(2025, 9, 30)    # leave >= 3 months of data after enabling
    for _, c in clients.iterrows():
        cid = c["client_id"]
        gap, decoy = profile[cid]["gap"], profile[cid]["decoy"]
        forced_on = {
            "qr_no_scanners": "QR Check-in", "room_not_synced": "Meeting Room Booking",
            "strict_policy": "Attendance Policy", "parking_zero_spots": "Parking",
            "bad_rollout": "Desk Booking",
        }
        for feature in FEATURES:
            enabled = rng.random() < ENABLE_PROB[feature][c["plan"]]
            if forced_on.get(gap) == feature or (gap == "strict_policy" and feature == "Desk Booking"):
                enabled = True
            if decoy == "mild_policy_cap" and feature in ("Attendance Policy", "Desk Booking"):
                enabled = True
            if decoy == "partial_scanners" and feature == "QR Check-in":
                enabled = True
            if decoy == "one_room_unsynced" and feature == "Meeting Room Booking":
                enabled = True
            if decoy == "parking_one_office_zero" and feature == "Parking":
                enabled = True
            if decoy == "phased_rollout" and feature == "Desk Booking":
                enabled = True

            enabled_date, offices_enabled, max_days = None, 0, None
            if enabled:
                lo, hi = ENABLE_DELAY[feature]
                enabled_date = c["go_live_date"] + timedelta(days=int(rng.integers(lo, hi + 1)))
                if gap == "qr_no_scanners" and feature == "QR Check-in":
                    enabled_date = c["go_live_date"] + timedelta(days=int(rng.integers(14, 30)))
                enabled_date = min(enabled_date, last_enable_date)
                offices_enabled = int(c["n_offices"])
                if feature == "Desk Booking" and gap == "bad_rollout":
                    offices_enabled = 1                                   # only 1 office switched on
                if feature == "Desk Booking" and decoy == "phased_rollout":
                    offices_enabled = max(2, int(c["n_offices"]) // 2)    # 50%+ of offices
            if feature == "Attendance Policy" and enabled:
                if gap == "strict_policy":
                    max_days = 1
                elif decoy == "mild_policy_cap":
                    max_days = 2
                else:
                    max_days = int(rng.choice([3, 4, 5]))
            rows.append(dict(client_id=cid, feature=feature, enabled=int(enabled),
                             enabled_date=enabled_date, offices_enabled=offices_enabled,
                             policy_max_days_per_week=max_days))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Step 4: offices and employees
# --------------------------------------------------------------------------
def make_offices_and_employees(rng, clients, config, profile):
    office_rows, employee_rows = [], []
    office_counter, emp_counter = 0, 0

    for _, c in clients.iterrows():
        cid, gap, decoy = c["client_id"], profile[c["client_id"]]["gap"], profile[c["client_id"]]["decoy"]
        n_off = int(c["n_offices"])
        cfg = config[config["client_id"] == cid].set_index("feature")
        qr_on = bool(cfg.loc["QR Check-in", "enabled"])

        # Employees spread across the client's offices (uneven sizes).
        weights = rng.dirichlet(np.ones(n_off) * 2.0)
        office_of_emp = rng.choice(n_off, size=int(c["n_employees"]), p=weights)
        emp_per_office = np.bincount(office_of_emp, minlength=n_off)

        for k in range(n_off):
            office_counter += 1
            n_emp = int(emp_per_office[k])

            # --- config flags on the office, with planted gaps and decoys ---
            has_scanners = True if qr_on else bool(rng.random() < 0.4)
            calendar_synced = True
            parking_spots = int(round(n_emp * 0.25))

            if gap == "qr_no_scanners":
                has_scanners = (n_off >= 3 and k == 0)       # at most 1 office has scanners
            if decoy == "partial_scanners":
                has_scanners = (k != 0)
            if gap == "room_not_synced":
                calendar_synced = (n_off >= 4 and k == 0)
            if decoy == "one_room_unsynced":
                calendar_synced = (k != 0)
            if gap == "parking_zero_spots":
                parking_spots = 0
            if decoy == "parking_one_office_zero":
                parking_spots = 0 if k == 0 else parking_spots

            office_rows.append(dict(
                office_id=f"O{office_counter:03d}", client_id=cid,
                city=str(rng.choice(CITIES[c["region"]])),
                desks=int(np.ceil(n_emp * 0.55)), rooms=max(2, int(round(n_emp / 30))),
                parking_spots=parking_spots, has_qr_scanners=int(has_scanners),
                calendar_synced=int(calendar_synced)))

        first_office_num = office_counter - n_off + 1
        for e in range(int(c["n_employees"])):
            emp_counter += 1
            # 85% joined before the window, 15% joined during it.
            if rng.random() < 0.85:
                join = date(2022, 1, 1) + timedelta(days=int(rng.integers(0, 1096)))
            else:
                join = START + timedelta(days=int(rng.integers(0, 300)))
            employee_rows.append(dict(
                employee_id=f"E{emp_counter:05d}", client_id=cid,
                office_id=f"O{first_office_num + int(office_of_emp[e]):03d}",
                department=str(rng.choice(DEPARTMENTS)), join_date=join))
    return pd.DataFrame(office_rows), pd.DataFrame(employee_rows)


# --------------------------------------------------------------------------
# Step 5: events
# --------------------------------------------------------------------------
def stream_settings(feature, cfg_row, office, prof):
    """
    Work out the behaviour of one (client, feature, office) stream, including the
    effect of any planted gap.  Returns a dict of overrides.
    """
    params = dict(FEATURE_PARAMS[feature])
    gap, decoy = prof["gap"], prof["decoy"]
    share_scale = prof["engagement"]
    collapse_after = None            # day index after which usage collapses (QR gap)

    # 1) QR enabled but no scanner in this office -> usage collapses after month 1.
    if feature == "QR Check-in" and not office["has_qr_scanners"]:
        collapse_after = day_index(cfg_row["enabled_date"]) + 30

    # 2) Rooms not synced to calendar -> fewer bookings, many no-shows.
    if feature == "Meeting Room Booking" and not office["calendar_synced"]:
        share_scale *= 0.45
        params["p_no_show"] = 0.35

    # 3) Over-strict attendance policy -> people view desks but cannot book.
    if feature == "Desk Booking" and gap == "strict_policy":
        params["p_book"] = 0.15
    if feature == "Desk Booking" and decoy == "mild_policy_cap":
        params["p_book"] = 0.55

    # 5) Parking switched on but no spots -> people look, cannot book.
    if feature == "Parking" and office["parking_spots"] == 0:
        params["p_book"] = 0.02
        share_scale *= 0.3

    return params, share_scale, collapse_after


def simulate_stream(rng, emp_idx, emp_join_day, enabled_day, params, share_scale, day_mult, collapse_after):
    """
    Simulate one stream. Returns arrays (employee index, day, second-of-day) for each session.
    """
    n_active = int(round(len(emp_idx) * min(0.95, params["share"] * share_scale)))
    if n_active == 0:
        return None
    active = rng.choice(len(emp_idx), size=n_active, replace=False)

    # Each active employee starts after a random delay (slow ramp), and not before joining.
    start_day = enabled_day + rng.exponential(params["ramp"], size=n_active)
    start_day = np.maximum(start_day, emp_join_day[active])
    # Some employees eventually drift away (mild natural attrition).
    end_day = start_day + rng.exponential(400, size=n_active)
    # Heavy users vs light users.
    propensity = np.clip(rng.lognormal(0, 0.5, size=n_active), 0.2, 3.0)

    mult = day_mult.copy()
    if collapse_after is not None:
        mult[np.arange(N_DAYS) >= collapse_after] *= 0.04

    days = np.arange(N_DAYS)
    prob = np.minimum(0.9, params["rate"] * propensity[:, None] * mult[None, :])
    is_live = (days[None, :] >= start_day[:, None]) & (days[None, :] < end_day[:, None])
    happened = (rng.random(prob.shape) < prob) & is_live

    user_pos, day_pos = np.nonzero(happened)
    if len(user_pos) == 0:
        return None
    seconds = (rng.choice(HOURS, size=len(user_pos), p=HOUR_WEIGHTS) * 3600
               + rng.integers(0, 3600, size=len(user_pos)))
    return emp_idx[active[user_pos]], day_pos, seconds


def sessions_to_events(rng, feature, params, p_no_show_override, emp, day, sec):
    """Turn sessions into view / book / cancel / no_show / check_in events."""
    base_ts = day.astype(np.int64) * 86400 + sec          # seconds since START
    n = len(emp)
    out = []   # list of (employee_idx, ts_seconds, action)

    if feature == "QR Check-in":
        # A QR session is just a scan.
        return [(emp, base_ts, "check_in")]

    out.append((emp, base_ts, "view"))
    booked = rng.random(n) < params["p_book"]
    book_ts = base_ts + rng.integers(30, 300, size=n)
    out.append((emp[booked], book_ts[booked], "book"))

    outcome_ts = book_ts + rng.integers(1800, 9 * 3600, size=n)
    r = rng.random(n)
    cancelled = booked & (r < params["p_cancel"])
    no_show = booked & ~cancelled & (rng.random(n) < p_no_show_override)
    checked_in = booked & ~cancelled & ~no_show & (rng.random(n) < params["p_check_in"])
    out.append((emp[cancelled], outcome_ts[cancelled], "cancel"))
    out.append((emp[no_show], outcome_ts[no_show], "no_show"))
    out.append((emp[checked_in], outcome_ts[checked_in], "check_in"))
    return out


def make_events(rng, clients, config, offices, employees, profile):
    seasons = {r: season_multiplier(r) for r in REGIONS}
    weekday = np.array([WEEKDAY_MULT[(START + timedelta(days=i)).weekday()] for i in range(N_DAYS)])
    emp_join_day = np.array([day_index(d) for d in employees["join_date"]])

    pieces = []   # each piece: (employee idx array, ts array, action, feature)
    for _, c in clients.iterrows():
        cid = c["client_id"]
        prof = profile[cid]
        client_trend = np.ones(N_DAYS)
        if prof["gap"] == "silent_churn":
            client_trend = churn_trend(0.30)
        if prof["decoy"] == "mild_decline":
            client_trend = churn_trend(0.75)
        day_mult = weekday * seasons[c["region"]] * client_trend

        client_offices = offices[offices["client_id"] == cid].reset_index(drop=True)
        cfg = config[config["client_id"] == cid].set_index("feature")

        for feature in FEATURES:
            cfg_row = cfg.loc[feature]
            if not cfg_row["enabled"]:
                continue
            enabled_day = day_index(cfg_row["enabled_date"])
            # Features are switched on in the first `offices_enabled` offices.
            for _, office in client_offices.iloc[: int(cfg_row["offices_enabled"])].iterrows():
                emp_idx = np.flatnonzero((employees["office_id"] == office["office_id"]).to_numpy())
                if len(emp_idx) == 0:
                    continue
                params, share_scale, collapse_after = stream_settings(feature, cfg_row, office, prof)
                sim = simulate_stream(rng, emp_idx, emp_join_day, enabled_day, params,
                                      share_scale, day_mult, collapse_after)
                if sim is None:
                    continue
                for emp, ts, action in sessions_to_events(rng, feature, params, params["p_no_show"], *sim):
                    if len(emp):
                        pieces.append((emp, ts, action, feature))

    # Stack everything into one table.
    emp_all = np.concatenate([p[0] for p in pieces])
    ts_all = np.concatenate([p[1] for p in pieces])
    action_all = np.concatenate([np.full(len(p[0]), p[2]) for p in pieces])
    feature_all = np.concatenate([np.full(len(p[0]), p[3]) for p in pieces])

    # Drop anything that spills past the end of the window.
    keep = ts_all < N_DAYS * 86400
    emp_all, ts_all, action_all, feature_all = emp_all[keep], ts_all[keep], action_all[keep], feature_all[keep]

    events = pd.DataFrame({
        "employee_id": employees["employee_id"].to_numpy()[emp_all],
        "client_id": employees["client_id"].to_numpy()[emp_all],
        "feature": feature_all,
        "action": action_all,
        "ts": pd.to_datetime(ts_all, unit="s", origin=pd.Timestamp(START)),
    })
    events = events.sort_values("ts", kind="stable").reset_index(drop=True)
    events.insert(0, "event_id", np.arange(1, len(events) + 1))
    events["ts"] = events["ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return events


# --------------------------------------------------------------------------
# Step 6: support tickets
# --------------------------------------------------------------------------
# Which ticket categories dominate for each planted gap.
GAP_TICKET_PROFILE = {
    "qr_no_scanners":     ("QR Check-in",          dict(hardware=0.5, configuration=0.2, how_to=0.3)),
    "room_not_synced":    ("Meeting Room Booking", dict(integration=0.6, bug=0.2, how_to=0.2)),
    "strict_policy":      ("Attendance Policy",    dict(policy_restriction=0.55, feature_request=0.25, how_to=0.2)),
    "bad_rollout":        ("Desk Booking",         dict(access=0.45, feature_request=0.35, how_to=0.2)),
    "parking_zero_spots": ("Parking",              dict(configuration=0.6, how_to=0.2, bug=0.2)),
}


def random_ticket_days(rng, n, enabled_day, onboarding_share=0.4):
    """Ticket creation days: some burst right after enabling, the rest spread out."""
    first = max(0, enabled_day)
    onboarding = first + rng.exponential(60, size=n)
    spread = rng.uniform(first, N_DAYS, size=n)
    days = np.where(rng.random(n) < onboarding_share, onboarding, spread)
    days = np.where(days >= N_DAYS, rng.uniform(first, N_DAYS, size=n), days)
    return np.minimum(days, N_DAYS - 0.01)


def make_tickets(rng, clients, config, profile):
    rows = []

    def add(cid, feature, day_float, category):
        created = pd.Timestamp(START) + pd.Timedelta(days=float(day_float))
        created = created.floor("min")
        resolved = created + pd.Timedelta(days=float(rng.lognormal(0.8, 0.8)))
        if rng.random() < 0.06 or resolved >= pd.Timestamp(END):
            resolved = pd.NaT                          # still open
        rows.append(dict(client_id=cid, feature=feature, category=category,
                         created_at=created, resolved_at=resolved))

    for _, c in clients.iterrows():
        cid, gap = c["client_id"], profile[c["client_id"]]["gap"]
        cfg = config[config["client_id"] == cid].set_index("feature")

        # Baseline tickets for every enabled feature (more employees -> more tickets).
        for feature in FEATURES:
            if not cfg.loc[feature, "enabled"]:
                continue
            n = rng.poisson(4 + c["n_employees"] / 150)
            days = random_ticket_days(rng, n, day_index(cfg.loc[feature, "enabled_date"]))
            cats = rng.choice(TICKET_CATEGORIES, size=n, p=TICKET_BASE_WEIGHTS)
            for d, cat in zip(days, cats):
                add(cid, feature, d, cat)

        # Extra tickets that point at the planted problem.
        if gap in GAP_TICKET_PROFILE:
            feature, weights = GAP_TICKET_PROFILE[gap]
            n = int(rng.integers(25, 46))
            days = random_ticket_days(rng, n, day_index(cfg.loc[feature, "enabled_date"]), 0.2)
            cats = rng.choice(list(weights), size=n, p=list(weights.values()))
            for d, cat in zip(days, cats):
                add(cid, feature, d, cat)

        # Silent churn: ticket volume climbs in the last 3 months.
        if gap == "silent_churn":
            enabled_features = [f for f in FEATURES if cfg.loc[f, "enabled"]]
            oct1 = day_index(date(2025, 10, 1))
            for _ in range(int(rng.integers(40, 56))):
                add(cid, str(rng.choice(enabled_features)), rng.uniform(oct1, N_DAYS - 0.01),
                    str(rng.choice(["bug", "access", "how_to"], p=[0.5, 0.3, 0.2])))

    tickets = pd.DataFrame(rows).sort_values("created_at").reset_index(drop=True)
    tickets.insert(0, "ticket_id", [f"T{i + 1:04d}" for i in range(len(tickets))])
    return tickets


# --------------------------------------------------------------------------
# Step 7: ground truth, saving, sanity checks
# --------------------------------------------------------------------------
GAP_DESCRIPTIONS = {
    "qr_no_scanners": "QR Check-in enabled but offices have no QR scanners; check-ins collapse after month 1",
    "room_not_synced": "Meeting rooms not synced to calendar; low room bookings and high no-shows",
    "strict_policy": "Attendance policy caps bookings at 1 day/week; many views, few bookings",
    "bad_rollout": "Desk Booking enabled in only 1 office of a multi-office client",
    "parking_zero_spots": "Parking enabled but zero parking spots configured",
    "silent_churn": "Healthy usage that drops >50% in the last 3 months with rising tickets",
}


def build_ground_truth(clients, offices, employees, profile):
    gaps, decoys = [], []
    for _, c in clients.iterrows():
        cid = c["client_id"]
        gap, decoy = profile[cid]["gap"], profile[cid]["decoy"]
        emps = employees[employees["client_id"] == cid]
        offs = offices[offices["client_id"] == cid].reset_index(drop=True)
        if gap:
            if gap == "qr_no_scanners":
                affected_offices = offs.loc[offs["has_qr_scanners"] == 0, "office_id"]
            elif gap == "room_not_synced":
                affected_offices = offs.loc[offs["calendar_synced"] == 0, "office_id"]
            elif gap == "bad_rollout":
                affected_offices = offs["office_id"].iloc[1:]
            else:
                affected_offices = offs["office_id"]
            affected = int(emps["office_id"].isin(affected_offices).sum())
            gaps.append(dict(client_id=cid, client_name=c["name"], gap_type=gap,
                             description=GAP_DESCRIPTIONS[gap], employees_affected=affected))
        if decoy:
            decoys.append(dict(client_id=cid, client_name=c["name"], decoy_type=decoy,
                               note="Look-alike setup that is NOT a planted gap"))
    return {"seed": SEED, "window": [str(START), str(END - timedelta(days=1))],
            "gaps": gaps, "decoys_not_gaps": decoys}


def save_all(tables, ground_truth):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(RAW_DIR / f"{name}.csv", index=False)
    GROUND_TRUTH_PATH.write_text(json.dumps(ground_truth, indent=2, default=str))


def sanity_checks(t, ground_truth):
    clients, config, offices, employees, events, tickets = (
        t["clients"], t["client_config"], t["offices"], t["employees"], t["events"], t["support_tickets"])
    print("\n=== ROW COUNTS ===")
    for name, df in t.items():
        print(f"{name:16s} {len(df):>10,}")

    print("\n=== SANITY CHECKS ===")
    checks = [
        ("clients: ids unique", clients["client_id"].is_unique),
        ("client_config: 40 x 6 rows", len(config) == N_CLIENTS * len(FEATURES)),
        ("offices: ids unique, every client has >=1 office", offices["office_id"].is_unique and set(offices["client_id"]) == set(clients["client_id"])),
        ("employees: 20,000 unique ids", employees["employee_id"].is_unique and len(employees) == N_EMPLOYEES),
        ("employees: office belongs to same client", (employees.merge(offices, on="office_id", suffixes=("", "_o"))["client_id"] == employees.merge(offices, on="office_id", suffixes=("", "_o"))["client_id_o"]).all()),
        ("events: ids unique", events["event_id"].is_unique),
        ("events: all employee_ids exist", events["employee_id"].isin(employees["employee_id"]).all()),
        ("events: only enabled features", len(events[["client_id", "feature"]].drop_duplicates().merge(config[config["enabled"] == 1][["client_id", "feature"]], how="left", indicator=True).query("_merge == 'left_only'")) == 0),
        ("events: no nulls", not events.isnull().any().any()),
        ("tickets: ids unique", tickets["ticket_id"].is_unique),
        ("tickets: resolved_at never before created_at", (tickets["resolved_at"].isna() | (tickets["resolved_at"] >= tickets["created_at"])).all()),
        ("ground truth: 10 gaps planted", len(ground_truth["gaps"]) == 10),
    ]
    for label, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")

    ts = pd.to_datetime(events["ts"])
    print(f"\nEvent time range: {ts.min()}  ->  {ts.max()}")
    weekend_share = (ts.dt.weekday >= 5).mean()
    print(f"Weekend share of events: {weekend_share:.1%}  (expect small: hybrid offices are quiet on weekends)")
    print("\nEvents per feature:")
    print(events["feature"].value_counts().to_string())
    print("\nEvents per action:")
    print(events["action"].value_counts().to_string())
    print("\nEvents per month (note Diwali Oct / Christmas Dec dips):")
    print(ts.dt.to_period("M").value_counts().sort_index().to_string())
    print(f"\nFeatures enabled per client (avg): {config.groupby('client_id')['enabled'].sum().mean():.2f} of 6")
    print(f"Offices total: {len(offices)}")
    print("\nTickets by category:")
    print(tickets["category"].value_counts().to_string())


def main():
    rng = np.random.default_rng(SEED)
    Faker.seed(SEED)
    fake = Faker("en_IN")

    clients = make_clients(rng, fake)
    profile = plan_gaps_and_decoys(rng, clients)
    config = make_client_config(rng, clients, profile)
    offices, employees = make_offices_and_employees(rng, clients, config, profile)
    events = make_events(rng, clients, config, offices, employees, profile)
    tickets = make_tickets(rng, clients, config, profile)
    ground_truth = build_ground_truth(clients, offices, employees, profile)

    tables = {
        "clients": clients.drop(columns=["n_employees", "n_offices"]),
        "client_config": config,
        "offices": offices,
        "employees": employees,
        "events": events,
        "support_tickets": tickets,
    }
    save_all(tables, ground_truth)
    sanity_checks(tables, ground_truth)


if __name__ == "__main__":
    main()
