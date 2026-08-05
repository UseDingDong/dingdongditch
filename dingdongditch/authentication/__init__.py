"""Authentication/session infrastructure capability.

Browser authentication state is owned here; runtime operations only consume the
capability exposed by the browser backend.
"""

from .capability import AuthenticationCapability
from .callbacks import AuthEvent, AuthEventType, AuthenticationCallbacks
from .errors import AuthenticationError, AuthenticationFailureKind
from .profiles import ProfileInfo, ProfileManager, profile_root
from .secrets import MappingSecretProvider, SecretProvider, SecretValue, redact

__all__ = [
    "AuthEvent", "AuthEventType", "AuthenticationCallbacks",
    "AuthenticationCapability", "AuthenticationError",
    "AuthenticationFailureKind", "MappingSecretProvider", "ProfileInfo",
    "ProfileManager", "SecretProvider", "SecretValue", "profile_root", "redact",
]
