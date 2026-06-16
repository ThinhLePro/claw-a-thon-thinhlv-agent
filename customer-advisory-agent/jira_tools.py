import os
import logging
import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
JIRA_USER_EMAIL = os.environ.get("JIRA_USER_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "KAN")

_TIMEOUT = 15


def _jira_auth() -> tuple[str, str]:
    return (JIRA_USER_EMAIL, JIRA_API_TOKEN)


def _jira_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _is_configured() -> bool:
    return bool(JIRA_BASE_URL and JIRA_USER_EMAIL and JIRA_API_TOKEN)


def _text_to_adf(text: str) -> dict:
    paragraphs = text.split("\n\n") if "\n\n" in text else [text]
    doc_content = []
    for para in paragraphs:
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


_STATUS_ALIASES: dict[str, list[str]] = {
    "IN_PROGRESS": ["in progress", "start progress", "in-progress"],
    "WAITING":     ["waiting", "wait", "blocked", "on hold"],
    "ERROR":       ["error", "fail", "failed"],
    "DONE":        ["done", "complete", "resolve", "closed", "close"],
}


def _find_transition_id(issue_key: str, target_status: str) -> tuple[str | None, str]:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    resp = requests.get(url, auth=_jira_auth(), headers=_jira_headers(), timeout=_TIMEOUT)
    if resp.status_code != 200:
        return None, f"Failed to fetch transitions for {issue_key}: HTTP {resp.status_code} — {resp.text[:500]}"

    transitions = resp.json().get("transitions", [])
    if not transitions:
        return None, f"No transitions available for {issue_key}. The ticket may already be in a terminal state."

    target_norm = target_status.strip().upper().replace(" ", "_")
    aliases = _STATUS_ALIASES.get(target_norm, [target_status.lower()])

    for t in transitions:
        t_name_lower = t["name"].lower()
        for alias in aliases:
            if alias in t_name_lower:
                return t["id"], t["name"]

    available = ", ".join(f'"{t["name"]}"' for t in transitions)
    return None, f"No transition matching '{target_status}' found for {issue_key}. Available transitions: {available}"


@tool
def create_jira_task(summary: str, description: str) -> str:
    """Create a new Task ticket on the Jira KAN board."""
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
            logger.info(f"Jira ticket created: {issue_key}")
            return (
                f"✅ Đã tạo ticket Jira: **{issue_key}**\n"
                f"Link: {JIRA_BASE_URL}/browse/{issue_key}\n"
                f"Summary: {summary}"
            )
        else:
            error_detail = resp.text[:800]
            logger.error(f"Jira create failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error creating Jira ticket: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira create exception: {e}")
        return f"Error creating Jira ticket: {e}"


@tool
def update_task_status(issue_key: str, target_status: str) -> str:
    """Change the status of a Jira ticket."""
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
            logger.info(f"Jira {issue_key} transitioned to '{match_info}'")
            return f"✅ Ticket {issue_key} đã chuyển sang trạng thái: **{match_info}**"
        else:
            error_detail = resp.text[:500]
            logger.error(f"Jira transition failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error transitioning {issue_key}: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira transition exception: {e}")
        return f"Error transitioning {issue_key}: {e}"


@tool
def add_task_comment(issue_key: str, comment_body: str) -> str:
    """Add a comment (log entry / report) to a Jira ticket."""
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
            logger.info(f"Comment added to {issue_key}")
            return f"✅ Đã ghi comment vào ticket {issue_key} (comment #{comment_id})"
        else:
            error_detail = resp.text[:500]
            logger.error(f"Jira comment failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error adding comment to {issue_key}: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira comment exception: {e}")
        return f"Error adding comment to {issue_key}: {e}"


@tool
def query_previous_incidents(device_ip: str) -> str:
    """Search Jira for previous incident tasks related to a specific device IP or hostname."""
    if not _is_configured():
        return "Error: Jira is not configured."

    jql = f'project = "{JIRA_PROJECT_KEY}" AND (summary ~ "{device_ip}" OR description ~ "{device_ip}")'

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/search"
        resp = requests.get(
            url,
            params={"jql": jql, "maxResults": 10},
            auth=_jira_auth(),
            headers=_jira_headers(),
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            issues = data.get("issues", [])
            if not issues:
                return f"No previous incidents found on Jira for device {device_ip}."

            lines = [f"Found {len(issues)} previous incident(s) for device {device_ip}:"]
            for issue in issues:
                key = issue.get("key")
                fields = issue.get("fields", {})
                summary = fields.get("summary", "No Summary")
                status = fields.get("status", {}).get("name", "Unknown")
                created = fields.get("created", "Unknown")[:10]
                lines.append(f"- **{key}** ({status}) | Created: {created} | Summary: {summary}")
            return "\n".join(lines)
        else:
            error_detail = resp.text[:500]
            logger.error(f"Jira search failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error searching Jira: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira search exception: {e}")
        return f"Error searching Jira: {e}"
