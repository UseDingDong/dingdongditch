"""Stable runtime states and timing limits shared by contracts and executors."""

from __future__ import annotations

from enum import Enum

MIN_PLAN_TIMEOUT_MS = 100
MAX_PLAN_TIMEOUT_MS_CEILING = 3_600_000


class ExecutionStatus(str, Enum):
    NOT_STARTED = "not_started"
    VALIDATION_FAILED = "validation_failed"
    BROWSER_SETUP_FAILED = "browser_setup_failed"
    PAGE_PRECONDITION_FAILED = "page_precondition_failed"
    COMPLETED = "completed"
    FAILED = "failed"


class RuntimeFailureKind(str, Enum):
    CONTRADICTORY_BROWSER_CONFIG = "contradictory_browser_config"
    PAGE_PRECONDITION_MISMATCH = "page_precondition_mismatch"
    PAGE_PRECONDITION_INDETERMINATE = "page_precondition_indeterminate"
    PLAN_DEADLINE_EXPIRED = "plan_deadline_expired"
    ACTION_DISPATCH_FAILED = "action_dispatch_failed"
    OBSERVATION_FAILED = "observation_failed"
    VERIFICATION_FAILED = "verification_failed"
    INTERNAL_RUNTIME_ERROR = "internal_runtime_error"


class LifecycleState(str, Enum):
    NOT_STARTED = "not_started"
    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    CRASHED = "crashed"


class CleanupOutcome(str, Enum):
    NOT_REQUIRED = "not_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    HOST_OWNED = "host_owned"


class DeadlinePhase(str, Enum):
    BACKEND_START = "backend_start"
    PAGE_PRECONDITION = "page_precondition"
    PRE_OBSERVATION = "pre_observation"
    TARGET_RESOLUTION = "target_resolution"
    DISPATCH = "dispatch"
    WAIT = "wait"
    POST_OBSERVATION = "post_observation"
    VERIFICATION = "verification"
    RECEIPT = "receipt"
    CLEANUP = "cleanup"
