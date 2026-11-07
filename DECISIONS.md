# DECISIONS

Log of choices made where SPEC.md was ambiguous.

- P1: `data/raw/events.csv` and `data/workplace.db` are gitignored (large, fully regenerable with seed 42). Smaller CSVs and ground_truth.json are committed.
- P1: Power BI file (`dashboard/adoption.pbix`) is built manually by the user; this repo provides tidy CSVs in `outputs/powerbi/`.
