"""Command ACL — Whitelist/Blacklist Regex Filtering for Network Commands.

Implements the Fast-Track Command ACL as specified in workflows.md:
- Whitelist: Only allow safe operational commands (show, ping, traceroute, monitor)
- Blacklist: Block all configuration/system intervention keywords
- No resource protection (per user decision)

The ACL is the single security gate for the view_network_status tool.
"""

import re
import logging

logger = logging.getLogger("command-acl")

# ---------------------------------------------------------------------------
# Whitelist: only these command prefixes are allowed through
# ---------------------------------------------------------------------------
WHITELIST_PATTERN = re.compile(
    r"^(show|ping|traceroute|monitor|request\s+ping|request\s+traceroute)\s+.*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Blacklist: these keywords are ALWAYS blocked, even if whitelist matches
# ---------------------------------------------------------------------------
BLACKLIST_KEYWORDS = [
    "set ",
    "delete ",
    "edit ",
    "configure",
    "request system",
    "clear ",
    "restart ",
    "commit",
    "rollback",
    "load ",
    "activate ",
    "deactivate ",
    "request chassis",
    "file ",
    "start shell",
    "run ",
]


class CommandACL:
    """Validates network CLI commands against whitelist/blacklist rules.

    Usage:
        acl = CommandACL()
        allowed, message = acl.validate("show interfaces terse")
        # allowed=True, message="Command is allowed."

        allowed, message = acl.validate("set interfaces xe-0/0/1 disable")
        # allowed=False, message="BLOCKED: Command contains blacklisted keyword 'set '."
    """

    def __init__(
        self,
        whitelist_pattern: re.Pattern = WHITELIST_PATTERN,
        blacklist_keywords: list[str] | None = None,
    ):
        self.whitelist_pattern = whitelist_pattern
        self.blacklist_keywords = blacklist_keywords or BLACKLIST_KEYWORDS

    def validate(self, command: str) -> tuple[bool, str]:
        """Validate a command against the ACL rules.

        Returns:
            (is_allowed, message) tuple.
        """
        command_stripped = command.strip()

        if not command_stripped:
            return False, "BLOCKED: Empty command."

        # Step 1: Check blacklist first (highest priority)
        command_lower = command_stripped.lower()
        for keyword in self.blacklist_keywords:
            if command_lower.startswith(keyword) or f" {keyword}" in f" {command_lower}":
                logger.warning(f"Command ACL BLOCKED (blacklist): '{command_stripped}' matched keyword '{keyword}'")
                return False, f"BLOCKED: Command contains blacklisted keyword '{keyword.strip()}'. Configuration and system commands must go through the propose_network_change workflow."

        # Step 2: Check whitelist
        if not self.whitelist_pattern.match(command_stripped):
            logger.warning(f"Command ACL BLOCKED (whitelist): '{command_stripped}' did not match whitelist pattern")
            return False, (
                f"BLOCKED: Command '{command_stripped}' is not in the allowed command list. "
                f"Only operational commands (show, ping, traceroute, monitor) are permitted. "
                f"For configuration changes, use propose_network_change."
            )

        logger.info(f"Command ACL ALLOWED: '{command_stripped}'")
        return True, "Command is allowed."


# Module-level singleton for convenience
_default_acl = CommandACL()


def validate_command(command: str) -> tuple[bool, str]:
    """Module-level convenience function to validate a command."""
    return _default_acl.validate(command)
