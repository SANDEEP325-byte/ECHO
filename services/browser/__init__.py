"""ECHO Browser Automation Package.

Phase 5A: Browser Security Policy & URL Sandbox.
"""

from services.browser.policy import (
    BrowserPolicyCheckResult,
    BrowserPolicyErrorCode,
    BrowserSecurityPolicy,
    BrowserSecurityPolicyError,
    DNSResolver,
    HostClassification,
    browser_security_policy,
)

__all__ = [
    "BrowserPolicyCheckResult",
    "BrowserPolicyErrorCode",
    "BrowserSecurityPolicy",
    "BrowserSecurityPolicyError",
    "DNSResolver",
    "HostClassification",
    "browser_security_policy",
]
