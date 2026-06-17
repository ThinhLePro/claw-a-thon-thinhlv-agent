#!/bin/bash
# =============================================================================
# 🚨 NOC Traffic Anomaly Detector — Auto-trigger AI Agent
# =============================================================================
# Monitor interface ge-0/0/47 trên LAB-INTERNET-GATEWAY-01
# Khi phát hiện Input rate bất thường (> threshold) → tự động gửi alert
# đến Supervisor Agent qua Slack #noc-l3-alerts
#
# Usage:
#   ./detect_ddos.sh              # Chạy monitor (default threshold 100Mbps)
#   ./detect_ddos.sh --threshold 50   # Custom threshold (Mbps)
#   ./detect_ddos.sh --dry-run        # Chỉ monitor, không trigger agent
# =============================================================================

# ─── Configuration ───────────────────────────────────────────────────────────
DEVICE_IP="10.116.0.54"
DEVICE_PORT="22"
DEVICE_USER="network-agent"
DEVICE_PASS="${DEVICE_PASS:-}"
DEVICE_NAME="LAB-INTERNET-GATEWAY-01"
INTERFACE="ge-0/0/47"
TARGET_CUSTOMER_IP="14.238.122.111"

# Monitoring
POLL_INTERVAL=5          # Giây giữa mỗi lần poll
THRESHOLD_MBPS=100       # Ngưỡng cảnh báo (Mbps)
ALERT_COOLDOWN=300       # Cooldown giữa các lần alert (giây) - tránh spam

# Slack
SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN:-}"
SLACK_CHANNEL_ALERTS="C0BAPPKR8RZ"  # #noc-l3-alerts

# Supervisor Agent (lấy từ Redis hoặc hardcode)
REDIS_HOST="10.116.0.181"
REDIS_PORT="6379"

# State
DRY_RUN=false
LAST_ALERT_TIME=0
ALERT_SENT=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color
BOLD='\033[1m'
BLINK='\033[5m'

# ─── Parse arguments ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --threshold)
            THRESHOLD_MBPS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --interval)
            POLL_INTERVAL="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--threshold MBPS] [--interval SECONDS] [--dry-run]"
            exit 1
            ;;
    esac
done

THRESHOLD_BPS=$((THRESHOLD_MBPS * 1000000))

# ─── Functions ───────────────────────────────────────────────────────────────

get_interface_stats() {
    # SSH to Juniper và lấy interface stats
    local output
    output=$(sshpass -p "$DEVICE_PASS" ssh -o StrictHostKeyChecking=no \
        -o ConnectTimeout=10 -o LogLevel=ERROR \
        -p "$DEVICE_PORT" "${DEVICE_USER}@${DEVICE_IP}" \
        "show interfaces ${INTERFACE} | match \"rate|packets|errors|drops\"" 2>/dev/null)

    if [ $? -ne 0 ]; then
        echo "ERROR"
        return 1
    fi
    echo "$output"
}

parse_input_rate_bps() {
    local stats="$1"
    # Parse "Input rate: 965432000 bps (xxx pps)" hoặc tương tự
    local rate
    rate=$(echo "$stats" | grep -i "input rate" | head -1 | grep -oP '\d+' | head -1)
    echo "${rate:-0}"
}

parse_output_rate_bps() {
    local stats="$1"
    local rate
    rate=$(echo "$stats" | grep -i "output rate" | head -1 | grep -oP '\d+' | head -1)
    echo "${rate:-0}"
}

format_rate() {
    local bps=$1
    if [ "$bps" -ge 1000000000 ]; then
        echo "$(echo "scale=2; $bps/1000000000" | bc) Gbps"
    elif [ "$bps" -ge 1000000 ]; then
        echo "$(echo "scale=2; $bps/1000000" | bc) Mbps"
    elif [ "$bps" -ge 1000 ]; then
        echo "$(echo "scale=2; $bps/1000" | bc) Kbps"
    else
        echo "${bps} bps"
    fi
}

send_slack_alert() {
    local input_rate_fmt="$1"
    local output_rate_fmt="$2"
    local input_bps="$3"

    local message="🚨 *[P1 CRITICAL] DDoS Traffic Anomaly — International Link Saturated*

⚠️ *BLAST RADIUS: DATACENTER-WIDE* — Toàn bộ kết nối quốc tế bị nghẽn!

*Device:* \`${DEVICE_NAME}\` (${DEVICE_IP})
*Interface:* \`${INTERFACE}\` — *Link quốc tế duy nhất, capacity 1 Gbps*
*Target IP:* \`${TARGET_CUSTOMER_IP}\` (customer-001 Proxy Server)
*Input Rate:* 🔴 \`${input_rate_fmt}\` / 1 Gbps (**${input_bps}00** saturation)
*Output Rate:* \`${output_rate_fmt}\`

📊 *Analysis:*
• Traffic flood >950 Mbps trên link 1 Gbps → gần bão hòa hoàn toàn
• Input cực cao + Output = 0 → DDoS flood pattern
• Link quốc tế nghẽn → **TẤT CẢ khách hàng datacenter mất kết nối quốc tế**
• Phải chặn traffic bất thường NGAY LẬP TỨC để bảo vệ hạ tầng chung

🎯 *Required Action:* Block abnormal traffic to ${TARGET_CUSTOMER_IP} immediately. This is a mandatory action — no alternative available.

_Auto-detected by NOC Traffic Anomaly Detector at $(date '+%Y-%m-%d %H:%M:%S')_
@channel"

    curl -s -X POST "https://slack.com/api/chat.postMessage" \
        -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$(jq -n \
            --arg channel "$SLACK_CHANNEL_ALERTS" \
            --arg text "$message" \
            '{channel: $channel, text: $text, mrkdwn: true}')" \
        >/dev/null 2>&1

    return $?
}

trigger_supervisor_agent() {
    local input_rate_fmt="$1"

    # Lấy Supervisor URL từ Redis
    local supervisor_url
    supervisor_url=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" GET "agent:url:supervisor-network-engineer-agent" 2>/dev/null)

    # Strip quotes
    supervisor_url=$(echo "$supervisor_url" | tr -d '"')

    if [ -z "$supervisor_url" ] || [ "$supervisor_url" = "(nil)" ]; then
        echo -e "${YELLOW}  ⚠ Supervisor URL not found in Redis, skipping direct trigger${NC}"
        return 1
    fi

    local invocation_url="${supervisor_url%/}/invocations"
    local session_id="DDOS-ALERT-$(date +%s)"

    local message="[P1 CRITICAL - AUTO-DETECTED] DDoS traffic anomaly on ${DEVICE_NAME} interface ${INTERFACE} (international uplink, 1Gbps capacity). Input rate: ${input_rate_fmt} — link nearly saturated. Output rate: near 0 bps. Target: ${TARGET_CUSTOMER_IP} (customer-001 proxy). BLAST RADIUS: DATACENTER-WIDE — all customers lose international connectivity. This is asymmetric flood traffic, classic DDoS pattern. MANDATORY ACTION: Block abnormal inbound traffic to ${TARGET_CUSTOMER_IP} immediately to protect shared infrastructure. No alternative available — entire datacenter international link is congested."

    curl -s -X POST "$invocation_url" \
        -H "Content-Type: application/json" \
        -d "$(jq -n \
            --arg message "$message" \
            --arg session_id "$session_id" \
            --arg user_id "noc-traffic-monitor" \
            '{message: $message, session_id: $session_id, user_id: $user_id}')" \
        >/dev/null 2>&1

    return $?
}

print_header() {
    clear
    echo -e "${GREEN}"
    echo "  ╔══════════════════════════════════════════════════════════════════╗"
    echo "  ║          🛡️  NOC Traffic Anomaly Detector v1.0                  ║"
    echo "  ║          GreenNode NOC — Real-time DDoS Monitor                ║"
    echo "  ╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo -e "  ${CYAN}Device:${NC}     ${DEVICE_NAME} (${DEVICE_IP})"
    echo -e "  ${CYAN}Interface:${NC}  ${INTERFACE} → ${TARGET_CUSTOMER_IP}"
    echo -e "  ${CYAN}Threshold:${NC}  ${THRESHOLD_MBPS} Mbps"
    echo -e "  ${CYAN}Interval:${NC}   ${POLL_INTERVAL}s"
    echo -e "  ${CYAN}Mode:${NC}       $([ "$DRY_RUN" = true ] && echo "${YELLOW}DRY RUN (no alerts)${NC}" || echo "${GREEN}LIVE (auto-alert)${NC}")"
    echo ""
    echo -e "  ${GRAY}Press Ctrl+C to stop${NC}"
    echo -e "  ${GRAY}────────────────────────────────────────────────────────────────${NC}"
    echo ""
}

print_status_line() {
    local timestamp="$1"
    local input_bps="$2"
    local output_bps="$3"
    local input_fmt="$4"
    local output_fmt="$5"
    local is_anomaly="$6"

    if [ "$is_anomaly" = true ]; then
        echo -e "  ${RED}${BLINK}⚠${NC} ${WHITE}${timestamp}${NC}  │  IN: ${RED}${BOLD}${input_fmt}${NC}  │  OUT: ${YELLOW}${output_fmt}${NC}  │  ${RED}${BOLD}🔴 ANOMALY DETECTED${NC}"
    else
        echo -e "  ${GREEN}✓${NC} ${GRAY}${timestamp}${NC}  │  IN: ${GREEN}${input_fmt}${NC}  │  OUT: ${GREEN}${output_fmt}${NC}  │  ${GREEN}🟢 Normal${NC}"
    fi
}

# ─── Main Loop ───────────────────────────────────────────────────────────────

# Check dependencies
for cmd in sshpass jq curl bc; do
    if ! command -v $cmd &>/dev/null; then
        echo "❌ Missing dependency: $cmd. Install with: sudo apt-get install $cmd"
        exit 1
    fi
done

print_header

echo -e "  ${CYAN}Connecting to ${DEVICE_NAME}...${NC}"
echo ""

poll_count=0
anomaly_count=0

trap 'echo -e "\n\n  ${YELLOW}Monitor stopped. Total polls: ${poll_count}, Anomalies: ${anomaly_count}${NC}\n"; exit 0' INT

while true; do
    timestamp=$(date '+%H:%M:%S')
    poll_count=$((poll_count + 1))

    # Get interface stats
    stats=$(get_interface_stats)

    if [ "$stats" = "ERROR" ]; then
        echo -e "  ${RED}✗${NC} ${GRAY}${timestamp}${NC}  │  ${RED}Connection failed — retrying in ${POLL_INTERVAL}s${NC}"
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Parse rates
    input_bps=$(parse_input_rate_bps "$stats")
    output_bps=$(parse_output_rate_bps "$stats")
    input_fmt=$(format_rate "$input_bps")
    output_fmt=$(format_rate "$output_bps")

    # Check anomaly
    is_anomaly=false
    if [ "$input_bps" -gt "$THRESHOLD_BPS" ]; then
        is_anomaly=true
        anomaly_count=$((anomaly_count + 1))
    fi

    # Print status
    print_status_line "$timestamp" "$input_bps" "$output_bps" "$input_fmt" "$output_fmt" "$is_anomaly"

    # Trigger alert if anomaly and not in cooldown
    if [ "$is_anomaly" = true ] && [ "$ALERT_SENT" = false ] && [ "$DRY_RUN" = false ]; then
        current_time=$(date +%s)
        time_since_last=$((current_time - LAST_ALERT_TIME))

        if [ "$time_since_last" -ge "$ALERT_COOLDOWN" ]; then
            echo ""
            echo -e "  ${RED}${BOLD}┌──────────────────────────────────────────────────────────────┐${NC}"
            echo -e "  ${RED}${BOLD}│  🚨 ALERT TRIGGERED — Sending to NOC Supervisor Agent...   │${NC}"
            echo -e "  ${RED}${BOLD}└──────────────────────────────────────────────────────────────┘${NC}"

            # Send Slack alert
            echo -e "  ${YELLOW}  → Posting alert to Slack #noc-l3-alerts...${NC}"
            if send_slack_alert "$input_fmt" "$output_fmt" "$input_bps"; then
                echo -e "  ${GREEN}  ✓ Slack alert sent${NC}"
            else
                echo -e "  ${RED}  ✗ Slack alert failed${NC}"
            fi

            # Trigger Supervisor Agent
            echo -e "  ${YELLOW}  → Triggering Supervisor Agent...${NC}"
            if trigger_supervisor_agent "$input_fmt"; then
                echo -e "  ${GREEN}  ✓ Supervisor Agent triggered${NC}"
            else
                echo -e "  ${YELLOW}  ⚠ Supervisor trigger skipped (URL not in Redis)${NC}"
            fi

            echo ""
            LAST_ALERT_TIME=$current_time
            ALERT_SENT=true
        fi
    fi

    # Reset alert state when traffic returns to normal
    if [ "$is_anomaly" = false ] && [ "$ALERT_SENT" = true ]; then
        echo -e "  ${GREEN}  ℹ Traffic normalized. Alert state reset.${NC}"
        ALERT_SENT=false
    fi

    sleep "$POLL_INTERVAL"
done
