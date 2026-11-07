"""
export_excel.py  -  builds the Excel tracker and the tidy CSVs for Power BI.

Run AFTER run_queries.py and gap_detector.py (it reads their CSV outputs in outputs/).

Creates:
    outputs/client_adoption_tracker.xlsx
        Feature Matrix  - client x feature adoption %, colour-scaled heat map
        Health Score    - score, band and the four components per client
        Gap Report      - detected gaps with evidence and suggested fix
        Notes           - definitions
    outputs/powerbi/*.csv    - tidy tables (one fact/dimension per file) + README.md

Note on "pivot": openpyxl cannot create real PivotTables. The Feature Matrix sheet is the
already-pivoted client x feature grid, with conditional formatting. The long-format table
(outputs/powerbi/fact_feature_adoption.csv) can be pivoted in Excel or Power BI in two clicks.
"""
from pathlib import Path

import pandas as pd
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path("outputs")
PBI = OUT / "powerbi"
RAW = Path("data/raw")
XLSX = OUT / "client_adoption_tracker.xlsx"

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
THIN = Side(style="thin", color="D9D9D9")

FEATURE_COLUMNS = {                       # wide-matrix column -> nicer header
    "desk_booking": "Desk Booking", "meeting_room": "Meeting Room", "parking": "Parking",
    "qr_checkin": "QR Check-in", "attendance_policy": "Attendance Policy", "visitor_mgmt": "Visitor Mgmt",
}


def read(name):
    return pd.read_csv(OUT / name)


# --------------------------------------------------------------------------
# Excel helpers
# --------------------------------------------------------------------------
def style_header(ws, n_cols):
    for col in range(1, n_cols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "C2"                # keep header row and the first two columns visible
    ws.auto_filter.ref = ws.dimensions


def set_widths(ws, widths):
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def add_borders(ws):
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# --------------------------------------------------------------------------
# Sheets
# --------------------------------------------------------------------------
def build_feature_matrix(writer, gaps):
    wide = read("04_feature_matrix__matrix_wide.csv")
    gaps_per_client = gaps.groupby("client_id").size()
    wide["gaps_flagged"] = wide["client_id"].map(gaps_per_client).fillna(0).astype(int)
    wide = wide.rename(columns={"client_id": "Client", "client_name": "Name", "region": "Region",
                                "plan": "Plan", "gaps_flagged": "Gaps flagged", **FEATURE_COLUMNS})
    wide.to_excel(writer, sheet_name="Feature Matrix", index=False)
    ws = writer.sheets["Feature Matrix"]
    style_header(ws, wide.shape[1])
    set_widths(ws, [9, 28, 9, 12, 13, 13, 11, 13, 16, 13, 12])
    last = ws.max_row

    first_feature_col = 5
    for col in range(first_feature_col, first_feature_col + len(FEATURE_COLUMNS)):
        letter = get_column_letter(col)
        rng = f"{letter}2:{letter}{last}"
        for row in range(2, last + 1):
            ws[f"{letter}{row}"].number_format = '0.0"%"'
            ws[f"{letter}{row}"].alignment = Alignment(horizontal="center")
        # One colour scale PER feature column: red = lowest, yellow = median, green = highest
        # among clients using that feature. Blank cells (feature not enabled) stay uncoloured.
        ws.conditional_formatting.add(rng, ColorScaleRule(
            start_type="min", start_color="F8696B",
            mid_type="percentile", mid_value=50, mid_color="FFEB84",
            end_type="max", end_color="63BE7B"))

    # Highlight clients that have at least one gap.
    gap_col = get_column_letter(first_feature_col + len(FEATURE_COLUMNS))
    ws.conditional_formatting.add(f"{gap_col}2:{gap_col}{last}", FormulaRule(
        formula=[f"{gap_col}2>0"], fill=PatternFill("solid", bgColor="F4B084"), font=Font(bold=True)))

    note_row = last + 2
    ws[f"A{note_row}"] = ("Values = % of all the client's employees with a booking or check-in in the last 90 days "
                          "(2025-10-03 to 2025-12-31). Colour scale is per column: compare clients within a feature. "
                          "Blank = feature not enabled.")
    ws[f"A{note_row}"].font = Font(italic=True, color="595959")
    add_borders_to_table(ws, last)


def add_borders_to_table(ws, last_row):
    for row in ws.iter_rows(min_row=1, max_row=last_row, max_col=ws.max_column):
        for cell in row:
            cell.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def build_health_sheet(writer, gaps):
    health = read("06_client_health__client_health.csv")
    health["gaps_flagged"] = health["client_id"].map(gaps.groupby("client_id").size()).fillna(0).astype(int)
    health = health.sort_values("health_score").reset_index(drop=True)
    columns = ["client_id", "client_name", "region", "plan", "total_employees", "health_score", "health_band",
               "weakest_component", "breadth_score", "depth_score", "trend_score", "ticket_load_score",
               "features_enabled", "features_in_use", "tickets_last_90d", "gaps_flagged"]
    health = health[columns]
    health.columns = ["Client", "Name", "Region", "Plan", "Employees", "Health score", "Band",
                      "Weakest component", "Breadth", "Depth", "Trend", "Ticket load",
                      "Features enabled", "Features in use", "Tickets (90d)", "Gaps flagged"]
    health.to_excel(writer, sheet_name="Health Score", index=False)
    ws = writer.sheets["Health Score"]
    style_header(ws, health.shape[1])
    set_widths(ws, [9, 28, 9, 12, 11, 11, 9, 16, 9, 9, 9, 11, 10, 10, 10, 9])
    last = ws.max_row

    # Band colours.
    for band, color in (("Green", "C6EFCE"), ("Amber", "FFEB9C"), ("Red", "FFC7CE")):
        ws.conditional_formatting.add(f"G2:G{last}", FormulaRule(
            formula=[f'$G2="{band}"'], fill=PatternFill("solid", bgColor=color), font=Font(bold=True)))
    # Data bar on the score itself.
    ws.conditional_formatting.add(f"F2:F{last}", DataBarRule(
        start_type="num", start_value=0, end_type="num", end_value=100, color="5B9BD5"))
    add_borders_to_table(ws, last)

    note_row = last + 2
    ws[f"A{note_row}"] = ("Score = 0.30 x Breadth + 0.30 x Depth + 0.25 x Trend + 0.15 x (100 - Ticket load). "
                          "Bands: Green >= 65, Amber 55 to < 65, Red < 55. Sorted worst first.")
    ws[f"A{note_row}"].font = Font(italic=True, color="595959")


def build_gap_sheet(writer, gaps):
    sheet = gaps[["client_id", "client_name", "gap_type", "feature", "employees_affected", "evidence", "suggested_fix"]]
    sheet = sheet.sort_values("employees_affected", ascending=False)
    sheet.columns = ["Client", "Name", "Gap type", "Feature", "Employees affected", "Evidence", "Suggested fix"]
    sheet.to_excel(writer, sheet_name="Gap Report", index=False)
    ws = writer.sheets["Gap Report"]
    style_header(ws, sheet.shape[1])
    set_widths(ws, [9, 28, 20, 20, 12, 70, 60])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.conditional_formatting.add(f"E2:E{ws.max_row}", DataBarRule(
        start_type="num", start_value=0, end_type="max", color="F4B084"))
    add_borders_to_table(ws, ws.max_row)


def build_notes_sheet(writer):
    notes = pd.DataFrame({"Item": [
        "Dataset", "Use (adoption)", "Adoption %", "Health score", "Gap report", "How to refresh"], "Meaning": [
        "SYNTHETIC data (seed 42) with ~10 implementation gaps planted on purpose. Not real client data.",
        "A 'use' is a book or check_in event. A view alone is not adoption.",
        "Employees active in the last 90 days / all client employees.",
        "Weighted breadth, depth, trend and ticket load. See DECISIONS.md.",
        "Rule-based detector: each rule combines config and usage signals. Evaluated against the planted ground truth in the README.",
        "python generate_data.py; python load_db.py; python run_queries.py; python gap_detector.py; python export_excel.py"]})
    notes.to_excel(writer, sheet_name="Notes", index=False)
    ws = writer.sheets["Notes"]
    style_header(ws, 2)
    ws.freeze_panes = "A2"
    set_widths(ws, [20, 110])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def write_excel(gaps):
    with pd.ExcelWriter(XLSX, engine="openpyxl") as writer:
        build_feature_matrix(writer, gaps)
        build_health_sheet(writer, gaps)
        build_gap_sheet(writer, gaps)
        build_notes_sheet(writer)
    print(f"wrote {XLSX}")


# --------------------------------------------------------------------------
# Power BI tables
# --------------------------------------------------------------------------
def month_to_date(df, column="month"):
    """Power BI handles real dates better than 'YYYY-MM' text; use the first day of the month."""
    df[column] = pd.to_datetime(df[column] + "-01").dt.strftime("%Y-%m-%d")
    return df


def write_powerbi(gaps):
    PBI.mkdir(parents=True, exist_ok=True)
    clients = pd.read_csv(RAW / "clients.csv")
    health = read("06_client_health__client_health.csv")
    n_offices = pd.read_csv(RAW / "offices.csv").groupby("client_id").size().rename("offices")
    gap_counts = gaps.groupby("client_id").size().rename("gaps_flagged")
    employees_at_risk = gaps.groupby("client_id")["employees_affected"].max().rename("max_employees_affected")

    # ---- Dimensions ----
    dim_clients = (clients.merge(health[["client_id", "total_employees", "health_score", "health_band",
                                         "weakest_component", "breadth_score", "depth_score", "trend_score",
                                         "ticket_load_score", "features_enabled", "features_in_use"]], on="client_id")
                   .merge(n_offices, on="client_id", how="left")
                   .merge(gap_counts, on="client_id", how="left")
                   .merge(employees_at_risk, on="client_id", how="left"))
    dim_clients["gaps_flagged"] = dim_clients["gaps_flagged"].fillna(0).astype(int)
    dim_clients["max_employees_affected"] = dim_clients["max_employees_affected"].fillna(0).astype(int)
    dim_clients = dim_clients.rename(columns={"name": "client_name"})
    dim_clients.to_csv(PBI / "dim_clients.csv", index=False)

    features = ["Desk Booking", "Meeting Room Booking", "Parking", "QR Check-in", "Attendance Policy", "Visitor Management"]
    pd.DataFrame({"feature": features, "sort_order": range(1, 7)}).to_csv(PBI / "dim_feature.csv", index=False)

    # ---- Facts ----
    matrix = read("04_feature_matrix__client_feature.csv")
    matrix = matrix[["client_id", "feature", "enabled", "offices_enabled", "total_offices", "total_employees",
                     "eligible_employees", "active_employees", "adoption_pct_of_employees",
                     "adoption_pct_of_eligible", "coverage_pct"]]
    matrix.to_csv(PBI / "fact_feature_adoption.csv", index=False)

    funnel = read("01_adoption_funnel__client_feature.csv").drop(columns=["client_name"])
    funnel.to_csv(PBI / "fact_funnel.csv", index=False)

    monthly = month_to_date(read("07_client_monthly_usage.csv"))
    monthly.to_csv(PBI / "fact_client_monthly_usage.csv", index=False)

    portfolio = month_to_date(read("03_dau_wau_mau__by_feature_month.csv"))
    portfolio.to_csv(PBI / "fact_feature_stickiness_monthly.csv", index=False)

    cohorts = read("02_cohort_retention__all_features.csv")
    cohorts = month_to_date(cohorts, "cohort_month")
    cohorts.to_csv(PBI / "fact_cohort_retention.csv", index=False)

    why_not = read("05_why_not__all_enabled.csv").drop(columns=["client_name"])
    why_not.to_csv(PBI / "fact_why_not.csv", index=False)

    gap_facts = gaps.drop(columns=["client_name"])
    gap_facts.to_csv(PBI / "fact_gaps.csv", index=False)

    tickets = pd.read_csv(RAW / "support_tickets.csv")
    tickets["month"] = tickets["created_at"].str[:7]
    tickets_monthly = (tickets.groupby(["client_id", "feature", "category", "month"]).size()
                       .rename("tickets").reset_index())
    tickets_monthly = month_to_date(tickets_monthly)
    tickets_monthly.to_csv(PBI / "fact_tickets_monthly.csv", index=False)

    write_powerbi_readme()
    print(f"wrote {len(list(PBI.glob('*.csv')))} CSVs to {PBI}/")


def write_powerbi_readme():
    (PBI / "README.md").write_text("""# Power BI tables

SYNTHETIC data. Import every CSV in this folder (Get Data > Text/CSV, or Get Data > Folder).
Set `client_id` to Text, `*month*` columns to Date, percentages to Decimal Number.

## Model (star schema)
- `dim_clients` (1 row per client) -> one-to-many to every fact table on `client_id`
- `dim_feature` (1 row per feature) -> one-to-many to every fact table that has `feature`, on `feature`
  (`fact_feature_stickiness_monthly`, `fact_feature_adoption`, `fact_funnel`, `fact_client_monthly_usage`,
  `fact_why_not`, `fact_tickets_monthly`, `fact_gaps`)
- `fact_cohort_retention` has no client key: it is portfolio-level.
- Set `dim_feature[feature]` "Sort by column" = `sort_order`.
- Set `dim_clients[health_band]` sort order manually: Green, Amber, Red.

## Suggested pages
1. **Portfolio overview:** cards (clients, employees, % Green/Amber/Red), donut of `health_band`,
   line chart of `fact_feature_stickiness_monthly[mau]` by `month` and `feature`.
2. **Feature heat map and funnel:** matrix visual with `client_name` on rows, `feature` on columns,
   `adoption_pct_of_employees` as values with a colour scale (Format > Cell elements > Background colour).
   Funnel visual from `fact_funnel`: eligible_employees, employees_ever_used, employees_habitual.
3. **Client drill-down:** slicer on `client_name`; table from `fact_gaps` (gap_type, evidence,
   employees_affected, suggested_fix); line chart of `fact_client_monthly_usage[active_employees]`;
   stacked bar of `fact_tickets_monthly[tickets]` by `category`.

## Handy measures
```
Employees = SUM(dim_clients[total_employees])
Pct Green = DIVIDE(CALCULATE(COUNTROWS(dim_clients), dim_clients[health_band] = "Green"), COUNTROWS(dim_clients))
Employees Affected By Gaps = SUM(fact_gaps[employees_affected])
View To Book = DIVIDE(SUM(fact_client_monthly_usage[bookings]), SUM(fact_client_monthly_usage[views]))
```
Note: `fact_gaps[employees_affected]` can count the same employee more than once if a client has several gaps.
""", encoding="utf-8")


def main():
    gaps = read("gap_report.csv")
    write_excel(gaps)
    write_powerbi(gaps)


if __name__ == "__main__":
    main()
