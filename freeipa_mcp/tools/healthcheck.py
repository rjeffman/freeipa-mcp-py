# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

# Security: Allowed severity values for healthcheck
_ALLOWED_SEVERITIES = frozenset(["SUCCESS", "WARNING", "ERROR", "CRITICAL"])

# Security: Pattern for valid source/check names
# (alphanumeric, dots, hyphens, underscores)
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")

# Cache TTL in seconds (24 hours)
_CACHE_TTL_SECONDS = 24 * 60 * 60


def _get_kerberos_principal() -> str:
    result = subprocess.run(  # noqa: S603 - klist is a trusted Kerberos tool
        ["klist"],  # noqa: S607 - standard Kerberos utility
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError("No Kerberos ticket found. Run the login tool first.")
    for line in result.stdout.splitlines():
        if line.startswith("Default principal:"):
            return line.split(":", 1)[1].strip().split("@")[0]
    raise RuntimeError("Could not parse Kerberos principal from klist output")


def _is_safe_identifier(name: str) -> bool:
    """Check if name contains only safe characters.

    Allowed: alphanumeric, dots, hyphens, underscores.

    Args:
        name: String to validate

    Returns:
        True if name matches safe pattern, False otherwise
    """
    return _SAFE_IDENTIFIER_PATTERN.match(name) is not None


def _get_cache_dir(server_hostname: str) -> Path:
    """Get cache directory for healthcheck sources.

    Args:
        server_hostname: Server hostname (must be validated FQDN)

    Returns:
        Path to cache directory with 0700 permissions
    """
    # SECURITY: Set restrictive umask before creating directory
    old_umask = os.umask(0o077)
    try:
        cache_dir = Path.home() / ".cache" / "freeipa-mcp-py" / server_hostname
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Ensure directory has correct permissions even if it already existed
        cache_dir.chmod(0o700)
        return cache_dir
    finally:
        os.umask(old_umask)


def _parse_list_sources(output: str) -> dict[str, list[str]]:
    """Parse ipa-healthcheck --list-sources output into dict of sources and checks.

    Expected format:
        source.name.here
          CheckName1
          CheckName2
        another.source
          Check3

    Args:
        output: Raw output from ipa-healthcheck --list-sources

    Returns:
        Dictionary mapping source names to lists of check names

    Raises:
        ValueError: If source or check name contains shell metacharacters
    """
    if not output or not output.strip():
        return {}

    sources: dict[str, list[str]] = {}
    current_source: str | None = None

    for line in output.splitlines():
        if not line:
            continue
        if line.startswith((" ", "\t")):
            # This is a check under current source
            if current_source is not None:
                check = line.strip()
                if check:
                    # SECURITY: Validate check name format
                    if not _is_safe_identifier(check):
                        raise ValueError(
                            f"Invalid check name format: '{check}'. "
                            f"Check names must contain only alphanumeric characters, "
                            f"dots, hyphens, and underscores."
                        )
                    sources[current_source].append(check)
        else:
            # This is a source name
            source = line.strip()
            if source:
                # SECURITY: Validate source name format
                if not _is_safe_identifier(source):
                    raise ValueError(
                        f"Invalid source name format: '{source}'. "
                        f"Source names must contain only alphanumeric characters, "
                        f"dots, hyphens, and underscores."
                    )
                current_source = source
                sources[current_source] = []

    return sources


def _validate_cached_sources(cached_sources: dict[str, list[str]]) -> None:
    """Validate cached source data for safe identifiers.

    Args:
        cached_sources: Dictionary of source names to check lists

    Raises:
        ValueError: If any source or check name contains shell metacharacters
    """
    for source, checks in cached_sources.items():
        # SECURITY: Validate source name
        if not _is_safe_identifier(source):
            raise ValueError(
                f"Invalid source name in cache: '{source}'. "
                f"Cache may be corrupted or poisoned."
            )
        # SECURITY: Validate all check names
        for check in checks:
            if not _is_safe_identifier(check):
                raise ValueError(
                    f"Invalid check name in cache: '{check}' for source '{source}'. "
                    f"Cache may be corrupted or poisoned."
                )


def _get_cached_sources(
    server_hostname: str, username: str, password: str | None
) -> dict[str, list[str]]:
    """Get cached healthcheck sources, fetching if necessary.

    Implements cache TTL - refreshes after 24 hours.

    Args:
        server_hostname: Server hostname (must be validated FQDN)
        username: SSH username
        password: Optional sudo password

    Returns:
        Dictionary mapping source names to lists of check names

    Raises:
        ValueError: If cached data contains invalid identifiers
    """
    cache_dir = _get_cache_dir(server_hostname)
    cache_file = cache_dir / "healthcheck-sources.json"

    # Try to load from cache if it exists and is fresh
    if cache_file.exists():
        try:
            # Check cache age (TTL: 24 hours)
            cache_age = time.time() - cache_file.stat().st_mtime
            if cache_age < _CACHE_TTL_SECONDS:
                data = json.loads(cache_file.read_text())
                if isinstance(data, dict):
                    # SECURITY: Validate loaded cache data
                    _validate_cached_sources(data)
                    return data
        except (json.JSONDecodeError, OSError, ValueError):
            # Cache corrupted, stale, or poisoned - will refetch
            pass

    # Fetch sources from server
    output = _exec_ssh(
        server_hostname, username, "ipa-healthcheck --list-sources", password
    )
    sources = _parse_list_sources(output)

    # Save to cache with secure permissions
    # SECURITY: Set restrictive umask before creating file
    old_umask = os.umask(0o077)
    try:
        cache_file.write_text(json.dumps(sources, indent=2))
        # Ensure file has correct permissions
        cache_file.chmod(0o600)
    finally:
        os.umask(old_umask)

    return sources


def _validate_source(source: str | None, cached_sources: dict[str, list[str]]) -> None:
    """Validate source parameter against allowlist of cached sources.

    Args:
        source: Source name to validate (or None)
        cached_sources: Dictionary of known-good sources from server

    Raises:
        ValueError: If source is not in the allowlist
    """
    if source is None:
        return

    # Check if source exists in cache (allowlist validation)
    if source not in cached_sources:
        raise ValueError(
            f"Invalid source: '{source}'. "
            f"Available sources: {', '.join(sorted(cached_sources.keys()))}"
        )


def _validate_check(
    source: str | None, check: str | None, cached_sources: dict[str, list[str]]
) -> None:
    """Validate check parameter against cached checks for the given source.

    Raises:
        ValueError: If check is invalid or source is missing.
    """
    if check is None:
        return

    if source is None:
        raise ValueError("Check parameter requires a source parameter to be specified")

    # Validate source first
    if source not in cached_sources:
        raise ValueError(f"Invalid source: '{source}'")

    # Check if check exists for this source
    available_checks = cached_sources[source]
    if check not in available_checks:
        raise ValueError(
            f"Invalid check: '{check}' for source '{source}'. "
            f"Available checks: {', '.join(sorted(available_checks))}"
        )


def _validate_severity(severity: list[str] | None) -> None:
    """Validate severity parameter values.

    Args:
        severity: List of severity values to validate (or None)

    Raises:
        ValueError: If any severity value is not in allowed list
    """
    if severity is None:
        return

    for sev in severity:
        if sev not in _ALLOWED_SEVERITIES:
            raise ValueError(
                f"Invalid severity: '{sev}'. "
                f"Allowed values: {', '.join(sorted(_ALLOWED_SEVERITIES))}"
            )


def _exec_ssh(
    hostname: str, username: str, command: str, password: str | None = None
) -> str:
    quoted_cmd = shlex.quote(command)

    if password is not None:
        remote = f"cd / && sudo --stdin {quoted_cmd}; echo $?"
        ssh_input = f"{password}\n"
    else:
        remote = f"cd / && sudo {quoted_cmd}; echo $?"
        ssh_input = None

    # SECURITY: All callers of _exec_ssh MUST validate inputs before calling.
    # Current callers: _get_cached_sources (validated hostname),
    # _healthcheck_blocking (validated source/check/severity against allowlist)
    result = subprocess.run(  # noqa: S603 - inputs validated by all callers
        [  # noqa: S607 - standard ssh command
            "ssh",
            "-T",
            "-o",
            "GSSAPIAuthentication=yes",
            "-o",
            "GSSAPIDelegateCredentials=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=30",
            f"{username}@{hostname}",
            remote,
        ],
        input=ssh_input,
        capture_output=True,
        text=True,
        timeout=120,
    )

    stdout_lines = result.stdout.splitlines()
    if stdout_lines:
        try:
            exit_code = int(stdout_lines[-1])
            output = "\n".join(stdout_lines[:-1])
        except ValueError:
            exit_code = result.returncode
            output = result.stdout
    else:
        exit_code = result.returncode
        output = result.stdout

    stderr = result.stderr.strip()
    if exit_code != 0:
        if "incorrect password" in stderr.lower() or "sorry" in stderr.lower():
            raise RuntimeError("sudo authentication failed: incorrect password")
        if "not in the sudoers" in stderr.lower():
            raise RuntimeError(
                f"User {username} is not permitted to run sudo on {hostname}"
            )
        raise RuntimeError(
            f"Remote command failed (exit {exit_code}): {stderr or output}"
        )
    return output


_SNAKE_SPECIAL: dict[str, str] = {
    "msg": "Message",
    "ca": "CA",
    "dns": "DNS",
    "ntp": "NTP",
    "url": "URL",
    "uri": "URI",
    "uuid": "UUID",
    "id": "ID",
}


def _snake_to_title(s: str) -> str:
    if s.lower() in _SNAKE_SPECIAL:
        return _SNAKE_SPECIAL[s.lower()]
    parts = []
    for word in s.split("_"):
        parts.append(_SNAKE_SPECIAL.get(word.lower(), word.capitalize()))
    return " ".join(parts)


def _format_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(_format_value(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"))
    if value is None:
        return "null"
    return str(value)


def _format_kw(kw: dict) -> str:
    if not kw:
        return "*(No additional details)*\n"
    lines = []
    for key, value in kw.items():
        lines.append(f"- **{_snake_to_title(key)}:** {_format_value(value)}")
    return "\n".join(lines) + "\n"


def _format_entry(entry: dict) -> str:
    source = entry.get("source", "")
    check = entry.get("check", "")
    result = entry.get("result", "")
    kw = entry.get("kw", {})
    return (
        f"### {source} - {check}\n\n**Status:** {result}\n\n{_format_kw(kw)}\n---\n\n"
    )


def _generate_summary(grouped: dict[str, list]) -> str:
    total = sum(len(v) for v in grouped.values())
    critical = len(grouped.get("CRITICAL", []))
    errors = len(grouped.get("ERROR", []))
    warnings = len(grouped.get("WARNING", []))
    success = len(grouped.get("SUCCESS", []))

    lines = [
        "## Summary",
        f"- **Total Checks:** {total}",
        f"- **Critical:** {critical} \U0001f534",
        f"- **Errors:** {errors} \U0001f7e0",
        f"- **Warnings:** {warnings} \U0001f7e1",
        f"- **Success:** {success} \U0001f7e2",
        "",
    ]
    if critical > 0 or errors > 0:
        lines.append("**Overall Status:** Issues found that require attention")
    elif warnings > 0:
        lines.append("**Overall Status:** Minor issues detected")
    else:
        lines.append("**Overall Status:** All checks passed \u2705")
    return "\n".join(lines)


def _format_as_markdown(json_output: str) -> str:
    try:
        results = json.loads(json_output)
    except json.JSONDecodeError:
        return json_output
    if not isinstance(results, list):
        return json_output

    if not results:
        return "# IPA Healthcheck Results\n\nNo healthcheck results found.\n"

    grouped: dict[str, list] = {}
    for item in results:
        grouped.setdefault(item.get("result", "UNKNOWN"), []).append(item)

    out = "# IPA Healthcheck Results\n\n"
    out += _generate_summary(grouped) + "\n"

    for sev in ["CRITICAL", "ERROR", "WARNING", "SUCCESS"]:
        entries = grouped.get(sev, [])
        if entries:
            out += f"## {sev} Results\n\n"
            for entry in entries:
                out += _format_entry(entry)

    if grouped.get("CRITICAL") or grouped.get("ERROR") or grouped.get("WARNING"):
        out += (
            "## Recommendations\n\n"
            "Review the issues above and take appropriate action:\n"
            "1. Address CRITICAL and ERROR items immediately\n"
            "2. Plan fixes for WARNING items\n"
            "3. Re-run healthcheck after making changes to verify fixes\n\n"
            "For more information, see:"
            " https://www.freeipa.org/page/Troubleshooting\n"
        )

    return out


def _healthcheck_blocking(
    server_hostname: str,
    username: str,
    mode: str,
    source: str | None,
    check: str | None,
    failures_only: bool,
    severity: list[str] | None,
    password: str | None,
    output_format: str,
) -> str:
    if mode == "log":
        cmd = "cat /var/log/ipa/healthcheck/healthcheck.log"
        output = _exec_ssh(server_hostname, username, cmd, password)
    else:
        # SECURITY: Fetch and validate parameters against cached sources
        cached_sources = _get_cached_sources(server_hostname, username, password)
        _validate_source(source, cached_sources)
        _validate_check(source, check, cached_sources)
        _validate_severity(severity)

        # Build command with validated parameters
        parts = ["ipa-healthcheck", "--output-type", "json"]
        if source:
            parts += ["--source", source]
        if check:
            parts += ["--check", check]
        if failures_only:
            parts.append("--failures-only")
        if severity:
            for s in severity:
                parts += ["--severity", s]
        output = _exec_ssh(server_hostname, username, " ".join(parts), password)

    if output_format == "json":
        return output
    return _format_as_markdown(output)


async def execute(
    server_hostname: str,
    mode: str = "live",
    source: str | None = None,
    check: str | None = None,
    failures_only: bool = True,
    severity: list[str] | None = None,
    passwordless: bool = False,
    output_format: str = "markdown",
) -> str:
    """Execute FreeIPA healthcheck on remote server.

    Args:
        server_hostname: FQDN of FreeIPA server
        mode: "live" or "log" mode
        source: Optional source filter
        check: Optional check filter (requires source)
        failures_only: Only show failures (default: True)
        severity: Optional severity filter
        passwordless: Skip sudo password prompt
        output_format: "markdown" or "json"

    Returns:
        Healthcheck results in requested format

    Raises:
        ValueError: If server_hostname is invalid FQDN or parameters fail validation
        RuntimeError: If Kerberos authentication fails or SSH command fails
    """
    # SECURITY: Validate server hostname to prevent path traversal and SSH redirection
    from .create_ipaconf import validate_fqdn

    validate_fqdn(server_hostname)

    username = await asyncio.to_thread(_get_kerberos_principal)

    password: str | None = None
    if not passwordless:
        from .sudo_gui import get_sudo_password

        password = await asyncio.to_thread(get_sudo_password, username, server_hostname)

    return await asyncio.to_thread(
        _healthcheck_blocking,
        server_hostname,
        username,
        mode,
        source,
        check,
        failures_only,
        severity,
        password,
        output_format,
    )
