"""ECHO Browser Automation Package.

Phase 5A: Browser Security Policy & URL Sandbox.
Phase 5B: BrowserService & BrowserSession Lifecycle Management.
Phase 5C: Safe Browser Inspection & Navigation.
Phase 5D: Controlled Browser Interaction.
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
from services.browser.operations import (
    BrowserOperations,
    browser_operations,
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
from services.browser.runner import (
    BrowserAsyncRunner,
    browser_runner,
)
from services.browser.service import (
    BrowserService,
    BrowserServiceState,
    browser_service,
)
from services.browser.session import (
    BrowserSession,
    BrowserSessionState,
)

__all__ = [
    "BrowserAsyncRunner",
    "BrowserBinaryMissingError",
    "BrowserConfigurationError",
    "BrowserError",
    "BrowserLifecycleError",
    "BrowserOperations",
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
    "browser_operations",
    "browser_runner",
    "browser_security_policy",
    "browser_service",
]
