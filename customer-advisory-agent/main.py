import os
import logging
import json
import threading
import requests
from datetime import datetime
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain.agents import create_agent
import redis

from greennode_agentbase import (
    GreenNodeAgentBaseApp,
    RequestContext,
    PingStatus,
)

from system_prompt import CUSTOMER_ADVISORY_PROMPT
from mcp_client import discover_mcp_tools
from context import thread_local
from agent_tools import (
    read_file,
    write_file,
    list_workspace_files,
    http_request,
)
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

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/sse")

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


# --- Discover MCP Tools (includes all Slack/Jira/notification tools via ACL) ---
logger.info(f"Discovering MCP tools from {MCP_SERVER_URL}...")
try:
    mcp_tools = discover_mcp_tools(MCP_SERVER_URL, agent_name="customer-advisory-agent", redis_client=redis_client)
    logger.info(f"Successfully registered {len(mcp_tools)} MCP tools")
except Exception as e:
    logger.error(f"Failed to discover MCP tools: {e}")
    mcp_tools = []

# --- Create Agent ---
# Local tools: workspace ops only
# MCP tools: all Slack, Jira, and notification tools (centralized)
tools = [
    read_file,
    write_file,
    list_workspace_files,
    http_request,
    *mcp_tools
]

# We will construct a GreenNode agent
agent = create_agent(
    llm,
    tools=tools,
    system_prompt=CUSTOMER_ADVISORY_PROMPT,
)


def run_advisory_work(session_id: str):
    """Run customer advisory agent logic."""
    thread_local.session_id = session_id
    state = StateManager.get_state(session_id)
    if not state:
        logger.error(f"Session state not found for {session_id}")
        return

    logger.info(f"Running customer advisory for session {session_id}")
    state["diagnostic_logs"].append(f"Customer Advisory Agent started at {datetime.now().isoformat()}")

    # Prepare inputs for the agent
    user_id = state.get('user_id', 'Unknown')
    calling_tenant = "noc-ops"
    if user_id:
        if "customer-a" in user_id.lower():
            calling_tenant = "customer-a"
        elif "customer-b" in user_id.lower():
            calling_tenant = "customer-b"
        elif "customer-001" in user_id.lower():
            calling_tenant = "customer-001"

    user_profile = state.get("user_profile", {})
    agent_input = f"""Session ID: {session_id}
Incident Symptoms: {state['symptoms']}
Reporting User: {user_id}
User Profile: {json.dumps(user_profile, ensure_ascii=False)}
Calling Tenant (slug): {calling_tenant}
JIRA Ticket: {state.get('jira_issue_key', 'None')}
RCA Summary so far: {state.get('rca_summary', '')}
Triage & Diagnostics logs:
{chr(10).join(state['diagnostic_logs'])}"""

    try:
        # Run agent
        result = agent.invoke(
            {"messages": [{"role": "user", "content": agent_input}]}
        )
        
        # Search backwards for the last non-empty AIMessage content
        agent_output = ""
        for msg in reversed(result["messages"]):
            if msg.type == "ai" and msg.content.strip():
                agent_output = msg.content
                break
        if not agent_output and result["messages"]:
            agent_output = result["messages"][-1].content
            
        logger.info(f"Customer Advisory Agent output: {agent_output}")
        
        # Reload state in case it changed via tools
        state = StateManager.get_state(session_id)
        state["diagnostic_logs"].append(f"Customer Advisory Agent completed: {agent_output}")
        
        # Update rca_summary to the final output text that will be shown to user
        state["rca_summary"] = agent_output
        state["current_assignee"] = "FINISH"
        
        # Save updated state
        StateManager.save_state(session_id, state)
        
    except Exception as e:
        logger.error(f"Customer Advisory Agent failed: {e}", exc_info=True)
        state = StateManager.get_state(session_id)
        state["diagnostic_logs"].append(f"Customer Advisory Agent failed with error: {e}")
        state["current_assignee"] = "FINISH"
        StateManager.save_state(session_id, state)

    # Call back the Supervisor
    supervisor_url = StateManager.get_agent_url("supervisor-network-engineer-agent")
    if supervisor_url:
        try:
            url = supervisor_url.rstrip("/") + "/invocations"
            logger.info(f"Triggering supervisor callback: {url}")
            response = requests.post(url, json={
                "action": "callback",
                "session_id": session_id,
                "sender": "customer-advisory-agent"
            }, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to callback supervisor: {e}")


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    session_id = payload.get("session_id")
    if not session_id:
        return {"status": "error", "message": "Missing session_id"}

    # Run asynchronously to allow instant HTTP response
    threading.Thread(target=run_advisory_work, args=(session_id,), daemon=True).start()

    return {
        "status": "success",
        "message": "Customer advisory triggered",
        "timestamp": datetime.now().isoformat()
    }


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


import html
import time

def send_telegram_raw(token: str, chat_id: str, text: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.error(f"Telegram API error: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
    return {}

def edit_telegram_raw(token: str, chat_id: str, message_id: int, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to edit Telegram message {message_id}: {e}")
    return False

def run_sla_monitor():
    logger.info("SLA Monitor loop started")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_SLA_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    sla_threshold = int(os.environ.get("SLA_THRESHOLD_SECONDS", "120"))

    if not bot_token or not chat_id:
        logger.error("SLA Monitor: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
        return

    logger.info(f"SLA Monitor configured with SLA: {sla_threshold}s, Chat ID: {chat_id}")

    while True:
        try:
            time.sleep(10)
            
            keys = redis_client.keys("state:*")
            for key in keys:
                state_data = redis_client.get(key)
                if not state_data:
                    continue
                try:
                    state = json.loads(state_data)
                except Exception as parse_ex:
                    logger.error(f"SLA Monitor: failed to parse state for key {key}: {parse_ex}")
                    continue

                session_id = state.get("session_id")
                if not session_id:
                    continue

                assignee = state.get("current_assignee")
                
                # Check if it was resolved
                if assignee == "FINISH":
                    if not state.get("sla_final_status"):
                        msg_id = state.get("sla_telegram_message_id")
                        elapsed = int(state.get("sla_elapsed_time", 0))
                        rca = state.get("rca_summary", "No summary available.")
                        if msg_id:
                            edit_text = (
                                f"✅ <b>[Incident Resolved within SLA]</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"▪️ <b>Session ID</b>: <code>{html.escape(session_id)}</code>\n"
                                f"▪️ <b>SLA Limit</b>: {sla_threshold}s\n"
                                f"▪️ <b>Resolved In</b>: {elapsed}s\n"
                                f"▪️ <b>RCA Summary</b>: {html.escape(rca[:500])}...\n"
                                f"━━━━━━━━━━━━━━━━━━━"
                            )
                            edit_telegram_raw(bot_token, chat_id, msg_id, edit_text)
                        else:
                            # Send direct resolution notification if msg_id wasn't created yet
                            res_text = (
                                f"✅ <b>[Incident Resolved within SLA]</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"▪️ <b>Session ID</b>: <code>{html.escape(session_id)}</code>\n"
                                f"▪️ <b>SLA Limit</b>: {sla_threshold}s\n"
                                f"▪️ <b>Resolved In</b>: {elapsed}s\n"
                                f"▪️ <b>RCA Summary</b>: {html.escape(rca[:500])}...\n"
                                f"━━━━━━━━━━━━━━━━━━━"
                            )
                            send_telegram_raw(bot_token, chat_id, res_text)
                        state["sla_final_status"] = "resolved"
                        redis_client.set(key, json.dumps(state))
                    continue

                if state.get("sla_final_status"):
                    continue

                # Get or initialize start_time
                start_time_str = state.get("start_time")
                if not start_time_str:
                    # Try to parse from the first log entry
                    logs = state.get("diagnostic_logs", [])
                    for log in logs:
                        if "started at" in log:
                            try:
                                parts = log.split("started at ")
                                if len(parts) > 1:
                                    datetime.fromisoformat(parts[1].strip())
                                    start_time_str = parts[1].strip()
                                    break
                            except Exception:
                                pass
                    if not start_time_str:
                        start_time_str = datetime.now().isoformat()
                    state["start_time"] = start_time_str
                    redis_client.set(key, json.dumps(state))

                # Calculate elapsed time
                try:
                    start_time = datetime.fromisoformat(start_time_str)
                    elapsed = int((datetime.now() - start_time).total_seconds())
                except Exception as time_ex:
                    logger.error(f"SLA Monitor: time calculation error for {session_id}: {time_ex}")
                    continue

                remaining = max(0, sla_threshold - elapsed)
                symptoms = state.get("symptoms", "No details available.")

                msg_id = state.get("sla_telegram_message_id")
                if not msg_id:
                    # First time seeing this session, post initial message
                    init_text = (
                        f"🚨 <b>[SLA Countdown Started]</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"▪️ <b>Session ID</b>: <code>{html.escape(session_id)}</code>\n"
                        f"▪️ <b>Symptoms</b>: {html.escape(symptoms[:200])}\n"
                        f"▪️ <b>SLA Limit</b>: {sla_threshold}s\n"
                        f"▪️ <b>Remaining</b>: <b>{remaining}s</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━"
                    )
                    resp = send_telegram_raw(bot_token, chat_id, init_text)
                    if resp and resp.get("ok"):
                        msg_id = resp["result"]["message_id"]
                        state["sla_telegram_message_id"] = msg_id
                        state["sla_elapsed_time"] = elapsed
                        redis_client.set(key, json.dumps(state))
                else:
                    # Update countdown message
                    if remaining > 0:
                        update_text = (
                            f"⏳ <b>[SLA Countdown]</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"▪️ <b>Session ID</b>: <code>{html.escape(session_id)}</code>\n"
                            f"▪️ <b>Symptoms</b>: {html.escape(symptoms[:200])}\n"
                            f"▪️ <b>SLA Limit</b>: {sla_threshold}s\n"
                            f"▪️ <b>Time Elapsed</b>: {elapsed}s\n"
                            f"▪️ <b>Remaining Time</b>: <b>{remaining}s</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━"
                        )
                        edit_telegram_raw(bot_token, chat_id, msg_id, update_text)
                        state["sla_elapsed_time"] = elapsed
                        redis_client.set(key, json.dumps(state))
                    else:
                        # SLA Breached! Escalate if not already done
                        if not state.get("sla_escalated"):
                            # Edit original message to show breach
                            breach_text = (
                                f"🔥 <b>[SLA BREACHED & ESCALATED]</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"▪️ <b>Session ID</b>: <code>{html.escape(session_id)}</code>\n"
                                f"▪️ <b>Symptoms</b>: {html.escape(symptoms[:200])}\n"
                                f"▪️ <b>SLA Limit</b>: {sla_threshold}s\n"
                                f"▪️ <b>Time Elapsed</b>: {elapsed}s (Breached)\n"
                                f"⚠️ <b>Status</b>: Escalated to L3 Engineer and Manager!\n"
                                f"━━━━━━━━━━━━━━━━━━━"
                            )
                            edit_telegram_raw(bot_token, chat_id, msg_id, breach_text)

                            # Send new escalation alert
                            alert_text = (
                                f"🚨 <b>[URGENT SLA ESCALATION]</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"⚠️ <b>Incident SLA Breached!</b>\n"
                                f"▪️ <b>Session ID</b>: <code>{html.escape(session_id)}</code>\n"
                                f"▪️ <b>SLA Limit</b>: {sla_threshold}s\n"
                                f"▪️ <b>Total Elapsed</b>: {elapsed}s\n"
                                f"▪️ <b>Symptoms</b>: {html.escape(symptoms)}\n\n"
                                f"📢 <b>Escalating to L3 Engineer & Manager for immediate manual review.</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━"
                            )
                            send_telegram_raw(bot_token, chat_id, alert_text)
                            
                            state["sla_escalated"] = True
                            state["sla_elapsed_time"] = elapsed
                            state["sla_final_status"] = "breached"
                            redis_client.set(key, json.dumps(state))

        except Exception as loop_ex:
            logger.error(f"SLA Monitor loop exception: {loop_ex}")

# Start SLA monitor thread
threading.Thread(target=run_sla_monitor, daemon=True).start()


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
