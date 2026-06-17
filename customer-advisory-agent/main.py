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


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
