import time
import json
import redis
import requests

# Redis Config
redis_client = redis.Redis(
    host="127.0.0.1",
    port=6379,
    decode_responses=True
)

session_id = "test-ack-session-999"
supervisor_url = redis_client.get("agent:url:supervisor-network-engineer-agent")

print(f"Supervisor Endpoint URL: {supervisor_url}")

# 1. Initialize state representing an already escalated incident (loop_count > 5, log shows escalation)
test_state = {
    "session_id": session_id,
    "user_id": "slack-U12345",
    "user_profile": {
        "real_name": "Thinh Le",
        "title": "Lead Network Engineer",
        "pronouns": "he/him"
    },
    "alert_source": "Test",
    "symptoms": "Hardware failure",
    "affected_entities": [],
    "inventory_context": {},
    "diagnostic_logs": [
        "Pre-existing diagnostic logs",
        "Supervisor: Max loop count exceeded. Escalating to Level 3."
    ],
    "current_assignee": "FINISH",
    "rca_summary": "Simulated Escalated Summary.",
    "jira_issue_key": "",
    "loop_count": 6,
    "messages": []
}

redis_client.set(f"state:{session_id}", json.dumps(test_state))
print("Seeded test state in Redis.")

# 2. Call the supervisor with a simple acknowledgment message "OK"
payload = {
    "message": "OK",
    "user_id": "slack-U12345",
    "session_id": session_id
}

url = supervisor_url.rstrip("/") + "/invocations"
print(f"Sending message 'OK' to {url}...")
try:
    resp = requests.post(url, json=payload, timeout=20)
    print("Response status code:", resp.status_code)
    resp_data = resp.json()
    print("Response JSON:")
    print(json.dumps(resp_data, indent=2, ensure_ascii=False))
except Exception as e:
    print("Failed to call endpoint:", e)

# 3. Clean up
redis_client.delete(f"state:{session_id}")
print("Cleaned up test state.")
