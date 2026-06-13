"""Jira Task Management Tools for the Network Engineer Agent.

Provides 3 LangChain tools that integrate with Jira REST API v3
to manage operational tasks on the KAN Kanban board:

  1. create_jira_task   — Create a new Task ticket
  2. update_task_status  — Transition ticket status (IN_PROGRESS/WAITING/ERROR/DONE)
  3. add_task_comment    — Add a log/comment to a ticket

Authentication uses HTTP Basic (email + API token).
"""

import os
import logging
import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jira connection configuration (loaded from environment)
# ---------------------------------------------------------------------------
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
JIRA_USER_EMAIL = os.environ.get("JIRA_USER_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "KAN")

_TIMEOUT = 15  # seconds


def _jira_auth() -> tuple[str, str]:
    """Return (email, token) tuple for requests auth."""
    return (JIRA_USER_EMAIL, JIRA_API_TOKEN)


def _jira_headers() -> dict[str, str]:
    """Standard headers for Jira REST API v3."""
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _is_configured() -> bool:
    """Check whether Jira env vars are present."""
    return bool(JIRA_BASE_URL and JIRA_USER_EMAIL and JIRA_API_TOKEN)


# ---------------------------------------------------------------------------
# Helper: convert plain text → Atlassian Document Format (ADF)
# ---------------------------------------------------------------------------
def _text_to_adf(text: str) -> dict:
    """Convert a plain-text string to minimal ADF (Atlassian Document Format).

    Jira REST API v3 requires ADF for description and comment bodies.
    We split on double-newlines into paragraphs, preserving single newlines
    via hardBreak nodes.
    """
    paragraphs = text.split("\n\n") if "\n\n" in text else [text]
    doc_content = []
    for para in paragraphs:
        # Split single newlines into separate text + hardBreak nodes
        lines = para.split("\n")
        inline_nodes = []
        for i, line in enumerate(lines):
            if line:
                inline_nodes.append({"type": "text", "text": line})
            if i < len(lines) - 1:
                inline_nodes.append({"type": "hardBreak"})
        if inline_nodes:
            doc_content.append({
                "type": "paragraph",
                "content": inline_nodes,
            })
    return {
        "version": 1,
        "type": "doc",
        "content": doc_content or [
            {"type": "paragraph", "content": [{"type": "text", "text": "(empty)"}]}
        ],
    }


# ---------------------------------------------------------------------------
# Helper: map user-friendly status names → Jira transition IDs
# ---------------------------------------------------------------------------
# Normalisation map: the keys the Agent will pass → substrings to fuzzy-match
# against the transition names returned by Jira's workflow.
_STATUS_ALIASES: dict[str, list[str]] = {
    "IN_PROGRESS": ["in progress", "start progress", "in-progress"],
    "WAITING":     ["waiting", "wait", "blocked", "on hold"],
    "ERROR":       ["error", "fail", "failed"],
    "DONE":        ["done", "complete", "resolve", "closed", "close"],
}


def _find_transition_id(issue_key: str, target_status: str) -> tuple[str | None, str]:
    """GET available transitions and find the one matching *target_status*.

    Returns (transition_id, message).
    """
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    resp = requests.get(url, auth=_jira_auth(), headers=_jira_headers(), timeout=_TIMEOUT)
    if resp.status_code != 200:
        return None, f"Failed to fetch transitions for {issue_key}: HTTP {resp.status_code} — {resp.text[:500]}"

    transitions = resp.json().get("transitions", [])
    if not transitions:
        return None, f"No transitions available for {issue_key}. The ticket may already be in a terminal state."

    # Build lookup: normalised name → id
    target_norm = target_status.strip().upper().replace(" ", "_")
    aliases = _STATUS_ALIASES.get(target_norm, [target_status.lower()])

    for t in transitions:
        t_name_lower = t["name"].lower()
        for alias in aliases:
            if alias in t_name_lower:
                return t["id"], t["name"]

    available = ", ".join(f'"{t["name"]}"' for t in transitions)
    return None, f"No transition matching '{target_status}' found for {issue_key}. Available transitions: {available}"


# ===================================================================
# Tool 1: Create Jira Task
# ===================================================================
@tool
def create_jira_task(summary: str, description: str) -> str:
    """Create a new Task ticket on the Jira KAN board.

    Use this when receiving a new operational request from the user.
    The tool returns the Issue Key (e.g. KAN-15) that you MUST remember
    and reference throughout the task lifecycle.

    Args:
        summary: Short title for the ticket (e.g. "Check BGP status on SRX5600 cluster").
        description: Detailed description of what needs to be done.
    """
    if not _is_configured():
        return "Error: Jira is not configured. Missing JIRA_BASE_URL, JIRA_USER_EMAIL, or JIRA_API_TOKEN."

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": summary,
            "description": _text_to_adf(description),
            "issuetype": {"name": "Task"},
        }
    }

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue"
        resp = requests.post(
            url,
            json=payload,
            auth=_jira_auth(),
            headers=_jira_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            issue_key = data.get("key", "UNKNOWN")
            issue_id = data.get("id", "")
            logger.info(f"Jira ticket created: {issue_key} (id={issue_id})")
            return (
                f"✅ Đã tạo ticket Jira: **{issue_key}**\n"
                f"Link: {JIRA_BASE_URL}/browse/{issue_key}\n"
                f"Summary: {summary}"
            )
        else:
            error_detail = resp.text[:800]
            logger.error(f"Jira create failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error creating Jira ticket: HTTP {resp.status_code} — {error_detail}"
    except requests.exceptions.Timeout:
        return "Error: Jira API request timed out."
    except Exception as e:
        logger.error(f"Jira create exception: {e}")
        return f"Error creating Jira ticket: {e}"


# ===================================================================
# Tool 2: Update Task Status (Transition)
# ===================================================================
@tool
def update_task_status(issue_key: str, target_status: str) -> str:
    """Change the status of a Jira ticket.

    Use this to move a ticket through the Kanban workflow.

    Args:
        issue_key: The Jira issue key (e.g. "KAN-15").
        target_status: Target status — one of: IN_PROGRESS, WAITING, ERROR, DONE.
    """
    if not _is_configured():
        return "Error: Jira is not configured."

    transition_id, match_info = _find_transition_id(issue_key, target_status)
    if transition_id is None:
        return f"Error: {match_info}"

    payload = {"transition": {"id": transition_id}}

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
        resp = requests.post(
            url,
            json=payload,
            auth=_jira_auth(),
            headers=_jira_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code == 204:
            logger.info(f"Jira {issue_key} transitioned to '{match_info}' (id={transition_id})")
            return f"✅ Ticket {issue_key} đã chuyển sang trạng thái: **{match_info}**"
        else:
            error_detail = resp.text[:500]
            logger.error(f"Jira transition failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error transitioning {issue_key}: HTTP {resp.status_code} — {error_detail}"
    except requests.exceptions.Timeout:
        return f"Error: Jira API request timed out while transitioning {issue_key}."
    except Exception as e:
        logger.error(f"Jira transition exception: {e}")
        return f"Error transitioning {issue_key}: {e}"


# ===================================================================
# Tool 3: Add Task Comment
# ===================================================================
@tool
def add_task_comment(issue_key: str, comment_body: str) -> str:
    """Add a comment (log entry / report) to a Jira ticket.

    Use this to log progress, diagnostic results, error traces, or
    final reports into the ticket's activity stream.

    Args:
        issue_key: The Jira issue key (e.g. "KAN-15").
        comment_body: The comment content (plain text — will be converted to ADF).
    """
    if not _is_configured():
        return "Error: Jira is not configured."

    payload = {"body": _text_to_adf(comment_body)}

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
        resp = requests.post(
            url,
            json=payload,
            auth=_jira_auth(),
            headers=_jira_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            comment_id = resp.json().get("id", "?")
            logger.info(f"Comment added to {issue_key} (comment_id={comment_id})")
            return f"✅ Đã ghi comment vào ticket {issue_key} (comment #{comment_id})"
        else:
            error_detail = resp.text[:500]
            logger.error(f"Jira comment failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error adding comment to {issue_key}: HTTP {resp.status_code} — {error_detail}"
    except requests.exceptions.Timeout:
        return f"Error: Jira API request timed out while commenting on {issue_key}."
    except Exception as e:
        logger.error(f"Jira comment exception: {e}")
        return f"Error adding comment to {issue_key}: {e}"
