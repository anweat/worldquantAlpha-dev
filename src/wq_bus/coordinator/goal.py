"""Goal expression evaluator + tasks.yaml loader for the R6-C Coordinator.

A goal expression is a small DSL (see config/tasks.yaml header for grammar):
    leaf:  {<counter>: {<op>: <value>}}     op ∈ >=,>,<=,<,==,!=
    and :  {and: [expr, ...]}
    or  :  {or:  [expr, ...]}
    not :  {not: expr}

Pure module — no I/O except yaml load (cached).
"""
from __future__ import annotations

import operator as _op
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional


_OPS = {
    ">=": _op.ge, ">": _op.gt,
    "<=": _op.le, "<": _op.lt,
    "==": _op.eq, "!=": _op.ne,
}


def _coerce(v: Any) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def evaluate(expr: Any, progress: dict) -> bool:
    """Return True iff *expr* is satisfied against the *progress* dict.

    Unknown operators / malformed branches return False (fail-closed) so a
    typo in tasks.yaml never accidentally satisfies a goal.
    """
    if expr is None:
        return False
    if isinstance(expr, bool):
        return expr
    if not isinstance(expr, dict) or not expr:
        return False
    if "and" in expr:
        return all(evaluate(e, progress) for e in (expr["and"] or []))
    if "or" in expr:
        return any(evaluate(e, progress) for e in (expr["or"] or []))
    if "not" in expr:
        return not evaluate(expr["not"], progress)
    if len(expr) != 1:
        # Multiple keys at top level → implicit AND for ergonomics.
        return all(evaluate({k: v}, progress) for k, v in expr.items())
    counter, body = next(iter(expr.items()))
    if not isinstance(body, dict) or not body:
        return False
    if len(body) != 1:
        return all(evaluate({counter: {k: v}}, progress) for k, v in body.items())
    op_name, target = next(iter(body.items()))
    op = _OPS.get(op_name)
    if op is None:
        return False
    actual = progress.get(counter, 0)
    try:
        return bool(op(_coerce(actual), _coerce(target)))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# tasks.yaml dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PipelineStep:
    id: str
    emit: Optional[str] = None
    payload: Optional[dict] = None
    wait_for: Optional[str] = None
    wait_for_any: Optional[tuple[str, ...]] = None
    collect_until: Optional[dict] = None
    timeout: int = 300
    condition: Any = None


@dataclass(frozen=True)
class PipelineDef:
    name: str
    description: str
    steps: tuple[PipelineStep, ...]


@dataclass(frozen=True)
class FailurePolicy:
    soft: tuple[str, ...]
    hard: tuple[str, ...]
    abort_after_consecutive_soft: int


@dataclass(frozen=True)
class TaskDef:
    name: str
    pipeline: str
    description: str
    goal: dict
    failure_policy: FailurePolicy
    max_iterations: int
    wall_time_secs: int


def _step_from_dict(d: dict) -> PipelineStep:
    waf = d.get("wait_for_any")
    if waf is not None and not isinstance(waf, (list, tuple)):
        waf = [waf]
    return PipelineStep(
        id=str(d["id"]),
        emit=d.get("emit"),
        payload=d.get("payload"),
        wait_for=d.get("wait_for"),
        wait_for_any=tuple(waf) if waf else None,
        collect_until=d.get("collect_until"),
        timeout=int(d.get("timeout", 300)),
        condition=d.get("condition"),
    )


def _policy_from_dict(d: Optional[dict], defaults: dict) -> FailurePolicy:
    src = {**(defaults.get("failure_policy") or {}), **(d or {})}
    return FailurePolicy(
        soft=tuple(src.get("soft", []) or []),
        hard=tuple(src.get("hard", []) or []),
        abort_after_consecutive_soft=int(src.get("abort_after_consecutive_soft", 5)),
    )


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    try:
        from wq_bus.utils.yaml_loader import load_yaml
        return load_yaml("tasks") or {}
    except Exception:
        return {}


def reload() -> None:
    """Drop cache; re-read tasks.yaml on next call."""
    _load_raw.cache_clear()


def get_pipeline(name: str) -> Optional[PipelineDef]:
    pipelines = (_load_raw().get("pipelines") or {})
    p = pipelines.get(name)
    if not p:
        return None
    steps = tuple(_step_from_dict(s) for s in (p.get("steps") or []))
    return PipelineDef(name=name, description=str(p.get("description", "")), steps=steps)


def get_task(name: str) -> Optional[TaskDef]:
    raw = _load_raw()
    defaults = raw.get("defaults") or {}
    tasks = raw.get("tasks") or {}
    t = tasks.get(name)
    if not t:
        return None
    return TaskDef(
        name=name,
        pipeline=str(t["pipeline"]),
        description=str(t.get("description", "")),
        goal=dict(t.get("goal") or {}),
        failure_policy=_policy_from_dict(t.get("failure_policy"), defaults),
        max_iterations=int(t.get("max_iterations", defaults.get("max_iterations", 20))),
        wall_time_secs=int(t.get("wall_time_secs", defaults.get("wall_time_secs", 7200))),
    )


def list_pipelines() -> list[str]:
    return sorted((_load_raw().get("pipelines") or {}).keys())


def list_tasks() -> list[str]:
    return sorted((_load_raw().get("tasks") or {}).keys())


def classify_failure(reason: str, policy: FailurePolicy) -> str:
    """Return 'soft' | 'hard' | 'unknown' for a TRACE_FAILED reason string."""
    r = (reason or "").upper()
    for code in policy.hard:
        if code and code.upper() in r:
            return "hard"
    for code in policy.soft:
        if code and code.upper() in r:
            return "soft"
    return "unknown"


def validate() -> list[str]:
    """Return validation errors (empty list = OK)."""
    errors: list[str] = []
    raw = _load_raw()
    pipelines = raw.get("pipelines") or {}
    tasks = raw.get("tasks") or {}
    pipeline_names = set(pipelines.keys())
    for pname, pdef in pipelines.items():
        steps = pdef.get("steps") or []
        if not steps:
            errors.append(f"pipeline {pname!r}: has no steps")
        seen_ids: set[str] = set()
        for i, s in enumerate(steps):
            if not isinstance(s, dict) or "id" not in s:
                errors.append(f"pipeline {pname!r} step #{i}: missing id")
                continue
            sid = s["id"]
            if sid in seen_ids:
                errors.append(f"pipeline {pname!r} step {sid}: duplicate id")
            seen_ids.add(sid)
            waits = sum(int(bool(s.get(k))) for k in ("wait_for", "wait_for_any", "collect_until"))
            if waits > 1:
                errors.append(
                    f"pipeline {pname!r} step {sid}: only one of "
                    "wait_for/wait_for_any/collect_until allowed"
                )
    for tname, tdef in tasks.items():
        if "pipeline" not in tdef:
            errors.append(f"task {tname!r}: missing pipeline")
            continue
        if tdef["pipeline"] not in pipeline_names:
            errors.append(f"task {tname!r}: pipeline {tdef['pipeline']!r} not defined")
        if "goal" not in tdef:
            errors.append(f"task {tname!r}: missing goal")
    return errors
