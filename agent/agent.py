"""Tool-calling agent (integrator tasks 9-12). It investigates and explains; Python decides; the API applies.
Providers behind LLMProvider.chat(system, messages, tools):
  - DatabricksProvider: Databricks model serving endpoint (DATABRICKS_MODEL_ENDPOINT), if configured.
  - AnthropicProvider: API-key fallback (LLM_API_KEY), official `anthropic` SDK, imported lazily.
  - none configured -> scripted deterministic investigation + fallback explanation (demo works with no keys).
Caps: AGENT_MAX_TOOL_CALLS (8) and AGENT_TIME_CAP_S (60). Any model failure -> fallback explanation; the schedule is
never touched here (Services.apply is the only commit)."""
from __future__ import annotations

import json, os, time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from agent.explain import CAVEAT, ISO_RE, SECTIONS, check_grounding, fallback_explanation, fmt_time, sources_for_check
from agent.tools import SPEC, ToolBox, ToolError

MAX_TOOL_CALLS = int(os.getenv("AGENT_MAX_TOOL_CALLS", "8"))
TIME_CAP_S = float(os.getenv("AGENT_TIME_CAP_S", "60"))
ANTHROPIC_MODEL = "claude-opus-5-5"


# ---------------- provider adapter ----------------
@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class AssistantMsg:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None          # provider-native content, echoed back unchanged on the next turn
    refused: bool = False


class LLMProvider(Protocol):
    model_id: str

    def chat(self, system: str, messages: list[dict], tools: Optional[list[dict]], timeout: float) -> AssistantMsg: ...
    # neutral messages: {"role":"user","content":str} | {"role":"assistant","msg":AssistantMsg}
    #                   | {"role":"tool","tool_call_id":str,"content":str,"is_error":bool}


class AnthropicProvider:
    def __init__(self, api_key: str, model: str = ANTHROPIC_MODEL):
        import anthropic  # lazy: only needed when LLM_API_KEY is set
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=1)
        self.model_id = model

    def _convert(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                out.append({"role": "assistant", "content": m["msg"].raw})
            else:  # all tool results for one assistant turn go in a single user message
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"],
                         "is_error": m["is_error"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def chat(self, system, messages, tools, timeout) -> AssistantMsg:
        kw = {"tools": [{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                        for t in tools]} if tools else {}
        resp = self.client.with_options(timeout=timeout).beta.messages.create(
            model=self.model_id, max_tokens=16000, system=system, messages=self._convert(messages),
            output_config={"effort": "medium"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        self.model_id = resp.model
        if resp.stop_reason == "refusal":
            return AssistantMsg(refused=True, raw=resp.content)
        return AssistantMsg(text="".join(b.text for b in resp.content if b.type == "text"),
                            tool_calls=[ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"],
                            raw=resp.content)


class DatabricksProvider:
    """Databricks model serving endpoint, chat-completions request shape."""

    def __init__(self, host: str, token: str, endpoint: str):
        self.url = f"{host.rstrip('/')}/serving-endpoints/{endpoint}/invocations"
        self.token, self.model_id = token, f"databricks:{endpoint}"

    def _convert(self, system, messages):
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                a, msg = m["msg"], {"role": "assistant"}  # empty keys omitted: some endpoints reject nulls
                if a.text:
                    msg["content"] = a.text
                if a.tool_calls:
                    msg["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name,
                                          "arguments": json.dumps(c.input)}} for c in a.tool_calls]
                out.append(msg)
            else:
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        return out

    def chat(self, system, messages, tools, timeout) -> AssistantMsg:
        import httpx
        body = {"messages": self._convert(system, messages), "max_tokens": 4000, "temperature": 0}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["input_schema"]}} for t in tools]
        r = httpx.post(self.url, json=body, headers={"Authorization": f"Bearer {self.token}"}, timeout=timeout)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = [ToolCall(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))
                 for c in msg.get("tool_calls") or []]
        content = msg.get("content") or ""
        if isinstance(content, list):  # some endpoints return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return AssistantMsg(text=content, tool_calls=calls, raw=msg)


def select_provider() -> Optional[LLMProvider]:
    env = lambda k: (os.getenv(k) or "").split("#")[0].strip()  # tolerate inline .env comments
    ep, host, tok = env("DATABRICKS_MODEL_ENDPOINT"), env("DATABRICKS_HOST"), env("DATABRICKS_TOKEN")
    if ep and host and tok:
        return DatabricksProvider(host, tok, ep)
    if os.getenv("LLM_API_KEY"):
        return AnthropicProvider(os.environ["LLM_API_KEY"])
    return None


# ---------------- investigation ----------------
SYSTEM = """You are FocusFlow's study-plan coach, writing directly to the student. A student's replayed wearable
state and a SYNTHETIC exam-week calendar are available through tools. Investigate, then request one schedule
proposal and explain it in plain language a student would actually read.
Rules:
- Use tools for every fact. Every number and clock time you write must appear in a tool result. Do not compute scores.
- Call request_schedule_replan at most once, with reason codes chosen only from: {codes}.
- You cannot change the schedule. The proposal is NOT applied; say "proposed, not applied" (or, if the proposal has
  no changes and no unscheduled work, say "No changes needed: nothing left to move tonight").
- Scores are engineering heuristics, not diagnoses. Say "estimated rest", never "sleep quality".
- Never write state_id, run_id, proposal_id, or schedule_version anywhere in your answer -- those are tracked
  separately, not something a student reads. Refer to the plan itself, not its internal identifiers.
- The uncertainty section comes only from the wearable's quality.missing_reasons and any activity/sensor confound
  tools report. If nothing is missing and there is no confound, say so plainly (e.g. "All signals had full
  coverage") -- never invent uncertainty, and never claim data is missing when it is present.
- Write times in the {tz} timezone like "Tue 10:00 AM".
- Keep the whole answer short: about 120 words total, plain language, no jargon.
Final answer: plain text with exactly these four labeled sections, in order, each one or two short sentences:
What we saw: (the key numbers: load, estimated rest vs target, recovery, hours until next exam, deadline pressure)
What we're unsure about: (missing data or confounds only, or "All signals had full coverage")
What the coach suggests: (the proposed changes in plain words, or "No changes needed: nothing left to move tonight")
Status: (proposed, not applied / applied / no changes needed)
End with: "{caveat}" """


def _evidence(box: ToolBox, state) -> list[str]:
    ids = list(state.wearable.evidence_ids)
    for c in box.calls:
        for v in json.dumps(c["result"], default=str).split('"'):
            if v.startswith(("window-", "rest-")) and v not in ids:
                ids.append(v)
    return ids


def _scripted(box: ToolBox, state, reason_codes: list[str], emit) -> None:
    """Deterministic investigation: calls each evidence tool once (skips ones the model already called)."""
    done = {c["tool"] for c in box.calls}
    plan = [("get_current_student_state", {"run_id": state.run_id}),
            ("compare_to_baseline", {"metric": "physiological_load", "window": "last_20_min"}),
            ("get_recent_rest", {"as_of": state.model_dump(mode="json")["as_of"]}),
            ("get_upcoming_deadlines", {"as_of": state.model_dump(mode="json")["as_of"]}),
            ("get_remaining_tasks", {})]
    for name, args in plan:
        if name not in done:
            emit(name, box.call(name, args))
    if box.proposal is None:
        emit("request_schedule_replan", box.call("request_schedule_replan", {
            "state_id": state.state_id, "schedule_version": state.academic.schedule_version, "reason_codes": reason_codes}))


def _for_model(obj: Any, tz: str) -> Any:
    """Tool output as the model sees it: each UTC timestamp also carries its local time, so the model copies
    "Mon 11:30 PM" instead of converting (or misreading) "03:30Z" itself."""
    if isinstance(obj, dict):
        return {k: _for_model(v, tz) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_for_model(v, tz) for v in obj]
    if isinstance(obj, str) and ISO_RE.fullmatch(obj):
        return f"{obj} ({fmt_time(obj, tz)} {tz})"
    return obj


def _llm_loop(provider: LLMProvider, box: ToolBox, state, reason_codes: list[str], emit, deadline: float,
              errors: Optional[list] = None) -> str:
    tz = state.scenario_timezone
    system = SYSTEM.format(codes=", ".join(reason_codes), tz=tz, caveat=CAVEAT)
    messages: list[dict] = [{"role": "user", "content":
                             f"Current state_id={state.state_id}, schedule_version={state.academic.schedule_version}, "
                             f"run_id={state.run_id}. Investigate and request a replan."}]
    n = 0
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("agent time cap reached")
        msg = provider.chat(system, messages, SPEC["tools"] if n < MAX_TOOL_CALLS else None, timeout=left)
        if msg.refused:
            raise RuntimeError("model declined the request")
        messages.append({"role": "assistant", "msg": msg})
        if not msg.tool_calls:
            return msg.text
        for c in msg.tool_calls:
            n += 1
            if n > MAX_TOOL_CALLS:
                out, err = {"error": "tool call cap reached; write the final answer now"}, True
            else:
                if c.name == "request_schedule_replan" and set(c.input.get("reason_codes", [])) - set(reason_codes):
                    out, err = {"error": f"reason_codes must be chosen from {reason_codes}"}, True
                else:
                    try:
                        out, err = box.call(c.name, c.input), False
                        emit(c.name, out)
                    except ToolError as e:
                        out, err = {"error": str(e)}, True
            if err and errors is not None:
                errors.append(f"{c.name}: {out['error']}"[:200])
            content = json.dumps(_for_model(json.loads(json.dumps(out, default=str)), tz))
            messages.append({"role": "tool", "tool_call_id": c.id, "content": content, "is_error": err})


def run_investigation(svc, job_id: str, req, state) -> dict:
    """Backend investigator hook (Services.investigator). Returns proposal + explanation + audit fields."""
    box = ToolBox(svc, state)

    def emit(name, result):
        svc.bus.emit(svc.run_id, "agent.tool_result", {"job_id": job_id, "tool": name,
                                                       "ok": "error" not in result if isinstance(result, dict) else True})

    provider, text, notes, tool_errors = select_provider(), None, [], []
    if provider is not None:
        try:
            text = _llm_loop(provider, box, state, list(req.reason_codes), emit, time.monotonic() + TIME_CAP_S, tool_errors)
        except Exception as e:  # noqa: BLE001 - unavailable / timeout / malformed -> fallback
            notes.append(f"model failed: {type(e).__name__}: {str(e)[:200]}")
        notes += [f"tool error: {t}" for t in tool_errors]
        if text and box.proposal is None:
            notes.append("model did not request a replan; its text cannot describe the diff")
            text = None
    # Only what the model actually saw: its own tool call results, plus the facts given directly in the
    # _llm_loop prompt (state_id, schedule_version, run_id) rather than via a tool call. Without the
    # second part, a model that correctly echoes back its own state_id or schedule_version gets its
    # whole answer rejected as "ungrounded", since those numbers never appear in any tool result.
    sources = sources_for_check([c["result"] for c in box.calls] +
                                 [{"state_id": state.state_id, "schedule_version": state.academic.schedule_version,
                                   "run_id": state.run_id}])
    _scripted(box, state, list(req.reason_codes), emit)  # fills any evidence the model skipped; never re-plans
    latest = {c["tool"]: c["result"] for c in box.calls}
    kind, model_id = "fallback", "none"
    if text:
        ok, problems = check_grounding(text, sources, state.scenario_timezone)
        if ok:
            kind, model_id = "llm", provider.model_id
        else:
            notes.append("grounding check failed: " + "; ".join(problems[:5]))
            text = None
    if text is None:
        text = fallback_explanation(latest, state.scenario_timezone)
    audit = [{"tool": c["tool"], "args": c["args"], "result": c["result"]} for c in box.calls]
    if notes:
        audit.append({"tool": "_agent_notes", "args": {}, "result": {"notes": notes}})
    return {"proposal": box.proposal, "explanation": text, "evidence_ids": _evidence(box, state),
            "tool_results": audit, "model_id": model_id if kind == "llm" else (provider.model_id + " (failed)" if provider else "none"),
            "explanation_kind": kind}


# ---------------- chat (task 12) ----------------
CHAT_SYSTEM = """Answer the student's question about a past FocusFlow schedule decision using ONLY the saved decision
returned by get_schedule_change and the current state. Every number and time must appear in those tool results.
Do not guess or re-plan. Write times in {tz} like "Tue 10:00 AM". Keep it under 120 words. End with: "{caveat}" """


def saved_answer(d: dict) -> str:
    after = f"v{d['after_version']}" if d["after_version"] is not None else "not applied"
    return (f"From saved decision {d['decision_id']} (state {d['state_id']}, rule {d['rule_version']}, "
            f"schedule v{d['before_version']} -> {after}):\n{d['explanation']}")


def run_chat(svc, message: str, decision_id: Optional[str]) -> dict:
    """Answers from saved decisions (history), never a fresh guess about today's state."""
    d = svc.store.decision(decision_id) if decision_id else (svc.store.decisions(svc.run_id) or [None])[-1]
    if d is None:
        return {"answer": "No schedule decisions have been saved in this run yet.", "evidence_ids": [],
                "decision_id": None, "kind": "fallback"}
    base = {"evidence_ids": d["evidence_ids"], "decision_id": d["decision_id"]}
    provider = select_provider()
    state = svc.compose()
    if provider is None or state is None:
        return {**base, "answer": saved_answer(d), "kind": "saved"}
    box = ToolBox(svc, state)
    try:
        saved = box.call("get_schedule_change", {"decision_id": d["decision_id"]})
        msgs = [{"role": "user", "content": f"Saved decision:\n{json.dumps(saved, default=str)}\n\nQuestion: {message}"}]
        msg = provider.chat(CHAT_SYSTEM.format(tz=state.scenario_timezone, caveat=CAVEAT), msgs, None, timeout=TIME_CAP_S)
        text = "" if msg.refused else msg.text
        nums_ok, problems = check_grounding(text + "\n" + "\n".join(SECTIONS), sources_for_check([saved]),
                                            state.scenario_timezone)
        if text and nums_ok:
            return {**base, "answer": text, "kind": "llm"}
    except Exception:  # noqa: BLE001
        pass
    return {**base, "answer": saved_answer(d), "kind": "saved"}
