"""Agent tool interface (HANDOFF 9.6). STUB: owner = Integrator. Each tool returns JSON with time ranges + evidence IDs.
The agent supplies permitted reason codes only; the backend maps them to a policy. Agent text never changes the schedule."""
import json, pathlib

SPEC = json.loads((pathlib.Path(__file__).resolve().parents[1] / "contracts" / "agent_tools.json").read_text())


def tool_names() -> list[str]:
    return [t["name"] for t in SPEC["tools"]]
