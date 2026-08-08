"""Authentication/session infrastructure capability.

Browser authentication state is owned here; runtime operations only consume the
capability exposed by the browser backend.
"""

from .capability import AuthenticationCapability
from .callbacks import AuthEvent, AuthEventType, AuthenticationCallbacks
from .errors import AuthenticationError, AuthenticationFailureKind
from .profiles import ProfileInfo, ProfileManager, profile_root
from .secrets import (
    MappingSecretProvider,
    SecretProvider,
    SecretReference,
    SecretResolutionReceipt,
    SecretValue,
    redact,
)
from .portable_state import (
    PORTABLE_STATE_SCHEMA_VERSION,
    PortableStateFeature,
    PortableStatePolicy,
    PortableStateReceipt,
)
from .webauthn import (
    CallbackWebAuthnTransport,
    WebAuthnParticipationReceipt,
    WebAuthnParticipationRequest,
    WebAuthnParticipationStatus,
    WebAuthnTransport,
    WebAuthnTransportEvent,
    WebAuthnTransportResult,
)

__all__ = [
    "AuthEvent", "AuthEventType", "AuthenticationCallbacks",
    "AuthenticationCapability", "AuthenticationError",
    "AuthenticationFailureKind", "MappingSecretProvider", "ProfileInfo",
    "ProfileManager", "SecretProvider", "SecretReference", "SecretResolutionReceipt",
    "SecretValue", "PORTABLE_STATE_SCHEMA_VERSION", "PortableStateFeature",
    "PortableStatePolicy", "PortableStateReceipt", "profile_root", "redact",
    "WebAuthnParticipationRequest", "WebAuthnParticipationReceipt",
    "WebAuthnParticipationStatus", "WebAuthnTransport", "WebAuthnTransportEvent",
    "WebAuthnTransportResult", "CallbackWebAuthnTransport",
]
