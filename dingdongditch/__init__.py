"""DingDongDitch — browser execution infrastructure (plan-consuming runtime).

Public API for typed contracts and execute_operation / execute_plan.
Does not include a planner, site explorer, or workflow author.
"""

__version__ = "0.2.0"

from dingdongditch.contract.browser import (
    BrowserChannel,
    BrowserConfig,
    BrowserEngine,
    BrowserProvider,
    BrowserProfile,
    default_browser_config,
)
from dingdongditch.contract.expectation import Expectation, ExpectationType
from dingdongditch.contract.dialog import DialogAction, DialogContract, DialogRequirement, DialogType
from dingdongditch.contract.screenshot import ScreenshotConfig, ScreenshotPolicy
from dingdongditch.contract.operation import (
    Action,
    ActionType,
    FreshnessPolicy,
    KeyPressScope,
    Locator,
    LocatorStrategy,
    Operation,
    SelectMode,
)
from dingdongditch.contract.page_precondition import (
    FragmentPolicy,
    PageCondition,
    PageConditionResult,
    PageConditionResultValue,
    PageConditionType,
    PagePrecondition,
    PagePreconditionEvaluation,
)
from dingdongditch.contract.wait import LoadState, WaitCondition, WaitConditionType
from dingdongditch.contract.plan import (
    CompletionStatus,
    ExecutionPlan,
    FailurePolicy,
    PlanReceipt,
    PlanVerdict,
)
from dingdongditch.contract.receipt import ExecutionReceipt
from dingdongditch.contract.target import (
    AttributeOperator,
    CardinalityPolicy,
    ConstraintType,
    NameMatchMode,
    TargetConstraint,
)
from dingdongditch.contract.verdict import Verdict
from dingdongditch.runtime.executor import execute_operation
from dingdongditch.runtime.plan_executor import execute_plan
from dingdongditch.plan_builder import PlanBuilder
from dingdongditch.inspection import inspect_target, list_dialog_history, observe_page
from dingdongditch.runtime.session import SessionCheckpoint, SessionPhase, SessionStatus
from dingdongditch.runtime.typing_session import (
    TypingFocusPolicy,
    TypingSession,
    TypingSessionConfig,
    TypingSessionResult,
    TypingKeyReceipt,
)
from dingdongditch.contract.download import (
    DownloadArtifact, DownloadArtifactStore, DownloadChecksumPolicy,
    DownloadCollisionPolicy, DownloadCoordinator, DownloadEventMonitor,
    DownloadFailureReason, DownloadLifecycleState, DownloadPageEffectPolicy,
    DownloadMimeSource, DownloadPolicy, DownloadRequest, DownloadResult,
    DownloadTriggerAction,
    SafeFilenameResolver, CollisionResolver, DownloadIntegrityVerifier,
    StagingRecoveryManager,
    TrustedDownloadConfig,
)
from dingdongditch.contract.pointer import PointerMoveRequest, PointerOrigin
from dingdongditch.contract.observation import (
    ObservationFreshnessResult,
    ObservationReference,
    PageObservation,
    PageObservationOptions,
)
from dingdongditch.page_observer import PageObserver

__all__ = [
    "__version__",
    "Operation",
    "Action",
    "ActionType",
    "KeyPressScope",
    "SelectMode",
    "WaitCondition",
    "WaitConditionType",
    "LoadState",
    "Locator",
    "LocatorStrategy",
    "FreshnessPolicy",
    "PageConditionType",
    "FragmentPolicy",
    "PageCondition",
    "PagePrecondition",
    "PageConditionResultValue",
    "PageConditionResult",
    "PagePreconditionEvaluation",
    "Expectation",
    "ExpectationType",
    "DialogType",
    "DialogAction",
    "DialogRequirement",
    "DialogContract",
    "ScreenshotPolicy",
    "ScreenshotConfig",
    "Verdict",
    "ExecutionReceipt",
    "execute_operation",
    "execute_plan",
    "ExecutionPlan",
    "PlanReceipt",
    "PlanVerdict",
    "CompletionStatus",
    "FailurePolicy",
    "TargetConstraint",
    "ConstraintType",
    "AttributeOperator",
    "NameMatchMode",
    "CardinalityPolicy",
    "BrowserConfig",
    "BrowserProvider",
    "BrowserEngine",
    "BrowserChannel",
    "BrowserProfile",
    "default_browser_config",
    "PlanBuilder",
    "inspect_target",
    "list_dialog_history",
    "observe_page",
    "SessionCheckpoint",
    "SessionPhase",
    "SessionStatus",
    "TypingFocusPolicy",
    "TypingSession",
    "TypingSessionConfig",
    "TypingSessionResult",
    "TypingKeyReceipt",
    "DownloadRequest",
    "DownloadPolicy",
    "DownloadCollisionPolicy",
    "DownloadChecksumPolicy",
    "DownloadPageEffectPolicy",
    "DownloadTriggerAction",
    "DownloadLifecycleState",
    "DownloadFailureReason",
    "DownloadMimeSource",
    "DownloadArtifact",
    "DownloadResult",
    "DownloadArtifactStore",
    "SafeFilenameResolver",
    "CollisionResolver",
    "DownloadIntegrityVerifier",
    "DownloadCoordinator",
    "DownloadEventMonitor",
    "StagingRecoveryManager",
    "TrustedDownloadConfig",
    "PointerMoveRequest",
    "PointerOrigin",
    "PageObservation",
    "PageObservationOptions",
    "ObservationReference",
    "ObservationFreshnessResult",
    "PageObserver",
]
