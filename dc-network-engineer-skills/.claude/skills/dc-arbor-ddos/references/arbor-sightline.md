# Arbor Sightline (Peakflow SP) — Traffic Visibility & Detection

## 1. What Is Arbor Sightline?

Arbor Sightline (formerly Peakflow SP / Peakflow X) is a **network-wide traffic visibility and DDoS detection platform**. It does NOT mitigate attacks — it **detects** them and **triggers mitigation** on other devices (AED/TMS, routers, cloud).

### Core Functions
| Function | Description |
|---|---|
| **Traffic visibility** | Collects and analyzes flow data (NetFlow/sFlow/IPFIX) from routers/switches |
| **Anomaly detection** | Learns traffic baselines, detects deviations (volumetric, protocol, application) |
| **Alert management** | Generates alerts when anomalies exceed thresholds |
| **Mitigation orchestration** | Triggers mitigation on TMS/AED, BGP RTBH, Flowspec, or Cloud Signaling |
| **Reporting** | Historical traffic analysis, top-N reports, peering analysis |
| **BGP integration** | Receives full BGP table for traffic attribution to customers/services |

### How It Works
```
                    ┌──────────────────────────────────────┐
                    │         ARBOR SIGHTLINE               │
                    │  ┌──────────┐  ┌──────────────────┐  │
                    │  │ Flow     │  │ Anomaly          │  │
  NetFlow/sFlow ───→  │ Collector│→ │ Detection Engine │  │
  from routers      │  └──────────┘  └────────┬─────────┘  │
                    │                          │            │
  BGP feed ────────→  ┌──────────┐            ▼            │
  (full table)      │  │ BGP      │  ┌──────────────────┐  │
                    │  │ Peering  │  │ Alert Manager    │  │
                    │  └──────────┘  │ (thresholds,     │  │
                    │                │  notifications)   │  │
                    │                └────────┬─────────┘  │
                    │                         │            │
                    │                         ▼            │
                    │  ┌──────────────────────────────────┐│
                    │  │ Mitigation Orchestrator          ││
                    │  │ → Trigger TMS/AED mitigation     ││
                    │  │ → Signal BGP RTBH to router      ││
                    │  │ → Signal Flowspec to router       ││
                    │  │ → Cloud Signaling (upstream ISP)  ││
                    │  └──────────────────────────────────┘│
                    └──────────────────────────────────────┘
```

---

## 2. Key Concepts

### Managed Object (MO)
A **Managed Object** is any network resource that Sightline monitors and protects. Each MO has its own **traffic baseline** and **alert thresholds**.

| MO Type | Example | Typical Use |
|---|---|---|
| **Customer** | "VNG Cloud Services" | Group of prefixes belonging to a customer or service |
| **Peer** | "ISP-VNPT" | A BGP peering partner |
| **Profile** | "DNS Servers" | A specific application profile (port-based) |
| **Network boundary** | "Edge-01 interface" | An interface or link on a router |

### Configuring a Managed Object
```
Sightline UI → Administration → Managed Objects → Add

Fields:
- Name: "PROD-WEB-SERVERS"
- Match type: CIDR (prefix-based)
- Prefixes: 203.0.113.0/24, 198.51.100.0/25
- Alert settings:
  - bps threshold: 5 Gbps (auto or manual)
  - pps threshold: 2 Mpps
  - Detection: Misuse detection (profile-based)
- Mitigation:
  - Auto-mitigation: ON (when threshold exceeded)
  - Mitigation type: TMS diversion (BGP)
```

### Traffic Baseline (Tự động học traffic pattern)
Sightline **learns the normal traffic pattern** for each Managed Object over time (typically 2-4 weeks). It tracks:
- **Bandwidth (bps)** — bits per second in/out
- **Packet rate (pps)** — packets per second
- **Protocol distribution** — % TCP, UDP, ICMP, etc.
- **Port distribution** — top ports (80, 443, 53, etc.)
- **Source/destination patterns** — geographic, AS distribution

**Anomaly** = current traffic significantly deviates from the learned baseline.

### Alert Severity

| Severity | Trigger | Typical Action |
|---|---|---|
| **Low** | Minor deviation from baseline (1.5-2× normal) | Monitor, no action |
| **Medium** | Significant deviation (2-5× normal) | Investigate, prepare mitigation |
| **High** | Major spike (5-10× normal) or known attack signature | **Auto-mitigate** or manual trigger |
| **Critical** | Extreme volume (>10× normal) or link saturation | **Immediate mitigation + escalation** |

---

## 3. Flow Data Collection

### Supported Flow Protocols

| Protocol | Source Device | Sampling | Notes |
|---|---|---|---|
| **NetFlow v5** | Cisco legacy routers | 1:N | Most basic, IPv4 only |
| **NetFlow v9** | Cisco modern routers | 1:N | Template-based, flexible |
| **IPFIX** | Standards-based (RFC 7011) | 1:N | NetFlow v10, vendor-neutral |
| **sFlow** | Juniper, Arista, others | 1:N (packet sampling) | Samples actual packets |
| **J-Flow** | Juniper | 1:N | Juniper's NetFlow equivalent |

### Juniper sFlow/J-Flow Configuration (Sending flows to Sightline)

```junos
# Option 1: sFlow (recommended for Juniper QFX/EX)
set protocols sflow collector-udp-port 6343
set protocols sflow agent-id 10.0.0.11                        # Loopback IP
set protocols sflow polling-interval 20
set protocols sflow sample-rate ingress 2048                   # 1 in 2048 packets
set protocols sflow collector 10.254.0.100 udp-port 6343      # Sightline IP
set protocols sflow interfaces xe-0/0/0.0
set protocols sflow interfaces et-0/0/30.0                    # Uplink interfaces

# Option 2: Inline J-Flow (for MX routers)
set services flow-monitoring version-ipfix template IPV4 flow-active-timeout 60
set services flow-monitoring version-ipfix template IPV4 flow-inactive-timeout 30
set services flow-monitoring version-ipfix template IPV4 template-refresh-rate seconds 300
set services flow-monitoring version-ipfix template IPV4 ipv4-template

set forwarding-options sampling instance SAMPLE input rate 1024
set forwarding-options sampling instance SAMPLE family inet output flow-server 10.254.0.100 port 9996
set forwarding-options sampling instance SAMPLE family inet output flow-server 10.254.0.100 version-ipfix template IPV4
set forwarding-options sampling instance SAMPLE family inet output inline-jflow source-address 10.0.0.11

# Apply to interface
set interfaces et-0/0/0 unit 0 family inet sampling input
```

### BGP Peering with Sightline

Sightline needs a **BGP feed** (full table or partial) to map traffic flows to Managed Objects (which customer/prefix owns this traffic?).

```junos
# On edge router — peer with Sightline (iBGP, read-only)
set protocols bgp group SIGHTLINE-FEED type internal
set protocols bgp group SIGHTLINE-FEED local-address 10.0.0.1
set protocols bgp group SIGHTLINE-FEED neighbor 10.254.0.100    # Sightline IP
set protocols bgp group SIGHTLINE-FEED family inet unicast
set protocols bgp group SIGHTLINE-FEED export EXPORT-FULL-TABLE  # Send full table
set protocols bgp group SIGHTLINE-FEED import REJECT-ALL         # Don't accept routes from Sightline
```

---

## 4. Sightline UI Navigation

### Key Pages

| Page | Path | Purpose |
|---|---|---|
| **Dashboard** | Home | Overview: top alerts, traffic summary, active mitigations |
| **Alerts** | Alerts → All Alerts | Active and historical alerts, filtering, actions |
| **Traffic** | Traffic → Query | Ad-hoc traffic analysis (top sources, destinations, protocols) |
| **Managed Objects** | Administration → Managed Objects | Configure monitored resources |
| **Mitigations** | Mitigation → Active | View/manage active mitigations |
| **Reports** | Reports → Scheduled | Automated reports (daily/weekly traffic summaries) |
| **System** | Administration → System | Health, collectors, BGP peers |

### Alert Workflow in UI
```
1. Alerts → All Alerts
2. Click on alert row → Alert Detail
3. Review:
   - Attack traffic graph (bps/pps over time)
   - Source IPs / ASNs / countries
   - Destination IPs / ports
   - Protocol breakdown
4. Actions:
   - "Mitigate" → Start TMS/AED mitigation
   - "Blackhole" → Trigger RTBH on router
   - "Flowspec" → Push Flowspec rule to router
   - "Cloud Signal" → Signal upstream provider
   - "Acknowledge" → Mark as reviewed
   - "Ignore" → False positive, suppress
```

---

## 5. Sightline CLI (SSH)

Sightline also has a CLI accessible via SSH:

```bash
ssh admin@10.254.0.100

# Show system status
/ services sp status

# Show active alerts
/ services sp alerts list

# Show managed objects
/ services sp managed_objects list

# Show BGP peers
/ services sp bgp peers

# Show flow collectors
/ services sp flow collectors

# Show active mitigations
/ services sp mitigations list

# Traffic query (last hour, top destinations by bps)
/ services sp traffic query --duration 1h --by dst_ip --top 10 --sort bps
```

---

## 6. Key Metrics to Monitor on Sightline

| Metric | Normal | Warning | Critical |
|---|---|---|---|
| **Flow ingestion rate** | Stable (±10%) | Drop >20% | Drop >50% (flow loss) |
| **BGP peer status** | Established | Peer flapping | Peer DOWN |
| **Active alerts** | 0-5 | 5-20 | >20 (possible attack wave) |
| **System CPU** | <60% | 60-80% | >80% (capacity issue) |
| **Disk usage** | <70% | 70-85% | >85% (purge old data) |
| **Collector reachability** | All UP | Any DOWN | Multiple DOWN |

> **Tuyệt đối quan trọng (Critical)**: Nếu Sightline mất flow data (flow ingestion drops), nó sẽ **không phát hiện được tấn công**. Luôn monitor flow ingestion rate và BGP peer status.
