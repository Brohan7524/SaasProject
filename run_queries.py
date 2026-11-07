"""
run_queries.py  -  runs every file in sql/ against data/workplace.db and saves the
results to outputs/*.csv, then prints the headline numbers.

SQL file format:
  * A file with no markers is one query; its result is saved as outputs/<file>.csv
  * A file may contain lines like   -- @result some_name
    Text BEFORE the first marker is "setup" (e.g. CREATE TEMP TABLE) and is just executed.
    Each marker starts a query whose result is saved as outputs/<file>__some_name.csv
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path("data/workplace.db")
SQL_DIR = Path("sql")
OUT_DIR = Path("outputs")
MARKER = re.compile(r"^-- @result\s+(\w+)\s*$", re.MULTILINE)


def split_sql_file(text):
    """Return (setup_sql, [(result_name, query_sql), ...]). result_name None = single query."""
    parts = MARKER.split(text)
    if len(parts) == 1:
        return "", [(None, text)]
    setup = parts[0]
    queries = list(zip(parts[1::2], parts[2::2]))
    return setup, queries


def run_file(conn, path):
    """Run one SQL file; return {output_name: DataFrame}."""
    setup, queries = split_sql_file(path.read_text(encoding="utf-8"))
    if setup.strip():
        conn.executescript(setup)
    results = {}
    for name, sql in queries:
        df = pd.read_sql_query(sql, conn)
        out_name = path.stem if name is None else f"{path.stem}__{name}"
        df.to_csv(OUT_DIR / f"{out_name}.csv", index=False)
        results[out_name] = df
        print(f"  saved outputs/{out_name}.csv  ({len(df)} rows)")
    return results


def print_headlines(r):
    """Print the numbers worth looking at first. All values come straight from the query results."""
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)

    if "01_adoption_funnel__by_feature" in r:
        print("\n=== 01  Adoption funnel by feature (employee-weighted) ===")
        print(r["01_adoption_funnel__by_feature"].to_string(index=False))
        print("\n=== 01  QR repeat-use by client (lowest ratio first) ===")
        cols = ["client_id", "enabled_date", "month1_checkins", "later_per_30d", "repeat_ratio", "no_repeat_use"]
        print(r["01_adoption_funnel__qr_repeat_by_client"][cols].to_string(index=False))
        print("\n=== 01  Headline X: QR-enabled clients with no repeat use after month 1 ===")
        print(r["01_adoption_funnel__qr_headline"].to_string(index=False))

    if "02_cohort_retention__all_features" in r:
        print("\n=== 02  Cohort retention (any booking): % still booking N months after first booking ===")
        c = r["02_cohort_retention__all_features"]
        grid = c.pivot(index="cohort_month", columns="month_n", values="retention_pct")
        grid.insert(0, "cohort_size", c[c["month_n"] == 0].set_index("cohort_month")["cohort_size"])
        keep = [col for col in grid.columns if col in ("cohort_size", 1, 2, 3, 6)]
        print(grid[keep].to_string())

    if "03_dau_wau_mau__by_feature_month" in r:
        print("\n=== 03  Stickiness by feature, Sep 2025 vs Nov 2025 ===")
        s = r["03_dau_wau_mau__by_feature_month"]
        s = s[s["month"].isin(["2025-09", "2025-11"])]
        print(s.pivot(index="feature", columns="month", values=["avg_dau", "mau", "dau_mau"]).to_string())

    if "04_feature_matrix__by_feature" in r:
        print("\n=== 04  Feature enablement and adoption (last 90 days, % of all employees) ===")
        print(r["04_feature_matrix__by_feature"].to_string(index=False))
        print("\n=== 04  Client x feature matrix (adoption % of employees; blank = not enabled) ===")
        print(r["04_feature_matrix__matrix_wide"].drop(columns=["client_name"]).to_string(index=False))

    if "05_why_not__low_vs_rest_by_feature" in r:
        print("\n=== 05  Low adopters (lowest quartile per feature) vs the rest ===")
        print(r["05_why_not__low_vs_rest_by_feature"].to_string(index=False))
        print("\n=== 05  Ticket mix, % of tickets ===")
        print(r["05_why_not__ticket_mix_low_vs_rest"].to_string(index=False))

    if "06_client_health__band_summary" in r:
        print("\n=== 06  Client health bands ===")
        print(r["06_client_health__band_summary"].to_string(index=False))
        print("\n=== 06  Ten lowest health scores ===")
        cols = ["client_id", "total_employees", "breadth_score", "depth_score", "trend_score",
                "ticket_load_score", "health_score", "health_band", "weakest_component"]
        print(r["06_client_health__client_health"][cols].head(10).to_string(index=False))


def main():
    OUT_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    all_results = {}
    for path in sorted(SQL_DIR.glob("*.sql")):
        print(f"running {path}")
        all_results.update(run_file(conn, path))
    conn.close()
    print_headlines(all_results)


if __name__ == "__main__":
    main()
