import os
import json
import subprocess
import requests

# 1. Get Token
token_process = subprocess.run(
    ["bash", "greennode-agentbase-skills/.claude/skills/agentbase/scripts/get_token.sh"],
    capture_output=True,
    text=True,
    check=True
)
token = token_process.stdout.strip()

# 2. Get Registry Credentials
cred_resp = requests.get(
    "https://agentbase.api.vngcloud.vn/cr/api/v1/registry-credential",
    headers={"Authorization": f"Bearer {token}"}
)
print("Registry credentials response code:", cred_resp.status_code)
cred_data = cred_resp.json()
username = cred_data.get("username")
secret = cred_data.get("secret")

# 3. Read env file
env_vars = {}
with open("./supervisor-network-engineer-agent/.env", "r") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            env_vars[key.strip()] = val.strip()

# 4. Construct body
body = {
    "imageUrl": "vcr.vngcloud.vn/111480-abp111817/supervisor-network-engineer-agent:v20260617044706",
    "flavorId": "runtime-s2-general-4x8",
    "description": "Deploy update for supervisor-network-engineer-agent",
    "command": [],
    "args": [],
    "environmentVariables": env_vars,
    "autoscaling": {
        "minReplicas": 1,
        "maxReplicas": 1,
        "cpuUtilization": 50,
        "memoryUtilization": 50
    },
    "imageAuth": {
        "enabled": True,
        "username": username,
        "password": secret
    }
}

# 5. Send PATCH
url = "https://agentbase.api.vngcloud.vn/runtime/agent-runtimes/runtime-422395a0-9631-49d2-80e3-0ca48f79e472"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

print("Sending PATCH request...")
print("Body:", json.dumps(body, indent=2))
resp = requests.patch(url, headers=headers, json=body)
print("Response Status Code:", resp.status_code)
print("Response Headers:", resp.headers)
try:
    print("Response JSON:", json.dumps(resp.json(), indent=2))
except Exception:
    print("Response Text:", resp.text)
