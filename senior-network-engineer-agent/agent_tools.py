import os
import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

WORKSPACE_DIR = os.environ.get("AGENT_WORKSPACE", "/tmp/agent-workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

MAX_FILE_SIZE = 10 * 1024 * 1024


# ===================================================================
# LOCAL WORKSPACE TOOLS (Agent-local, not available via MCP)
# ===================================================================

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


# ===================================================================
# DIAGNOSTIC TOOLS (Agent-local, uses MCP internally)
# ===================================================================

@tool
def check_flapping_history(device_ip: str, interface: str = "") -> str:
    """Check the syslog history of a device to see if an interface is flapping (frequent up/down events)."""
    mcp_server_url = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/sse")
    from mcp_client import call_mcp_tool

    try:
        logs_str = call_mcp_tool(mcp_server_url, "get_device_logs", {"device_ip": device_ip})
        if "Error" in logs_str or not logs_str:
            return f"Failed to retrieve logs for flapping analysis on device {device_ip}."

        import re
        lines = logs_str.strip().split("\n")
        
        flap_pattern = re.compile(
            r"(link[_-]?(up|down)|state\s+changed\s+to\s+(up|down)|snmp_link(down|up))",
            re.IGNORECASE
        )
        
        events = []
        for line in lines:
            if interface and interface.lower() not in line.lower():
                continue
            if flap_pattern.search(line):
                events.append(line)

        if not events:
            return f"No interface flapping events detected on device {device_ip}" + (f" for interface {interface}." if interface else ".")

        count = len(events)
        summary = [f"Detected {count} interface status transition events on device {device_ip}:"]
        for evt in events[-10:]:
            summary.append(f"- {evt}")
            
        if count >= 3:
            summary.append(f"\n⚠️ WARNING: Flapping threshold exceeded ({count} events detected). The interface is likely flapping.")
        else:
            summary.append(f"\nInfo: Flap frequency is stable ({count} transitions detected).")
            
        return "\n".join(summary)
    except Exception as e:
        logger.error(f"Error in check_flapping_history: {e}")
        return f"Error checking flapping history: {e}"


@tool
def capture_state_snapshot(device_ip: str) -> str:
    """Capture a diagnostic snapshot of the current device status."""
    mcp_server_url = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/sse")
    from mcp_client import call_mcp_tool
    import datetime

    alarms = call_mcp_tool(mcp_server_url, "check_device_alarms", {"device_ip": device_ip})
    interfaces = call_mcp_tool(mcp_server_url, "execute_device_command", {"device_ip": device_ip, "command": "show interfaces terse"})
    bgp = call_mcp_tool(mcp_server_url, "execute_device_command", {"device_ip": device_ip, "command": "show bgp neighbor"})
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_filename = f"snapshot_{device_ip}_{timestamp}.txt"
    filepath = os.path.join(WORKSPACE_DIR, snapshot_filename)
    
    snapshot_content = f"""==================================================
DEVICE STATE SNAPSHOT: {device_ip}
Captured At: {datetime.datetime.now().isoformat()}
==================================================

1. ACTIVE SYSTEM ALARMS:
--------------------------------------------------
{alarms}

2. INTERFACE STATUS:
--------------------------------------------------
{interfaces[:5000]}

3. BGP NEIGHBOR STATUS:
--------------------------------------------------
{bgp[:5000]}
"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(snapshot_content)
        return (
            f"✅ Successfully captured state snapshot for {device_ip}.\n"
            f"File saved to workspace: [snapshot_{device_ip}_{timestamp}.txt](file://{filepath})\n"
            f"Active Alarms: {alarms[:100].strip()}..."
        )
    except Exception as e:
        logger.error(f"Error saving state snapshot: {e}")
        return f"Error capturing state snapshot: {e}"


# ===================================================================
# NOTE: All Slack and URL tools have been CENTRALIZED to the MCP Server.
# They are now discovered dynamically via MCP tool discovery and controlled
# by Redis-backed ACLs. Duplicate implementations removed to maintain
# Single Source of Truth:
#
# Centralized to MCP (mcp_server.py):
#   - slack_react_message
#   - slack_check_user_profile (was: slack_view_profile)
#   - slack_view_status
#   - slack_send_file
#   - slack_read_file
#   - slack_send_url
#   - slack_reply_in_thread
#   - slack_update_message
#   - slack_mention_user_or_group
#   - slack_create_channel
#   - slack_invite_to_channel
#   - slack_send_block_kit
#   - slack_get_channel_history
#   - read_url
#   - send_notification
# ===================================================================
