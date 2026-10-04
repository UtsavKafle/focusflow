"""Explanations (integrator tasks 10 + 11).
- fallback_explanation(): deterministic, no LLM, built only from tool results + the proposal diff. Labeled as fallback.
- check_grounding(): every number and clock time in an explanation must appear in tool outputs or the diff, and the
  four sections (What we saw, What we're unsure about, What the coach suggests, Status) must be present.
Plain language for a student: short, four sections, no state_id/run_id/proposal_id/schedule_version in the body
(those stay in the evidence footer the API already returns separately)."""
from __future__ import annotations

import json, re
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

SECTIONS = ("What we saw:", "What we're unsure about:", "What the coach suggests:", "Status:")
FALLBACK_LABEL = "Fallback explanation (generated without a language model from saved tool results)."
CAVEAT = "Scores are engineering heuristics from one recorded wearable, not a diagnosis or sleep assessment."
NO_CHANGES = "No changes needed: nothing left to move tonight."
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\s?(AM|PM)?\b", re.I)
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z")
NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_time(iso: str, tz: str) -> str:
    d = _ts(iso).astimezone(ZoneInfo(tz))
    return d.strftime("%a ") + d.strftime("%I:%M %p").lstrip("0")


def fmt_pct(v: float) -> str:
    """0..1 heuristic score as a 0-100 integer, matching the UI's own gauges (e.g. recovery_score=0.27 -> "27")."""
    return str(round(v * 100))


def fmt_hm(total_minutes: float) -> str:
    """Minutes as "H h M m" (or just "H h" / "M m"), matching how a student reads a duration."""
    n = round(total_minutes)
    h, m = divmod(n, 60)
    if h and m:
        return f"{h} h {m} m"
    return f"{h} h" if h else f"{m} m"


def _span(b: dict, tz: str) -> str:
    return f"{fmt_time(b['start'], tz)}-{fmt_time(b['end'], tz)}"


def _change_line(c: dict, tz: str) -> str:
    new, old = c.get("new_blocks") or [], c.get("old_blocks") or []
    if new and new[0]["kind"] == "sleep_extension":
        b = new[0]
        return f"Add a {b['minutes']}-minute rest block {_span(b, tz)}."
    blocks = new or old
    mins = sum(b["minutes"] for b in new) or (blocks[0]["minutes"] if blocks else 0)
    where = _span(new[0], tz) if new else "later"
    verb = {"added": "Add", "moved": "Move", "removed": "Remove"}.get(c.get("action"), c.get("action", "Change").capitalize())
    return f"{verb} a {mins}-minute study block to {where}." if new else f"{verb} a {mins}-minute study block."


def fallback_explanation(results: dict[str, dict], tz: str) -> str:
    """results: tool name -> its (latest) output. Uses only values present in those outputs."""
    st = results.get("get_current_student_state", {})
    cmp = results.get("compare_to_baseline", {})
    rest = results.get("get_recent_rest", {})
    dl = results.get("get_upcoming_deadlines", {})
    plan = results.get("request_schedule_replan")
    w = st.get("wearable", {})
    q = w.get("quality", {})
    ac = st.get("academic", {})
    trig = st.get("trigger", {})

    saw = []
    if cmp.get("mean") is not None:
        saw.append(f"Load was at or above {fmt_pct(cmp.get('threshold', 0.7))} for "
                   f"{cmp.get('minutes_at_or_above_threshold')} of the last {cmp['valid_minutes']} minutes.")
    else:
        saw.append("No valid load minutes were available in the recent window.")
    if rest.get("estimated_rest_minutes") is not None and rest.get("target_rest_minutes"):
        line = f"Estimated rest was {fmt_hm(rest['estimated_rest_minutes'])} against a {fmt_hm(rest['target_rest_minutes'])} target"
        if rest.get("recovery_score") is not None:
            line += f"; recovery is {fmt_pct(rest['recovery_score'])}/100."
        else:
            line += "."
        saw.append(line)
    else:
        saw.append("Estimated rest is unknown for last night.")
    exams = [e for e in dl.get("fixed_events", []) if e["kind"] == "exam"]
    if exams:
        saw.append(f"Next exam in {exams[0]['hours_until']:.1f} hours.")
    if ac.get("deadline_pressure") is not None:
        saw.append(f"Deadline pressure is {fmt_pct(ac['deadline_pressure'])}%.")

    # Uncertainty comes only from quality.missing_reasons and confound flags -- never invented, and never
    # silent when there is genuinely nothing to report.
    unc = []
    reasons = q.get("missing_reasons") or {}
    if reasons:
        unc.append("Missing: " + ", ".join(f"{k.replace('_', ' ')} ({v})" for k, v in sorted(reasons.items())) + ".")
    if "ACTIVITY_CONFOUND" in (trig.get("suppressed_reason_codes") or []):
        unc.append("Movement may be confounding the load estimate.")
    if not unc:
        unc.append("All signals had full coverage.")

    sug = []
    has_changes = bool(plan and (plan.get("changes") or plan.get("unscheduled_work")))
    if not plan:
        sug.append("No schedule proposal was produced.")
    elif not has_changes:
        sug.append(NO_CHANGES)
    else:
        for c in plan["changes"]:
            sug.append(_change_line(c, tz))
        for u in plan["unscheduled_work"]:
            sug.append(f"{u['minutes']} minutes could not fit before the deadline {fmt_time(u['deadline'], tz)}.")

    status = "Applied." if plan and plan.get("applied") else (NO_CHANGES if plan and not has_changes else "proposed, not applied.")

    body = "\n".join([FALLBACK_LABEL, "What we saw: " + " ".join(saw), "What we're unsure about: " + " ".join(unc),
                      "What the coach suggests: " + " ".join(sug), "Status: " + status])
    return body + "\n" + CAVEAT


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
    if isinstance(v, int) and v >= 30:  # minutes may be quoted as decimal hours, or split "H h M m"
        out |= {f"{v / 60:g}", f"{v / 60:.1f}"}
        h, m = divmod(v, 60)
        out |= {str(h), str(m)}
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
    """Returns (ok, problems). Problems list ungrounded numbers/times and missing sections. Does not require
    state_id/run_id/proposal_id/schedule_version -- the explanation is instructed to never cite them, so
    there is nothing ID-shaped to ground; only values actually written into the text are checked."""
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
