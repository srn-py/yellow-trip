# tests/compose_helpers.py
"""Shared helpers for the deployment tests (not a test file itself)."""

import re


def referenced_variables(compose_text: str) -> dict[str, list[str]]:
    """Find every ${VARIABLE...} in a compose file.

    Args:
        compose_text: The compose file as text.

    Returns:
        {variable name: [the text after the name in each use, such as ":-default" or ":?message"]}.
    """
    text = compose_text.replace("$$", "")  # "$$" is an escaped dollar for the container's shell
    found: dict[str, list[str]] = {}
    for match in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)([^}]*)\}", text):
        found.setdefault(match.group(1), []).append(match.group(2))
    return found


def required_variables(compose_text: str) -> set[str]:
    """Variables a compose file cannot start without (used with no default value).

    Args:
        compose_text: The compose file as text.

    Returns:
        The variable names.
    """
    return {
        name
        for name, uses in referenced_variables(compose_text).items()
        if any(not use.startswith((":-", "-")) for use in uses)
    }


def env_keys(env_text: str) -> set[str]:
    """The variable names set in an env file.

    Args:
        env_text: The file content.

    Returns:
        The names.
    """
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", env_text, flags=re.MULTILINE))
