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
BOT_USER_ID = ""
if SLACK_BOT_TOKEN and SLACK_APP_TOKEN:
    app = App(token=SLACK_BOT_TOKEN)
    # Auto-detect the bot's own user ID to prevent duplicate event processing
    try:
        auth_result = app.client.auth_test()
        if auth_result.get("ok"):
            BOT_USER_ID = auth_result.get("user_id", "")
            logger.info(f"Slack bot user ID: {BOT_USER_ID}")
    except Exception as e:
        logger.warning(f"Failed to auto-detect bot user ID: {e}")
    BOT_USER_ID = BOT_USER_ID or os.environ.get("SLACK_BOT_USER_ID", "")
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
                        "text": "✅ Approve"
                    },
                    "style": "primary",
                    "value": issue_key,
                    "action_id": "approve_change"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ Reject"
                    },
                    "style": "danger",
                    "value": issue_key,
                    "action_id": "reject_change"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🔄 Request Changes"
                    },
                    "value": issue_key,
                    "action_id": "request_changes"
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
        # Skip if this message is also an app_mention (handled by handle_app_mention)
        # to prevent duplicate processing
        text = event.get("text", "")
        if BOT_USER_ID and f"<@{BOT_USER_ID}>" in text:
            return
        # Process message
        _handle_text_event(event, say)

    def _handle_text_event(event, say):
        if not _process_message_fn:
            return
            
        user = event.get("user")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts", event.get("ts"))
        channel_id = event.get("channel", "")
        
        user_id = f"slack-{user}"
        session_id = f"slack_thread:{thread_ts}"
        
        logger.info(f"Slack msg from {user}: {text[:80]}...")
        
        # --- Save Slack context into Redis state for async callback replies ---
        try:
            import redis as redis_lib
            redis_host = os.environ.get("REDIS_HOST", "49.213.77.222")
            redis_port = int(os.environ.get("REDIS_PORT", "6379"))
            r = redis_lib.Redis(host=redis_host, port=redis_port, decode_responses=True)
            state_key = f"state:{session_id}"
            state_data = r.get(state_key)
            if state_data:
                state = json.loads(state_data)
                state["slack_channel_id"] = channel_id
                state["slack_thread_ts"] = thread_ts
                r.set(state_key, json.dumps(state))
            else:
                # Will be created by run_supervisor_loop, pre-seed the slack context
                r.set(f"slack_ctx:{session_id}", json.dumps({
                    "channel_id": channel_id,
                    "thread_ts": thread_ts
                }))
        except Exception as e:
            logger.warning(f"Failed to save Slack context to Redis: {e}")
        
        # --- Context Enrichment: Fetch last 10 messages from thread/channel ---
        context_text = ""
        try:
            if thread_ts:
                # Fetch thread replies for context
                result = app.client.conversations_replies(
                    channel=channel_id,
                    ts=thread_ts,
                    limit=10
                )
            else:
                # Fetch channel history for context
                result = app.client.conversations_history(
                    channel=channel_id,
                    limit=10
                )
            
            messages = result.get("messages", [])
            if messages:
                context_lines = []
                for msg in messages[-10:]:
                    msg_user = msg.get("user", "bot")
                    msg_text = msg.get("text", "")
                    msg_ts = msg.get("ts", "")
                    # Resolve user display name
                    try:
                        user_info = app.client.users_info(user=msg_user)
                        if user_info.get("ok"):
                            profile = user_info["user"].get("profile", {})
                            display = profile.get("display_name") or profile.get("real_name") or msg_user
                        else:
                            display = msg_user
                    except Exception:
                        display = msg_user
                    context_lines.append(f"[{display}]: {msg_text}")
                
                if context_lines:
                    context_text = (
                        "\n\n--- Conversation Context (last {} messages) ---\n".format(len(context_lines))
                        + "\n".join(context_lines)
                        + "\n--- End Context ---\n"
                    )
                    logger.info(f"Enriched message with {len(context_lines)} context messages for thread {thread_ts}")
        except Exception as e:
            logger.warning(f"Failed to fetch conversation context: {e}")
        
        # Combine context with user message
        enriched_message = text
        if context_text:
            enriched_message = f"{text}{context_text}"
        
        try:
            response = _process_message_fn(enriched_message, user_id, session_id)
            say(text=response, thread_ts=thread_ts)
        except Exception as e:
            logger.error(f"Error processing Slack message: {e}", exc_info=True)
            say(text="⚠️ An error occurred while processing your message. Please try again later.", thread_ts=thread_ts)

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

    def _find_session_by_jira_key(issue_key):
        """Search Redis for the session that has the given jira_issue_key."""
        try:
            import redis as redis_lib
            redis_host = os.environ.get("REDIS_HOST", "49.213.77.222")
            redis_port = int(os.environ.get("REDIS_PORT", "6379"))
            r = redis_lib.Redis(host=redis_host, port=redis_port, decode_responses=True)
            
            for key in r.scan_iter("state:*"):
                data = r.get(key)
                if data:
                    try:
                        state = json.loads(data)
                        if state.get("jira_issue_key") == issue_key:
                            return state.get("session_id", key.split("state:", 1)[1])
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Failed to search Redis for jira key {issue_key}: {e}")
        return None

    def _trigger_l3_rework(issue_key, l3_feedback="L3 Human requested changes on this proposal."):
        """Find the session for this Jira issue and trigger l3_rework on the Supervisor."""
        session_id = _find_session_by_jira_key(issue_key)
        if not session_id:
            logger.error(f"No session found for Jira issue {issue_key}")
            return False
        
        # Get supervisor URL from Redis
        try:
            import redis as redis_lib
            redis_host = os.environ.get("REDIS_HOST", "49.213.77.222")
            redis_port = int(os.environ.get("REDIS_PORT", "6379"))
            r = redis_lib.Redis(host=redis_host, port=redis_port, decode_responses=True)
            supervisor_url = r.get("agent:url:supervisor-network-engineer-agent")
            
            if not supervisor_url:
                # Fallback: call process_message_fn directly if we're in-process
                logger.warning("Supervisor URL not in Redis, attempting local rework injection.")
                return False
            
            url = supervisor_url.rstrip("/") + "/invocations"
            resp = requests.post(url, json={
                "action": "l3_rework",
                "session_id": session_id,
                "l3_feedback": l3_feedback,
                "sender": "l3-human-slack"
            }, timeout=15)
            logger.info(f"L3 rework triggered for {issue_key} (session {session_id}): HTTP {resp.status_code}")
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to trigger L3 rework for {issue_key}: {e}")
            return False

    @app.action("request_changes")
    def handle_request_changes(ack, body, logger):
        ack()
        user = body["user"]["id"]
        action_value = body["actions"][0]["value"]  # issue_key
        
        # Update Slack message
        try:
            app.client.chat_update(
                channel=body["channel"]["id"],
                ts=body["message"]["ts"],
                text=f"🔄 Change Request `{action_value}` — *CHANGES REQUESTED* by <@{user}>. "
                     f"Agent will rework the proposal based on L3 feedback.",
                blocks=[]
            )
        except Exception as e:
            logger.error(f"Failed to update chat message: {e}")
        
        # Trigger rework flow
        _trigger_l3_rework(
            action_value,
            l3_feedback=f"L3 Engineer <@{user}> requested changes on proposal {action_value}. "
                        f"Check Jira comments for specific adjustment instructions."
        )

def start_slack_bot(process_message_fn):
    global _process_message_fn
    _process_message_fn = process_message_fn
    
    if not app:
        logger.error("Slack tokens not found. Slack bot cannot start.")
        return
        
    logger.info("Starting Slack bot in Socket Mode...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
