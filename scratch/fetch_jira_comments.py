import requests
import json
import os

url = "https://greennode-network-agent-team.atlassian.net/rest/api/3/issue/KAN-13/comment"
resp = requests.get(
    url,
    auth=(os.environ.get("JIRA_USER_EMAIL", ""), os.environ.get("JIRA_API_TOKEN", "")),
    headers={"Accept": "application/json"}
)

if resp.status_code == 200:
    comments = resp.json().get("comments", [])
    print(f"Total Comments on KAN-13: {len(comments)}")
    print("=" * 60)
    for idx, c in enumerate(comments, 1):
        print(f"[{idx}] Comment ID: {c['id']} | Author: {c['author']['displayName']}")
        body_text = ""
        body_doc = c.get("body", {})
        if isinstance(body_doc, dict):
            for block in body_doc.get("content", []):
                for node in block.get("content", []):
                    if node.get("type") == "text":
                        body_text += node.get("text", "")
                    elif node.get("type") == "hardBreak":
                        body_text += "\n"
                body_text += "\n"
        else:
            body_text = str(body_doc)
        print(body_text.strip())
        print("-" * 60)
else:
    print(f"Error: HTTP {resp.status_code} - {resp.text}")
