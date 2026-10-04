"""Read-only Bronze verification through an existing SQL warehouse.

Lists existing warehouses by default. --warehouse-id executes bounded queries
and saves their actual responses. It never creates a warehouse or alters tables.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .landing_writer import identifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse-id")
    parser.add_argument("--run-id", default="mock-demo-002")
    parser.add_argument("--output", type=Path, default=Path("data/derived/mock-demo-002/bronze-report.json"))
    args = parser.parse_args()
    identifier(args.run_id)
    from dotenv import load_dotenv
    from databricks.sdk import WorkspaceClient
    load_dotenv(override=False)
    client = WorkspaceClient()
    if not args.warehouse_id:
        print(json.dumps([{"id": w.id, "name": w.name, "state": w.state.value if w.state else None,
                           "serverless": w.enable_serverless_compute, "auto_stop_minutes": w.auto_stop_mins}
                          for w in client.warehouses.list()], indent=2))
        return
    where = f"FROM focusflow.main.bronze_wearable_events WHERE run_id='{args.run_id}'"
    queries = {
        "session_timezone": "SELECT current_timezone() AS timezone",
        "requested_flag_reason_query": f"SELECT signal, quality, flag_reason, COUNT(*) {where} GROUP BY 1,2,3 ORDER BY 1,2,3",
        "quality_counts": f"SELECT signal, quality, COUNT(*) AS row_count {where} GROUP BY 1,2 ORDER BY 1,2",
        "signal_spans": f"SELECT signal, COUNT(*) AS row_count, MIN(event_time) AS min_event_time, MAX(event_time) AS max_event_time, COUNT(DISTINCT event_id) AS unique_events {where} GROUP BY 1 ORDER BY 1",
        "schema": "DESCRIBE TABLE focusflow.main.bronze_wearable_events",
    }
    report = {"run_id": args.run_id, "warehouse_id": args.warehouse_id, "queries": {}}
    for name, sql in queries.items():
        response = client.statement_execution.execute_statement(sql, args.warehouse_id, wait_timeout="10s", row_limit=100)
        deadline = time.monotonic() + 180
        while response.status.state.value in {"PENDING", "RUNNING"}:
            if time.monotonic() >= deadline:
                client.statement_execution.cancel_execution(response.statement_id)
                raise TimeoutError("read-only report query exceeded its bounded wait")
            time.sleep(2)
            response = client.statement_execution.get_statement(response.statement_id)
        entry = {"sql": sql, "state": response.status.state.value}
        if response.status.error:
            entry["error"] = response.status.error.as_dict()
        if response.result:
            entry["columns"] = [column.name for column in response.manifest.schema.columns]
            entry["rows"] = response.result.data_array
        report["queries"][name] = entry
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({name: entry}, indent=2), flush=True)


if __name__ == "__main__":
    main()
