import os
import logging
import json
import hmac
import hashlib
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

logger = logging.getLogger(__name__)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")

# Initialize app only if tokens are present
if SLACK_BOT_TOKEN and SLACK_APP_TOKEN:
    app = App(token=SLACK_BOT_TOKEN)
else:
    app = None

# Globals for channel tracking
SLACK_CHANNEL_CUSTOMER = os.environ.get("SLACK_CHANNEL_CUSTOMER", "#all-customer-001")
SLACK_CHANNEL_ALERTS = os.environ.get("SLACK_CHANNEL_ALERTS", "#noc-l3-alerts")
SLACK_CHANNEL_APPROVALS = os.environ.get("SLACK_CHANNEL_APPROVALS", "#noc-cab-approvals")

_process_message_fn = None

def send_slack_message(channel_id, text, blocks=None):
    """Utility to send messages to specific Slack channels."""
    if not app:
        logger.warning("Slack app is not initialized. Cannot send message.")
        return
    try:
        if blocks:
            app.client.chat_postMessage(channel=channel_id, text=text, blocks=blocks)
        else:
            app.client.chat_postMessage(channel=channel_id, text=text)
    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")

def send_approval_request(issue_key, reason, diff_text):
    """Send an approval request with Block Kit buttons to the CAB channel."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔔 Change Request Required: {issue_key}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Reason:*\n{reason}\n\n*Configuration Diff:*\n```\n{diff_text}\n```"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approve"
                    },
                    "style": "primary",
                    "value": issue_key,
                    "action_id": "approve_change"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Reject"
                    },
                    "style": "danger",
                    "value": issue_key,
                    "action_id": "reject_change"
                }
            ]
        }
    ]
    send_slack_message(SLACK_CHANNEL_APPROVALS, f"Change Request: {issue_key}", blocks=blocks)

if app:
    @app.event("app_mention")
    def handle_app_mention(event, say):
        _handle_text_event(event, say)

    @app.event("message")
    def handle_message(event, say):
        if "subtype" in event:
            return
        # Process message
        _handle_text_event(event, say)

    def _handle_text_event(event, say):
        if not _process_message_fn:
            return
            
        user = event.get("user")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts", event.get("ts"))
        
        user_id = f"slack-{user}"
        session_id = f"slack_thread:{thread_ts}"
        
        logger.info(f"Slack msg from {user}: {text[:80]}...")
        
        try:
            response = _process_message_fn(text, user_id, session_id)
            say(text=response, thread_ts=thread_ts)
        except Exception as e:
            logger.error(f"Error processing Slack message: {e}", exc_info=True)
            say(text="⚠️ Có lỗi xảy ra khi xử lý tin nhắn. Vui lòng thử lại sau.", thread_ts=thread_ts)

    @app.action("approve_change")
    def handle_approve(ack, body, logger):
        ack()
        user = body["user"]["id"]
        action_value = body["actions"][0]["value"]
        
        # Trigger webhook
        _trigger_mcp_approval(action_value, "Approved")
        
        # Update message
        try:
            app.client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text=f"✅ Change Request `{action_value}` has been APPROVED by <@{user}>.",
                blocks=[] 
            )
        except Exception as e:
            logger.error(f"Failed to update chat message: {e}")

    @app.action("reject_change")
    def handle_reject(ack, body, logger):
        ack()
        user = body["user"]["id"]
        action_value = body["actions"][0]["value"]
        
        _trigger_mcp_approval(action_value, "Rejected")
        
        try:
            app.client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text=f"❌ Change Request `{action_value}` has been REJECTED by <@{user}>.",
                blocks=[]
            )
        except Exception as e:
            logger.error(f"Failed to update chat message: {e}")

    def _trigger_mcp_approval(issue_key, status_name):
        jira_secret = os.environ.get("JIRA_WEBHOOK_SECRET", "Gng0D3c8U0BsYOSlxdIT")
        mcp_url = os.environ.get("MCP_WEBHOOK_URL", "http://localhost:8980/webhook/jira")
        
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {
                "key": issue_key,
                "fields": {
                    "status": {"name": status_name},
                    "description": "Approval handled by Slack integration"
                }
            }
        }
        
        payload_bytes = json.dumps(payload).encode("utf-8")
        signature = hmac.new(jira_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        
        headers = {
            "Content-Type": "application/json",
            "X-Hub-Signature": f"sha256={signature}"
        }
        
        try:
            resp = requests.post(mcp_url, data=payload_bytes, headers=headers)
            logger.info(f"Webhook to MCP triggered for {issue_key}: {status_name}, Status: {resp.status_code}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to trigger MCP approval webhook: {e}")
            return False

def start_slack_bot(process_message_fn):
    global _process_message_fn
    _process_message_fn = process_message_fn
    
    if not app:
        logger.error("Slack tokens not found. Slack bot cannot start.")
        return
        
    logger.info("Starting Slack bot in Socket Mode...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
