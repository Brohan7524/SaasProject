"""
gap_detector.py  -  finds implementation gaps in client setups using 6 plain rules.

Each rule looks at CONFIG (how the client is set up) and USAGE (what employees actually do):
    1. qr_no_scanners       QR enabled, no scanners at most offices, check-ins collapse after month 1
    2. room_not_synced      rooms not synced to calendar at most offices, and no-shows far above normal
    3. strict_policy        attendance policy caps days at <= 2/week, and desk views rarely become bookings
    4. bad_rollout          a feature is switched on in only a small share of a multi-office client's offices
    5. parking_zero_spots   parking enabled but zero spots configured at most offices
    6. silent_churn         usage fell by more than half in the last 3 months (after removing the
                            seasonal dip every client has) and support tickets are rising

Output:  outputs/gap_report.csv  (one row per flagged client + gap type)

IMPORTANT: the rules never read data/ground_truth.json. Only the evaluation step at the bottom
does, AFTER the report is written. All thresholds below were fixed before the first run and
have not been changed since.
"""
import json
from pathlib import Path

import pandas as pd

RAW = Path("data/raw")
OUT = Path("outputs")
GROUND_TRUTH = Path("data/ground_truth.json")

LAST_DAY = pd.Timestamp("2025-12-31")
USE_ACTIONS = ("book", "check_in")      # what counts as real use (same definition as the SQL files)

# ---- Thresholds (see comments for the reasoning) ----
MAJORITY = 0.5              # "most offices" = at least half
QR_REPEAT_RATIO_MAX = 0.5   # QR: later usage below half of month-1 usage = collapse
ROOM_NOSHOW_X_MEDIAN = 2.0  # rooms: no-show rate at least 2x the portfolio median
POLICY_CAP_MAX = 2          # policy: cap of 2 days/week or less is "strict"
POLICY_CONVERSION_X_MEDIAN = 0.5  # desk view->book rate below half the portfolio median
ROLLOUT_SHARE_MAX = 0.25    # rollout: feature on in 25% of offices or fewer ...
ROLLOUT_MIN_OFFICES = 3     # ... for clients with at least 3 offices
CHURN_ADJUSTED_RATIO_MAX = 0.5   # churn: seasonally adjusted usage ratio below 0.5 (a >50% drop)
CHURN_MIN_BASELINE_EVENTS = 200  # ignore clients too small to measure a trend
TICKET_RISE_X = 1.25        # churn: tickets in last 90 days >= 1.25x the previous 90 days
# Churn windows: "now" = last 30 days; "3 months ago" = the 30 days ending 90 days before the end.
NOW_START, NOW_END = "2025-12-02", "2025-12-31"
BASE_START, BASE_END = "2025-09-03", "2025-10-02"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
class Data:
    """All tables the rules need, plus a few handy lookups."""

    def __init__(self):
        self.clients = pd.read_csv(RAW / "clients.csv").set_index("client_id")
        self.config = pd.read_csv(RAW / "client_config.csv")
        self.offices = pd.read_csv(RAW / "offices.csv")
        self.employees = pd.read_csv(RAW / "employees.csv")
        self.tickets = pd.read_csv(RAW / "support_tickets.csv")

        events = pd.read_csv(RAW / "events.csv", usecols=["employee_id", "client_id", "feature", "action", "ts"])
        events["day"] = events["ts"].str[:10]                       # 'YYYY-MM-DD' sorts correctly as text
        office_of = self.employees.set_index("employee_id")["office_id"]
        events["office_id"] = events["employee_id"].map(office_of)
        self.events = events
        # Split once by (client, feature) so each rule can grab a client's events quickly.
        self.events_by = {key: df for key, df in events.groupby(["client_id", "feature"])}

        self.employees_per_office = self.employees.groupby("office_id").size()
        self.employees_per_client = self.employees.groupby("client_id").size()

    def events_for(self, client_id, feature):
        return self.events_by.get((client_id, feature), self.events.iloc[0:0])

    def enabled_rows(self, feature):
        cfg = self.config[(self.config["feature"] == feature) & (self.config["enabled"] == 1)]
        return cfg.itertuples(index=False)

    def offices_of(self, client_id):
        return self.offices[self.offices["client_id"] == client_id].sort_values("office_id")

    def employees_in(self, office_ids):
        return int(self.employees_per_office.reindex(list(office_ids)).fillna(0).sum())


class Finding:
    """One rule's verdict for one client. `fired` False rows are kept so misses can be explained."""

    def __init__(self, client_id, gap_type, fired, evidence, employees_affected=0, suggested_fix="", feature=""):
        self.client_id = client_id
        self.gap_type = gap_type
        self.fired = fired
        self.evidence = evidence
        self.employees_affected = employees_affected
        self.suggested_fix = suggested_fix
        self.feature = feature


def rate(numerator, denominator):
    """Safe division: returns None when there is nothing to divide by."""
    return None if denominator == 0 else numerator / denominator


def fmt(x, digits=2):
    return "n/a" if x is None else f"{x:.{digits}f}"


# --------------------------------------------------------------------------
# Rule 1: QR check-in enabled but no scanners
# --------------------------------------------------------------------------
def rule_qr_no_scanners(d):
    findings = []
    for cfg in d.enabled_rows("QR Check-in"):
        offices = d.offices_of(cfg.client_id)
        no_scanner = offices[offices["has_qr_scanners"] == 0]
        share = len(no_scanner) / len(offices)

        # Usage: QR check-ins in month 1 vs the later 30-day rate.
        ev = d.events_for(cfg.client_id, "QR Check-in")
        ev = ev[ev["action"] == "check_in"]
        month1_end = (pd.Timestamp(cfg.enabled_date) + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        month1 = int(((ev["day"] >= cfg.enabled_date) & (ev["day"] < month1_end)).sum())
        later = int((ev["day"] >= month1_end).sum())
        days_after = (LAST_DAY - pd.Timestamp(month1_end)).days + 1
        later_per_30d = later * 30 / days_after
        ratio = rate(later_per_30d, month1)

        fired = share >= MAJORITY and (ratio is not None and ratio < QR_REPEAT_RATIO_MAX)
        evidence = (f"no QR scanners at {len(no_scanner)} of {len(offices)} offices; check-ins {month1} in month 1 "
                    f"vs {later_per_30d:.0f} per 30 days after (ratio {fmt(ratio)})")
        fix = (f"Install QR scanners at {len(no_scanner)} offices or switch to geofenced check-in")
        findings.append(Finding(cfg.client_id, "qr_no_scanners", fired, evidence,
                                d.employees_in(no_scanner["office_id"]), fix, "QR Check-in"))
    return findings


# --------------------------------------------------------------------------
# Rule 2: meeting rooms not synced to the calendar
# --------------------------------------------------------------------------
def room_noshow_rate(events):
    """No-shows as a share of bookings for Meeting Room events."""
    return rate((events["action"] == "no_show").sum(), (events["action"] == "book").sum())


def rule_room_not_synced(d):
    # Benchmark: median no-show rate across all clients that have rooms on.
    rates = []
    for cfg in d.enabled_rows("Meeting Room Booking"):
        r = room_noshow_rate(d.events_for(cfg.client_id, "Meeting Room Booking"))
        if r is not None:
            rates.append(r)
    median_rate = float(pd.Series(rates).median())

    findings = []
    for cfg in d.enabled_rows("Meeting Room Booking"):
        offices = d.offices_of(cfg.client_id)
        unsynced = offices[offices["calendar_synced"] == 0]
        share = len(unsynced) / len(offices)

        ev = d.events_for(cfg.client_id, "Meeting Room Booking")
        ev_unsynced = ev[ev["office_id"].isin(unsynced["office_id"])]
        noshow = room_noshow_rate(ev_unsynced) if len(unsynced) else None

        fired = (share >= MAJORITY and noshow is not None
                 and noshow >= ROOM_NOSHOW_X_MEDIAN * median_rate)
        evidence = (f"calendar not synced at {len(unsynced)} of {len(offices)} offices; room no-show rate there "
                    f"{fmt(noshow)} vs portfolio median {fmt(median_rate)}")
        fix = f"Enable calendar sync for {len(unsynced)} offices (and auto-release rooms when a meeting is declined)"
        findings.append(Finding(cfg.client_id, "room_not_synced", fired, evidence,
                                d.employees_in(unsynced["office_id"]), fix, "Meeting Room Booking"))
    return findings


# --------------------------------------------------------------------------
# Rule 3: over-strict attendance policy
# --------------------------------------------------------------------------
def desk_conversion(events):
    """Share of desk 'view' sessions that became a booking."""
    return rate((events["action"] == "book").sum(), (events["action"] == "view").sum())


def rule_strict_policy(d):
    conv = []
    for cfg in d.enabled_rows("Desk Booking"):
        c = desk_conversion(d.events_for(cfg.client_id, "Desk Booking"))
        if c is not None:
            conv.append(c)
    median_conv = float(pd.Series(conv).median())

    findings = []
    for cfg in d.enabled_rows("Attendance Policy"):
        cap = int(cfg.policy_max_days_per_week)
        c = desk_conversion(d.events_for(cfg.client_id, "Desk Booking"))
        strict = cap <= POLICY_CAP_MAX
        low_conversion = c is not None and c < POLICY_CONVERSION_X_MEDIAN * median_conv
        fired = strict and low_conversion
        evidence = (f"policy caps office days at {cap}/week; only {fmt(c)} of desk views become bookings "
                    f"(portfolio median {fmt(median_conv)})")
        fix = f"Raise the cap from {cap} to 3 days/week or allow manager exceptions; review the policy with the client"
        findings.append(Finding(cfg.client_id, "strict_policy", fired, evidence,
                                int(d.employees_per_client[cfg.client_id]), fix, "Attendance Policy"))
    return findings


# --------------------------------------------------------------------------
# Rule 4: bad rollout (feature on in too few offices)
# --------------------------------------------------------------------------
def rule_bad_rollout(d):
    findings = []
    enabled = d.config[d.config["enabled"] == 1]
    for cfg in enabled.itertuples(index=False):
        offices = d.offices_of(cfg.client_id)
        n_off = len(offices)
        share = cfg.offices_enabled / n_off
        fired = n_off >= ROLLOUT_MIN_OFFICES and share <= ROLLOUT_SHARE_MAX
        missing = offices.iloc[cfg.offices_enabled:]          # features are on in the first N offices
        evidence = f"{cfg.feature} enabled in {cfg.offices_enabled} of {n_off} offices ({share:.0%})"
        fix = (f"Roll out {cfg.feature} to the remaining {len(missing)} offices; "
               f"start with the largest ones")
        findings.append(Finding(cfg.client_id, "bad_rollout", fired, evidence,
                                d.employees_in(missing["office_id"]), fix, cfg.feature))
    return findings


# --------------------------------------------------------------------------
# Rule 5: parking enabled, zero spots configured
# --------------------------------------------------------------------------
def rule_parking_zero_spots(d):
    findings = []
    for cfg in d.enabled_rows("Parking"):
        offices = d.offices_of(cfg.client_id).iloc[: cfg.offices_enabled]   # offices where parking is on
        zero = offices[offices["parking_spots"] == 0]
        share = len(zero) / len(offices)

        ev = d.events_for(cfg.client_id, "Parking")
        conversion = desk_conversion(ev)       # book/view works for any bookable feature

        fired = share >= MAJORITY
        evidence = (f"parking enabled but 0 spots configured at {len(zero)} of {len(offices)} offices; "
                    f"only {fmt(conversion)} of parking views become bookings")
        fix = f"Configure parking spots for {len(zero)} offices, or turn Parking off there so employees stop seeing it"
        findings.append(Finding(cfg.client_id, "parking_zero_spots", fired, evidence,
                                d.employees_in(zero["office_id"]), fix, "Parking"))
    return findings


# --------------------------------------------------------------------------
# Rule 6: silent churn
# --------------------------------------------------------------------------
def rule_silent_churn(d):
    use = d.events[d.events["action"].isin(USE_ACTIONS)]
    now = use[(use["day"] >= NOW_START) & (use["day"] <= NOW_END)].groupby("client_id").size()
    base = use[(use["day"] >= BASE_START) & (use["day"] <= BASE_END)].groupby("client_id").size()
    ratios = (now / base).dropna()
    # Every client dips in December (holidays). Divide by the portfolio median to remove that.
    seasonal_median = float(ratios[base.reindex(ratios.index) >= CHURN_MIN_BASELINE_EVENTS].median())

    tickets = d.tickets.copy()
    tickets["day"] = tickets["created_at"].str[:10]
    t_last = tickets[tickets["day"] >= "2025-10-03"].groupby("client_id").size()
    t_prev = tickets[(tickets["day"] >= "2025-07-05") & (tickets["day"] < "2025-10-03")].groupby("client_id").size()

    findings = []
    for client_id in d.clients.index:
        b = int(base.get(client_id, 0))
        n = int(now.get(client_id, 0))
        raw = rate(n, b)
        adjusted = None if raw is None else raw / seasonal_median
        tl, tp = int(t_last.get(client_id, 0)), int(t_prev.get(client_id, 0))
        tickets_rising = tl >= TICKET_RISE_X * max(tp, 1)
        usage_drop = (adjusted is not None and b >= CHURN_MIN_BASELINE_EVENTS
                      and adjusted < CHURN_ADJUSTED_RATIO_MAX)
        fired = usage_drop and tickets_rising
        drop_text = "n/a" if adjusted is None else f"{1 - adjusted:.0%}"
        evidence = (f"usage {b} -> {n} events (30 days vs 3 months earlier); after removing the portfolio-wide "
                    f"seasonal dip ({seasonal_median:.2f}x) that is a {drop_text} drop; "
                    f"tickets {tp} -> {tl} (previous vs last 90 days)")
        fix = ("Customer-success call this week: review recent tickets, run a re-training session, "
               "and check for changes such as a policy update or office closure")
        findings.append(Finding(client_id, "silent_churn", fired, evidence,
                                int(d.employees_per_client[client_id]), fix, "All features"))
    return findings


RULES = [rule_qr_no_scanners, rule_room_not_synced, rule_strict_policy,
         rule_bad_rollout, rule_parking_zero_spots, rule_silent_churn]


def run_rules(d):
    """Run every rule; return all findings (fired or not)."""
    findings = []
    for rule in RULES:
        findings.extend(rule(d))
    return findings


def write_report(d, findings):
    rows = []
    for f in findings:
        if f.fired:
            rows.append(dict(client_id=f.client_id, client_name=d.clients.loc[f.client_id, "name"],
                             gap_type=f.gap_type, feature=f.feature, evidence=f.evidence,
                             employees_affected=f.employees_affected, suggested_fix=f.suggested_fix))
    report = pd.DataFrame(rows, columns=["client_id", "client_name", "gap_type", "feature", "evidence",
                                         "employees_affected", "suggested_fix"])
    report = report.sort_values(["gap_type", "client_id"]).reset_index(drop=True)
    OUT.mkdir(exist_ok=True)
    report.to_csv(OUT / "gap_report.csv", index=False)
    return report


# --------------------------------------------------------------------------
# Evaluation against ground truth (the ONLY place ground_truth.json is read)
# --------------------------------------------------------------------------
def evaluate(report, findings):
    truth = json.loads(GROUND_TRUTH.read_text())
    planted = {(g["client_id"], g["gap_type"]): g for g in truth["gaps"]}
    decoys = {x["client_id"]: x["decoy_type"] for x in truth["decoys_not_gaps"]}
    detected = {(r.client_id, r.gap_type): r for r in report.itertuples(index=False)}
    all_findings = {(f.client_id, f.gap_type): f for f in findings}      # includes non-fired, for miss reasons

    tp = sorted(set(planted) & set(detected))
    fp = sorted(set(detected) - set(planted))
    fn = sorted(set(planted) - set(detected))

    precision = len(tp) / len(detected) if detected else float("nan")
    recall = len(tp) / len(planted)

    print("\n" + "=" * 70)
    print("EVALUATION vs ground_truth.json  (unit = client + gap type)")
    print("=" * 70)
    print(f"Planted gaps: {len(planted)}   Detected: {len(detected)}")
    print(f"True positives: {len(tp)}   False positives: {len(fp)}   Misses: {len(fn)}")
    print(f"Precision = {len(tp)}/{len(detected)} = {precision:.1%}")
    print(f"Recall    = {len(tp)}/{len(planted)} = {recall:.1%}")

    print("\nPer gap type:")
    for gap_type in sorted({k[1] for k in planted} | {k[1] for k in detected}):
        p = sum(1 for k in planted if k[1] == gap_type)
        t = sum(1 for k in tp if k[1] == gap_type)
        dd = sum(1 for k in detected if k[1] == gap_type)
        print(f"  {gap_type:20s} planted {p}  detected {dd}  correct {t}")

    print("\nFalse positives (flagged but not planted):")
    for key in fp:
        note = f"look-alike decoy ({decoys[key[0]]})" if key[0] in decoys else "not a planted gap or listed decoy"
        print(f"  {key[0]} {key[1]}: {note}\n      evidence: {detected[key].evidence}")
    if not fp:
        print("  none")

    print("\nMisses (planted but not flagged):")
    for key in fn:
        f = all_findings.get(key)
        why = f.evidence if f else "rule did not evaluate this client (precondition not met)"
        print(f"  {key[0]} {key[1]}\n      rule saw: {why}")
    if not fn:
        print("  none")

    # Save the detail for the README.
    rows = [dict(client_id=k[0], gap_type=k[1], result="true_positive") for k in tp]
    rows += [dict(client_id=k[0], gap_type=k[1], result="false_positive") for k in fp]
    rows += [dict(client_id=k[0], gap_type=k[1], result="miss") for k in fn]
    pd.DataFrame(rows).to_csv(OUT / "gap_evaluation.csv", index=False)
    return precision, recall


def main():
    data = Data()
    findings = run_rules(data)
    report = write_report(data, findings)

    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 140)
    print(f"Gap report: {len(report)} findings across {report['client_id'].nunique()} clients -> outputs/gap_report.csv\n")
    print(report[["client_id", "gap_type", "feature", "employees_affected", "evidence"]].to_string(index=False))

    evaluate(report, findings)
    print(f"\nN (distinct clients flagged by the detector) = {report['client_id'].nunique()}")


if __name__ == "__main__":
    main()
