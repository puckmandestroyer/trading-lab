"""Non-authoritative primitives and the explicitly configured observed runtime."""

from .model import (
    OBSERVABILITY_CONTRACT_VERSION, ObservabilityError, ObservabilityValidationError,
    ObservabilityProjectionError, ObservabilityStorageError, ObservabilitySeverity,
    ObservabilityHealthLevel, EvidenceFreshness, ObservabilityEventType, ObservabilityEvent,
    new_run_id, make_event, event_from_json,
)
from .projection import (project_retained_events, project_checkpoint_transition,
                         cycle_completed, scheduler_exited, critical_failure, process_started,
                         process_stopped, scheduler_started, observability_degraded)
from .health import HealthSnapshot, HealthReason, build_health_snapshot, health_from_json, freshness
from .storage import ObservabilityStorage, EventReadResult, safe_append_event, safe_write_health
from .runtime_integration import run_observed_hourly_scheduler

__all__ = [
    "OBSERVABILITY_CONTRACT_VERSION", "ObservabilityError", "ObservabilityValidationError",
    "ObservabilityProjectionError", "ObservabilityStorageError", "ObservabilitySeverity",
    "ObservabilityHealthLevel", "EvidenceFreshness", "ObservabilityEventType", "ObservabilityEvent",
    "new_run_id", "make_event", "event_from_json", "project_retained_events", "project_checkpoint_transition",
    "cycle_completed", "scheduler_exited", "critical_failure", "HealthSnapshot", "HealthReason",
    "process_started", "process_stopped", "scheduler_started", "observability_degraded",
    "build_health_snapshot", "health_from_json", "freshness", "ObservabilityStorage", "EventReadResult",
    "safe_append_event", "safe_write_health",
    "run_observed_hourly_scheduler",
]
