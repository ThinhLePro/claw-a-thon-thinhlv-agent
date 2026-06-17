import time
import json
import redis
import requests

# Redis Config (local host connects via 127.0.0.1)
redis_client = redis.Redis(
    host="127.0.0.1",
    port=6379,
    decode_responses=True
)

session_id = "test-loop-session-123"
supervisor_url = redis_client.get("agent:url:supervisor-network-engineer-agent")

print(f"Supervisor Endpoint URL: {supervisor_url}")

# 1. Initialize dummy state with loop_count > 5 and current_assignee = "FINISH"
test_state = {
    "session_id": session_id,
    "user_id": "test-user",
    "alert_source": "Test",
    "symptoms": "Simulated symptoms",
    "affected_entities": [],
    "inventory_context": {},
    "diagnostic_logs": ["Pre-existing diagnostic logs"],
    "current_assignee": "FINISH",
    "rca_summary": "Simulated Diagnostic Completed Successfully.",
    "jira_issue_key": "",
    "loop_count": 6,
    "messages": []
}

redis_client.set(f"state:{session_id}", json.dumps(test_state))
print("Seeded test state in Redis.")

# 2. Call the supervisor callback API
callback_payload = {
    "action": "callback",
    "session_id": session_id,
    "sender": "customer-advisory-agent"
}

url = supervisor_url.rstrip("/") + "/invocations"
print(f"Sending callback to {url}...")
try:
    resp = requests.post(url, json=callback_payload, timeout=10)
    print("Callback response:", resp.status_code, resp.text)
except Exception as e:
    print("Callback failed:", e)

# 3. Wait for 5 seconds to ensure any async worker threads in Supervisor finish execution
print("Waiting 5 seconds for background execution...")
time.sleep(5)

# 4. Fetch the state from Redis again and verify
final_state_data = redis_client.get(f"state:{session_id}")
if final_state_data:
    final_state = json.loads(final_state_data)
    print("Final State in Redis:")
    print(json.dumps(final_state, indent=2))
    
    # Assert conditions
    if final_state.get("current_assignee") == "FINISH":
        print("Success! current_assignee remained 'FINISH'.")
    else:
        print(f"FAILED: current_assignee changed to '{final_state.get('current_assignee')}'")
        
    if final_state.get("loop_count") == 6:
        print("Success! loop_count did not increment (remained 6).")
    else:
        print(f"FAILED: loop_count changed to {final_state.get('loop_count')}")
else:
    print("FAILED: State was deleted or not found.")

# Clean up
redis_client.delete(f"state:{session_id}")
print("Cleaned up test state.")
