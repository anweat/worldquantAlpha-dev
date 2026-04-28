"""Coordinator package — drives Tasks (outer goal loop) over Pipelines (inner trace).

Submodules:
  goal     — goal expression evaluator + tasks.yaml loader (pure, no I/O)
  runner   — async Coordinator agent (subscribes bus events, owns task lifecycle)
"""
from wq_bus.coordinator.goal import (  # re-export
    evaluate,
    get_pipeline,
    get_task,
    list_pipelines,
    list_tasks,
    reload,
    validate,
    PipelineDef,
    PipelineStep,
    TaskDef,
    FailurePolicy,
)
from wq_bus.coordinator.runner import CoordinatorAgent

__all__ = [
    "evaluate",
    "get_pipeline",
    "get_task",
    "list_pipelines",
    "list_tasks",
    "reload",
    "validate",
    "PipelineDef",
    "PipelineStep",
    "TaskDef",
    "FailurePolicy",
    "CoordinatorAgent",
]
