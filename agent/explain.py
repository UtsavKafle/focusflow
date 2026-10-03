"""Explanations (integrator tasks 10 + 11).
- fallback_explanation(): deterministic, no LLM, built only from tool results + the proposal diff. Labeled as fallback.
- check_grounding(): every number and clock time in an explanation must appear in tool outputs or the diff, and the
  four sections (Observation, Uncertainty, Planning reason, Action/status) must be present."""
from __future__ import annotations

import json, re
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

SECTIONS = ("Observation:", "Uncertainty:", "Planning reason:", "Action/status:")
FALLBACK_LABEL = "Fallback explanation (generated without a language model from saved tool results)."
CAVEAT = "Scores are engineering heuristics from one recorded wearable, not a diagnosis or sleep assessment."
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\s?(AM|PM)?\b", re.I)
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z")
NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_time(iso: str, tz: str) -> str:
    d = _ts(iso).astimezone(ZoneInfo(tz))
    return d.strftime("%a ") + d.strftime("%I:%M %p").lstrip("0")


def _span(b: dict, tz: str) -> str:
    return f"{fmt_time(b['start'], tz)}-{fmt_time(b['end'], tz)}"


def fallback_explanation(results: dict[str, dict], tz: str) -> str:
    """results: tool name -> its (latest) output. Uses only values present in those outputs."""
    st = results.get("get_current_student_state", {})
    cmp = results.get("compare_to_baseline", {})
    rest = results.get("get_recent_rest", {})
    dl = results.get("get_upcoming_deadlines", {})
    plan = results.get("request_schedule_replan")
    w, q, ac = st.get("wearable", {}), st.get("wearable", {}).get("quality", {}), st.get("academic", {})

    obs = []
    if cmp.get("mean") is not None:
        obs.append(f"From {fmt_time(cmp['start'], tz)} to {fmt_time(cmp['end'], tz)}, estimated physiological load averaged "
                   f"{cmp['mean']} and was at or above {cmp.get('threshold')} in {cmp.get('minutes_at_or_above_threshold')} "
                   f"of {cmp['valid_minutes']} valid minutes, relative to personal baseline {cmp.get('baseline_id')}.")
    else:
        obs.append("No valid physiological load minutes were available in the recent window.")
    if rest.get("estimated_rest_minutes") is not None:
        obs.append(f"Estimated rest was {rest['estimated_rest_minutes']} minutes against a {rest['target_rest_minutes']}-minute "
                   f"target (recovery score {rest.get('recovery_score')}).")
    else:
        obs.append("Estimated rest is unknown for the last night.")

    unc = [f"Data quality is {q.get('status', 'unknown')}."]
    if q.get("missing_reasons"):
        unc.append("Unavailable: " + ", ".join(f"{k} ({v})" for k, v in sorted(q["missing_reasons"].items())) + ".")
    if rest.get("overnight_coverage") is not None:
        unc.append(f"Overnight coverage was {rest['overnight_coverage']}.")
    unc.append("Low movement may be quiet wakefulness or a removed device. " + CAVEAT)

    pr = []
    trig = st.get("trigger", {})
    if trig.get("reason_codes"):
        pr.append("Rule signals present: " + ", ".join(trig["reason_codes"]) + ".")
    exams = [e for e in dl.get("fixed_events", []) if e["kind"] == "exam"]
    if exams:
        pr.append(f"Next exam: {exams[0]['title']} at {fmt_time(exams[0]['start'], tz)} ({exams[0]['hours_until']} hours away).")
    if ac:
        pr.append(f"Remaining work is {ac.get('remaining_work_minutes')} minutes; deadline pressure is {ac.get('deadline_pressure')}.")
    pr.append("Tasks are placed by earliest deadline, then priority; fixed events and protected sleep never move.")

    act = []
    if not plan:
        act.append("No schedule proposal was produced.")
    else:
        for c in plan["changes"]:
            if c["new_blocks"] and c["new_blocks"][0]["kind"] == "sleep_extension":
                act.append(f"Add a rest block {_span(c['new_blocks'][0], tz)} ({c['reason_code']}).")
                continue
            task = (c["new_blocks"] or c["old_blocks"])[0]["task_id"]
            old = ", ".join(_span(b, tz) for b in c["old_blocks"]) or "unscheduled"
            new = ", ".join(_span(b, tz) for b in c["new_blocks"]) or "removed"
            mins = sum(b["minutes"] for b in c["new_blocks"])
            act.append(f"{c['action'].capitalize()} {task}: {old} -> {new}, {mins} minutes ({c['reason_code']}).")
        for u in plan["unscheduled_work"]:
            act.append(f"{u['task_id']}: {u['minutes']} minutes could not be placed before its deadline "
                       f"{fmt_time(u['deadline'], tz)} (no feasible plan found by this scheduler).")
        if not plan["changes"] and not plan["unscheduled_work"]:
            act.append("No schedule change is recommended.")
        act.append("Status: proposed, not applied." if not plan.get("applied") else "Status: applied.")

    return "\n".join([FALLBACK_LABEL, "Observation: " + " ".join(obs), "Uncertainty: " + " ".join(unc),
                      "Planning reason: " + " ".join(pr), "Action/status: " + " ".join(act)])


def _walk(x: Any) -> Iterable[Any]:
    if isinstance(x, dict):
        for v in x.values(): yield from _walk(v)
    elif isinstance(x, (list, tuple)):
        for v in x: yield from _walk(v)
    else:
        yield x


def _num_forms(v: float) -> set[str]:
    out = {str(v), f"{v:g}", f"{v:.2f}", f"{v:.1f}", str(round(v)), str(int(v))}
    if 0 <= v <= 1:
        out |= {str(round(v * 100)), f"{v * 100:g}"}
    if isinstance(v, int) and v >= 30:  # minutes may be quoted as hours
        out |= {f"{v / 60:g}", f"{v / 60:.1f}"}
    return out


def allowed_tokens(sources: list[Any], tz: str) -> tuple[set[str], set[str]]:
    nums, times = set(), set()
    for v in _walk(sources):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            nums |= _num_forms(v)
        elif isinstance(v, str):
            nums |= set(re.findall(r"\d+(?:\.\d+)?", v))
            for iso in ISO_RE.findall(v):
                d = _ts(iso).astimezone(ZoneInfo(tz))
                times |= {d.strftime("%I:%M").lstrip("0"), d.strftime("%H:%M"), d.strftime("%I:%M")}
                nums |= {str(d.day), str(d.hour), str(int(d.strftime("%I")))}
    return nums, times


def check_grounding(text: str, sources: list[Any], tz: str) -> tuple[bool, list[str]]:
    """Returns (ok, problems). Problems list ungrounded numbers/times and missing sections."""
    problems = [f"missing section {s}" for s in SECTIONS if s not in text]
    nums, times = allowed_tokens(sources, tz)
    body = text.replace(FALLBACK_LABEL, "")
    for m in TIME_RE.finditer(body):
        if m.group(1).lstrip("0") not in times and m.group(1) not in times:
            problems.append(f"time {m.group(0)} not in tool results")
    body = TIME_RE.sub(" ", body)
    for n in NUM_RE.findall(body):
        if n not in nums:
            problems.append(f"number {n} not in tool results")
    return not problems, problems


def sources_for_check(results: list[dict]) -> list[Any]:
    return [json.loads(json.dumps(r, default=str)) for r in results]
