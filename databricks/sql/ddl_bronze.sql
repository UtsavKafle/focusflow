-- Run once in the intended Unity Catalog workspace. No raw values are scaled.
-- CREATE CATALOG requires admin rights; an admin can create it separately.
CREATE CATALOG IF NOT EXISTS focusflow;
CREATE SCHEMA IF NOT EXISTS focusflow.main;
CREATE VOLUME IF NOT EXISTS focusflow.main.landing;
CREATE VOLUME IF NOT EXISTS focusflow.main.checkpoints;

CREATE TABLE IF NOT EXISTS focusflow.main.bronze_wearable_events (
  schema_version STRING NOT NULL,
  run_id STRING NOT NULL,
  event_id STRING NOT NULL,
  participant_id STRING NOT NULL,
  source_kind STRING NOT NULL,
  source_timestamp TIMESTAMP NOT NULL,
  event_time TIMESTAMP NOT NULL,
  ingested_at TIMESTAMP NOT NULL,
  signal STRING NOT NULL,
  `values` MAP<STRING, DOUBLE> NOT NULL,
  unit STRING NOT NULL,
  quality STRING NOT NULL,
  source_file STRING NOT NULL,
  source_row BIGINT NOT NULL
) USING DELTA;

-- Databricks accepts CHECK constraints via ALTER TABLE after creation, not in
-- CREATE TABLE's table-constraint clause. Run each ADD once; if a named constraint
-- already exists on a rerun, leave it in place and skip that ADD statement.
ALTER TABLE focusflow.main.bronze_wearable_events
  ADD CONSTRAINT bronze_schema CHECK (schema_version = '1.0');
ALTER TABLE focusflow.main.bronze_wearable_events
  ADD CONSTRAINT bronze_source CHECK (source_kind IN ('recorded_replay', 'synthetic_fixture', 'synthetic_injection'));
ALTER TABLE focusflow.main.bronze_wearable_events
  ADD CONSTRAINT bronze_signal CHECK (signal IN ('hr', 'eda', 'acc', 'ibi', 'temp'));
ALTER TABLE focusflow.main.bronze_wearable_events
  ADD CONSTRAINT bronze_quality CHECK (quality IN ('valid', 'flagged', 'dropped'));
ALTER TABLE focusflow.main.bronze_wearable_events
  ADD CONSTRAINT bronze_source_row CHECK (source_row > 0);

-- (run_id,event_id) uniqueness is enforced by insert-only MERGE in bronze_stream.
-- Run only one Bronze writer per table; overlapping writers require orchestration.
