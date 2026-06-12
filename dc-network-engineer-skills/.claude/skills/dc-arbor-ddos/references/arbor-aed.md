# Arbor AED (Availability Protection System) — Inline Mitigation

## 1. What Is Arbor AED?

Arbor AED (formerly TMS — Threat Management System, and Pravail APS) is a **DDoS mitigation appliance** that inspects traffic and removes malicious packets while allowing legitimate traffic to pass.

### Deployment Modes

| Mode | Description | Topology | Pros | Cons |
|---|---|---|---|---|
| **Inline** (always-on) | AED sits in the traffic path permanently | Router → AED → Internal network | Zero delay to start mitigation, always protecting | Adds latency to all traffic, single point of failure |
| **Out-of-band (diversion)** | Traffic is diverted to AED only during attacks via BGP | Normal: Router → Network; Attack: Router → AED → Network | No latency in normal state, scalable | Diversion delay (30-90 sec), requires BGP integration |
| **Monitor** (tap/span) | AED monitors a copy of traffic (passive) | Mirror port → AED | No impact, great for learning | Cannot mitigate (only alerts) |

### Typical DC Deployment (Inline)

```
Internet → Edge Router → [AED Inline] → Spine/Leaf → Servers
                              │
                              ├── Clean traffic → passes through
                              └── Attack traffic → dropped/rate-limited
```

### Typical DC Deployment (Out-of-Band with Sightline)

```
Normal traffic flow:
Internet → Edge Router ──────────────────────→ Spine/Leaf → Servers

During attack (Sightline triggers diversion):
Internet → Edge Router → BGP diversion → [AED] → GRE/Direct → Edge Router → Servers
                              │                       │
                         Sightline signals        AED scrubs traffic
                         BGP route to divert      returns clean traffic
```

---

## 2. Key Concepts

### Protection Group (PG)
A **Protection Group** defines what traffic the AED protects and how it protects it. Think of it as a "security policy" for a set of IP addresses.

| Component | Description |
|---|---|
| **Name** | Descriptive name (e.g., "WEB-SERVERS-PROD") |
| **Protected Prefixes** | IP ranges being protected (e.g., 203.0.113.0/24) |
| **Protection Level** | Low / Medium / High / Custom |
| **Countermeasures** | List of enabled detection/mitigation techniques |
| **Mode** | Active (mitigating) / Inactive / Monitor-only |

### Countermeasures (Biện pháp đối phó)
Countermeasures are the **individual techniques** that AED uses to identify and block attack traffic.

| Category | Countermeasure | What It Does | Default State |
|---|---|---|---|
| **Protocol validation** | Invalid Packets | Drops malformed IP/TCP/UDP packets | ✅ Enabled |
| | TCP SYN Auth (SYN Proxy) | Validates TCP handshake, blocks SYN floods | ✅ Enabled |
| | DNS Authentication | Validates DNS queries (forces TCP retry or CAPTCHA) | ⚠️ Monitor first |
| | HTTP Authentication | Validates HTTP clients (JavaScript challenge, cookie) | ⚠️ Monitor first |
| **Rate-based** | Per-Source Rate Limit | Limits bps/pps from each source IP | ✅ Enabled |
| | Per-Destination Rate Limit | Limits bps/pps to each destination IP | ⚠️ Configure carefully |
| | Protocol Rate Limit | Limits by protocol (UDP, ICMP, etc.) | ✅ Enabled |
| | UDP Flood Mitigation | Detects and rate-limits UDP floods | ✅ Enabled |
| | ICMP Flood Mitigation | Rate-limits ICMP traffic | ✅ Enabled |
| **Behavioral** | Zombie Detection | Identifies botnet sources by behavior patterns | ✅ Enabled |
| | DNS Malformed | Blocks invalid DNS queries (amplification attacks) | ✅ Enabled |
| | HTTP Malformed | Blocks malformed HTTP requests (Slowloris, etc.) | ✅ Enabled |
| **Access control** | Blacklist/Whitelist | Static IP lists (block known bad, allow known good) | Manual |
| | GeoIP Blocking | Block traffic from specific countries | Manual |
| | Regular Expression (Regex) | Match and block by payload pattern | Advanced |
| **Advanced** | Payload Regex | Deep packet inspection with regex matching | Advanced |
| | Botnet Signatures | ATLAS Intelligence Feed (AIF) — known bad sources | ✅ Enabled (with license) |
| | TLS/SSL Inspection | Inspect encrypted traffic (requires cert) | ⚠️ Complex setup |

### Protection Levels (Preset Configurations)

| Level | Countermeasures Enabled | Aggressiveness | Use Case |
|---|---|---|---|
| **Low** | Basic validation, rate limits only | Conservative | Always-on baseline, low false-positive risk |
| **Medium** | + SYN Auth, DNS Auth, Zombie Detection | Moderate | Standard protection |
| **High** | + HTTP Auth, strict rate limits, GeoIP | Aggressive | Active attack mitigation |
| **Custom** | Manual selection per countermeasure | Varies | Tailored to specific service |

---

## 3. AED Configuration (Web UI)

### Creating a Protection Group
```
AED UI → Protection Groups → Add New

Step 1: General
  - Name: "PROD-WEB-SERVERS"
  - Description: "Production web server cluster"
  - Protected Prefixes: 203.0.113.0/24

Step 2: Protection Settings
  - Protection Level: Medium
  - Mode: Monitor (start here, then switch to Active after tuning)

Step 3: Countermeasures (fine-tune each)
  - Invalid Packets: ON
  - TCP SYN Authentication: ON, Mode: SYN Cookie
  - DNS Authentication: ON, Mode: Monitor (learn first)
  - HTTP Authentication: OFF (enable only during HTTP floods)
  - Per-Source Rate Limit: ON, Limit: 100 Mbps / 100 Kpps per source
  - UDP Flood: ON, Threshold: 500 Mbps aggregate
  - ICMP Rate Limit: ON, Limit: 10 Mbps aggregate
  - Botnet Signatures (AIF): ON

Step 4: Notifications
  - Alert when: any countermeasure triggers
  - Send to: syslog, email, SNMP trap
```

### Important: Monitor Before Enforce (Quan trọng: Monitor trước khi Enforce)

> ⚠️ **CRITICAL**: Khi deploy Protection Group mới hoặc bật countermeasure mới, **LUÔN bắt đầu ở mode Monitor (detect-only)** trong ít nhất 24-48 giờ. Xem các traffic bị match, verify rằng đó thực sự là attack traffic, không phải legitimate traffic, rồi mới chuyển sang Active (enforce).

```
Workflow:
1. Create PG → Mode: Monitor → Wait 24-48h
2. Review detected traffic → is it really malicious?
3. If false positives → adjust thresholds or whitelist
4. If clean → Switch to Active (enforce)
5. Continue monitoring for 7 days → fine-tune
```

---

## 4. AED CLI (SSH)

```bash
ssh admin@<aed-ip>

# === System Status ===
system status                                    # Overall system health
system show interfaces                          # Network interfaces
system show version                             # Software version

# === Protection Groups ===
services aed protection-groups list              # List all PGs
services aed protection-groups show "PROD-WEB"   # Show specific PG details
services aed protection-groups stats "PROD-WEB"  # Traffic stats for PG

# === Countermeasure Status ===
services aed countermeasures list "PROD-WEB"     # List countermeasures for PG
services aed countermeasures stats "PROD-WEB"    # Countermeasure hit counters

# === Blocked Traffic ===
services aed blocked list                        # Currently blocked IPs/flows
services aed blocked hosts "PROD-WEB"            # Blocked hosts for PG

# === Whitelist/Blacklist ===
services aed whitelist show "PROD-WEB"           # Show whitelist entries
services aed blacklist show "PROD-WEB"           # Show blacklist entries
services aed blacklist add "PROD-WEB" host 1.2.3.4  # Add IP to blacklist
services aed blacklist remove "PROD-WEB" host 1.2.3.4

# === Traffic Summary ===
services aed traffic summary                     # Current traffic through AED
services aed traffic top-sources "PROD-WEB" --count 20  # Top 20 source IPs
services aed traffic top-talkers                 # Top traffic contributors

# === Alerts ===
services aed alerts list                         # Active alerts
services aed alerts list --severity high         # Filter by severity

# === Mitigation (for out-of-band mode) ===
services aed mitigations list                    # Active mitigations
services aed mitigations status                  # Mitigation system status
```

---

## 5. AED Interfaces (Network Setup)

### Inline Deployment

| Interface Role | Description | Connected To |
|---|---|---|
| **External (untrusted)** | Internet-facing, receives potentially malicious traffic | Edge router output |
| **Internal (trusted)** | Clean traffic exits here to the internal network | Spine switch / firewall |
| **Management** | Out-of-band management access | Management switch |
| **HA (High Availability)** | Heartbeat and state sync between AED pair | Directly to peer AED |

```
                   External          Internal
Internet → Router → [eth1] AED [eth2] → Internal Network
                        │
                    [mgmt0] → Management network (SSH, WebUI)
                        │
                     [eth3] → HA peer (AED-02)
```

### AED High Availability (HA Pair)

| Mode | Description |
|---|---|
| **Active/Standby** | One AED processes traffic, the other is standby. Failover on failure. |
| **Active/Active** | Both AEDs process traffic (load sharing). Requires external load balancer. |

```
                        ┌────────┐
Internet → Router →─────│ AED-01 │──── Internal
                   │    │(Active)│  │
                   │    └───┬────┘  │
                   │        │ HA    │
                   │    ┌───┴────┐  │
                   └────│ AED-02 │──┘
                        │(Stndby)│
                        └────────┘
```

---

## 6. Key AED Metrics to Monitor

| Metric | Where to Check | Normal | Warning | Critical |
|---|---|---|---|---|
| **Throughput** | `traffic summary` | Within license limit | >70% license | >90% license (risk of dropping clean traffic) |
| **Packets dropped** | PG stats | 0 (no attack) or expected drops | Unexpected drops | False positives (legitimate traffic blocked) |
| **CPU utilization** | `system status` | <50% | 50-75% | >75% (may affect inspection depth) |
| **HA status** | `system show ha` | Synced, Active/Standby | Sync delay | Peer DOWN |
| **Interface errors** | `system show interfaces` | 0 errors | Any errors | Increasing errors |
| **Countermeasure hits** | `countermeasures stats` | Low/zero (no attack) | Increasing (possible attack) | Very high + alerts |
| **License utilization** | `system show license` | Within limits | Approaching limit | Exceeded (features disabled) |

> **Lưu ý thực tế (Practical note)**: AED có license throughput limit (ví dụ: 2 Gbps, 10 Gbps, 40 Gbps). Nếu traffic vượt quá license, AED sẽ **pass-through** traffic không inspect được. Luôn check license utilization khi thấy traffic cao.
