"""DC Network Engineer Agent — Main Entry Point.

Orchestrates:
- LLM + LangChain agent with memory & planning tools
- MCP device tools (auto-discovered from MCP server)
- HTTP entrypoint (GreenNode AgentBase runtime)
- Telegram bot (background thread)
"""

import os
import threading
import logging
from datetime import datetime


from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.tools import tool

from greennode_agentbase import (
    GreenNodeAgentBaseApp,
    RequestContext,
    PingStatus,
)
from greennode_agentbase.memory import MemoryClient
from greennode_agentbase.memory.models import MemoryRecordSearchRequest
from greennode_agent_bridge import AgentBaseMemoryEvents
from langgraph.config import get_config

from system_prompt import SYSTEM_PROMPT
from mcp_client import discover_mcp_tools
from agent_tools import read_file, write_file, list_workspace_files, http_request
from context_manager import ConversationCompactor, ConversationCompactorMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Detect Outbound Public IP ---
import urllib.request
try:
    with urllib.request.urlopen("https://icanhazip.com", timeout=5) as response:
        public_ip = response.read().decode("utf-8").strip()
        logger.info(f"AGENT_OUTBOUND_PUBLIC_IP: {public_ip}")
except Exception as e:
    logger.error(f"Failed to get outbound public IP: {e}")

app = GreenNodeAgentBaseApp()

# --- Memory Configuration ---
MEMORY_ID = os.environ.get("MEMORY_ID", "")
if not MEMORY_ID:
    raise ValueError("MEMORY_ID environment variable is required for memory-enabled agents")

MEMORY_STRATEGY_ID = os.environ.get("MEMORY_STRATEGY_ID", "default")

# CheckpointSaver: persists conversation state as events in AgentBase Memory
checkpointer = AgentBaseMemoryEvents(memory_id=MEMORY_ID)

# MemoryClient: used by long-term memory tools to store/search semantic facts
memory_client = MemoryClient()

# --- LLM Configuration ---
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
if not LLM_MODEL or not LLM_BASE_URL or not LLM_API_KEY:
    raise ValueError(
        "LLM_MODEL, LLM_BASE_URL, and LLM_API_KEY environment variables are required. "
        "Set them in your .env file or use /agentbase-llm to get a platform API key."
    )

llm = ChatOpenAI(
    model=LLM_MODEL,
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY,
)

# --- Conversation Compactor (intelligent context management) ---
# Instead of naively trimming messages (which loses context), we summarize
# older conversation history when approaching the model's context limit.
# Inspired by Claude Code's auto-compact and Gemini CLI's /compress.
compactor = ConversationCompactor(
    llm=llm,
    memory_client=memory_client,
    memory_id=MEMORY_ID,
)
compactor_middleware = ConversationCompactorMiddleware(compactor)

# --- MCP Server Configuration ---
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://49.213.77.221:8000/sse")


# --- Long-Term Memory Tools ---
def _get_actor_id() -> str:
    """Get actor_id from LangGraph configurable."""
    config = get_config()
    return config["configurable"].get("actor_id", "default")


def _build_namespace(actor_id: str) -> str:
    """Build memory namespace from strategy_id and actor_id."""
    return f"/strategies/{MEMORY_STRATEGY_ID}/actors/{actor_id}"


@tool
def remember(fact: str) -> str:
    """Store a fact in long-term memory for later retrieval.
    Use this to remember important information about the network, devices, incidents,
    configurations, maintenance windows, and operational decisions.

    Args:
        fact: The fact or information to remember. Be specific and include context.
    """
    namespace = _build_namespace(_get_actor_id())
    memory_client.insert_memory_records_directly(
        id=MEMORY_ID,
        namespace=namespace,
        request=[fact],
    )
    return f"Remembered: {fact}"


@tool
def recall(query: str) -> str:
    """Search long-term memory for facts relevant to a query.
    Use this to recall previously stored information about the network, past incidents,
    device configurations, or operational context.

    Args:
        query: Natural language search query about network operations.
    """
    namespace = _build_namespace(_get_actor_id())
    results = memory_client.search_memory_records(
        id=MEMORY_ID,
        namespace=namespace,
        request=MemoryRecordSearchRequest(query=query, limit=10),
    )
    if not results:
        return "No relevant memories found."
    return "\n".join(f"- {r.memory} (score: {r.score:.2f})" for r in results)


# --- Planning Tools (Goal Decomposition & Task Tracking) ---
@tool
def create_execution_plan(task_description: str, steps: str) -> str:
    """Create a structured execution plan for a complex network task.
    Use this when the user's request requires multiple sequential steps.

    Args:
        task_description: Brief description of the overall goal.
        steps: Numbered list of steps to execute (one per line).
    """
    plan_lines = [f"EXECUTION PLAN: {task_description}"]
    plan_lines.append("=" * 50)
    for i, step in enumerate(steps.strip().split("\n"), 1):
        step = step.strip().lstrip("0123456789.-) ")
        if step:
            plan_lines.append(f"  [ ] Step {i}: {step}")
    plan_lines.append("=" * 50)
    plan = "\n".join(plan_lines)
    # Store plan in long-term memory for tracking
    try:
        namespace = _build_namespace(_get_actor_id())
        memory_client.insert_memory_records_directly(
            id=MEMORY_ID,
            namespace=namespace,
            request=[f"ACTIVE_PLAN: {task_description} | Steps: {steps}"],
        )
    except Exception as e:
        logger.warning(f"Failed to store plan in memory: {e}")
    return plan


@tool
def update_plan_step(step_number: int, status: str, result_summary: str) -> str:
    """Mark a step in the current execution plan as completed or failed.

    Args:
        step_number: The step number to update (1-based).
        status: Either 'completed', 'failed', or 'skipped'.
        result_summary: Brief summary of the result or error.
    """
    emoji = {"completed": "Done", "failed": "FAILED", "skipped": "SKIPPED"}.get(status, "??")
    return f"[{emoji}] Step {step_number}: {status.upper()} — {result_summary}"


# --- Auto-discover MCP Device Tools ---
logger.info(f"Discovering MCP tools from {MCP_SERVER_URL}...")
mcp_tools = discover_mcp_tools(MCP_SERVER_URL)
logger.info(f"Successfully registered {len(mcp_tools)} MCP tools")


# --- Create Agent with Checkpointer + Conversation Compaction ---
agent = create_agent(
    llm,
    tools=[
        # Memory tools
        remember,
        recall,
        # Planning tools
        create_execution_plan,
        update_plan_step,
        # File & HTTP tools (Phase 3)
        read_file,
        write_file,
        list_workspace_files,
        http_request,
        # MCP Device tools (auto-discovered)
        *mcp_tools,
    ],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
    middleware=[compactor_middleware],
)


# --- Core message processing (shared by HTTP + Telegram) ---
def process_message(message: str, user_id: str, session_id: str) -> str:
    """Process a message through the agent and return the response text.

    Includes fallback error handling: if the LLM still returns a token
    overflow error (edge case), forces an aggressive compaction and retries.
    """
    config = {
        "configurable": {
            "thread_id": session_id,
            "actor_id": user_id,
        }
    }
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
        )
        return result["messages"][-1].content
    except Exception as e:
        error_msg = str(e)
        if "context length" in error_msg or "input_tokens" in error_msg:
            logger.warning(
                f"Token overflow despite compaction, forcing aggressive retry: {e}"
            )
            # Force compaction with a much lower threshold and retry
            compactor.compaction_threshold = compactor.max_context_tokens // 2
            try:
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": message}]},
                    config=config,
                )
                return result["messages"][-1].content
            except Exception as retry_err:
                logger.error(f"Retry also failed: {retry_err}")
                return (
                    "⚠️ Xin lỗi, cuộc hội thoại quá dài và không thể tiếp tục. "
                    "Vui lòng bắt đầu phiên mới để tiếp tục làm việc."
                )
            finally:
                # Restore original threshold
                compactor.compaction_threshold = compactor.max_context_tokens * 80 // 100
        raise


# --- HTTP Entrypoint (AgentBase Runtime) ---
@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """Main agent entrypoint with LangChain + Memory support."""
    if not context.user_id or not context.session_id:
        return {
            "status": "error",
            "error": "Missing required headers: X-GreenNode-AgentBase-User-Id and X-GreenNode-AgentBase-Session-Id are required when using memory.",
        }

    message = payload.get("message", "Hello")
    response = process_message(message, context.user_id, context.session_id)
    return {
        "status": "success",
        "response": response,
        "timestamp": datetime.now().isoformat(),
    }


@app.ping
def health_check() -> PingStatus:
    """Custom health check for GET /health endpoint."""
    return PingStatus.HEALTHY


# --- Telegram Bot (background thread) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

if TELEGRAM_BOT_TOKEN:
    from telegram_bot import start_telegram_bot

    telegram_thread = threading.Thread(
        target=start_telegram_bot,
        args=(process_message, TELEGRAM_BOT_TOKEN),
        daemon=True,
    )
    telegram_thread.start()
    logger.info("Telegram bot thread launched")


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
