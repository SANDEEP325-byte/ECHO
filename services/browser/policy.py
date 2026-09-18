"""ECHO Browser Security Policy & URL Sandbox.

Phase 5A: Pure security and policy layer for browser navigation and URL validation.
Implements robust scheme enforcement, credential stripping/blocking, loopback,
private-network (RFC 1918), link-local, cloud metadata, port, and domain validation.

ARCHITECTURE & SECURITY BOUNDARY NOTICE:
This module performs static and DNS-resolved URL validation at the policy boundary.
DNS Rebinding Note:
Validating a hostname's resolved IP address here prevents navigation to internal targets,
but does not replace network-layer IP enforcement. In subsequent Phase 5 subphases
(e.g., BrowserService/Playwright route interception), network requests must re-verify
the actual connected socket IP address to fully mitigate time-of-check-to-time-of-use (TOCTOU)
DNS rebinding attacks.
"""

import ipaddress
import re
import socket
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from packages.interfaces.security import PermissionDecision, RiskLevel
from services.logging.logger import logger  # type: ignore[attr-defined]


class BrowserPolicyErrorCode(str, Enum):
    """Structured browser policy violation error codes."""

    INVALID_URL = "invalid_url"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    EMBEDDED_CREDENTIALS = "embedded_credentials"
    MISSING_HOSTNAME = "missing_hostname"
    INVALID_PORT = "invalid_port"
    NON_STANDARD_PORT_BLOCKED = "non_standard_port_blocked"
    LOOPBACK_BLOCKED = "loopback_blocked"
    PRIVATE_IP_BLOCKED = "private_ip_blocked"
    LINK_LOCAL_BLOCKED = "link_local_blocked"
    CLOUD_METADATA_BLOCKED = "cloud_metadata_blocked"
    MULTICAST_BLOCKED = "multicast_blocked"
    RESERVED_IP_BLOCKED = "reserved_ip_blocked"
    DOMAIN_BLOCKED = "domain_blocked"
    DOMAIN_NOT_ALLOWED = "domain_not_allowed"
    DOMAIN_CONFIRMATION_REQUIRED = "domain_confirmation_required"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    UNSAFE_RESOLVED_IP = "unsafe_resolved_ip"


class HostClassification(str, Enum):
    """Structured classification of destination host/IP."""

    PUBLIC = "public"
    LOCAL = "local"
    PRIVATE = "private"
    LOOPBACK = "loopback"
    LINK_LOCAL = "link_local"
    METADATA = "metadata"
    MULTICAST = "multicast"
    RESERVED = "reserved"
    INVALID = "invalid"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class BrowserPolicyCheckResult:
    """Represents the structured evaluation result of a browser URL navigation target."""

    allowed: bool
    decision: PermissionDecision
    risk_level: RiskLevel
    reason_code: BrowserPolicyErrorCode | None = None
    reason: str = ""
    normalized_url: str | None = None
    hostname: str | None = None
    classification: HostClassification = HostClassification.INVALID
    port: int | None = None
    scheme: str | None = None
    resolved_ips: tuple[str, ...] = ()


class BrowserSecurityPolicyError(PermissionError):
    """Raised when a URL or browser operation violates the browser security policy."""

    def __init__(
        self,
        reason: str,
        error_code: BrowserPolicyErrorCode,
        normalized_url: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_code = error_code
        self.normalized_url = normalized_url


DNSResolver = Callable[[str], Sequence[str]]


def default_dns_resolver(hostname: str) -> list[str]:
    """Default system DNS resolver using standard library socket.getaddrinfo.

    Resolves both IPv4 and IPv6 addresses for the given hostname.
    """
    try:
        results = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        ips: list[str] = []
        for _, _, _, _, sockaddr in results:
            ip_str = str(sockaddr[0])
            if ip_str not in ips:
                ips.append(ip_str)
        return ips
    except (socket.gaierror, socket.herror, OSError) as exc:
        logger.warning("DNS resolution failed for host '%s': %s", hostname, exc)
        return []


def _try_parse_alternate_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Parse alternative IPv4 representations into an IPv4Address.

    Handles:
    - Standard dotted-decimal (e.g., '127.0.0.1')
    - Decimal integer (e.g., '2130706433')
    - Hexadecimal integer (e.g., '0x7f000001')
    - Dotted hexadecimal (e.g., '0x7f.0.0.1')
    - Dotted octal (e.g., '0177.0.0.1')
    - Shorthand multi-part forms (e.g., '127.1', '127.0.1')

    Returns None if the host string is not a numeric IPv4 representation.
    """
    parts = host.split(".")
    if len(parts) > 4:
        return None

    vals: list[int] = []
    for p in parts:
        p_clean = p.strip()
        if not p_clean:
            return None
        try:
            if p_clean.lower().startswith("0x"):
                val = int(p_clean, 16)
            elif p_clean.startswith("0") and len(p_clean) > 1 and p_clean.isdigit():
                val = int(p_clean, 8)
            elif p_clean.isdigit():
                val = int(p_clean, 10)
            else:
                return None
            vals.append(val)
        except ValueError:
            return None

    try:
        if len(vals) == 1:
            if 0 <= vals[0] <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(vals[0])
        elif len(vals) == 2:
            if 0 <= vals[0] <= 255 and 0 <= vals[1] <= 0xFFFFFF:
                return ipaddress.IPv4Address((vals[0] << 24) | vals[1])
        elif len(vals) == 3:
            if 0 <= vals[0] <= 255 and 0 <= vals[1] <= 255 and 0 <= vals[2] <= 0xFFFF:
                return ipaddress.IPv4Address((vals[0] << 24) | (vals[1] << 16) | vals[2])
        elif len(vals) == 4 and all(0 <= v <= 255 for v in vals):
            return ipaddress.IPv4Address(
                (vals[0] << 24) | (vals[1] << 16) | (vals[2] << 8) | vals[3]
            )
    except (ValueError, OverflowError):
        return None

    return None


def _parse_ip_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a host string into an IPv4Address or IPv6Address, handling bracketed IPv6 and alternate IPv4."""
    clean_host = host.strip()
    if clean_host.startswith("[") and clean_host.endswith("]"):
        clean_host = clean_host[1:-1]

    try:
        return ipaddress.ip_address(clean_host)
    except ValueError:
        pass

    return _try_parse_alternate_ipv4(clean_host)


class BrowserSecurityPolicy:
    """Security-first browser policy engine and URL sandbox validator.

    Protects against:
    - SSRF (Server-Side Request Forgery)
    - Localhost / loopback access (including decimal, hex, octal, and mapped IPv6 notation)
    - Private network access (RFC 1918 / IPv6 ULA)
    - Cloud metadata access (169.254.169.254, fd00:ec2::254, etc.)
    - Dangerous URL schemes (file://, javascript:, data:, blob:, chrome:, etc.)
    - Credential leakage via embedded userinfo
    - Malformed ports and restricted ports
    - Deceptive domain suffix matching
    - Unsafe DNS resolution targets
    """

    DEFAULT_ALLOWED_SCHEMES = frozenset({"http", "https"})
    DEFAULT_ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})

    # Known loopback names & metadata domains
    KNOWN_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost."})
    KNOWN_METADATA_HOSTNAMES = frozenset(
        {
            "metadata.google.internal",
            "metadata.google.internal.",
            "instance-data",
            "instance-data.",
        }
    )

    # Well-known metadata IPs
    CLOUD_METADATA_IPV4 = ipaddress.IPv4Address("169.254.169.254")
    CLOUD_METADATA_IPV6 = ipaddress.IPv6Address("fd00:ec2::254")

    # Control character regex (CRLF, tab, null byte, etc.)
    _CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

    def __init__(
        self,
        allowed_domains: Sequence[str] | None = None,
        blocked_domains: Sequence[str] | None = None,
        allowed_schemes: Sequence[str] | None = None,
        allowed_ports: Sequence[int] | None = None,
        allow_subdomains: bool = True,
        allow_non_standard_ports: bool = False,
        confirm_unlisted_domains: bool = False,
        enforce_dns_resolution: bool = True,
        dns_resolver: DNSResolver | None = None,
    ) -> None:
        """Initialize BrowserSecurityPolicy with explicit security parameters."""
        self.allowed_domains = (
            tuple(self._normalize_domain(d) for d in allowed_domains if d and d.strip())
            if allowed_domains is not None
            else None
        )
        self.blocked_domains = tuple(
            self._normalize_domain(d) for d in (blocked_domains or ()) if d and d.strip()
        )
        self.allowed_schemes = (
            frozenset(s.lower().strip() for s in allowed_schemes)
            if allowed_schemes is not None
            else self.DEFAULT_ALLOWED_SCHEMES
        )
        self.allowed_ports = (
            frozenset(allowed_ports) if allowed_ports is not None else self.DEFAULT_ALLOWED_PORTS
        )
        self.allow_subdomains = allow_subdomains
        self.allow_non_standard_ports = allow_non_standard_ports
        self.confirm_unlisted_domains = confirm_unlisted_domains
        self.enforce_dns_resolution = enforce_dns_resolution
        self.dns_resolver: DNSResolver = dns_resolver or default_dns_resolver

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        """Normalize a domain string for consistent matching."""
        d = domain.strip().lower()
        d = d.lstrip("*.")
        return d.rstrip(".")

    def classify_ip(
        self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> tuple[HostClassification, BrowserPolicyErrorCode | None]:
        """Classify an IP address and determine its security disposition.

        Returns (classification, error_code_if_blocked).
        """
        # Handle IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            return self.classify_ip(ip.ipv4_mapped)

        # 1. Cloud Metadata Check
        if ip == self.CLOUD_METADATA_IPV4 or ip == self.CLOUD_METADATA_IPV6:
            return HostClassification.METADATA, BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED

        # 2. Loopback / Unspecified Check (127.0.0.0/8, ::1, 0.0.0.0, 0.0.0.0/8, ::)
        if (
            ip.is_loopback
            or ip.is_unspecified
            or ip == ipaddress.IPv4Address("0.0.0.0")
            or str(ip).startswith("0.")
        ):
            return HostClassification.LOOPBACK, BrowserPolicyErrorCode.LOOPBACK_BLOCKED

        # 3. Link-Local Check (169.254.0.0/16, fe80::/10)
        if ip.is_link_local:
            return HostClassification.LINK_LOCAL, BrowserPolicyErrorCode.LINK_LOCAL_BLOCKED

        # 4. Private Network Check (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
        if ip.is_private:
            return HostClassification.PRIVATE, BrowserPolicyErrorCode.PRIVATE_IP_BLOCKED

        # 5. Multicast Check (224.0.0.0/4, ff00::/8)
        if ip.is_multicast:
            return HostClassification.MULTICAST, BrowserPolicyErrorCode.MULTICAST_BLOCKED

        # 6. Reserved Check (240.0.0.0/4, etc.)
        if ip.is_reserved:
            return HostClassification.RESERVED, BrowserPolicyErrorCode.RESERVED_IP_BLOCKED

        # 7. Public IP
        if ip.is_global:
            return HostClassification.PUBLIC, None

        return HostClassification.RESERVED, BrowserPolicyErrorCode.RESERVED_IP_BLOCKED

    def is_domain_blocked(self, hostname: str) -> bool:
        """Check if hostname matches any configured blocked domains."""
        norm_host = self._normalize_domain(hostname)
        for blocked in self.blocked_domains:
            if norm_host == blocked:
                return True
            if self.allow_subdomains and norm_host.endswith("." + blocked):
                return True
        return False

    def is_domain_allowed(self, hostname: str) -> bool:
        """Check if hostname matches any configured allowed domains.

        If allowed_domains is None, all domains are considered allowed (subject to security checks).
        Uses strict domain boundary logic (rejects evil-example.com matching example.com).
        """
        if self.allowed_domains is None:
            return True

        norm_host = self._normalize_domain(hostname)
        for allowed in self.allowed_domains:
            if norm_host == allowed:
                return True
            if self.allow_subdomains and norm_host.endswith("." + allowed):
                return True
        return False

    def normalize_url(self, raw_url: str) -> tuple[str, urllib.parse.SplitResult, str, int | None]:
        """Validate format, sanitize, and normalize a URL.

        Returns (normalized_url_string, split_result, normalized_hostname, port).
        Raises BrowserSecurityPolicyError if malformed, dangerous scheme, or credentials found.
        """
        if not raw_url or not isinstance(raw_url, str):
            raise BrowserSecurityPolicyError(
                "URL cannot be empty or non-string.",
                BrowserPolicyErrorCode.INVALID_URL,
            )

        trimmed = raw_url.strip()
        if not trimmed:
            raise BrowserSecurityPolicyError(
                "URL cannot be whitespace-only.",
                BrowserPolicyErrorCode.INVALID_URL,
            )

        if self._CONTROL_CHAR_RE.search(trimmed):
            raise BrowserSecurityPolicyError(
                "URL contains prohibited control characters.",
                BrowserPolicyErrorCode.INVALID_URL,
            )

        try:
            parsed = urllib.parse.urlsplit(trimmed)
        except Exception as exc:
            raise BrowserSecurityPolicyError(
                "URL parsing failed.",
                BrowserPolicyErrorCode.INVALID_URL,
            ) from exc

        # Scheme validation
        scheme = (parsed.scheme or "").lower()
        if not scheme:
            raise BrowserSecurityPolicyError(
                "URL is missing a scheme (http:// or https:// required).",
                BrowserPolicyErrorCode.UNSUPPORTED_SCHEME,
            )

        if scheme not in self.allowed_schemes:
            raise BrowserSecurityPolicyError(
                f"URL scheme '{scheme}' is forbidden. Only HTTP/HTTPS are supported.",
                BrowserPolicyErrorCode.UNSUPPORTED_SCHEME,
            )

        # Embedded Credentials validation (NEVER leak the credential in errors or logs)
        if parsed.username or parsed.password or ("@" in parsed.netloc):
            raise BrowserSecurityPolicyError(
                "URLs containing authentication credentials or userinfo are strictly prohibited.",
                BrowserPolicyErrorCode.EMBEDDED_CREDENTIALS,
            )

        # Hostname validation
        raw_host = parsed.hostname
        if not raw_host or not raw_host.strip():
            raise BrowserSecurityPolicyError(
                "URL is missing a valid destination hostname.",
                BrowserPolicyErrorCode.MISSING_HOSTNAME,
            )

        norm_host = raw_host.strip().lower().rstrip(".")

        # Port validation
        port: int | None = None
        try:
            port = parsed.port
        except ValueError as exc:
            raise BrowserSecurityPolicyError(
                "URL specifies an invalid or non-numeric port number.",
                BrowserPolicyErrorCode.INVALID_PORT,
            ) from exc

        if port is not None:
            if not (1 <= port <= 65535):
                raise BrowserSecurityPolicyError(
                    f"Port {port} is outside the valid TCP range (1-65535).",
                    BrowserPolicyErrorCode.INVALID_PORT,
                )
            if not self.allow_non_standard_ports and port not in self.allowed_ports:
                raise BrowserSecurityPolicyError(
                    f"Port {port} is not in the allowed ports list {sorted(self.allowed_ports)}.",
                    BrowserPolicyErrorCode.NON_STANDARD_PORT_BLOCKED,
                )

        # Reconstruct clean normalized URL (guarantees zero userinfo)
        netloc = norm_host
        if parsed.hostname and parsed.hostname.startswith("[") and parsed.hostname.endswith("]"):
            netloc = f"[{norm_host}]"

        default_port = 80 if scheme == "http" else 443
        if port is not None and port != default_port:
            netloc = f"{netloc}:{port}"

        path = parsed.path or "/"
        reconstructed = urllib.parse.urlunsplit(
            (
                scheme,
                netloc,
                path,
                parsed.query,
                parsed.fragment,
            )
        )

        return reconstructed, parsed, norm_host, port

    def validate_url(
        self,
        url: str,
        dns_resolver: DNSResolver | None = None,
    ) -> BrowserPolicyCheckResult:
        """Validate a target URL against all browser security rules.

        Returns a structured BrowserPolicyCheckResult. Never raises exceptions.
        """
        # Step 1: Normalization and syntax check
        try:
            norm_url, parsed, norm_host, port = self.normalize_url(url)
        except BrowserSecurityPolicyError as exc:
            return BrowserPolicyCheckResult(
                allowed=False,
                decision=PermissionDecision.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                reason_code=exc.error_code,
                reason=exc.reason,
                classification=HostClassification.INVALID,
            )

        scheme = parsed.scheme.lower()

        # Step 2: Named loopback hostnames check
        if norm_host in self.KNOWN_LOOPBACK_HOSTNAMES or norm_host.endswith(".localhost"):
            return BrowserPolicyCheckResult(
                allowed=False,
                decision=PermissionDecision.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                reason_code=BrowserPolicyErrorCode.LOOPBACK_BLOCKED,
                reason=f"Access to localhost destination '{norm_host}' is blocked.",
                normalized_url=norm_url,
                hostname=norm_host,
                classification=HostClassification.LOOPBACK,
                port=port,
                scheme=scheme,
            )

        # Step 3: Named cloud metadata hostnames check
        if norm_host in self.KNOWN_METADATA_HOSTNAMES:
            return BrowserPolicyCheckResult(
                allowed=False,
                decision=PermissionDecision.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                reason_code=BrowserPolicyErrorCode.CLOUD_METADATA_BLOCKED,
                reason=f"Access to cloud metadata destination '{norm_host}' is blocked.",
                normalized_url=norm_url,
                hostname=norm_host,
                classification=HostClassification.METADATA,
                port=port,
                scheme=scheme,
            )

        # Step 4: Blocked domains check
        if self.is_domain_blocked(norm_host):
            return BrowserPolicyCheckResult(
                allowed=False,
                decision=PermissionDecision.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                reason_code=BrowserPolicyErrorCode.DOMAIN_BLOCKED,
                reason=f"Domain '{norm_host}' is in the configured blocked domains list.",
                normalized_url=norm_url,
                hostname=norm_host,
                classification=HostClassification.BLOCKED,
                port=port,
                scheme=scheme,
            )

        # Step 5: Check if hostname is an IP literal or alternative IP notation
        parsed_ip = _parse_ip_address(norm_host)
        if parsed_ip is not None:
            classification, err_code = self.classify_ip(parsed_ip)
            if err_code is not None:
                return BrowserPolicyCheckResult(
                    allowed=False,
                    decision=PermissionDecision.BLOCK,
                    risk_level=RiskLevel.CRITICAL,
                    reason_code=err_code,
                    reason=f"Target IP address '{parsed_ip}' is classified as {classification.value} and is blocked.",
                    normalized_url=norm_url,
                    hostname=norm_host,
                    classification=classification,
                    port=port,
                    scheme=scheme,
                    resolved_ips=(str(parsed_ip),),
                )

            # Public IP literal: check allowlist if active
            if self.allowed_domains is not None and not self.is_domain_allowed(norm_host):
                if self.confirm_unlisted_domains:
                    return BrowserPolicyCheckResult(
                        allowed=False,
                        decision=PermissionDecision.CONFIRM,
                        risk_level=RiskLevel.MODERATE,
                        reason_code=BrowserPolicyErrorCode.DOMAIN_CONFIRMATION_REQUIRED,
                        reason=f"Destination IP '{norm_host}' is not in the allowed domains list and requires confirmation.",
                        normalized_url=norm_url,
                        hostname=norm_host,
                        classification=HostClassification.PUBLIC,
                        port=port,
                        scheme=scheme,
                        resolved_ips=(str(parsed_ip),),
                    )
                return BrowserPolicyCheckResult(
                    allowed=False,
                    decision=PermissionDecision.BLOCK,
                    risk_level=RiskLevel.SENSITIVE,
                    reason_code=BrowserPolicyErrorCode.DOMAIN_NOT_ALLOWED,
                    reason=f"Destination IP '{norm_host}' is not in the allowed domains list.",
                    normalized_url=norm_url,
                    hostname=norm_host,
                    classification=HostClassification.PUBLIC,
                    port=port,
                    scheme=scheme,
                    resolved_ips=(str(parsed_ip),),
                )

            return BrowserPolicyCheckResult(
                allowed=True,
                decision=PermissionDecision.ALLOW,
                risk_level=RiskLevel.SAFE,
                reason_code=None,
                reason="URL target IP is public and permitted.",
                normalized_url=norm_url,
                hostname=norm_host,
                classification=HostClassification.PUBLIC,
                port=port,
                scheme=scheme,
                resolved_ips=(str(parsed_ip),),
            )

        # Step 6: Domain allowlist check
        if self.allowed_domains is not None and not self.is_domain_allowed(norm_host):
            if self.confirm_unlisted_domains:
                return BrowserPolicyCheckResult(
                    allowed=False,
                    decision=PermissionDecision.CONFIRM,
                    risk_level=RiskLevel.MODERATE,
                    reason_code=BrowserPolicyErrorCode.DOMAIN_CONFIRMATION_REQUIRED,
                    reason=f"Domain '{norm_host}' is outside configured allowed domains and requires confirmation.",
                    normalized_url=norm_url,
                    hostname=norm_host,
                    classification=HostClassification.PUBLIC,
                    port=port,
                    scheme=scheme,
                )
            return BrowserPolicyCheckResult(
                allowed=False,
                decision=PermissionDecision.BLOCK,
                risk_level=RiskLevel.SENSITIVE,
                reason_code=BrowserPolicyErrorCode.DOMAIN_NOT_ALLOWED,
                reason=f"Domain '{norm_host}' is not in the configured allowed domains list.",
                normalized_url=norm_url,
                hostname=norm_host,
                classification=HostClassification.PUBLIC,
                port=port,
                scheme=scheme,
            )

        # Step 7: DNS resolution & resolved IP address classification
        resolved_ips: list[str] = []
        if self.enforce_dns_resolution:
            resolver = dns_resolver or self.dns_resolver
            try:
                raw_resolved = resolver(norm_host)
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning("DNS resolver raised error for '%s': %s", norm_host, exc)
                raw_resolved = []

            if not raw_resolved:
                return BrowserPolicyCheckResult(
                    allowed=False,
                    decision=PermissionDecision.BLOCK,
                    risk_level=RiskLevel.CRITICAL,
                    reason_code=BrowserPolicyErrorCode.DNS_RESOLUTION_FAILED,
                    reason=f"DNS resolution failed or returned no IP addresses for host '{norm_host}'.",
                    normalized_url=norm_url,
                    hostname=norm_host,
                    classification=HostClassification.INVALID,
                    port=port,
                    scheme=scheme,
                )

            for ip_str in raw_resolved:
                resolved_ips.append(ip_str)
                parsed_resolved = _parse_ip_address(ip_str)
                if parsed_resolved is None:
                    return BrowserPolicyCheckResult(
                        allowed=False,
                        decision=PermissionDecision.BLOCK,
                        risk_level=RiskLevel.CRITICAL,
                        reason_code=BrowserPolicyErrorCode.DNS_RESOLUTION_FAILED,
                        reason=f"DNS returned unparseable IP address '{ip_str}' for host '{norm_host}'.",
                        normalized_url=norm_url,
                        hostname=norm_host,
                        classification=HostClassification.INVALID,
                        port=port,
                        scheme=scheme,
                        resolved_ips=tuple(resolved_ips),
                    )

                ip_class, ip_err = self.classify_ip(parsed_resolved)
                if ip_err is not None:
                    return BrowserPolicyCheckResult(
                        allowed=False,
                        decision=PermissionDecision.BLOCK,
                        risk_level=RiskLevel.CRITICAL,
                        reason_code=BrowserPolicyErrorCode.UNSAFE_RESOLVED_IP,
                        reason=(
                            f"Host '{norm_host}' resolved to unsafe address '{ip_str}' "
                            f"classified as {ip_class.value}."
                        ),
                        normalized_url=norm_url,
                        hostname=norm_host,
                        classification=ip_class,
                        port=port,
                        scheme=scheme,
                        resolved_ips=tuple(resolved_ips),
                    )

        # Step 8: All security checks passed
        return BrowserPolicyCheckResult(
            allowed=True,
            decision=PermissionDecision.ALLOW,
            risk_level=RiskLevel.SAFE,
            reason_code=None,
            reason="URL is safe and compliant with BrowserSecurityPolicy.",
            normalized_url=norm_url,
            hostname=norm_host,
            classification=HostClassification.PUBLIC,
            port=port,
            scheme=scheme,
            resolved_ips=tuple(resolved_ips),
        )

    def validate_url_or_raise(
        self,
        url: str,
        dns_resolver: DNSResolver | None = None,
    ) -> BrowserPolicyCheckResult:
        """Validate target URL and raise BrowserSecurityPolicyError if not allowed."""
        result = self.validate_url(url, dns_resolver=dns_resolver)
        if not result.allowed:
            err_code = result.reason_code or BrowserPolicyErrorCode.INVALID_URL
            raise BrowserSecurityPolicyError(
                reason=result.reason,
                error_code=err_code,
                normalized_url=result.normalized_url,
            )
        return result

    def validate_redirect(
        self,
        original_url: str,
        redirect_url: str,
        dns_resolver: DNSResolver | None = None,
    ) -> BrowserPolicyCheckResult:
        """Validate a redirect target URL.

        A redirect target NEVER inherits trust from the original URL. It undergoes
        complete, independent policy evaluation.
        """
        return self.validate_url(redirect_url, dns_resolver=dns_resolver)


# Global default browser security policy instance
browser_security_policy = BrowserSecurityPolicy()
