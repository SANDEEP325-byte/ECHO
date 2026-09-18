"""Tests for ECHO BrowserSecurityPolicy and URL Sandbox (Phase 5A).

All tests are 100% offline, deterministic, and isolated.
Mock DNS resolvers are injected to prevent live network access.
"""

import pytest

from packages.interfaces.security import PermissionDecision, RiskLevel
from services.browser.policy import (
    BrowserPolicyErrorCode,
    BrowserSecurityPolicy,
    BrowserSecurityPolicyError,
    HostClassification,
    browser_security_policy,
)

# Mock DNS lookup table for offline, deterministic tests
MOCK_DNS_TABLE: dict[str, list[str]] = {
    "example.com": ["93.184.216.34"],
    "docs.example.com": ["93.184.216.35"],
    "sub.example.com": ["93.184.216.36"],
    "dualstack.example.com": ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"],
    "poisoned.example.com": ["93.184.216.34", "127.0.0.1"],
    "poisoned-private.example.com": ["93.184.216.34", "10.0.0.5"],
    "internal.example.com": ["192.168.1.100"],
    "loopback.example.com": ["127.0.0.1"],
    "metadata.example.com": ["169.254.169.254"],
    "linklocal.example.com": ["169.254.1.1"],
    "ipv6-ula.example.com": ["fc00::1"],
    "other.org": ["93.184.216.34"],
    "evil-example.com": ["93.184.216.34"],
    "trusted.net": ["198.51.100.1"],
}


def mock_dns_resolver(host: str) -> list[str]:
    """Offline mock DNS resolver."""
    clean = host.lower().rstrip(".")
    return MOCK_DNS_TABLE.get(clean, [])


def failing_dns_resolver(host: str) -> list[str]:
    """Simulates DNS resolution error / NXDOMAIN."""
    return []


def erroring_dns_resolver(host: str) -> list[str]:
    """Simulates resolver raising an exception."""
    raise OSError("Network is unreachable (simulated)")


@pytest.fixture
def policy() -> BrowserSecurityPolicy:
    """Default offline BrowserSecurityPolicy with mock DNS resolver."""
    return BrowserSecurityPolicy(dns_resolver=mock_dns_resolver)


@pytest.fixture
def allowlist_policy() -> BrowserSecurityPolicy:
    """BrowserSecurityPolicy enforcing domain allowlist."""
    return BrowserSecurityPolicy(
        allowed_domains=["example.com"],
        dns_resolver=mock_dns_resolver,
    )


@pytest.fixture
def blocklist_policy() -> BrowserSecurityPolicy:
    """BrowserSecurityPolicy enforcing domain blocklist."""
    return BrowserSecurityPolicy(
        blocked_domains=["malicious.com"],
        dns_resolver=mock_dns_resolver,
    )


# ==============================================================================
# 1. Valid URLs
# ==============================================================================


def test_valid_http_url(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("http://example.com")
    assert result.allowed is True
    assert result.decision == PermissionDecision.ALLOW
    assert result.risk_level == RiskLevel.SAFE
    assert result.reason_code is None
    assert result.hostname == "example.com"
    assert result.scheme == "http"
    assert result.classification == HostClassification.PUBLIC


def test_valid_https_url(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://example.com")
    assert result.allowed is True
    assert result.decision == PermissionDecision.ALLOW
    assert result.scheme == "https"


def test_valid_url_with_path(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://example.com/docs/api/v1")
    assert result.allowed is True
    assert result.normalized_url == "https://example.com/docs/api/v1"


def test_valid_url_with_query(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://example.com/search?q=security&page=1")
    assert result.allowed is True
    assert result.normalized_url == "https://example.com/search?q=security&page=1"


def test_valid_url_with_fragment(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://example.com/page#overview")
    assert result.allowed is True
    assert result.normalized_url == "https://example.com/page#overview"


def test_valid_url_with_explicit_standard_ports(policy: BrowserSecurityPolicy) -> None:
    res_80 = policy.validate_url("http://example.com:80/")
    assert res_80.allowed is True
    assert res_80.port == 80

    res_443 = policy.validate_url("https://example.com:443/")
    assert res_443.allowed is True
    assert res_443.port == 443


def test_valid_url_with_allowed_alternate_port(policy: BrowserSecurityPolicy) -> None:
    res_8080 = policy.validate_url("http://example.com:8080/")
    assert res_8080.allowed is True
    assert res_8080.port == 8080


def test_valid_public_ip_literal(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://93.184.216.34/")
    assert result.allowed is True
    assert result.classification == HostClassification.PUBLIC
    assert result.hostname == "93.184.216.34"


def test_valid_public_ipv6_literal(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://[2606:2800:220:1:248:1893:25c8:1946]/")
    assert result.allowed is True
    assert result.classification == HostClassification.PUBLIC


def test_valid_url_normalization_case_and_trailing_dot(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("hTTps://ExAMPle.COM./path")
    assert result.allowed is True
    assert result.hostname == "example.com"
    assert result.normalized_url == "https://example.com/path"


def test_validate_url_or_raise_success(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url_or_raise("https://example.com")
    assert result.allowed is True


# ==============================================================================
# 2. Dangerous URL Schemes
# ==============================================================================


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/System32/calc.exe",
        "file:///etc/passwd",
        "data:text/html,<script>alert(1)</script>",
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "  javascript:alert(1)",
        "blob:https://example.com/550e8400-e29b-41d4-a716-446655440000",
        "about:blank",
        "chrome://settings",
        "chrome-extension://abcdefghijklmno/page.html",
        "edge://flags",
        "view-source:https://example.com",
        "ftp://ftp.example.com/file.txt",
        "ws://example.com/socket",
        "wss://example.com/secure-socket",
    ],
)
def test_dangerous_schemes_blocked(policy: BrowserSecurityPolicy, url: str) -> None:
    result = policy.validate_url(url)
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.reason_code == BrowserPolicyErrorCode.UNSUPPORTED_SCHEME


def test_validate_url_or_raise_on_dangerous_scheme(policy: BrowserSecurityPolicy) -> None:
    with pytest.raises(BrowserSecurityPolicyError) as exc_info:
        policy.validate_url_or_raise("file:///etc/passwd")
    assert exc_info.value.error_code == BrowserPolicyErrorCode.UNSUPPORTED_SCHEME


# ==============================================================================
# 3. Localhost and Loopback Blocking (including alternate IP notations)
# ==============================================================================


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://localhost.",
        "http://LocalHost",
        "http://sub.localhost",
        "http://127.0.0.1",
        "http://127.0.0.2",
        "http://127.123.45.67",
        "http://127.255.255.255",
        "http://0.0.0.0",
        "http://[::1]",
        "http://[::]",
        "http://[::ffff:127.0.0.1]",
        "http://[::ffff:7f00:1]",
        # Decimal IPv4
        "http://2130706433/",
        # Hexadecimal IPv4
        "http://0x7f000001/",
        "http://0x7f.0.0.1/",
        # Octal-like IPv4
        "http://0177.0.0.1/",
        # Dotted shorthand
        "http://127.1/",
        "http://127.0.1/",
    ],
)
def test_localhost_and_loopback_blocked(policy: BrowserSecurityPolicy, url: str) -> None:
    result = policy.validate_url(url)
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.reason_code == BrowserPolicyErrorCode.LOOPBACK_BLOCKED
    assert result.classification == HostClassification.LOOPBACK


# ==============================================================================
# 4. Private Network (RFC 1918 & IPv6 ULA) Blocking
# ==============================================================================


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/",
        "http://10.254.254.254/",
        "http://172.16.0.1/",
        "http://172.31.255.255/",
        "http://192.168.0.1/",
        "http://192.168.1.100/",
        "http://[fc00::1]/",
        "http://[fd00::1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://[::ffff:192.168.1.1]/",
    ],
)
def test_private_network_ips_blocked(policy: BrowserSecurityPolicy, url: str) -> None:
    result = policy.validate_url(url)
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.reason_code == BrowserPolicyErrorCode.PRIVATE_IP_BLOCKED
    assert result.classification == HostClassification.PRIVATE


# ==============================================================================
# 5. Link-Local and Cloud Metadata Blocking
# ==============================================================================


@pytest.mark.parametrize(
    "url,expected_code,expected_class",
    [
        (
            "http://169.254.169.254/latest/meta-data/",
            BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED,
            HostClassification.METADATA,
        ),
        (
            "http://[fd00:ec2::254]/",
            BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED,
            HostClassification.METADATA,
        ),
        (
            "http://metadata.google.internal/",
            BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED,
            HostClassification.METADATA,
        ),
        (
            "http://instance-data/",
            BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED,
            HostClassification.METADATA,
        ),
        (
            "http://169.254.1.1/",
            BrowserPolicyErrorCode.LINK_LOCAL_BLOCKED,
            HostClassification.LINK_LOCAL,
        ),
        (
            "http://[fe80::1]/",
            BrowserPolicyErrorCode.LINK_LOCAL_BLOCKED,
            HostClassification.LINK_LOCAL,
        ),
        (
            "http://[::ffff:169.254.169.254]/",
            BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED,
            HostClassification.METADATA,
        ),
        # Decimal representation of 169.254.169.254
        (
            "http://2852039166/",
            BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED,
            HostClassification.METADATA,
        ),
        # Hex representation of 169.254.169.254
        (
            "http://0xa9fea9fe/",
            BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED,
            HostClassification.METADATA,
        ),
    ],
)
def test_metadata_and_link_local_blocked(
    policy: BrowserSecurityPolicy,
    url: str,
    expected_code: BrowserPolicyErrorCode,
    expected_class: HostClassification,
) -> None:
    result = policy.validate_url(url)
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.reason_code == expected_code
    assert result.classification == expected_class


# ==============================================================================
# 6. Embedded Credentials Rejection & Non-Leakage
# ==============================================================================


@pytest.mark.parametrize(
    "url,secret_values",
    [
        ("https://myuser:mypassword@example.com/", ["mypassword", "myuser"]),
        ("https://admin:supersecret123@example.com:443/", ["supersecret123", "admin"]),
        ("https://john_doe@example.com/", ["john_doe"]),
        ("https://token:ghp_1234567890@example.com/", ["ghp_1234567890", "token"]),
    ],
)
def test_embedded_credentials_blocked_without_leakage(
    policy: BrowserSecurityPolicy,
    url: str,
    secret_values: list[str],
) -> None:
    result = policy.validate_url(url)
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.reason_code == BrowserPolicyErrorCode.EMBEDDED_CREDENTIALS

    # Critical security check: credentials must NEVER appear in reason or logs
    for secret in secret_values:
        assert secret not in result.reason
        if result.normalized_url:
            assert secret not in result.normalized_url


# ==============================================================================
# 7. Malformed Inputs
# ==============================================================================


@pytest.mark.parametrize(
    "url,expected_code",
    [
        ("", BrowserPolicyErrorCode.INVALID_URL),
        ("   ", BrowserPolicyErrorCode.INVALID_URL),
        ("https://", BrowserPolicyErrorCode.MISSING_HOSTNAME),
        ("https://:443", BrowserPolicyErrorCode.MISSING_HOSTNAME),
        ("https://example.com:abc/", BrowserPolicyErrorCode.INVALID_PORT),
        ("https://example.com:99999/", BrowserPolicyErrorCode.INVALID_PORT),
        ("https://example.com:0/", BrowserPolicyErrorCode.INVALID_PORT),
        ("https://example.com:-1/", BrowserPolicyErrorCode.INVALID_PORT),
        ("https://[::ffff:127.1]/", BrowserPolicyErrorCode.INVALID_URL),
        ("https://example.com\r\n/path", BrowserPolicyErrorCode.INVALID_URL),
        ("https://example.com\x00/", BrowserPolicyErrorCode.INVALID_URL),
        ("not_a_url", BrowserPolicyErrorCode.UNSUPPORTED_SCHEME),
    ],
)
def test_malformed_urls_fail_closed(
    policy: BrowserSecurityPolicy,
    url: str,
    expected_code: BrowserPolicyErrorCode,
) -> None:
    result = policy.validate_url(url)
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.reason_code == expected_code


# ==============================================================================
# 8. Port Policy
# ==============================================================================


def test_non_standard_ports_blocked_by_default(policy: BrowserSecurityPolicy) -> None:
    # Port 22 (SSH), 25 (SMTP), 6379 (Redis)
    for p in [22, 25, 6379, 3306]:
        result = policy.validate_url(f"https://example.com:{p}/")
        assert result.allowed is False
        assert result.decision == PermissionDecision.BLOCK
        assert result.reason_code == BrowserPolicyErrorCode.NON_STANDARD_PORT_BLOCKED


def test_allow_non_standard_ports_option() -> None:
    permissive_policy = BrowserSecurityPolicy(
        allow_non_standard_ports=True,
        dns_resolver=mock_dns_resolver,
    )
    result = permissive_policy.validate_url("https://example.com:9000/")
    assert result.allowed is True
    assert result.port == 9000


def test_custom_allowed_ports() -> None:
    custom_policy = BrowserSecurityPolicy(
        allowed_ports=[80, 443, 3000],
        dns_resolver=mock_dns_resolver,
    )
    res_3000 = custom_policy.validate_url("http://example.com:3000/")
    assert res_3000.allowed is True
    assert res_3000.port == 3000

    res_8080 = custom_policy.validate_url("http://example.com:8080/")
    assert res_8080.allowed is False
    assert res_8080.reason_code == BrowserPolicyErrorCode.NON_STANDARD_PORT_BLOCKED


# ==============================================================================
# 9. Domain Allowlist & Blocklist
# ==============================================================================


def test_domain_allowlist_exact_and_subdomain(allowlist_policy: BrowserSecurityPolicy) -> None:
    # Exact domain
    res_exact = allowlist_policy.validate_url("https://example.com/home")
    assert res_exact.allowed is True

    # Subdomain allowed
    res_sub = allowlist_policy.validate_url("https://docs.example.com/guide")
    assert res_sub.allowed is True

    # Sub-subdomain allowed
    res_sub2 = allowlist_policy.validate_url("https://sub.example.com/api")
    assert res_sub2.allowed is True


def test_domain_allowlist_rejects_evil_suffix(allowlist_policy: BrowserSecurityPolicy) -> None:
    # Critical security test: evil-example.com must NOT match example.com
    result = allowlist_policy.validate_url("https://evil-example.com/")
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.reason_code == BrowserPolicyErrorCode.DOMAIN_NOT_ALLOWED


def test_domain_allowlist_rejects_unrelated_domain(allowlist_policy: BrowserSecurityPolicy) -> None:
    result = allowlist_policy.validate_url("https://other.org/")
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.reason_code == BrowserPolicyErrorCode.DOMAIN_NOT_ALLOWED


def test_domain_allowlist_case_and_trailing_dot(allowlist_policy: BrowserSecurityPolicy) -> None:
    result = allowlist_policy.validate_url("https://EXAMPLE.COM./page")
    assert result.allowed is True
    assert result.hostname == "example.com"


def test_domain_blocklist(blocklist_policy: BrowserSecurityPolicy) -> None:
    # Direct blocked domain
    res_direct = blocklist_policy.validate_url("https://malicious.com/")
    assert res_direct.allowed is False
    assert res_direct.reason_code == BrowserPolicyErrorCode.DOMAIN_BLOCKED

    # Subdomain of blocked domain
    res_sub = blocklist_policy.validate_url("https://evil.malicious.com/")
    assert res_sub.allowed is False
    assert res_sub.reason_code == BrowserPolicyErrorCode.DOMAIN_BLOCKED


def test_confirm_unlisted_domains() -> None:
    confirm_policy = BrowserSecurityPolicy(
        allowed_domains=["example.com"],
        confirm_unlisted_domains=True,
        dns_resolver=mock_dns_resolver,
    )
    result = confirm_policy.validate_url("https://trusted.net/page")
    assert result.allowed is False
    assert result.decision == PermissionDecision.CONFIRM
    assert result.risk_level == RiskLevel.MODERATE
    assert result.reason_code == BrowserPolicyErrorCode.DOMAIN_CONFIRMATION_REQUIRED


# ==============================================================================
# 10. DNS Resolution & SSRF Protection via DNS
# ==============================================================================


def test_dns_resolution_resolves_to_private_ip_fails_closed(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://internal.example.com/")
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.reason_code == BrowserPolicyErrorCode.UNSAFE_RESOLVED_IP
    assert result.classification == HostClassification.PRIVATE


def test_dns_resolution_resolves_to_loopback_fails_closed(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://loopback.example.com/")
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.reason_code == BrowserPolicyErrorCode.UNSAFE_RESOLVED_IP
    assert result.classification == HostClassification.LOOPBACK


def test_dns_resolution_resolves_to_metadata_fails_closed(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_url("https://metadata.example.com/")
    assert result.allowed is False
    assert result.reason_code == BrowserPolicyErrorCode.UNSAFE_RESOLVED_IP
    assert result.classification == HostClassification.METADATA


def test_dns_multiple_ips_one_unsafe_fails_closed(policy: BrowserSecurityPolicy) -> None:
    # Poisoned DNS returning public IP + 127.0.0.1
    result = policy.validate_url("https://poisoned.example.com/")
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.reason_code == BrowserPolicyErrorCode.UNSAFE_RESOLVED_IP


def test_dns_multiple_ips_one_private_fails_closed(policy: BrowserSecurityPolicy) -> None:
    # Poisoned DNS returning public IP + 10.0.0.5
    result = policy.validate_url("https://poisoned-private.example.com/")
    assert result.allowed is False
    assert result.reason_code == BrowserPolicyErrorCode.UNSAFE_RESOLVED_IP


def test_dns_resolution_failure_fails_closed() -> None:
    failing_policy = BrowserSecurityPolicy(dns_resolver=failing_dns_resolver)
    result = failing_policy.validate_url("https://nonexistent-domain-xyz.com/")
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.reason_code == BrowserPolicyErrorCode.DNS_RESOLUTION_FAILED


def test_dns_resolver_exception_fails_closed() -> None:
    erroring_policy = BrowserSecurityPolicy(dns_resolver=erroring_dns_resolver)
    result = erroring_policy.validate_url("https://example.com/")
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.reason_code == BrowserPolicyErrorCode.DNS_RESOLUTION_FAILED


# ==============================================================================
# 11. Redirect Validation Behavior
# ==============================================================================


def test_validate_redirect_to_safe_target(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_redirect(
        original_url="https://example.com/login",
        redirect_url="https://example.com/dashboard",
    )
    assert result.allowed is True
    assert result.decision == PermissionDecision.ALLOW


def test_validate_redirect_to_private_network_fails_closed(policy: BrowserSecurityPolicy) -> None:
    # Redirect target must NOT inherit trust
    result = policy.validate_redirect(
        original_url="https://example.com/out",
        redirect_url="http://192.168.1.1/admin",
    )
    assert result.allowed is False
    assert result.decision == PermissionDecision.BLOCK
    assert result.reason_code == BrowserPolicyErrorCode.PRIVATE_IP_BLOCKED


def test_validate_redirect_to_metadata_fails_closed(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_redirect(
        original_url="https://example.com/out",
        redirect_url="http://169.254.169.254/latest/meta-data/",
    )
    assert result.allowed is False
    assert result.reason_code == BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED


def test_validate_redirect_to_dangerous_scheme_fails_closed(policy: BrowserSecurityPolicy) -> None:
    result = policy.validate_redirect(
        original_url="https://example.com/out",
        redirect_url="file:///etc/passwd",
    )
    assert result.allowed is False
    assert result.reason_code == BrowserPolicyErrorCode.UNSUPPORTED_SCHEME


def test_validate_redirect_to_unallowed_domain_fails_closed(
    allowlist_policy: BrowserSecurityPolicy,
) -> None:
    result = allowlist_policy.validate_redirect(
        original_url="https://example.com/out",
        redirect_url="https://other.org/welcome",
    )
    assert result.allowed is False
    assert result.reason_code == BrowserPolicyErrorCode.DOMAIN_NOT_ALLOWED


# ==============================================================================
# 12. Default Singleton Instance
# ==============================================================================


def test_browser_security_policy_singleton_exists() -> None:
    assert isinstance(browser_security_policy, BrowserSecurityPolicy)
    # The default instance uses system default resolver and standard allowed schemes
    assert "http" in browser_security_policy.allowed_schemes
    assert "https" in browser_security_policy.allowed_schemes
    assert "file" not in browser_security_policy.allowed_schemes
