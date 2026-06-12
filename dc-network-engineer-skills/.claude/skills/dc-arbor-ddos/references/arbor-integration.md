# Arbor Integration — BGP, Router, Cloud Signaling

## 1. Integration Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                     DDoS PROTECTION ECOSYSTEM                      │
│                                                                    │
│  ┌──────────┐     BGP feed      ┌────────────────┐               │
│  │ Edge     │ ──────────────→   │   SIGHTLINE    │               │
│  │ Router   │                   │  (Detection)   │               │
│  │ (MX/QFX) │  ←─ RTBH/Flowspec │                │               │
│  │          │  ←─ BGP diversion  │  Triggers ──→  │               │
│  └────┬─────┘                   └───────┬────────┘               │
│       │                                  │                        │
│       │                           ┌──────┴──────┐                │
│       │                           │    AED      │                │
│       ├── inline ────────────→    │ (Mitigation)│                │
│       │                           │             │                │
│       │   ←── clean traffic ──    │             │                │
│       │       (GRE or direct)     └──────┬──────┘                │
│       │                                  │                        │
│       │                           ┌──────┴──────┐                │
│       │                           │ ATLAS Cloud │                │
│       │                           │ (Upstream   │                │
│       │                           │  scrubbing) │                │
│       │                           └─────────────┘                │
│       ▼                                                           │
│    Internal Network                                               │
└───────────────────────────────────────────────────────────────────┘
```

---

## 2. BGP Integration with Sightline

### Purpose
Sightline uses BGP to:
1. **Receive** the full routing table (to map traffic to Managed Objects)
2. **Send** RTBH/diversion routes to edge routers (to trigger mitigation)

### Sightline → Router: BGP RTBH

When Sightline detects an attack and the operator (or auto-mitigation) triggers RTBH:

```
Sightline announces via BGP:
  Prefix: <attacked-ip>/32
  Next-hop: 192.0.2.1 (RFC 5635 discard next-hop)
  Community: <RTBH community agreed with ISP, e.g., 65001:666>

Router receives this announcement:
  → Installs route to <attacked-ip>/32 → discard (null route)
  → If community matches ISP RTBH, re-advertises to ISP
  → ISP drops traffic to <attacked-ip> at their edge
```

### Router Configuration for Sightline BGP

```junos
# === Edge Router — Accepting RTBH from Sightline ===

# Static discard route for the blackhole next-hop
set routing-options static route 192.0.2.1/32 discard

# BGP peer with Sightline
set protocols bgp group SIGHTLINE type internal
set protocols bgp group SIGHTLINE local-address 10.0.0.1
set protocols bgp group SIGHTLINE neighbor 10.254.0.100          # Sightline IP
set protocols bgp group SIGHTLINE family inet unicast
set protocols bgp group SIGHTLINE import ACCEPT-SIGHTLINE-RTBH   # Accept RTBH routes
set protocols bgp group SIGHTLINE export EXPORT-FULL-TABLE        # Send full table to Sightline

# Import policy: only accept /32 routes with RTBH community
set policy-options community RTBH members 65001:666

set policy-options policy-statement ACCEPT-SIGHTLINE-RTBH term RTBH-ROUTES from community RTBH
set policy-options policy-statement ACCEPT-SIGHTLINE-RTBH term RTBH-ROUTES from route-filter 0.0.0.0/0 prefix-length-range /32-/32
set policy-options policy-statement ACCEPT-SIGHTLINE-RTBH term RTBH-ROUTES then {
    next-hop 192.0.2.1;
    accept;
}
set policy-options policy-statement ACCEPT-SIGHTLINE-RTBH term REJECT then reject

# Export policy: send full table to Sightline for traffic attribution
set policy-options policy-statement EXPORT-FULL-TABLE term ALL then accept

# Optionally re-advertise RTBH to upstream ISPs
set policy-options policy-statement EXPORT-TO-ISP term RTBH from community RTBH
set policy-options policy-statement EXPORT-TO-ISP term RTBH then {
    community add ISP-RTBH-COMMUNITY;   # ISP's RTBH community
    next-hop 192.0.2.1;
    accept;
}
```

### Sightline → Router: BGP Flowspec

If the router supports Flowspec and it's configured in Sightline:

```junos
# Enable Flowspec on BGP group
set protocols bgp group SIGHTLINE family inet flow

# Sightline will push flow routes like:
# Match: dst 203.0.113.100/32, protocol UDP, src-port 53 → discard
# This blocks DNS amplification to a specific IP without blackholing all traffic
```

---

## 3. BGP Diversion to AED (Out-of-Band / TMS Mode)

### How TMS Diversion Works

```
Normal state:
Internet → Edge Router → [route: 203.0.113.0/24 via ISP] → Servers

Attack detected → Sightline signals diversion:
Sightline BGP announces:
  Prefix: 203.0.113.0/24
  Next-hop: <AED-diversion-IP>
  Community: <diversion community>
  With higher local-preference than normal route

Edge Router:
  → Prefers Sightline's route (higher LP)
  → Sends traffic to AED instead of directly to servers
  → AED scrubs → returns clean traffic via GRE → Router → Servers
```

### Router Configuration for Diversion

```junos
# GRE tunnel for clean traffic return from AED
set interfaces gr-0/0/0 unit 0 tunnel source 10.0.0.1            # Router loopback
set interfaces gr-0/0/0 unit 0 tunnel destination 10.254.0.110    # AED tunnel endpoint
set interfaces gr-0/0/0 unit 0 family inet mtu 1476               # 1500 - 24 (GRE overhead)
set interfaces gr-0/0/0 unit 0 family inet address 10.100.0.1/31

# Static route for clean return traffic (via GRE)
# This is needed to avoid re-diverting clean traffic
set routing-instances CLEAN-RETURN instance-type virtual-router
set routing-instances CLEAN-RETURN interface gr-0/0/0.0
set routing-instances CLEAN-RETURN routing-options static route 203.0.113.0/24 next-hop 10.100.0.0

# Import Sightline diversion routes
set policy-options community DIVERSION members 65001:999

set policy-options policy-statement ACCEPT-SIGHTLINE-DIVERSION term DIVERT from community DIVERSION
set policy-options policy-statement ACCEPT-SIGHTLINE-DIVERSION term DIVERT then {
    local-preference 400;   # Higher than normal routes
    accept;
}
set policy-options policy-statement ACCEPT-SIGHTLINE-DIVERSION term DEFAULT then accept
```

### Preventing Re-Diversion Loop

⚠️ **Critical issue**: When AED returns clean traffic via GRE, the router must NOT re-divert it back to AED (routing loop).

**Solutions**:
1. **Separate routing instance** for GRE return path (shown above)
2. **PBR (Policy-Based Routing)**: Route GRE return traffic directly to internal network, bypassing BGP
3. **Tunnel endpoint on separate interface/VRF**: AED returns traffic to a different IP/VRF that doesn't participate in diversion

---

## 4. Cloud Signaling (ATLAS / Upstream Scrubbing)

### What Is Cloud Signaling?

When a DDoS attack is too large for on-premise AED to handle (saturates the ISP link before reaching AED), Sightline can **signal upstream ISPs or cloud scrubbing providers** to clean traffic before it reaches your network.

```
Without Cloud Signaling:
[100 Gbps attack] → ISP link (10 Gbps) → SATURATED → AED can't even receive traffic

With Cloud Signaling:
[100 Gbps attack] → ISP Cloud Scrubbing → [1 Gbps clean traffic] → ISP link (10 Gbps) → Your DC
```

### Integration with Cloud Providers

| Provider | Integration Method | Notes |
|---|---|---|
| **NETSCOUT ATLAS** | Built-in Cloud Signaling | Automated via Sightline UI/API |
| **ISP upstream scrubbing** | BGP RTBH or manual request | Depends on ISP capabilities |
| **Cloudflare** | BGP or DNS-based diversion | For HTTP/HTTPS services |
| **Akamai Prolexic** | BGP-based or GRE | Enterprise DDoS scrubbing |
| **AWS Shield Advanced** | API-based | For AWS-hosted services |

### Enabling Cloud Signaling in Sightline
```
Sightline UI → Administration → Cloud Signaling
  → Add provider
  → Configure API key / credentials
  → Map Managed Objects to provider
  → Set auto-signal rules:
    - Signal when: attack > AED capacity (e.g., > 10 Gbps)
    - Signal type: diversion request
    - Duration: until attack subsides + 30 min
```

---

## 5. SNMP & Syslog Integration (Monitoring)

### Sightline Syslog to Centralized Log Server

```
Sightline → Administration → Notification → Syslog
  → Server: 10.254.0.51
  → Port: 514
  → Facility: local0
  → Severity: warning+
  → Include: alerts, mitigations, system events
```

### AED Syslog Configuration

```bash
# AED CLI
system syslog add server 10.254.0.51 port 514
system syslog severity warning
```

### SNMP Trap Integration

```
# Sightline SNMP traps to monitoring (CheckMK/Zabbix)
Sightline → Administration → Notification → SNMP
  → Trap target: 10.254.0.50
  → Community: "MONITORING"
  → Version: v2c
  → Events: alert-start, alert-stop, mitigation-start, mitigation-stop
```

### Key SNMP OIDs for Monitoring

| OID / MIB | Description | Use |
|---|---|---|
| `PEAKFLOW-SP-MIB::spAlertTable` | Active alerts | Monitor alert count |
| `PEAKFLOW-SP-MIB::spMitigationTable` | Active mitigations | Monitor mitigation status |
| `PEAKFLOW-SP-MIB::spCollectorFlowRate` | Flow ingestion rate | Detect flow loss |
| `PEAKFLOW-SP-MIB::spSystemCpu` | Sightline CPU | Capacity monitoring |
| `PEAKFLOW-TMS-MIB::tmsMitigationTable` | TMS/AED mitigation stats | Monitor scrubbing |

---

## 6. Integration Verification Checklist

```bash
# === After Initial Setup ===

# 1. Flow collection working?
# On Sightline: / services sp flow stats
# Expect: consistent flow rate matching router sampling config

# 2. BGP peer ESTABLISHED?
# On Sightline: / services sp bgp peers
# On Router: show bgp summary | match <sightline-ip>

# 3. Managed Objects have traffic?
# On Sightline UI: Traffic → Query → Filter by MO
# Expect: traffic graph shows data matching MO's prefixes

# 4. Sightline can signal RTBH?
# Test: Create test blackhole for a non-production /32
# On Router: show route <test-ip>/32 → should show discard route
# Remove test blackhole immediately after verification

# 5. AED connectivity?
# On Sightline: / services sp tms status
# Expect: AED device shows CONNECTED

# 6. GRE tunnel working? (out-of-band only)
# On Router: ping <aed-gre-ip> source <router-gre-ip>
# On AED: ping <router-gre-ip>

# 7. Cloud Signaling configured? (if applicable)
# On Sightline: Administration → Cloud Signaling → Test connection
```

> **Lời khuyên cuối cùng (Final advice)**: Test toàn bộ mitigation workflow (end-to-end) ít nhất **mỗi quý một lần** bằng cách simulate một attack trên non-production IP. Điều này đảm bảo rằng khi attack thật xảy ra, tất cả các thành phần (Sightline detection → mitigation signal → AED scrubbing → clean traffic return) đều hoạt động đúng.
