import os
import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

WORKSPACE_DIR = os.environ.get("AGENT_WORKSPACE", "/tmp/agent-workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

MAX_FILE_SIZE = 10 * 1024 * 1024


@tool
def read_file(file_path: str) -> str:
    """Read contents of a file from the agent workspace."""
    if not os.path.isabs(file_path):
        file_path = os.path.join(WORKSPACE_DIR, file_path)

    resolved = os.path.realpath(file_path)
    if not resolved.startswith(os.path.realpath(WORKSPACE_DIR)):
        return f"Error: Access denied. File must be within workspace: {WORKSPACE_DIR}"

    if not os.path.exists(resolved):
        return f"Error: File not found: {file_path}"

    size = os.path.getsize(resolved)
    if size > MAX_FILE_SIZE:
        return f"Error: File too large ({size} bytes). Max: {MAX_FILE_SIZE} bytes."

    try:
        with open(resolved, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return f"--- File: {os.path.basename(resolved)} ({len(content)} chars) ---\n{content}"
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file in the agent workspace."""
    if not os.path.isabs(file_path):
        file_path = os.path.join(WORKSPACE_DIR, file_path)

    resolved = os.path.realpath(file_path)
    if not resolved.startswith(os.path.realpath(WORKSPACE_DIR)):
        return f"Error: Access denied. File must be within workspace: {WORKSPACE_DIR}"

    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Success: Written {len(content)} chars to {os.path.basename(resolved)}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def list_workspace_files(subdirectory: str = "") -> str:
    """List files in the agent workspace directory."""
    target = os.path.join(WORKSPACE_DIR, subdirectory) if subdirectory else WORKSPACE_DIR
    resolved = os.path.realpath(target)
    if not resolved.startswith(os.path.realpath(WORKSPACE_DIR)):
        return f"Error: Access denied."

    if not os.path.isdir(resolved):
        return f"Error: Directory not found: {subdirectory or WORKSPACE_DIR}"

    try:
        entries = []
        for item in sorted(os.listdir(resolved)):
            full = os.path.join(resolved, item)
            if os.path.isdir(full):
                entries.append(f"  📁 {item}/")
            else:
                size = os.path.getsize(full)
                entries.append(f"  📄 {item} ({size} bytes)")
        if not entries:
            return f"Workspace is empty: {resolved}"
        return f"Workspace: {resolved}\n" + "\n".join(entries)
    except Exception as e:
        return f"Error listing files: {e}"


@tool
def http_request(url: str, method: str = "GET", headers: str = "", body: str = "") -> str:
    """Make an HTTP request to an API endpoint."""
    import requests

    method = method.upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
        return f"Error: Unsupported HTTP method: {method}"

    req_headers = {}
    if headers:
        for line in headers.strip().split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                req_headers[key.strip()] = val.strip()

    try:
        resp = requests.request(
            method, url,
            headers=req_headers,
            data=body if body else None,
            timeout=30,
            verify=True,
        )
        body_text = resp.text[:20000]
        truncated = " [TRUNCATED]" if len(resp.text) > 20000 else ""
        return (
            f"--- HTTP {method} {url} ---\n"
            f"Status: {resp.status_code} {resp.reason}\n"
            f"Content-Type: {resp.headers.get('Content-Type', 'N/A')}\n"
            f"Body ({len(resp.text)} chars{truncated}):\n{body_text}"
        )
    except requests.exceptions.Timeout:
        return f"Error: Request timed out after 30 seconds."
    except requests.exceptions.ConnectionError as e:
        return f"Error: Connection failed to {url}: {e}"
    except Exception as e:
        return f"Error: HTTP request failed: {e}"


@tool
def send_notification(audience_type: str, message: str) -> str:
    """Send a notification report to a specific target audience.
    Use this to notify L3 engineers or customers.

    Args:
        audience_type: Target audience, either "L3_Engineer" or "Customer".
        message: The message content to send.
    """
    if audience_type.strip().lower() == "customer":
        logger.info(f"Customer Notification Webhook: {message}")
        return f"✅ Customer Notification sent successfully:\n{message}"

    # For L3_Engineer, send raw logs via Telegram
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "6405110990")

    if not telegram_token:
        return f"Info: Telegram token not set. L3 Notification printed to logs:\n{message}"

    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    try:
        import requests
        payload = {
            "chat_id": chat_id,
            "text": f"🚨 <b>L3 ENGINEER NOTIFICATION:</b>\n\n{message}",
            "parse_mode": "HTML"
        }
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return f"✅ L3 Engineer Notification sent successfully via Telegram to chat {chat_id}."
        else:
            return f"Failed to send Telegram notification: HTTP {resp.status_code} - {resp.text}"
    except Exception as e:
        logger.error(f"Telegram notification exception: {e}")
        return f"Error sending Telegram notification: {e}"
