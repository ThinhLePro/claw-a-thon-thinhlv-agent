import os
import logging
import threading
import json
import requests
import html
from datetime import datetime
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
import redis

from greennode_agentbase import (
    GreenNodeAgentBaseApp,
    RequestContext,
    PingStatus,
)

from system_prompt import SYSTEM_PROMPT
from slack_bot import start_slack_bot, send_slack_message, SLACK_CHANNEL_ALERTS
from telegram_bot import start_telegram_bot
from markdown_converter import markdown_to_telegram_html

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = GreenNodeAgentBaseApp()

# --- LLM Config ---
LLM_MODEL = os.environ.get("LLM_MODEL", "google/gemma-4-31b-it")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

llm = ChatOpenAI(
    model=LLM_MODEL,
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY,
)

# --- Redis Config ---
# NOTE: Connect via internal LAN IP '10.116.0.181' for local/on-premise hosts (e.g. MCP Server).
# Connect via public NAT IP '49.213.77.222' for cloud-deployed Greennode agents.
REDIS_HOST = os.environ.get("REDIS_HOST", "49.213.77.222")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True
)

class StateManager:
    @staticmethod
    def get_state(session_id: str) -> dict:
        data = redis_client.get(f"state:{session_id}")
        if data:
            return json.loads(data)
        return None

    @staticmethod
    def save_state(session_id: str, state: dict):
        redis_client.set(f"state:{session_id}", json.dumps(state))

    @staticmethod
    def get_agent_url(agent_name: str) -> str:
        return redis_client.get(f"agent:url:{agent_name}")

    @staticmethod
    def set_agent_url(agent_name: str, url: str):
        redis_client.set(f"agent:url:{agent_name}", url)


def send_telegram_message(message: str):
    """Send a message to Telegram using BOT_TOKEN and CHAT_ID from env."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        if resp.status_code == 200:
            logger.info("Successfully sent session log to Telegram.")
        else:
            logger.error(f"Failed to send Telegram message: HTTP {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")


def send_jira_comment(issue_key: str, comment_text: str):
    """Post a comment to a Jira ticket using credentials from env."""
    jira_base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    jira_user = os.environ.get("JIRA_USER_EMAIL")
    jira_token = os.environ.get("JIRA_API_TOKEN")
    
    if not jira_base_url or not jira_user or not jira_token:
        logger.warning("Jira configuration missing in Supervisor env. Cannot post comment.")
        return
        
    # Simple ADF converter
    paragraphs = comment_text.split("\n\n") if "\n\n" in comment_text else [comment_text]
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
            doc_content.append({"type": "paragraph", "content": inline_nodes})
            
    adf_body = {
        "version": 1,
        "type": "doc",
        "content": doc_content or [
            {"type": "paragraph", "content": [{"type": "text", "text": "(empty)"}]}
        ]
    }
    
    url = f"{jira_base_url}/rest/api/3/issue/{issue_key}/comment"
    try:
        resp = requests.post(
            url,
            auth=(jira_user, jira_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"body": adf_body},
            timeout=15
        )
        if resp.status_code == 201:
            logger.info(f"Successfully posted final result to Jira ticket {issue_key}")
        else:
            logger.error(f"Failed to post comment to Jira: HTTP {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"Error posting comment to Jira ticket {issue_key}: {e}")


def parse_json_garbage(text: str) -> dict:
    """Extract and parse first JSON block in text."""
    # Find JSON bounds
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]
    return json.loads(text)


def safe_get(d: dict, key: str, default: str = "") -> str:
    """Safely get string value from dict, stripping it, handling None and non-string types."""
    val = d.get(key)
    if val is None:
        return default
    return str(val).strip()


def get_slack_user_profile(user_id: str) -> dict:
    """Fetch user profile details from Slack using Web API."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token or not user_id or not user_id.startswith("slack-"):
        return {}
    slack_uid = user_id.replace("slack-", "")
    try:
        url = "https://slack.com/api/users.info"
        resp = requests.get(url, params={"user": slack_uid}, headers={"Authorization": f"Bearer {token}"}, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                user_data = data.get("user", {})
                profile = user_data.get("profile", {})
                return {
                    "real_name": user_data.get("real_name") or profile.get("real_name") or "",
                    "title": profile.get("title") or "",
                    "pronouns": profile.get("pronouns") or ""
                }
    except Exception as e:
        logger.error(f"Error fetching slack user profile: {e}")
    return {}


def run_supervisor_loop(session_id: str, user_message: str = None, user_id: str = None) -> str:
    """Load state, query router LLM, route to next worker, or conclude."""
    state = StateManager.get_state(session_id)
    
    if state and state.get("current_assignee") == "FINISH" and not user_message:
        logger.info(f"Session {session_id} is already in FINISH state. Skipping supervisor loop.")
        return state.get("rca_summary") or "Diagnostic workflow completed."
        
    if not state:
        state = {
            "session_id": session_id,
            "user_id": user_id,
            "alert_source": "User report" if user_id else "Monitoring system",
            "symptoms": user_message or "Diagnostic request",
            "affected_entities": [],
            "inventory_context": {},
            "diagnostic_logs": [],
            "current_assignee": "supervisor-network-engineer-agent",
            "rca_summary": "",
            "jira_issue_key": "",
            "loop_count": 0,
            "messages": []
        }
        # Fetch Slack user profile if user_id is provided
        if user_id and user_id.startswith("slack-"):
            state["user_profile"] = get_slack_user_profile(user_id)
        # Load pre-seeded Slack context if available (set by slack_bot.py before state existed)
        try:
            slack_ctx_data = redis_client.get(f"slack_ctx:{session_id}")
            if slack_ctx_data:
                slack_ctx = json.loads(slack_ctx_data)
                state["slack_channel_id"] = slack_ctx.get("channel_id", "")
                state["slack_thread_ts"] = slack_ctx.get("thread_ts", "")
                redis_client.delete(f"slack_ctx:{session_id}")  # Clean up
        except Exception:
            pass
    elif user_id:
        state["user_id"] = user_id
        if "user_profile" not in state and user_id.startswith("slack-"):
            state["user_profile"] = get_slack_user_profile(user_id)
    
    if user_message:
        state["messages"].append({"role": "user", "content": user_message})
        state["loop_count"] = 0

    # Increment loop count
    state["loop_count"] += 1
    
    # 1. Enforce Fallback Limit
    if state["loop_count"] > 5 and state.get("current_assignee") not in ["customer-advisory-agent", "FINISH"]:
        logger.warning(f"Loop limit exceeded ({state['loop_count']}) for session {session_id}. Forcing escalation.")
        state["diagnostic_logs"].append("Supervisor: Max loop count exceeded. Escalating to Level 3.")
        state["current_assignee"] = "customer-advisory-agent"
        StateManager.save_state(session_id, state)
        
        customer_url = StateManager.get_agent_url("customer-advisory-agent")
        if customer_url:
            try:
                url = customer_url.rstrip("/") + "/invocations"
                response = requests.post(url, json={"session_id": session_id}, timeout=10)
                response.raise_for_status()
                return "⚠️ Auto-processing time limit exceeded. Ticket has been escalated to L3 Human Engineers and the customer has been notified."
            except Exception as ex:
                logger.error(f"Failed to call customer advisory: {ex}")
        return "⚠️ Connection error while sending urgent support request. Please contact the NOC team directly."

    # 2. Invoke Router LLM
    try:
        state_summary = f"""Current State JSON:
{json.dumps(state, indent=2)}

Please evaluate the logs, assignee, and rca_summary. Respond ONLY with the JSON block."""
        
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=state_summary)
        ]
        
        response = llm.invoke(messages)
        res_json = parse_json_garbage(response.content.strip())
        
        next_agent = safe_get(res_json, "next_action", "FINISH")
        incident_class = safe_get(res_json, "incident_class", "Service")
        reasoning = safe_get(res_json, "reasoning", "")
        intent = safe_get(res_json, "intent", "INCIDENT_RESPONSE")
        priority = safe_get(res_json, "priority", "P3")
        
        state["priority"] = priority
        
        logger.info(f"Supervisor Route Decision: {next_agent} | Priority: {priority} | Intent: {intent} | Incident Class: {incident_class} | Reason: {reasoning}")
        
        if priority == "P1":
            logger.warning(f"CRITICAL P1 ALERT DETECTED for session {session_id}. Triggering L3 Slack alarm.")
            if not state.get("p1_alert_sent"):
                send_slack_message(
                    SLACK_CHANNEL_ALERTS,
                    f"<!channel> 🚨 *CRITICAL P1 ALERT* - Core infrastructure incident detected!\n"
                    f"*Symptoms:* {state.get('symptoms', 'Unknown core link/BGP down')}\n"
                    f"AI Agent is running full diagnostic pipeline. L3 NOC Team standby for oversight."
                )
                state["p1_alert_sent"] = True
                # P1 does NOT override routing — workflow continues normally
                # The LLM routing decision is preserved (next_agent stays as decided by the router)
                state["diagnostic_logs"].append("P1 CRITICAL: Slack alarm sent to L3 Human Engineers. Full pipeline continues.")
            
        state["diagnostic_logs"].append(f"Supervisor decision: Route to {next_agent} (Intent: {intent}, Priority: {priority}). Reason: {reasoning}")
        state["current_assignee"] = next_agent
        
        StateManager.save_state(session_id, state)
        
        if next_agent == "FINISH":
            # Return direct response from JSON if available, fallback to rca_summary or default
            direct_response = safe_get(res_json, "response", "")
            
            # Auto-send completed session logs to Telegram
            try:
                symptoms = state.get("symptoms", "No details")
                jira = state.get("jira_issue_key", "None")
                logs = state.get("diagnostic_logs", [])
                
                log_text = f"📋 <b>Session Completed: <code>{html.escape(session_id)}</code></b>\n"
                log_text += f"━━━━━━━━━━━━━━━━━━━\n"
                log_text += f"▪️ <b>Symptoms</b>: {markdown_to_telegram_html(symptoms)}\n"
                log_text += f"▪️ <b>Jira Ticket</b>: <code>{html.escape(jira)}</code>\n"
                log_text += f"━━━━━━━━━━━━━━━━━━━\n\n"
                log_text += "<b>Diagnostic History:</b>\n"
                for idx, log_entry in enumerate(logs, 1):
                    log_text += f"{idx}. {markdown_to_telegram_html(log_entry)}\n"
                
                send_telegram_message(log_text)
            except Exception as tg_ex:
                logger.error(f"Failed to auto-send Telegram logs: {tg_ex}")

            # --- Auto-notify Customer on Resolution (Closure Notification) ---
            # Safety net: only sends if Customer Advisory Agent didn't already notify
            try:
                # Reload state to check if closure_notified was set by send_notification MCP tool
                state = StateManager.get_state(session_id) or state
                
                slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
                customer_channel = os.environ.get("SLACK_CHANNEL_CUSTOMER", "#all-customer-001")
                slack_channel = state.get("slack_channel_id", "")
                if slack_token and not state.get("closure_notified") and (slack_channel == customer_channel):
                    symptoms = state.get("symptoms", "")
                    rca = state.get("rca_summary", "")
                    jira = state.get("jira_issue_key", "")
                    
                    raw_summary = rca or direct_response or ""
                    
                    is_escalated = False
                    if state.get("loop_count", 0) > 5:
                        is_escalated = True
                    else:
                        summary_lower = raw_summary.lower()
                        if "escalat" in summary_lower or "level 3" in summary_lower or "l3" in summary_lower:
                            is_escalated = True
                        for log in state.get("diagnostic_logs", []):
                            if "escalat" in log.lower() or "level 3" in log.lower() or "l3" in log.lower():
                                is_escalated = True
                                break
                    
                    if is_escalated:
                        closure_msg = "⚠️ *[Incident Escalated to L3]*\n\n"
                    else:
                        closure_msg = "✅ *[Incident Resolved]*\n\n"
                        
                    if jira:
                        closure_msg += f"📋 *Ticket:* `{jira}`\n"
                    
                    # Clean up technical details, logs, code blocks, or conversation context
                    import re
                    # Remove ```...``` code blocks
                    clean_summary = re.sub(r"```.*?```", "", raw_summary, flags=re.DOTALL)
                    
                    # Filter out log/debug lines and conversation context
                    lines = []
                    for line in clean_summary.split("\n"):
                        l_strip = line.strip()
                        if not l_strip:
                            continue
                        if l_strip.startswith("---") or "Conversation Context" in l_strip or "End Context" in l_strip:
                            continue
                        if any(k in l_strip.lower() for k in ["diagnostic_logs", "rca_summary", "loop_count"]):
                            continue
                        lines.append(line)
                    clean_summary = "\n".join(lines).strip()
                    
                    if clean_summary:
                        # Convert markdown bold to Slack format
                        clean_summary = clean_summary.replace("**", "*")
                        closure_msg += f"{clean_summary}\n"
                    else:
                        closure_msg += "The issue has been resolved by our engineering team.\n"
                    
                    closure_msg += f"\n💬 If you have any further questions, please reply here or contact the NOC team directly."
                    
                    import requests as req_lib_local
                    url = "https://slack.com/api/chat.postMessage"
                    headers = {
                        "Authorization": f"Bearer {slack_token}",
                        "Content-Type": "application/json; charset=utf-8"
                    }
                    payload = {
                        "channel": customer_channel,
                        "text": closure_msg
                    }
                    resp = req_lib_local.post(url, json=payload, headers=headers, timeout=10)
                    if resp.status_code == 200 and resp.json().get("ok"):
                        logger.info(f"Closure notification sent to customer channel {customer_channel}")
                        state["closure_notified"] = True
                        StateManager.save_state(session_id, state)
                    else:
                        logger.warning(f"Failed to send closure notification: {resp.json().get('error', resp.text[:200])}")
                elif state.get("closure_notified"):
                    logger.info(f"Skipping hardcoded closure — already notified by Customer Advisory Agent via MCP.")
            except Exception as closure_ex:
                logger.error(f"Failed to send customer closure notification: {closure_ex}")

            if direct_response:
                return direct_response
            return state["rca_summary"] or "Diagnostic workflow completed."
            
        # Trigger the worker agent dynamically
        worker_url = StateManager.get_agent_url(next_agent)
        if not worker_url:
            logger.error(f"Endpoint for agent {next_agent} not found in Redis.")
            return f"System error: Service endpoint for {next_agent} not found."
            
        # Call worker asynchronously
        def _trigger():
            try:
                url = worker_url.rstrip("/") + "/invocations"
                response = requests.post(url, json={"session_id": session_id}, timeout=30)
                response.raise_for_status()
                logger.info(f"Successfully triggered worker {next_agent} with status {response.status_code}")
            except Exception as e:
                logger.error(f"Failed to trigger worker {next_agent} at {worker_url}: {e}")
                
        threading.Thread(target=_trigger, daemon=True).start()
        
        # Return AI-generated status update to user
        ai_response = safe_get(res_json, "response", "")
        if ai_response:
            return ai_response
        return f"Routing to {next_agent} for processing..."
        
    except Exception as e:
        logger.error(f"Error in Supervisor loop: {e}", exc_info=True)
        return f"An error occurred during workflow orchestration: {e}"


def process_message(message: str, user_id: str, session_id: str) -> str:
    """Process incoming chat message from Telegram."""
    cmd = message.strip().lower().split()[0] if message.strip() else ""
    if cmd in ["/new", "/newchat", "/reset"]:
        redis_client.delete(f"state:{session_id}")
        return "🧹 *Previous session history cleared.* A new chat session has been initialized! Feel free to ask me anything. 🚀"
    return run_supervisor_loop(session_id, message, user_id)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """Standard HTTP Entrypoint."""
    user_id = payload.get("user_id") or context.user_id or "monitoring-system"
    session_id = payload.get("session_id") or context.session_id or "monitoring-session"

    # Handle webhook from Prometheus Alertmanager
    if "alerts" in payload:
        alert_details = []
        for alert in payload["alerts"]:
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            device = labels.get("device") or labels.get("instance") or "unknown"
            alert_name = labels.get("alertname") or "Network Alert"
            summary = annotations.get("summary") or annotations.get("description") or "No details"
            alert_details.append(f"Device: {device} | Alert: {alert_name} | Details: {summary}")
        
        alert_summary = "; ".join(alert_details)
        
        send_slack_message(SLACK_CHANNEL_ALERTS, f"🚨 *New Alert Received*\n{alert_summary}")
        
        # Initialize Redis State for Webhook
        state = {
            "session_id": session_id,
            "alert_source": "Prometheus",
            "symptoms": alert_summary,
            "affected_entities": [],
            "inventory_context": {},
            "diagnostic_logs": [f"AlertManager triggered: {alert_summary}"],
            "current_assignee": "supervisor-network-engineer-agent",
            "rca_summary": "",
            "jira_issue_key": "",
            "loop_count": 0,
            "messages": []
        }
        StateManager.save_state(session_id, state)
        
        response = run_supervisor_loop(session_id)
        return {
            "status": "success",
            "response": response,
            "timestamp": datetime.now().isoformat(),
        }

    # Handle callback from worker agents
    elif payload.get("action") == "callback":
        session_id_cb = payload.get("session_id")
        sender = payload.get("sender", "unknown")
        logger.info(f"Received callback from worker {sender} for session {session_id_cb}")
        
        # Resume the supervisor loop AND post result back to Slack thread / Jira comment
        def _callback_and_reply():
            result = run_supervisor_loop(session_id_cb)
            try:
                cb_state = StateManager.get_state(session_id_cb)
                if cb_state and cb_state.get("current_assignee") == "FINISH":
                    # 1. Post to Jira if associated
                    jira_key = cb_state.get("jira_issue_key")
                    if jira_key and result:
                        send_jira_comment(jira_key, result)
                    
                    # 2. Post to Slack thread
                    slack_channel = cb_state.get("slack_channel_id")
                    slack_thread = cb_state.get("slack_thread_ts")
                    if slack_channel and slack_thread and result:
                        slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
                        if slack_token:
                            import requests as req_cb
                            resp = req_cb.post(
                                "https://slack.com/api/chat.postMessage",
                                json={
                                    "channel": slack_channel,
                                    "thread_ts": slack_thread,
                                    "text": result
                                },
                                headers={
                                    "Authorization": f"Bearer {slack_token}",
                                    "Content-Type": "application/json; charset=utf-8"
                                },
                                timeout=10
                            )
                            if resp.status_code == 200 and resp.json().get("ok"):
                                logger.info(f"Posted callback result to Slack thread {slack_thread}")
                            else:
                                logger.warning(f"Failed to post callback to Slack: {resp.json().get('error', resp.text[:200])}")
            except Exception as e:
                logger.error(f"Failed to post callback result to destinations: {e}")
        
        threading.Thread(target=_callback_and_reply, daemon=True).start()
        return {
            "status": "success",
            "message": "Callback triggered",
            "timestamp": datetime.now().isoformat()
        }

    # Handle L3 Human rework request (from Slack "Request Changes" or Jira comment webhook)
    elif payload.get("action") == "l3_rework":
        session_id_rw = payload.get("session_id")
        l3_feedback = payload.get("l3_feedback", "L3 Human requested changes. Check Jira comments for details.")
        sender = payload.get("sender", "l3-human")
        logger.info(f"L3 REWORK request for session {session_id_rw} from {sender}")
        
        # Inject L3 feedback into session state and re-route to Senior Network Engineer
        state = StateManager.get_state(session_id_rw)
        if state:
            state["diagnostic_logs"].append(f"L3 HUMAN FEEDBACK: {l3_feedback}")
            state["diagnostic_logs"].append(f"REWORK REQUESTED BY L3 — Re-routing to Senior Network Engineer for adjustments.")
            state["current_assignee"] = "senior-network-engineer-agent"
            # Reset loop count to allow the agent to process the rework
            state["loop_count"] = max(0, state.get("loop_count", 0) - 1)
            StateManager.save_state(session_id_rw, state)
            
            # Re-trigger supervisor loop which will route to senior-network-engineer-agent
            threading.Thread(target=run_supervisor_loop, args=(session_id_rw,), daemon=True).start()
            return {
                "status": "success",
                "message": f"L3 rework triggered for session {session_id_rw}",
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "error",
                "message": f"Session {session_id_rw} not found in Redis"
            }

    # Handle standard chat messages
    else:
        message = payload.get("message", "Hello")
        response = process_message(message, user_id, session_id)
        return {
            "status": "success",
            "response": response,
            "timestamp": datetime.now().isoformat(),
        }


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


# --- Slack Bot Launch ---
slack_thread = threading.Thread(
    target=start_slack_bot,
    args=(process_message,),
    daemon=True,
)
slack_thread.start()
logger.info("Slack bot thread launched")



# --- Telegram Bot Launch ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if TELEGRAM_BOT_TOKEN:
    telegram_thread = threading.Thread(
        target=start_telegram_bot,
        args=(process_message, TELEGRAM_BOT_TOKEN),
        daemon=True,
    )
    telegram_thread.start()
    logger.info("Telegram bot thread launched")

if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
