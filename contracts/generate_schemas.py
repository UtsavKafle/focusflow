"""Regenerate contracts/schema/*.json from contracts/models.py."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from contracts import models as m

OUT = pathlib.Path(__file__).parent / "schema"
OUT.mkdir(exist_ok=True)
TOP = ["NormalizedEvent", "StudentState", "CalendarBundle", "Schedule", "ScheduleProposal",
       "ReplanRequest", "ReplanJob", "ApplyRequest", "ChatRequest", "TaskProgressRequest",
       "ReplayStartRequest", "ReplayStatus", "SSEEvent", "ErrorBody"]
for name in TOP:
    (OUT / f"{name}.schema.json").write_text(json.dumps(getattr(m, name).model_json_schema(), indent=2, sort_keys=True) + "\n")
print(f"wrote {len(TOP)} schemas to {OUT}")
