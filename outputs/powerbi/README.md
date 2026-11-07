# Power BI tables

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
