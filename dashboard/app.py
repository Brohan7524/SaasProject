"""
dashboard/app.py  -  Streamlit fallback dashboard (Power BI is built separately from the same CSVs).

Run from the repo root:   streamlit run dashboard/app.py

Needs outputs/powerbi/*.csv, so run these first:
    python run_queries.py && python gap_detector.py && python export_excel.py

Three pages:
    1. Portfolio overview
    2. Feature heat map + funnels
    3. Client drill-down (gaps and suggested fixes)

SYNTHETIC data with planted gaps. See README.md.
"""
import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent.parent / "outputs" / "powerbi"

FEATURE_ORDER = ["Desk Booking", "Meeting Room Booking", "Parking",
                 "QR Check-in", "Attendance Policy", "Visitor Management"]
# Status colours. Always shown together with the band name, never colour alone.
BAND_COLORS = {"Green": "#2f9e44", "Amber": "#e8a317", "Red": "#d1453b"}
BLUE = "#2a78d6"
# Light-to-mid blue ramp for the heat map: kept light enough that dark cell labels stay readable.
HEAT_SCALE = ["#e8f1fc", "#b7d3f6", "#86b6ef", "#5598e7"]
GAP_NAMES = {
    "qr_no_scanners": "QR check-in enabled, no scanners",
    "room_not_synced": "Meeting rooms not synced to calendar",
    "strict_policy": "Over-strict attendance policy",
    "bad_rollout": "Bad rollout (feature in too few offices)",
    "parking_zero_spots": "Parking enabled, zero spots",
    "silent_churn": "Silent churn",
}


# --------------------------------------------------------------------------
# Streamlit-version compatibility
# --------------------------------------------------------------------------
# Newer Streamlit (1.49+) wants width="stretch"; older versions want use_container_width=True
# and reject the string ("str object cannot be interpreted as an integer"). Pick by version.
def _streamlit_has_stretch_width():
    parts = [int(x) for x in re.findall(r"\d+", st.__version__)[:2]]
    return parts >= [1, 49]


def show_chart(fig):
    if _streamlit_has_stretch_width():
        st.plotly_chart(fig, width="stretch")
    else:
        st.plotly_chart(fig, use_container_width=True)


def show_table(df, **kwargs):
    if _streamlit_has_stretch_width():
        st.dataframe(df, width="stretch", **kwargs)
    else:
        st.dataframe(df, use_container_width=True, **kwargs)


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------
@st.cache_data
def load_tables():
    """Read every Power BI CSV once and keep it in memory."""
    names = ["dim_clients", "fact_feature_adoption", "fact_funnel", "fact_client_monthly_usage",
             "fact_feature_stickiness_monthly", "fact_why_not", "fact_gaps", "fact_tickets_monthly"]
    return {name: pd.read_csv(DATA_DIR / f"{name}.csv") for name in names}


def style(fig, height=380):
    """One consistent, quiet chart style."""
    fig.update_layout(template="plotly_white", height=height, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=-0.3, x=0))
    return fig


# --------------------------------------------------------------------------
# Page 1: portfolio overview
# --------------------------------------------------------------------------
def page_overview(t):
    clients, gaps = t["dim_clients"], t["fact_gaps"]
    st.header("Portfolio overview")

    band_counts = clients["health_band"].value_counts()
    cols = st.columns(5)
    cols[0].metric("Clients", len(clients))
    cols[1].metric("Employees", f"{clients['total_employees'].sum():,}")
    cols[2].metric("Green", int(band_counts.get("Green", 0)))
    cols[3].metric("Amber", int(band_counts.get("Amber", 0)))
    cols[4].metric("Red", int(band_counts.get("Red", 0)))
    st.caption(f"{gaps['client_id'].nunique()} clients have at least one implementation gap flagged by the rules.")

    left, right = st.columns(2)
    with left:
        st.subheader("Clients by health band")
        order = ["Green", "Amber", "Red"]
        counts = clients.groupby("health_band").agg(clients=("client_id", "count"),
                                                    employees=("total_employees", "sum")).reindex(order).reset_index()
        fig = px.bar(counts, x="health_band", y="clients", color="health_band", color_discrete_map=BAND_COLORS,
                     text="clients", hover_data={"employees": True}, labels={"health_band": "", "clients": "Clients"})
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, yaxis_title="Clients")
        show_chart(style(fig))
    with right:
        st.subheader("Top features: reach and depth")
        adoption = t["fact_feature_adoption"]
        enabled = adoption[adoption["enabled"] == 1]
        summary = enabled.groupby("feature").agg(clients_enabled=("client_id", "count"),
                                                 avg_adoption=("adoption_pct_of_employees", "mean")).reset_index()
        summary["avg_adoption"] = summary["avg_adoption"].round(1)
        summary = summary.sort_values("avg_adoption")
        fig = px.bar(summary, x="avg_adoption", y="feature", orientation="h", text="avg_adoption",
                     hover_data={"clients_enabled": True},
                     labels={"avg_adoption": "Avg adoption where enabled (% of employees)", "feature": ""})
        fig.update_traces(marker_color=BLUE, textposition="outside")
        show_chart(style(fig))

    st.subheader("Monthly active employees by feature")
    stick = t["fact_feature_stickiness_monthly"].copy()
    stick["month"] = pd.to_datetime(stick["month"])
    fig = px.line(stick, x="month", y="mau", color="feature", markers=True,
                  category_orders={"feature": FEATURE_ORDER},
                  labels={"mau": "Monthly active employees", "month": "", "feature": "Feature"})
    show_chart(style(fig, 420))
    st.caption("Usage ramps up as clients go live through the first half of the year. "
               "October dips (Diwali, India) and late-December dips (Christmas) are built into the data.")

    st.subheader("Gaps flagged, by type")
    by_type = (gaps.groupby("gap_type").agg(clients=("client_id", "nunique"),
                                            employees_affected=("employees_affected", "sum")).reset_index())
    by_type["gap"] = by_type["gap_type"].map(GAP_NAMES)
    by_type = by_type.sort_values("employees_affected", ascending=False)
    show_table(by_type[["gap", "clients", "employees_affected"]], hide_index=True)


# --------------------------------------------------------------------------
# Page 2: heat map and funnels
# --------------------------------------------------------------------------
def page_heatmap(t):
    st.header("Feature heat map and funnels")
    clients = t["dim_clients"]
    adoption = t["fact_feature_adoption"]

    c1, c2, c3 = st.columns(3)
    regions = c1.multiselect("Region", sorted(clients["region"].unique()), default=sorted(clients["region"].unique()))
    plans = c2.multiselect("Plan", ["Basic", "Pro", "Enterprise"], default=["Basic", "Pro", "Enterprise"])
    scale_mode = c3.radio("Colour scale", ["Absolute %", "Relative within each feature"], horizontal=True)

    keep = clients[clients["region"].isin(regions) & clients["plan"].isin(plans)].sort_values("health_score")
    if keep.empty:
        st.info("No clients match the filters.")
        return

    # Rows = clients (worst health first), columns = features.
    matrix = (adoption[adoption["client_id"].isin(keep["client_id"])]
              .pivot(index="client_id", columns="feature", values="adoption_pct_of_employees")
              .reindex(index=keep["client_id"], columns=FEATURE_ORDER))
    labels = [f"{cid}  {name[:22]}" for cid, name in zip(keep["client_id"], keep["client_name"])]

    # Relative mode: colour by rank within the feature column, but still show the real % in the cell.
    colour_values = matrix.rank(pct=True) if scale_mode.startswith("Relative") else matrix
    fig = go.Figure(go.Heatmap(
        z=colour_values.values, x=FEATURE_ORDER, y=labels, customdata=matrix.values,
        colorscale=HEAT_SCALE, xgap=2, ygap=2, hoverongaps=False,
        texttemplate="%{customdata:.0f}", textfont=dict(size=11, color="#1a1a19"),
        hovertemplate="%{y}<br>%{x}<br>Adoption: %{customdata:.1f}% of employees<extra></extra>",
        colorbar=dict(title="rank" if scale_mode.startswith("Relative") else "%")))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(side="top")
    show_chart(style(fig, max(420, 24 * len(labels) + 120)))
    st.caption("Cell = % of the client's employees with a booking or check-in in the last 90 days. "
               "Blank = feature not enabled. Rows sorted by health score, lowest first.")

    st.subheader("Adoption funnel")
    feature = st.selectbox("Feature", FEATURE_ORDER)
    funnel = t["fact_funnel"]
    funnel = funnel[(funnel["feature"] == feature) & funnel["client_id"].isin(keep["client_id"])]
    if funnel.empty:
        st.info("No selected client has this feature enabled.")
        return
    stages = ["Eligible employees", "Ever used", "Habitual (3 of last 4 weeks)"]
    values = [funnel["eligible_employees"].sum(), funnel["employees_ever_used"].sum(),
              funnel["employees_habitual"].sum()]
    fig = go.Figure(go.Funnel(y=stages, x=values, textinfo="value+percent initial", marker=dict(color=BLUE)))
    show_chart(style(fig, 320))
    st.caption(f"{len(funnel)} clients have {feature} enabled in this selection. "
               "'Used' means a booking or check-in, not just a view.")
    shown = funnel.merge(clients[["client_id", "client_name"]], on="client_id")
    shown = shown[["client_id", "client_name", "eligible_employees", "pct_ever_used", "pct_habitual",
                   "days_enable_to_first_use"]].sort_values("pct_habitual")
    show_table(shown, hide_index=True)


# --------------------------------------------------------------------------
# Page 3: client drill-down
# --------------------------------------------------------------------------
def page_client(t):
    st.header("Client drill-down")
    clients = t["dim_clients"].sort_values("client_id")
    options = {f"{r.client_id}  {r.client_name}": r.client_id for r in clients.itertuples()}
    choice = st.selectbox("Client", list(options))
    cid = options[choice]
    client = clients[clients["client_id"] == cid].iloc[0]

    cols = st.columns(5)
    cols[0].metric("Health score", f"{client['health_score']:.1f}")
    cols[1].metric("Band", client["health_band"])
    cols[2].metric("Employees", f"{int(client['total_employees']):,}")
    cols[3].metric("Offices", int(client["offices"]))
    cols[4].metric("Weakest component", str(client["weakest_component"]).replace("_", " "))
    st.caption(f"{client['region']} | {client['plan']} plan | {client['industry']} | live since {client['go_live_date']}")

    left, right = st.columns(2)
    with left:
        st.subheader("Health components (0-100, higher is better)")
        parts = pd.DataFrame({
            "component": ["Breadth", "Depth", "Trend", "Ticket load (inverted)"],
            "score": [client["breadth_score"], client["depth_score"], client["trend_score"],
                      100 - client["ticket_load_score"]]})
        fig = px.bar(parts, x="score", y="component", orientation="h", text="score", range_x=[0, 100])
        fig.update_traces(marker_color=BLUE, texttemplate="%{x:.0f}", textposition="outside")
        fig.update_layout(yaxis_title="", xaxis_title="")
        fig.update_yaxes(autorange="reversed")
        show_chart(style(fig, 280))
    with right:
        st.subheader("Gaps and suggested fixes")
        gaps = t["fact_gaps"]
        gaps = gaps[gaps["client_id"] == cid]
        if gaps.empty:
            st.success("No implementation gap flagged by the rules for this client.")
        for g in gaps.itertuples():
            with st.container(border=True):
                st.markdown(f"**{GAP_NAMES.get(g.gap_type, g.gap_type)}**  \n"
                            f"{g.feature} | {int(g.employees_affected):,} employees affected")
                st.markdown(f"*Evidence:* {g.evidence}")
                st.markdown(f"*Suggested fix:* {g.suggested_fix}")

    st.subheader("Monthly usage by feature")
    metric_label = st.radio("Measure", ["Active employees", "Booking and check-in events"], horizontal=True)
    metric = "active_employees" if metric_label == "Active employees" else "use_events"
    monthly = t["fact_client_monthly_usage"]
    monthly = monthly[monthly["client_id"] == cid].copy()
    monthly["month"] = pd.to_datetime(monthly["month"])
    fig = px.line(monthly, x="month", y=metric, color="feature", markers=True,
                  category_orders={"feature": FEATURE_ORDER}, labels={metric: metric_label, "month": "", "feature": "Feature"})
    show_chart(style(fig, 380))

    left, right = st.columns(2)
    with left:
        st.subheader("Behaviour by feature")
        why = t["fact_why_not"]
        why = why[why["client_id"] == cid][["feature", "adoption_pct_of_employees", "coverage_pct",
                                            "view_without_book_pct", "cancel_pct", "no_show_pct", "tickets_total"]]
        show_table(why, hide_index=True)
        st.caption("view_without_book: share of views that did not become a booking. "
                   "cancel and no_show: share of bookings. Blank = not applicable.")
    with right:
        st.subheader("Support tickets by category")
        tickets = t["fact_tickets_monthly"]
        tickets = tickets[tickets["client_id"] == cid].groupby("category")["tickets"].sum().reset_index()
        tickets = tickets.sort_values("tickets")
        fig = px.bar(tickets, x="tickets", y="category", orientation="h", text="tickets", labels={"category": ""})
        fig.update_traces(marker_color=BLUE, textposition="outside")
        show_chart(style(fig, 330))


# --------------------------------------------------------------------------
# App shell
# --------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="Workplace adoption analytics", layout="wide")
    st.sidebar.title("Workplace adoption analytics")
    st.sidebar.caption("SYNTHETIC data with planted implementation gaps.")
    page = st.sidebar.radio("Page", ["Portfolio overview", "Feature heat map and funnels", "Client drill-down"])

    if not (DATA_DIR / "dim_clients.csv").exists():
        st.error("Missing outputs/powerbi/*.csv. Run: python run_queries.py && python gap_detector.py "
                 "&& python export_excel.py")
        return
    tables = load_tables()
    if page == "Portfolio overview":
        page_overview(tables)
    elif page == "Feature heat map and funnels":
        page_heatmap(tables)
    else:
        page_client(tables)


main()
