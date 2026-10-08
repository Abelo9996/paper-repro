"""`compare`: put a measured number next to a claimed one and reach a verdict, with reasons."""

from __future__ import annotations

import math
import statistics
from typing import Any

from .metrics import resolve_selectors
from .study import Study, StudyError, locked
from .util import decimals, lower_is_better, metric_base, normalize_metric

VERDICTS = ("reproduced", "close", "not_reproduced", "inconclusive", "could_not_run")
RATIO_METRICS = {
    "accuracy",
    "top1_accuracy",
    "top5_accuracy",
    "balanced_accuracy",
    "f1",
    "macro_f1",
    "micro_f1",
    "precision",
    "recall",
    "roc_auc",
    "auc",
    "map",
    "iou",
    "miou",
    "dice",
    "error",
    "error_rate",
    "exact_match",
    "em",
}
DEFAULT_REL_TOL = 0.01
CLOSE_FACTOR = 3.0


def _fmt(x: float | None) -> str:
    if x is None:
        return "n/a"
    if x == 0:
        return "0"
    if abs(x) >= 1000 or abs(x) < 0.001:
        return f"{x:.4g}"
    return f"{x:.6g}"


def _pct(x: float) -> str:
    if x >= 10:
        return f"{x:.0f}%"
    if x >= 1:
        return f"{x:.1f}%"
    return f"{x:.2g}%"


@locked
def add_claim(
    study: Study,
    *,
    metric: str,
    value: float | None = None,
    lo: float | None = None,
    hi: float | None = None,
    percent: bool = False,
    source: str,
    text: str | None = None,
    value_text: str | None = None,
) -> dict:
    """Record a claim the README extractor missed (from the paper PDF, a table image, etc.)."""
    if value is None and (lo is None or hi is None):
        raise StudyError("A claim needs --value or both ends of --range.")
    if not source.strip():
        raise StudyError("A claim needs --source saying where the number is stated.")
    st = study.state()
    n = sum(1 for c in st["claims"] if c.startswith("u"))
    claim = {
        "id": f"u{n + 1}",
        "metric": normalize_metric(metric),
        "raw_metric": metric,
        "value": value,
        "value_text": value_text or (repr(value) if value is not None else None),
        "lo": lo,
        "hi": hi,
        "lo_text": repr(lo) if lo is not None else None,
        "hi_text": repr(hi) if hi is not None else None,
        "plus_minus": None,
        "percent": percent,
        "source": source,
        "line": None,
        "text": text or "",
        "kind": "manual",
    }
    return study.append("claim", {"claim": claim})


def _target(claim: dict) -> tuple[float, float, str]:
    """The interval a measurement should land in, before tolerance."""
    u = "%" if claim.get("percent") else ""
    if claim.get("lo") is not None and claim.get("hi") is not None:
        lo, hi = sorted((claim["lo"], claim["hi"]))
        a = claim.get("lo_text") or _fmt(lo)
        b = claim.get("hi_text") or _fmt(hi)
        return lo, hi, f"the range {a}{u} to {b}{u}"
    v = claim["value"]
    vt = claim.get("value_text") or _fmt(v)
    if claim.get("plus_minus"):
        pm = claim["plus_minus"]
        return v - pm, v + pm, f"{vt}{u} ± {_fmt(pm)} (treated as {_fmt(v - pm)} to {_fmt(v + pm)})"
    return v, v, f"{vt}{u}"


def same_quantity(a: str, b: str) -> bool:
    """Whether two metric names plausibly name the same thing ('test.accuracy' vs 'accuracy')."""
    ka = metric_base(a.replace(".", "_").split("_")[-1])
    kb = metric_base(b.replace(".", "_").split("_")[-1])
    return ka == kb


def _precision_text(claim: dict) -> str | None:
    if claim.get("value_text"):
        return claim["value_text"]
    return claim.get("hi_text") or claim.get("lo_text")


def _find_blocking(st: dict, blocking: str | None) -> dict | None:
    if blocking:
        for e in st["envs"]:
            if e["id"] == blocking:
                return _blocking_from_env(e)
        if blocking in st["runs"]:
            return _blocking_from_run(st["runs"][blocking])
        raise StudyError(f"Unknown env or run id {blocking!r}")
    candidates: list[tuple[int, dict]] = []
    for e in st["envs"]:
        if e["status"] != "ok":
            candidates.append((e["seq"], _blocking_from_env(e)))
    for r in st["runs"].values():
        if r["exit_code"] != 0 or r["timed_out"]:
            candidates.append((r["seq"], _blocking_from_run(r)))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def _blocking_from_env(e: dict) -> dict:
    f = e.get("failure") or {}
    return {
        "id": e["id"],
        "kind": "env",
        "command": f.get("command"),
        "exit_code": f.get("exit_code"),
        "timed_out": f.get("timed_out"),
        "error": f.get("error"),
    }


def _blocking_from_run(r: dict) -> dict:
    return {
        "id": r["id"],
        "kind": "run",
        "command": r["command"],
        "exit_code": r["exit_code"],
        "timed_out": r["timed_out"],
        "error": r["stderr"]["tail"] or r["stdout"]["tail"],
    }


@locked
def compare_claim(
    study: Study,
    *,
    claim_id: str,
    measured: list[str] | None = None,
    unsourced: list[float] | None = None,
    tol: float | None = None,
    rel_tol: float | None = None,
    close_tol: float | None = None,
    close_rel_tol: float | None = None,
    why: str | None = None,
    could_not_run: bool = False,
    blocking: str | None = None,
) -> dict:
    st = study.state()
    claim = st["claims"].get(claim_id)
    if not claim:
        known = ", ".join(list(st["claims"])[:30]) or "none"
        raise StudyError(f"Unknown claim {claim_id!r}. Known claims: {known}")
    measured = measured or []
    unsourced = unsourced or []
    reasoning: list[str] = []
    lo, hi, target_text = _target(claim)
    center = (lo + hi) / 2
    cid = study.next_id("k", "compare")
    claim_where = f"{claim['source']}" + (f" line {claim['line']}" if claim.get("line") else "")

    base: dict[str, Any] = {
        "id": cid,
        "claim": claim,
        "tolerance_reason": why,
    }

    if could_not_run or (not measured and not unsourced):
        block = _find_blocking(st, blocking)
        if not block and not could_not_run:
            raise StudyError(
                "No measured values given. Pass --measured with a metrics selector, or "
                "--could-not-run (optionally --blocking <env or run id>) if the code did not run."
            )
        reasoning.append(f"Claim: {claim['raw_metric']} {target_text} ({claim_where}).")
        if block:
            what = "Environment setup" if block["kind"] == "env" else "The run"
            how = (
                "timed out"
                if block.get("timed_out")
                else f"exited with code {block.get('exit_code')}"
            )
            reasoning.append(f"{what} {block['id']} {how}: `{block.get('command')}`.")
        else:
            reasoning.append("Marked as could not run by the agent; no failing step was recorded.")
        reasoning.append("No number was measured, so the claim was neither confirmed nor refuted.")
        return study.append(
            "compare",
            {
                **base,
                "verdict": "could_not_run",
                "scope": None,
                "counts_as_reproduction": False,
                "blocking": block,
                "measured": [],
                "stats": None,
                "reasoning": reasoning,
                "headline": f"Could not run: {claim['raw_metric']} {target_text} was not measured.",
            },
        )

    values: list[dict] = []
    for sel in measured:
        for found in resolve_selectors(study, sel):
            v = dict(found)
            v["selector"] = sel
            values.append(v)
    for u in unsourced:
        values.append(
            {
                "value": float(u),
                "selector": None,
                "source": "entered by the agent (not extracted from a recorded log)",
                "unsourced": True,
                "percent": False,
                "name": claim["metric"],
            }
        )

    # Put measured values on the claim's scale (91.3 % versus 0.913).
    ratio = metric_base(claim["metric"]) in RATIO_METRICS or claim["metric"] in RATIO_METRICS
    claim_pct = claim.get("percent") or (ratio and 1.0 < hi <= 100.0)
    scaled_any = False
    for v in values:
        v["value_on_claim_scale"] = v["value"]
        if claim_pct and not v.get("percent") and abs(v["value"]) <= 1.0:
            v["value_on_claim_scale"] = v["value"] * 100
            scaled_any = True
        elif not claim_pct and v.get("percent") and hi <= 1.0:
            v["value_on_claim_scale"] = v["value"] / 100
            scaled_any = True
    if scaled_any:
        reasoning.append(
            "Measured values are fractions and the claim is in percent (or the reverse); "
            "values were rescaled by 100 before comparing."
        )

    xs = [v["value_on_claim_scale"] for v in values]
    n = len(xs)
    mean = statistics.fmean(xs)
    std = statistics.stdev(xs) if n >= 2 else None
    stats = {
        "n": n,
        "mean": mean,
        "std": std,
        "min": min(xs),
        "max": max(xs),
    }

    # Tolerance
    if tol is not None:
        tol_abs, tol_desc = abs(tol), f"±{_fmt(abs(tol))} absolute"
    else:
        r = DEFAULT_REL_TOL if rel_tol is None else abs(rel_tol)
        tol_abs = r * abs(center)
        tol_desc = f"±{_fmt(tol_abs)} ({r * 100:g}% of the claimed value"
        tol_desc += ", default)" if rel_tol is None else ")"
    ptext = _precision_text(claim)
    half_ulp = 0.5 * 10 ** (-decimals(ptext)) if ptext else 0.0
    if half_ulp > tol_abs:
        reasoning.append(
            f"The claim is stated as {ptext}, so any value within ±{_fmt(half_ulp)} rounds to it; "
            f"tolerance widened from {_fmt(tol_abs)} to {_fmt(half_ulp)}."
        )
        tol_abs = half_ulp
        tol_desc = f"±{_fmt(half_ulp)} (rounding of the stated value)"
    if close_tol is not None:
        close_abs = abs(close_tol)
    elif close_rel_tol is not None:
        close_abs = abs(close_rel_tol) * abs(center)
    else:
        close_abs = CLOSE_FACTOR * tol_abs
    close_abs = max(close_abs, tol_abs)

    if lo <= mean <= hi:
        dist = 0.0
    else:
        dist = lo - mean if mean < lo else mean - hi
    signed = (
        mean - center
        if lo == hi
        else (mean - lo if mean < lo else (mean - hi if mean > hi else 0.0))
    )

    # Reasoning text
    reasoning.insert(0, f"Claim: {claim['raw_metric']} {target_text} ({claim_where}).")
    if n == 1:
        v = values[0]
        where = v.get("source", "")
        if v.get("line"):
            where += f" line {v['line']}"
        reasoning.append(f"Measured: {_fmt(xs[0])} from {where}.")
    else:
        reasoning.append(
            f"Measured over {n} runs: mean {_fmt(mean)}, std {_fmt(std)}, "
            f"min {_fmt(stats['min'])}, max {_fmt(stats['max'])}."
        )
    if dist == 0:
        reasoning.append(
            "The measured mean lies inside the claimed range." if lo != hi else "Exact match."
        )
    else:
        rel = f" ({_pct(abs(signed) / abs(center) * 100)} of the claim)" if center else ""
        reasoning.append(f"Distance from the claim: {_fmt(dist)}{rel}.")
    if signed:
        lib = lower_is_better(claim["metric"])
        better = (signed < 0) if lib else (signed > 0)
        reasoning.append(
            f"The measured value is {'better' if better else 'worse'} than claimed "
            f"({'lower' if signed < 0 else 'higher'}, and {'lower' if lib else 'higher'} is better for this metric)."
        )
    reasoning.append(f"Tolerance: {tol_desc}. Close band: ±{_fmt(close_abs)}.")
    if why:
        reasoning.append(f"Why this tolerance: {why}")

    if dist <= tol_abs + 1e-12:
        verdict = "reproduced"
    elif dist <= close_abs + 1e-12:
        verdict = "close"
    else:
        verdict = "not_reproduced"
    if n == 1:
        reasoning.append("Only one run: run-to-run variation was not measured.")
    else:
        if std is not None and std > tol_abs:
            reasoning.append(
                f"The spread across runs (std {_fmt(std)}) is larger than the tolerance, so this "
                "verdict depends on which seeds were run."
            )
        if (
            lo - tol_abs <= stats["max"]
            and stats["min"] <= hi + tol_abs
            and verdict != "reproduced"
        ):
            reasoning.append("At least one individual run landed within tolerance of the claim.")
    runs_used = [v.get("run") for v in values if v.get("run")]
    if len(runs_used) != len(set(runs_used)):
        reasoning.append(
            "Warning: more than one value came from the same run, so n counts values, not "
            "independent runs."
        )

    # Scope and caveats
    run_ids = sorted({v.get("run") for v in values if v.get("run")})
    scopes = {st["runs"][r]["scope"] for r in run_ids if r in st["runs"]}
    scope = "shortened" if scopes & {"shortened", "smoke"} else "full"
    for r in run_ids:
        run = st["runs"].get(r)
        if run and (run["exit_code"] != 0 or run["timed_out"]):
            reasoning.append(
                f"Run {r} did not exit cleanly (exit code {run['exit_code']}); its value is reported "
                "but should be treated with suspicion."
            )
    names = {v.get("name") for v in values if v.get("name")}
    if names and not all(same_quantity(claim["metric"], n) for n in names):
        reasoning.append(
            f"Name check: the claim says {claim['metric']!r}, the measured values are "
            f"{', '.join(sorted(n for n in names if n))}. Confirm they are the same quantity."
        )
    has_unsourced = any(v.get("unsourced") for v in values)
    if has_unsourced:
        reasoning.append(
            "At least one value was entered by hand rather than extracted from a recorded log."
        )
    if scope == "shortened":
        kinds = sorted(scopes & {"shortened", "smoke"})
        notes = "; ".join(
            f"{r}: {st['runs'][r]['note']}" for r in run_ids if st["runs"].get(r, {}).get("note")
        )
        cut = f" What was cut: {notes}." if notes else ""
        if not notes and "shortened" in kinds:
            cut = " What was cut: not stated."
        reasoning.append(
            f"This was a {' and '.join(kinds)} run, so it cannot confirm or refute the full "
            f"claim.{cut}"
        )
    counts = verdict == "reproduced" and scope == "full" and not has_unsourced

    unit = "%" if claim_pct else ""
    measured_text = f"{_fmt(mean)}{unit}" + (f" (mean of {n} runs)" if n > 1 else "")
    if dist == 0:
        gap = "inside the claimed range" if lo != hi else "an exact match"
    else:
        gap = f"{_fmt(dist)} away"
    where = {
        "reproduced": f"{gap}, within the tolerance of ±{_fmt(tol_abs)}",
        "close": f"{gap}: outside the tolerance of ±{_fmt(tol_abs)} but inside the close band "
        f"of ±{_fmt(close_abs)}",
        "not_reproduced": f"{gap}, beyond the close band of ±{_fmt(close_abs)}",
    }[verdict]
    body = f"{claim['raw_metric']} claimed {target_text}, measured {measured_text}, {where}."
    numbers_alone = None
    if scope == "shortened":
        numbers_alone = verdict
        verdict = "inconclusive"
        kind = " and ".join(sorted(scopes & {"shortened", "smoke"}))
        headline = (
            f"Inconclusive ({kind} run): {body} A {kind} run cannot confirm or refute the "
            "full claim; run the configuration the claim refers to with scope full."
        )
    else:
        headline = f"{verdict.replace('_', ' ').capitalize()}: {body}"
        if has_unsourced:
            headline += (
                " Includes a value typed in by hand, so it does not count as a reproduction."
            )
    if not math.isfinite(mean) and verdict != "inconclusive":
        verdict = "not_reproduced"
    return study.append(
        "compare",
        {
            **base,
            "verdict": verdict,
            "numbers_alone": numbers_alone,
            "scope": scope,
            "counts_as_reproduction": counts,
            "blocking": None,
            "measured": values,
            "stats": stats,
            "tolerance": {"abs": tol_abs, "close_abs": close_abs, "description": tol_desc},
            "distance": dist,
            "signed_difference": signed,
            "reasoning": reasoning,
            "headline": headline,
        },
    )
