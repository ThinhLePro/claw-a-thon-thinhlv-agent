#!/bin/bash
set -euo pipefail

# 1. Resolve paths dynamically
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR"
SKILLS_DIR="$( cd "$SCRIPT_DIR/../greennode-agentbase-skills" && pwd )"

CR_SCRIPT="$SKILLS_DIR/.claude/skills/agentbase/scripts/cr.sh"
RUNTIME_SCRIPT="$SKILLS_DIR/.claude/skills/agentbase/scripts/runtime.sh"
STATE_DIR="$PROJECT_DIR/.agentbase"
LAST_COMMIT_FILE="$STATE_DIR/last_deployed_commit"

# Ensure the state directory exists
mkdir -p "$STATE_DIR"

# Parse arguments
DESCRIPTION_ARG=""
FORCE_EDIT=false
PREV_COMMIT_ARG=""

while [[ $# -gt 0 ]]; do
  case $1 in
    -m|--message|--description)
      DESCRIPTION_ARG="$2"
      shift 2
      ;;
    -e|--edit)
      FORCE_EDIT=true
      shift
      ;;
    --since|--prev-commit)
      PREV_COMMIT_ARG="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [-m \"custom description\"] [-e|--edit] [--since commit]"
      exit 1
      ;;
  esac
done


# 2. Load GreenNode IAM credentials
if [ -z "${GREENNODE_CLIENT_ID:-}" ] || [ -z "${GREENNODE_CLIENT_SECRET:-}" ]; then
    GREENNODE_JSON="$PROJECT_DIR/.greennode.json"
    if [ -f "$GREENNODE_JSON" ]; then
        echo "Loading credentials from $GREENNODE_JSON..."
        GREENNODE_CLIENT_ID=$(jq -r '.client_id' "$GREENNODE_JSON")
        GREENNODE_CLIENT_SECRET=$(jq -r '.client_secret' "$GREENNODE_JSON")
        export GREENNODE_CLIENT_ID
        export GREENNODE_CLIENT_SECRET
    else
        echo "Error: GREENNODE_CLIENT_ID and GREENNODE_CLIENT_SECRET are not set, and $GREENNODE_JSON is missing."
        exit 1
    fi
fi

# 3. Registry & Runtime config
RUNTIME_NAME="dc-network-engineer"
RUNTIME_ID="runtime-62933765-2575-490c-9007-619079849e39"
FLAVOR="runtime-s2-general-4x8"

echo "Fetching Container Registry repository information..."
REPO_INFO=$(bash "$CR_SCRIPT" repo get)
REGISTRY_URL=$(echo "$REPO_INFO" | jq -r '.registryUrl')
REPO_NAME=$(echo "$REPO_INFO" | jq -r '.name')

if [ -z "$REGISTRY_URL" ] || [ -z "$REPO_NAME" ]; then
    echo "Error: Failed to fetch Container Registry repository information."
    exit 1
fi

echo "Registry URL: $REGISTRY_URL"
echo "Repository Name: $REPO_NAME"

# 4. Generate changelog description
cd "$PROJECT_DIR"

CHANGELOG_FILE=$(mktemp)
trap 'rm -f "$CHANGELOG_FILE"' EXIT

# Write header
if [ -n "$DESCRIPTION_ARG" ]; then
    echo "$DESCRIPTION_ARG" > "$CHANGELOG_FILE"
    echo "" >> "$CHANGELOG_FILE"
    echo "--- Code Changes ---" >> "$CHANGELOG_FILE"
else
    echo "Deploying update for $RUNTIME_NAME on GreenNode Cloud." > "$CHANGELOG_FILE"
    echo "" >> "$CHANGELOG_FILE"
fi

# Determine last deployed commit
PREV_COMMIT=""
if [ -n "$PREV_COMMIT_ARG" ]; then
    PREV_COMMIT="$PREV_COMMIT_ARG"
elif [ -f "$LAST_COMMIT_FILE" ]; then
    PREV_COMMIT=$(cat "$LAST_COMMIT_FILE")
fi

if [ -n "$PREV_COMMIT" ]; then
    # Verify commit exists in git history
    if ! git cat-file -e "$PREV_COMMIT" 2>/dev/null; then
        echo "Warning: Last deployed commit $PREV_COMMIT is not found in git history. Treating as first deployment."
        PREV_COMMIT=""
    fi
fi

if [ -n "$PREV_COMMIT" ]; then
    CURRENT_COMMIT=$(git rev-parse HEAD)
    if [ "$PREV_COMMIT" = "$CURRENT_COMMIT" ]; then
        echo "Warning: HEAD commit ($CURRENT_COMMIT) is the same as the last deployed commit."
        echo "No new git commits detected."
        echo "No changes since last deploy (re-deploying commit: ${CURRENT_COMMIT:0:7})." >> "$CHANGELOG_FILE"
        echo "" >> "$CHANGELOG_FILE"
    else
        echo "Calculating changes since last deployed commit ${PREV_COMMIT:0:7}..."
        echo "=== Commits ===" >> "$CHANGELOG_FILE"
        git log "${PREV_COMMIT}..HEAD" --oneline --no-merges >> "$CHANGELOG_FILE" || true
        echo "" >> "$CHANGELOG_FILE"
        echo "=== Files Modified ===" >> "$CHANGELOG_FILE"
        git diff "${PREV_COMMIT}..HEAD" --name-status >> "$CHANGELOG_FILE" || true
        echo "" >> "$CHANGELOG_FILE"
    fi
else
    echo "No previous deploy record found. Generating changelog from last 5 commits..."
    echo "=== Recent Commits ===" >> "$CHANGELOG_FILE"
    git log -n 5 --oneline --no-merges >> "$CHANGELOG_FILE" || true
    echo "" >> "$CHANGELOG_FILE"
    echo "=== Active File Status ===" >> "$CHANGELOG_FILE"
    git status -s >> "$CHANGELOG_FILE" || true
    echo "" >> "$CHANGELOG_FILE"
fi

# 5. Interactive edit of the changelog description
echo "--------------------------------------------------------"
echo "Auto-Generated Change Description:"
echo "--------------------------------------------------------"
cat "$CHANGELOG_FILE"
echo "--------------------------------------------------------"

INTERACTIVE=false
if [ -t 0 ] && [ -t 1 ]; then
    INTERACTIVE=true
fi

PROMPT_EDIT=true
if [ -n "$DESCRIPTION_ARG" ]; then
    PROMPT_EDIT=false
fi
if [ "$FORCE_EDIT" = true ]; then
    PROMPT_EDIT=true
fi

if [ "$INTERACTIVE" = true ] && [ "$PROMPT_EDIT" = true ]; then
    read -p "Would you like to edit this description before deploying? [y/N]: " EDIT_REPLY
    if [[ "$EDIT_REPLY" =~ ^[Yy]$ ]]; then
        EDITOR_BIN=${EDITOR:-$(which nano 2>/dev/null || which vi 2>/dev/null || echo "vi")}
        $EDITOR_BIN "$CHANGELOG_FILE"
    fi
else
    echo "Using generated description (non-interactive or message provided)."
fi

# Keep description as a single line to avoid argument parsing issues in CLI scripts
DESCRIPTION=${DESCRIPTION_ARG:-"Deploying update for dc-network-engineer on GreenNode Cloud"}

# 6. Build the Docker Image
TAG="v$(date +%Y%m%d%H%M%S)"
IMAGE_URL="$REGISTRY_URL/$REPO_NAME/$RUNTIME_NAME:$TAG"

echo "Building Docker image: $IMAGE_URL..."
docker build --platform linux/amd64 -t "$IMAGE_URL" .

# 7. Docker Login & Push
echo "Logging in to VNG Cloud Container Registry..."
bash "$CR_SCRIPT" credentials docker-login

echo "Pushing image to registry..."
docker push "$IMAGE_URL"

# 8. Deploy to GreenNode
echo "Deploying update to GreenNode runtime $RUNTIME_ID..."
echo "Checking existing network mode..."
LATEST_VERSION_CONFIG=$(bash "$RUNTIME_SCRIPT" versions "$RUNTIME_ID" --size 1 | jq -r '.listData[0] // empty')

NETWORK_ARGS=()
if [ -n "$LATEST_VERSION_CONFIG" ] && [ "$LATEST_VERSION_CONFIG" != "null" ]; then
    MODE=$(echo "$LATEST_VERSION_CONFIG" | jq -r '.networkConfig.mode // "PUBLIC"')
    VPC_ID=$(echo "$LATEST_VERSION_CONFIG" | jq -r '.networkConfig.vpcId // empty')
    SUBNET_ID=$(echo "$LATEST_VERSION_CONFIG" | jq -r '.networkConfig.subnetId // empty')
    ROUTE_CIDRS=$(echo "$LATEST_VERSION_CONFIG" | jq -r '[.networkConfig.routeCidrs[]] | join(",") // empty')
    
    echo "Detected network mode from previous version: $MODE"
    if [ "$MODE" = "VPC" ] && [ -n "$VPC_ID" ] && [ -n "$SUBNET_ID" ]; then
        echo "Using VPC parameters: vpcId=$VPC_ID, subnetId=$SUBNET_ID, routeCidrs=$ROUTE_CIDRS"
        NETWORK_ARGS=("--network-mode" "VPC" "--vpc-id" "$VPC_ID" "--subnet-id" "$SUBNET_ID")
        if [ -n "$ROUTE_CIDRS" ]; then
            NETWORK_ARGS+=("--route-cidrs" "$ROUTE_CIDRS")
        fi
    else
        NETWORK_ARGS=("--network-mode" "PUBLIC")
    fi
else
    echo "No previous version configuration found. Defaulting network mode to PUBLIC."
    NETWORK_ARGS=("--network-mode" "PUBLIC")
fi

bash "$RUNTIME_SCRIPT" update "$RUNTIME_ID" \
  --image "$IMAGE_URL" \
  --flavor "$FLAVOR" \
  --env-file .env \
  --from-cr \
  --description "$DESCRIPTION" \
  "${NETWORK_ARGS[@]}"

# 9. Record success state
git rev-parse HEAD > "$LAST_COMMIT_FILE"

echo "--------------------------------------------------------"
echo "Deployment successful!"
echo "Runtime: $RUNTIME_NAME ($RUNTIME_ID)"
echo "Image Tag: $TAG"
echo "Image URL: $IMAGE_URL"
echo "Change Description recorded on cloud."
echo "--------------------------------------------------------"
