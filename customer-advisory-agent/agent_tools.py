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
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return f"Warning: SLACK_BOT_TOKEN not set. Message printed to logs:\n[{audience_type}] {message}"

    aud = audience_type.strip().lower()
    if aud == "customer":
        channel = os.environ.get("SLACK_CHANNEL_CUSTOMER", "#all-customer-001")
        prefix = "📢 *Customer Update:*\n"
    elif aud == "l3_engineer":
        channel = os.environ.get("SLACK_CHANNEL_ALERTS", "#noc-l3-alerts")
        prefix = "🚨 *L3 Engineer Escalation:*\n"
    else:
        return f"Error: Unknown audience type '{audience_type}'."

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel,
        "text": f"{prefix}{message}"
    }

    try:
        import requests
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp_json = resp.json()
        if resp.status_code == 200 and resp_json.get("ok"):
            return f"✅ Notification sent successfully to Slack channel {channel}."
        else:
            return f"Failed to send Slack notification: HTTP {resp.status_code} - {resp_json.get('error', resp.text)}"
    except Exception as e:
        logger.error(f"Slack notification exception: {e}")
        return f"Error sending Slack notification: {e}"


@tool
def slack_view_profile(user_id: str) -> str:
    """Get the Slack profile details of a user.
    
    Args:
        user_id: The Slack User ID (e.g., U0123456789).
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    url = "https://slack.com/api/users.info"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        import requests
        import json
        resp = requests.get(url, headers=headers, params={"user": user_id}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            user = data["user"]
            profile = user.get("profile", {})
            info = {
                "id": user["id"],
                "name": user["name"],
                "real_name": user.get("real_name"),
                "display_name": profile.get("display_name"),
                "email": profile.get("email"),
                "status_text": profile.get("status_text"),
                "status_emoji": profile.get("status_emoji"),
                "timezone": user.get("tz"),
                "is_bot": user.get("is_bot"),
                "is_admin": user.get("is_admin")
            }
            return json.dumps(info, indent=2, ensure_ascii=False)
        else:
            return f"Error retrieving user info: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@tool
def slack_react_message(channel_id: str, message_ts: str, emoji_name: str) -> str:
    """Add a reaction emoji (e.g., thumbsup, white_check_mark) to a message.
    
    Args:
        channel_id: The Slack Channel ID where the message resides.
        message_ts: The timestamp (ts) of the message to react to.
        emoji_name: The name of the emoji (without colons, e.g., 'thumbsup').
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    url = "https://slack.com/api/reactions.add"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel_id,
        "timestamp": message_ts,
        "name": emoji_name
    }
    try:
        import requests
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"Success: Reacted with :{emoji_name}: to message {message_ts}."
        else:
            return f"Failed to react: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@tool
def slack_view_status(user_id: str) -> str:
    """Get the presence status (active/away) of a user in Slack.
    
    Args:
        user_id: The Slack User ID.
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    url = "https://slack.com/api/users.getPresence"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        import requests
        resp = requests.get(url, headers=headers, params={"user": user_id}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"User {user_id} presence status: {data.get('presence')}"
        else:
            return f"Failed to get presence: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@tool
def slack_send_file(channel_id: str, file_path: str, title: str = "", initial_comment: str = "") -> str:
    """Upload and share a file from the workspace to a Slack channel.
    
    Args:
        channel_id: The Slack Channel ID to send the file to.
        file_path: Relative or absolute path of the file in the workspace.
        title: Title of the file.
        initial_comment: Optional comment to post with the file.
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    if not os.path.isabs(file_path):
        file_path = os.path.join(WORKSPACE_DIR, file_path)
    
    resolved = os.path.realpath(file_path)
    if not resolved.startswith(os.path.realpath(WORKSPACE_DIR)):
        return f"Error: Access denied. File must be within workspace: {WORKSPACE_DIR}"
    
    if not os.path.exists(resolved):
        return f"Error: File not found: {file_path}"
        
    filename = os.path.basename(resolved)
    try:
        import requests
        file_size = os.path.getsize(resolved)
        
        # Step 1: Call files.getUploadURLExternal
        url_get_upload = "https://slack.com/api/files.getUploadURLExternal"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"filename": filename, "length": file_size}
        
        resp_get = requests.get(url_get_upload, headers=headers, params=params, timeout=10)
        data_get = resp_get.json()
        if not data_get.get("ok"):
            return f"Failed to get upload URL: {data_get.get('error')}"
            
        upload_url = data_get["upload_url"]
        file_id = data_get["file_id"]
        
        # Step 2: Upload the binary data to the upload URL
        with open(resolved, 'rb') as f:
            file_data = f.read()
        resp_upload = requests.post(upload_url, files={"file": (filename, file_data)}, timeout=30)
        if resp_upload.status_code != 200:
            return f"Failed uploading file content: HTTP {resp_upload.status_code}"
            
        # Step 3: Call files.completeUploadExternal
        url_complete = "https://slack.com/api/files.completeUploadExternal"
        complete_payload = {
            "files": [{"id": file_id, "title": title or filename}],
            "channel_id": channel_id
        }
        if initial_comment:
            complete_payload["initial_comment"] = initial_comment
            
        resp_complete = requests.post(url_complete, json=complete_payload, headers=headers, timeout=15)
        data_complete = resp_complete.json()
        if data_complete.get("ok"):
            return f"Success: File '{filename}' uploaded and shared to channel {channel_id}."
        else:
            return f"Failed to complete upload: {data_complete.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@tool
def slack_read_file(file_id: str) -> str:
    """Retrieve details and textual content of a shared Slack file.
    
    Args:
        file_id: The Slack File ID (e.g., F0123456789).
    """
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        return "Error: SLACK_BOT_TOKEN is not set."
        
    headers = {"Authorization": f"Bearer {token}"}
    try:
        import requests
        import json
        url_info = "https://slack.com/api/files.info"
        resp_info = requests.get(url_info, headers=headers, params={"file": file_id}, timeout=10)
        data_info = resp_info.json()
        if not data_info.get("ok"):
            return f"Failed to get file info: {data_info.get('error')}"
            
        file_meta = data_info["file"]
        download_url = file_meta.get("url_private_download")
        if not download_url:
            return f"File metadata retrieved, but no private download URL found: {json.dumps(file_meta, indent=2)}"
            
        resp_dl = requests.get(download_url, headers=headers, timeout=20)
        if resp_dl.status_code == 200:
            content_type = resp_dl.headers.get("Content-Type", "")
            if "text" in content_type or "json" in content_type or "javascript" in content_type:
                text_content = resp_dl.text[:20000]
                truncated = " [TRUNCATED]" if len(resp_dl.text) > 20000 else ""
                return f"File: {file_meta.get('name')} | Type: {file_meta.get('mimetype')}\nContent{truncated}:\n{text_content}"
            else:
                return f"File: {file_meta.get('name')} | Type: {file_meta.get('mimetype')} | Size: {file_meta.get('size')} bytes (Binary content, not printed)."
        else:
            return f"Failed to download file content: HTTP {resp_dl.status_code}"
    except Exception as e:
        return f"Error: {e}"


@tool
def read_url(url: str) -> str:
    """Fetch content of a URL and parse it into human-readable text.
    
    Args:
        url: The web URL to download and read.
    """
    try:
        import requests
        import re
        import html
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return f"Error: HTTP {resp.status_code}"
            
        html_content = resp.text
        # Remove script and style blocks
        html_content = re.sub(r'<(script|style).*?>.*?</\1>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        # Strip HTML tags
        text = re.sub(r'<[^>]*>', ' ', html_content)
        # Unescape HTML entities
        text = html.unescape(text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        truncated = text[:20000]
        if len(text) > 20000:
            truncated += "\n... [Content Truncated]"
        return truncated
    except Exception as e:
        return f"Error: {e}"
