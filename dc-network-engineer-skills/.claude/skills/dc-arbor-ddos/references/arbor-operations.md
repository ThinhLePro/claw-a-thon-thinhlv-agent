# Arbor Operations — Daily Monitoring, Alert Triage & Mitigation Lifecycle

## 1. Daily Operations Checklist

### Morning Check (Kiểm tra đầu ngày)

| Step | Action | Tool | Expected |
|---|---|---|---|
| 1 | Check Sightline dashboard | Sightline UI → Dashboard | No critical alerts, flow ingestion stable |
| 2 | Check AED system status | AED UI → System → Status | All interfaces UP, HA synced |
| 3 | Review overnight alerts | Sightline → Alerts → Last 12h | No unacknowledged high/critical alerts |
| 4 | Check flow ingestion rate | Sightline → System → Collectors | Rate stable (±10% of normal) |
| 5 | Check BGP peer status | Sightline → System → BGP | All peers ESTABLISHED |
| 6 | Check AED throughput | AED → Dashboard → Traffic | Within license limit |
| 7 | Check AED HA status | AED CLI: `system show ha` | Active/Standby, synced |
| 8 | Review active mitigations | Sightline → Mitigations → Active | Only intentional mitigations active |

### Quick CLI Check Script
```bash
# On Sightline
ssh admin@sightline
/ services sp status
/ services sp alerts list --severity high
/ services sp bgp peers
/ services sp mitigations list

# On AED
ssh admin@aed
system status
services aed traffic summary
services aed alerts list --severity high
services aed protection-groups list
```

---

## 2. Alert Triage Workflow (Quy trình xử lý alert)

### Step 1: Receive Alert
Alert arrives via: Sightline UI, email, Syslog, SNMP trap, or Zalo/Telegram integration.

Alert contains:
- **Managed Object** affected (which service/IP)
- **Alert severity** (Low/Medium/High/Critical)
- **Alert type** (volume, protocol, misuse, etc.)
- **Traffic metrics** (current bps/pps vs baseline)
- **Top sources** (attacking IPs/ASNs)

### Step 2: Classify the Alert

| Classification | Indicators | Action |
|---|---|---|
| **False Positive** | Traffic matches legitimate pattern (e.g., marketing campaign, game launch, CDN burst) | Acknowledge, adjust threshold or whitelist |
| **Legitimate Spike** | Known event (scheduled, expected traffic increase) | Acknowledge, document, no mitigation |
| **True Attack — Low Severity** | Small anomaly, no service impact | Monitor, prepare mitigation if escalates |
| **True Attack — High Severity** | Service impact, saturating links, user complaints | **Immediate mitigation** |

### Step 3: Investigate (Điều tra)

```
On Sightline:
1. Click alert → Alert Detail view
2. Check "Attack Traffic" graph — is it sustained or burst?
3. Check "Top Sources" — concentrated or distributed?
4. Check "Protocol Breakdown" — UDP flood? SYN flood? HTTP flood?
5. Check "Destination" — which specific IPs/ports affected?
6. Cross-reference with:
   - CheckMK / Grafana: Is service actually impacted?
   - Edge router: Interface utilization `show interfaces xe-0/0/0 extensive`
   - Application team: Any known events?
```

### Step 4: Decide Mitigation Strategy

| Attack Type | Recommended Mitigation | Device |
|---|---|---|
| **Volumetric UDP flood (>10 Gbps)** | BGP RTBH or upstream ISP filtering | Router + ISP |
| **Volumetric UDP flood (<10 Gbps)** | AED inline scrubbing or TMS diversion | AED |
| **SYN flood** | AED SYN Auth (SYN Proxy) | AED |
| **DNS amplification** | AED DNS Authentication + rate limit | AED |
| **HTTP flood** | AED HTTP Authentication (JS challenge) | AED |
| **Mixed / multi-vector** | AED full protection + upstream RTBH if volume exceeds capacity | AED + Router |
| **Single-source attack** | Blacklist on AED or firewall filter on router | AED or Router |

### Step 5: Execute Mitigation

**Option A: AED (Inline — if AED is inline)**
```
AED UI → Protection Groups → "PROD-WEB"
  → Set Mode: Active (if currently Monitor)
  → Verify countermeasures appropriate for attack type
  → Monitor "Blocked Traffic" — is attack being dropped?
```

**Option B: Sightline-triggered TMS diversion (Out-of-band)**
```
Sightline UI → Alerts → Select alert → "Mitigate"
  → Select TMS/AED device
  → Select mitigation template (e.g., "WEB-SCRUBBING")
  → Confirm → Sightline signals BGP diversion
  → Monitor mitigation status
```

**Option C: BGP RTBH (Nuclear option — sacrifices the target IP)**
```
Sightline UI → Alerts → Select alert → "Blackhole"
  → Select target prefix to blackhole
  → Confirm → Sightline signals RTBH to edge router

hoặc trên router:
set routing-options static route <attacked-ip>/32 discard tag 666
commit confirmed 30 comment "RTBH: DDoS on <attacked-ip>"
```

### Step 6: Monitor Mitigation Effectiveness

```
# On AED
services aed protection-groups stats "PROD-WEB"    # Check drop rate
services aed traffic summary                        # Total traffic vs dropped
services aed blocked hosts "PROD-WEB"               # Which sources blocked

# On Sightline
/ services sp mitigations show <mitigation-id>     # Mitigation effectiveness

# On Router
show interfaces xe-0/0/0 | match "bps"            # Link utilization dropping?

# On Application
curl -o /dev/null -s -w "%{http_code} %{time_total}s" https://service.example.com
# Service responding normally?
```

### Step 7: Close Mitigation

When attack subsides:

```
1. Verify attack traffic has stopped (Sightline shows return to baseline)
2. Wait 15-30 minutes after last attack traffic
3. Gradually step down mitigation:
   - Switch AED PG from Active → Monitor (observe for 15 min)
   - If no attack resumes → stop TMS diversion (if out-of-band)
   - Remove RTBH (if applied): delete routing-options static route <ip>/32
4. Confirm service is fully restored
5. Document: attack start/end time, type, mitigations applied, impact
```

---

## 3. Mitigation Templates (Mẫu mitigation)

Pre-configured templates for common attack scenarios (create these BEFORE an attack):

### Template: WEB-SCRUBBING (HTTP Flood Protection)
```
Protection Level: High
Countermeasures:
  ✅ Invalid Packets
  ✅ TCP SYN Authentication (SYN Cookie)
  ✅ HTTP Authentication (JS Challenge + Cookie)
  ✅ Per-Source Rate Limit: 50 Mbps / 50 Kpps
  ✅ HTTP Malformed
  ✅ Botnet Signatures (AIF)
  ✅ Zombie Detection
  ❌ DNS Authentication (not relevant)
  ❌ GeoIP Blocking (unless specific geo attack)
```

### Template: DNS-PROTECTION (DNS Amplification/Flood)
```
Protection Level: High
Countermeasures:
  ✅ Invalid Packets
  ✅ DNS Authentication (Force TCP Retry)
  ✅ DNS Malformed
  ✅ UDP Flood Mitigation: Threshold 200 Mbps
  ✅ Per-Source Rate Limit: 10 Mbps / 20 Kpps (DNS should be low volume)
  ✅ Botnet Signatures (AIF)
  ❌ HTTP Authentication (not relevant)
  ❌ TCP SYN Auth (not relevant for UDP DNS)
```

### Template: GAMING-PROTECTION (UDP Flood for Gaming Servers)
```
Protection Level: Medium
Countermeasures:
  ✅ Invalid Packets
  ✅ UDP Flood Mitigation: Threshold 1 Gbps
  ✅ Per-Source Rate Limit: 100 Mbps / 100 Kpps
  ✅ ICMP Rate Limit: 5 Mbps
  ✅ Botnet Signatures (AIF)
  ⚠️ Payload Regex (if known attack pattern)
  ❌ HTTP/DNS Auth (not relevant for gaming)
Note: Gaming traffic is UDP-heavy — be careful not to block legitimate game packets
```

### Template: VOLUMETRIC-EMERGENCY (Massive flood — any protocol)
```
Protection Level: High + Custom
Countermeasures:
  ✅ ALL basic countermeasures ON
  ✅ GeoIP Blocking: Block non-relevant countries
  ✅ Per-Source Rate Limit: 20 Mbps / 20 Kpps (aggressive)
  ✅ Protocol Rate Limit: ICMP 1 Mbps, UDP 500 Mbps
  ✅ Blacklist known attacker IPs
  ⚠️ Combined with RTBH or upstream filtering if volume exceeds AED capacity
```

---

## 4. Reporting & Documentation

### Post-Incident Report Template

```markdown
## DDoS Incident Report

**Date**: YYYY-MM-DD
**Duration**: HH:MM - HH:MM (X hours Y minutes)
**Target**: <IP/service affected>
**Managed Object**: <MO name in Sightline>

### Attack Details
- **Type**: <volumetric/protocol/application>
- **Vector**: <UDP flood / SYN flood / DNS amplification / HTTP flood / mixed>
- **Peak volume**: X Gbps / Y Mpps
- **Source**: <distributed / concentrated / specific ASN/country>
- **Target port(s)**: <80/443/53/random>

### Mitigation Applied
1. <timestamp> — AED Protection Group "X" switched to Active
2. <timestamp> — Countermeasure "TCP SYN Auth" triggered, blocking X pps
3. <timestamp> — (if applicable) RTBH activated for prefix Y
4. <timestamp> — Attack subsided, mitigation scaled down
5. <timestamp> — Full mitigation removed, service normal

### Impact
- Service downtime: X minutes
- Packet loss during attack: Y%
- Customer-facing impact: <description>

### Lessons Learned
- <What could be improved>
- <Threshold adjustments needed>
- <Automation opportunities>

### Action Items
- [ ] Adjust threshold for MO "X" from 5 Gbps to 3 Gbps
- [ ] Create Flowspec template for DNS amplification
- [ ] Request ISP to enable RTBH community
```

---

## 5. Automation & Integration

### Auto-Mitigation (Tự động mitigation)

Sightline can be configured to **automatically trigger mitigation** when certain conditions are met:

```
Sightline → Administration → Managed Objects → "PROD-WEB"
→ Alert Settings → Auto-Mitigation:
  - Trigger: When alert severity >= High
  - Action: Start TMS/AED mitigation
  - Template: WEB-SCRUBBING
  - Duration: Until alert clears + 30 min cooldown
  - Notification: Email + Syslog
```

> **Khuyến nghị (Recommendation)**: Chỉ enable auto-mitigation cho các service **đã được tuning kỹ** (Protection Group đã chạy Monitor mode ít nhất 2 tuần, false positive đã được xử lý). Đối với service mới, luôn dùng manual mitigation.

### Sightline REST API

```bash
# Get active alerts
curl -k -u admin:password https://sightline:443/api/sp/alerts/?severity=high

# Get active mitigations
curl -k -u admin:password https://sightline:443/api/sp/mitigations/

# Start mitigation via API (for automation/scripting)
curl -k -u admin:password -X POST https://sightline:443/api/sp/mitigations/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Auto-mitigate-WEB", "managed_object": "PROD-WEB", "template": "WEB-SCRUBBING"}'
```
