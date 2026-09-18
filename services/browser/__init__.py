"""ECHO Browser Automation Package.

Phase 5A: Browser Security Policy & URL Sandbox.
Phase 5B: BrowserService & BrowserSession Lifecycle Management.
"""

from services.browser.errors import (
    BrowserBinaryMissingError,
    BrowserConfigurationError,
    BrowserError,
    BrowserLifecycleError,
    BrowserSessionClosedError,
    BrowserSessionCreationError,
    BrowserSessionError,
    BrowserSessionLimitError,
    BrowserStartupError,
    BrowserTimeoutError,
    BrowserUnavailableError,
)
from services.browser.policy import (
    BrowserPolicyCheckResult,
    BrowserPolicyErrorCode,
    BrowserSecurityPolicy,
    BrowserSecurityPolicyError,
    DNSResolver,
    HostClassification,
    browser_security_policy,
)
from services.browser.service import (
    BrowserService,
    BrowserServiceState,
)
from services.browser.session import (
    BrowserSession,
    BrowserSessionState,
)

__all__ = [
    "BrowserBinaryMissingError",
    "BrowserConfigurationError",
    "BrowserError",
    "BrowserLifecycleError",
    "BrowserPolicyCheckResult",
    "BrowserPolicyErrorCode",
    "BrowserSecurityPolicy",
    "BrowserSecurityPolicyError",
    "BrowserService",
    "BrowserServiceState",
    "BrowserSession",
    "BrowserSessionClosedError",
    "BrowserSessionCreationError",
    "BrowserSessionError",
    "BrowserSessionLimitError",
    "BrowserSessionState",
    "BrowserStartupError",
    "BrowserTimeoutError",
    "BrowserUnavailableError",
    "DNSResolver",
    "HostClassification",
    "browser_security_policy",
]
