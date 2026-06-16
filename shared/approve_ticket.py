#!/usr/bin/env python3
import os
import sys
import json
import hmac
import hashlib
import requests

def load_env_file():
    # Search for .env files in standard locations
    paths = ['.env', '../.env', '../../.env', 'customer-advisory-agent/.env', '../customer-advisory-agent/.env']
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and '=' in line and not line.startswith('#'):
                            k, v = line.split('=', 1)
                            os.environ.setdefault(k.strip(), v.strip())
            except Exception:
                pass

load_env_file()

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://greennode-network-agent-team.atlassian.net")
JIRA_USER_EMAIL = os.environ.get("JIRA_USER_EMAIL", "tool.acl.thinhlv@gmail.com")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_WEBHOOK_SECRET = os.environ.get("JIRA_WEBHOOK_SECRET", "Gng0D3c8U0BsYOSlxdIT")
MCP_WEBHOOK_URL = os.environ.get("MCP_WEBHOOK_URL", "http://localhost:8980/webhook/jira")

if not JIRA_API_TOKEN:
    print("WARNING: JIRA_API_TOKEN is not set. Please set it in your environment or .env file.")

def approve_ticket(issue_key):
    print(f"Fetching ticket {issue_key} from Jira...")
    auth = (JIRA_USER_EMAIL, JIRA_API_TOKEN)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    
    # Get issue details
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
    resp = requests.get(url, auth=auth, headers=headers)
    if resp.status_code != 200:
        print(f"Error fetching issue: {resp.status_code} - {resp.text}")
        return False
        
    issue_data = resp.json()
    description = issue_data.get("fields", {}).get("description", {})
    
    # Construct Mock Jira Webhook Payload
    webhook_payload = {
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "key": issue_key,
            "fields": {
                "status": {
                    "name": "Approved"
                },
                "description": description
            }
        }
    }
    
    payload_bytes = json.dumps(webhook_payload).encode("utf-8")
    
    # Calculate HMAC-SHA256 signature
    signature = hmac.new(
        JIRA_WEBHOOK_SECRET.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()
    
    webhook_headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature": f"sha256={signature}"
    }
    
    print(f"Sending mock approval webhook to MCP server for {issue_key}...")
    w_resp = requests.post(MCP_WEBHOOK_URL, data=payload_bytes, headers=webhook_headers)
    
    print(f"Response status: {w_resp.status_code}")
    print(f"Response body: {w_resp.text}")
    return w_resp.status_code == 200

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: ./approve_ticket.py <JIRA_ISSUE_KEY>")
        sys.exit(1)
        
    ticket_key = sys.argv[1].strip()
    approve_ticket(ticket_key)
