#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR"
SKILLS_DIR="$( cd "$SCRIPT_DIR/greennode-agentbase-skills" && pwd )"

CR_SCRIPT="$SKILLS_DIR/.claude/skills/agentbase/scripts/cr.sh"
RUNTIME_SCRIPT="$SKILLS_DIR/.claude/skills/agentbase/scripts/runtime.sh"

# Load GreenNode IAM credentials
if [ -z "${GREENNODE_CLIENT_ID:-}" ] || [ -z "${GREENNODE_CLIENT_SECRET:-}" ]; then
    GREENNODE_JSON="$PROJECT_DIR/.greennode.json"
    if [ -f "$GREENNODE_JSON" ]; then
        echo "Loading credentials from $GREENNODE_JSON..."
        GREENNODE_CLIENT_ID=$(jq -r '.client_id' "$GREENNODE_JSON")
        GREENNODE_CLIENT_SECRET=$(jq -r '.client_secret' "$GREENNODE_JSON")
        export GREENNODE_CLIENT_ID
        export GREENNODE_CLIENT_SECRET
    else
        echo "Error: GREENNODE_CLIENT_ID and GREENNODE_CLIENT_SECRET are not set."
        exit 1
    fi
fi

# Set Registry details
REPO_INFO=$(bash "$CR_SCRIPT" repo get)
REGISTRY_URL=$(echo "$REPO_INFO" | jq -r '.registryUrl')
REPO_NAME=$(echo "$REPO_INFO" | jq -r '.name')

if [ -z "$REGISTRY_URL" ] || [ -z "$REPO_NAME" ]; then
    echo "Error: Failed to fetch Container Registry repository information."
    exit 1
fi

echo "Registry URL: $REGISTRY_URL"
echo "Repository Name: $REPO_NAME"

TAG="v$(date +%Y%m%d%H%M%S)"
FLAVOR="runtime-s2-general-4x8"
AGENT_NAME="customer-advisory-agent"

# Docker Login
echo "Logging in to VNG Cloud Container Registry..."
bash "$CR_SCRIPT" credentials docker-login

IMAGE_URL="$REGISTRY_URL/$REPO_NAME/$AGENT_NAME:$TAG"

# Build Docker Image
echo "Building Docker image: $IMAGE_URL..."
docker build --platform linux/amd64 -t "$IMAGE_URL" "./$AGENT_NAME"

# Push Image
echo "Pushing image to registry..."
docker push "$IMAGE_URL"

# Deploy to GreenNode
echo "Checking if runtime with name '$AGENT_NAME' already exists..."
EXISTING_ID=$(bash "$RUNTIME_SCRIPT" list | jq -r --arg name "$AGENT_NAME" '.listData[] | select(.name == $name) | .id' || true)

if [ -n "$EXISTING_ID" ] && [ "$EXISTING_ID" != "null" ]; then
    echo "Found existing runtime: $EXISTING_ID"
    RUNTIME_ID="$EXISTING_ID"
    echo "Updating runtime $RUNTIME_ID..."
    bash "$RUNTIME_SCRIPT" update "$RUNTIME_ID" \
      --image "$IMAGE_URL" \
      --flavor "$FLAVOR" \
      --env-file "./$AGENT_NAME/.env" \
      --from-cr \
      --description "Deploy update for $AGENT_NAME"
else
    echo "Creating new runtime: $AGENT_NAME..."
    CREATE_RESP=$(bash "$RUNTIME_SCRIPT" create \
      --name "$AGENT_NAME" \
      --image "$IMAGE_URL" \
      --flavor "$FLAVOR" \
      --env-file "./$AGENT_NAME/.env" \
      --from-cr \
      --description "Create agent $AGENT_NAME")
    RUNTIME_ID=$(echo "$CREATE_RESP" | jq -r '.id')
    echo "Created runtime with ID: $RUNTIME_ID"
fi

# Wait for dynamic endpoint URL to be generated and active
ENDPOINT_URL=""
echo "Querying public endpoint URL for $AGENT_NAME..."
for i in {1..20}; do
    ENDPOINT_INFO=$(bash "$RUNTIME_SCRIPT" endpoints list "$RUNTIME_ID")
    ENDPOINT_URL=$(echo "$ENDPOINT_INFO" | jq -r '.listData[0].url // empty')
    if [ -n "$ENDPOINT_URL" ] && [ "$ENDPOINT_URL" != "null" ]; then
        break
    fi
    echo "Waiting 5s for endpoint URL..."
    sleep 5
done

if [ -n "$ENDPOINT_URL" ] && [ "$ENDPOINT_URL" != "null" ]; then
    echo "Successfully resolved endpoint for $AGENT_NAME: $ENDPOINT_URL"
    
    # Register in Redis using VM LAN IP
    echo "Registering endpoint in Redis..."
    redis-cli -h "127.0.0.1" SET "agent:url:$AGENT_NAME" "$ENDPOINT_URL"
else
    echo "Warning: Failed to resolve endpoint URL for $AGENT_NAME."
fi

echo "Deploy customer completed."
