import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

TEAMS_BOT_APP_ID = os.environ.get("TEAMS_BOT_APP_ID")
TEAMS_BOT_APP_PASSWORD = os.environ.get("TEAMS_BOT_APP_PASSWORD")
TEAMS_BOT_TENANT_ID = os.environ.get("TEAMS_BOT_TENANT_ID", "botframework.com")

_token_cache = {
    "token": None,
    "expiry": 0
}

def get_teams_access_token():
    """Fetch or return cached Azure Bot Framework access token."""
    global _token_cache
    now = time.time()
    # If token exists and is valid for another 5 minutes, reuse it
    if _token_cache["token"] and _token_cache["expiry"] > now + 300:
        return _token_cache["token"]

    if not TEAMS_BOT_APP_ID or not TEAMS_BOT_APP_PASSWORD:
        logger.warning("TEAMS_BOT_APP_ID or TEAMS_BOT_APP_PASSWORD not set. Cannot fetch token.")
        return None

    try:
        tenant = TEAMS_BOT_TENANT_ID or "botframework.com"
        url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": TEAMS_BOT_APP_ID,
            "client_secret": TEAMS_BOT_APP_PASSWORD,
            "scope": "https://api.botframework.com/.default"
        }
        resp = requests.post(url, data=payload, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            _token_cache["token"] = token
            _token_cache["expiry"] = now + expires_in
            logger.info("Successfully fetched new Teams Bot access token.")
            return token
        else:
            logger.error(f"Failed to fetch Teams token: {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"Error fetching Teams Bot token: {e}")
    return None

def format_teams_markdown(text: str) -> str:
    """Preprocess markdown text to make it display cleanly in Microsoft Teams.
    Specifically:
    1. Preserves single line breaks in non-code blocks by adding two spaces at the end of lines.
    2. Ensures headers, code blocks, lists, and horizontal rules are formatted cleanly.
    """
    if not text:
        return text
        
    import re
    lines = text.split("\n")
    in_code_block = False
    formatted_lines = []
    
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            formatted_lines.append(line)
            continue
            
        if in_code_block:
            formatted_lines.append(line)
        else:
            if not stripped:
                formatted_lines.append(line)
            elif (stripped.startswith("#") or 
                  stripped.startswith("-") or 
                  stripped.startswith("*") or 
                  stripped.startswith(">") or 
                  stripped.startswith("1.") or
                  stripped.startswith("2.") or
                  stripped.startswith("3.") or
                  stripped.startswith("4.") or
                  stripped.startswith("5.") or
                  stripped.startswith("6.") or
                  stripped.startswith("7.") or
                  stripped.startswith("8.") or
                  stripped.startswith("9.") or
                  stripped.startswith("0.") or
                  re.match(r'^\d+\.', stripped) or
                  stripped.endswith("  ")):
                formatted_lines.append(line)
            else:
                formatted_lines.append(line + "  ")
                
    return "\n".join(formatted_lines)

def send_teams_message(service_url, conversation_id, text):
    """Send a plain or markdown message to a Microsoft Teams conversation."""
    token = get_teams_access_token()
    if not token:
        logger.warning("No access token available. Cannot send Teams message.")
        return False

    # Process markdown to preserve line breaks
    formatted_text = format_teams_markdown(text)

    url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "type": "message",
        "text": formatted_text,
        "textFormat": "markdown"
    }


    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in [200, 201, 202]:
            logger.info(f"Successfully sent message to Teams conversation {conversation_id}.")
            return True
        else:
            logger.error(f"Failed to send Teams message: HTTP {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"Error sending Teams message: {e}")
    return False

def send_teams_approval_request(service_url, conversation_id, issue_key, reason, diff_text):
    """Send an Adaptive Card for CAB approval to MS Teams."""
    token = get_teams_access_token()
    if not token:
        logger.warning("No access token available. Cannot send Teams approval request.")
        return False

    url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Construct Adaptive Card with Input.Text for comments/feedback
    card_content = {
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": f"🔔 Change Request Approval Required: {issue_key}",
                "weight": "Bolder",
                "size": "Medium",
                "color": "Warning"
            },
            {
                "type": "TextBlock",
                "text": f"**Reason:**\n{reason}",
                "wrap": True
            },
            {
                "type": "TextBlock",
                "text": "**Configuration Diff (Junos XML / CLI):**",
                "weight": "Bolder"
            },
            {
                "type": "TextBlock",
                "text": f"```\n{diff_text}\n```",
                "wrap": True,
                "fontType": "Monospace"
            },
            {
                "type": "Input.Text",
                "id": "l3_comment",
                "placeholder": "Nhập comment/feedback (bắt buộc nếu Rework/Reject)...",
                "isMultiline": True
            }
        ],
        "actions": [
            {
                "type": "Action.Submit",
                "title": "✅ Approve",
                "data": {
                    "action": "approve_change",
                    "value": issue_key
                }
            },
            {
                "type": "Action.Submit",
                "title": "❌ Reject",
                "data": {
                    "action": "reject_change",
                    "value": issue_key
                }
            },
            {
                "type": "Action.Submit",
                "title": "🔄 Request Changes (Rework)",
                "data": {
                    "action": "request_changes",
                    "value": issue_key
                }
            }
        ]
    }

    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card_content
            }
        ]
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in [200, 201, 202]:
            logger.info(f"Successfully sent Teams CAB approval request for {issue_key}.")
            return True
        else:
            logger.error(f"Failed to send Teams CAB approval request: HTTP {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"Error sending Teams CAB approval request: {e}")
    return False
