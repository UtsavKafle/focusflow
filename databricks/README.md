# databricks (Data A + Data B)
- `ingestion/` (Data A): adapters, landing writer, Bronze stream.
- `features/` (Data B): PURE pandas, no Spark. `minute_features.py` (Silver), `baselines.py` (causal robust z), `state.py` (Gold + `row_to_wearable_state`), `synthetic.py` (test data, synthetic), `run_local.py` (raw CSVs -> silver/gold + tuning summary).
- `streaming/` (Data B): Spark wrappers (M2).
- `sql/`: DDL (`ddl_bronze.sql` Data A; `ddl_silver.sql`, `ddl_gold.sql` Data B) and backend read queries.
Gold row -> contract: `databricks.features.state.row_to_wearable_state(row)`.
