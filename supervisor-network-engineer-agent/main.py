import os
import logging
import threading
import json
import requests
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
from telegram_bot import start_telegram_bot

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


def parse_json_garbage(text: str) -> dict:
    """Extract and parse first JSON block in text."""
    # Find JSON bounds
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]
    return json.loads(text)


def run_supervisor_loop(session_id: str, user_message: str = None) -> str:
    """Load state, query router LLM, route to next worker, or conclude."""
    state = StateManager.get_state(session_id)
    
    if not state:
        state = {
            "session_id": session_id,
            "alert_source": "User report",
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
    
    if user_message:
        state["messages"].append({"role": "user", "content": user_message})
        state["loop_count"] = 0

    # Increment loop count
    state["loop_count"] += 1
    
    # 1. Enforce Fallback Limit
    if state["loop_count"] > 5:
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
                return "⚠️ Quá thời gian tự động xử lý. Đã tự động chuyển ticket cho kỹ sư L3 và thông báo khách hàng."
            except Exception as ex:
                logger.error(f"Failed to call customer advisory: {ex}")
        return "⚠️ Lỗi kết nối khi gửi yêu cầu hỗ trợ khẩn cấp. Vui lòng liên hệ trực tiếp NOC."

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
        
        next_agent = res_json.get("next_action", "FINISH").strip()
        incident_class = res_json.get("incident_class", "Service").strip()
        reasoning = res_json.get("reasoning", "").strip()
        intent = res_json.get("intent", "INCIDENT_RESPONSE").strip()
        
        logger.info(f"Supervisor Route Decision: {next_agent} | Intent: {intent} | Incident Class: {incident_class} | Reason: {reasoning}")
        state["diagnostic_logs"].append(f"Supervisor decision: Route to {next_agent} (Intent: {intent}). Reason: {reasoning}")
        state["current_assignee"] = next_agent
        
        StateManager.save_state(session_id, state)
        
        if next_agent == "FINISH":
            # Return direct response from JSON if available, fallback to rca_summary or default
            direct_response = res_json.get("response", "").strip()
            if direct_response:
                return direct_response
            return state["rca_summary"] or "Quy trình chẩn đoán hoàn tất."
            
        # Trigger the worker agent dynamically
        worker_url = StateManager.get_agent_url(next_agent)
        if not worker_url:
            logger.error(f"Endpoint for agent {next_agent} not found in Redis.")
            return f"Lỗi hệ thống: Không tìm thấy địa chỉ dịch vụ của {next_agent}."
            
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
        
        # Return status update to user
        status_map = {
            "analytics-network-engineer-agent": "🔍 Hệ thống đang bắt đầu sàng lọc cảnh báo và phân tích sự cố (Triage/Analytics)...",
            "expert-engineer-agent": "⚙️ Đang chuyển tiếp thông tin lỗi đến Kỹ sư Mạng chuyên gia để chạy chẩn đoán sâu...",
            "customer-advisory-agent": "📝 Đang lập báo cáo dịch vụ và soạn thảo hướng dẫn tự xử lý cho khách hàng..."
        }
        return status_map.get(next_agent, f"Đang chuyển tiếp xử lý đến {next_agent}...")
        
    except Exception as e:
        logger.error(f"Error in Supervisor loop: {e}", exc_info=True)
        return f"Có lỗi xảy ra trong quá trình điều phối xử lý: {e}"


def process_message(message: str, user_id: str, session_id: str) -> str:
    """Process incoming chat message from Telegram."""
    cmd = message.strip().lower().split()[0] if message.strip() else ""
    if cmd in ["/new", "/newchat", "/reset"]:
        redis_client.delete(f"state:{session_id}")
        return "🧹 *Đã xóa lịch sử phiên chat cũ.* Phiên chat mới của bạn đã được khởi tạo! Hãy hỏi tôi bất kỳ câu hỏi nào. 🚀"
    return run_supervisor_loop(session_id, message)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """Standard HTTP Entrypoint."""
    user_id = context.user_id or "monitoring-system"
    session_id = context.session_id or "monitoring-session"

    # Handle webhook from Prometheus Alertmanager
    if "alerts" in payload:
        alert_details = []
        for alert in payload["alerts"]:
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            device = labels.get("device") or labels.get("instance") or "unknown"
            alert_name = labels.get("alertname") or "Network Alert"
            summary = annotations.get("summary") or annotations.get("description") or "No details"
            alert_details.append(f"Thiết bị: {device} | Cảnh báo: {alert_name} | Chi tiết: {summary}")
        
        alert_summary = "; ".join(alert_details)
        
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
        
        # Resume the supervisor loop
        run_supervisor_loop(session_id_cb)
        return {
            "status": "success",
            "message": "Callback processed",
            "timestamp": datetime.now().isoformat()
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
