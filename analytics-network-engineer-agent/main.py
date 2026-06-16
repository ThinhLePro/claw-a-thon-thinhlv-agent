import os
import logging
import json
import threading
import requests
from datetime import datetime
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, HumanMessage
import redis

from greennode_agentbase import (
    GreenNodeAgentBaseApp,
    RequestContext,
    PingStatus,
)

from system_prompt import ALERT_ANALYTICS_PROMPT
from mcp_client import discover_mcp_tools
from agent_tools import (
    check_flapping_history,
    read_file,
    write_file,
    list_workspace_files,
    http_request,
    slack_view_profile,
    slack_react_message,
    slack_view_status,
    slack_send_file,
    slack_read_file,
    read_url
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


# --- Discover MCP Tools ---
logger.info(f"Discovering MCP tools from {MCP_SERVER_URL}...")
try:
    mcp_tools = discover_mcp_tools(MCP_SERVER_URL, agent_name="analytics-network-engineer-agent", redis_client=redis_client)
    logger.info(f"Successfully registered {len(mcp_tools)} MCP tools")
except Exception as e:
    logger.error(f"Failed to discover MCP tools: {e}")
    mcp_tools = []

# --- Create Agent ---
tools = [
    check_flapping_history,
    read_file,
    write_file,
    list_workspace_files,
    http_request,
    slack_view_profile,
    slack_react_message,
    slack_view_status,
    slack_send_file,
    slack_read_file,
    read_url,
    *mcp_tools
]

# We will construct a GreenNode agent
agent = create_agent(
    llm,
    tools=tools,
    system_prompt=ALERT_ANALYTICS_PROMPT,
)


def run_analytics_work(session_id: str):
    """Run alert analytics agent logic."""
    state = StateManager.get_state(session_id)
    if not state:
        logger.error(f"Session state not found for {session_id}")
        return

    logger.info(f"Running alert analytics for session {session_id}")
    state["diagnostic_logs"].append(f"Analytics Agent started at {datetime.now().isoformat()}")

    # Prepare inputs for the agent
    user_id = state.get('user_id', 'Unknown')
    calling_tenant = "noc-ops"
    if user_id:
        if "customer-a" in user_id.lower():
            calling_tenant = "customer-a"
        elif "customer-b" in user_id.lower():
            calling_tenant = "customer-b"

    agent_input = f"""Incident Symptoms: {state['symptoms']}
Reporting User: {user_id}
Calling Tenant (slug): {calling_tenant}
JIRA Ticket: {state.get('jira_issue_key', 'None')}
Affected Entities: {state.get('affected_entities', [])}"""

    try:
        # Run agent
        result = agent.invoke(
            {"messages": [{"role": "user", "content": agent_input}]}
        )
        
        agent_output = result["messages"][-1].content
        logger.info(f"Analytics Agent output: {agent_output}")
        
        # Reload state in case it changed via tools
        state = StateManager.get_state(session_id)
        state["diagnostic_logs"].append(f"Analytics Agent finished: {agent_output}")
        
        # Save updated state
        StateManager.save_state(session_id, state)
        
    except Exception as e:
        logger.error(f"Analytics Agent failed: {e}", exc_info=True)
        state["diagnostic_logs"].append(f"Analytics Agent failed with error: {e}")
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
                "sender": "analytics-network-engineer-agent"
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
    threading.Thread(target=run_analytics_work, args=(session_id,), daemon=True).start()

    return {
        "status": "success",
        "message": "Analytics job triggered",
        "timestamp": datetime.now().isoformat()
    }


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
