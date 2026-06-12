# APS Countermeasures — Protection Settings Reference

> Source: NETSCOUT Arbor APS 6.4 User Guide

## Protection Settings Overview

APS protects against DDoS attacks through **countermeasure categories** that can be configured per **server type** and tuned per **protection level** (Low, Medium, High).

### All Countermeasure Categories

| Category | Attack Type | Description |
|---|---|---|
| **Application Misbehavior** | Application-layer | Detects misbehaving application clients |
| **ATLAS Intelligence Feed (AIF)** | Multi-vector | NETSCOUT threat intelligence — known bad IPs, botnets |
| **Block Malformed DNS** | DNS | Drops DNS packets that don't conform to RFC |
| **Block Malformed SIP** | VoIP | Drops SIP packets that don't conform to RFC |
| **Botnet Prevention** | Multi-vector | Identifies and blocks known botnet C&C traffic |
| **CDN and Proxy Support** | Application | Handles traffic from CDNs/proxies (X-Forwarded-For) |
| **DNS Authentication** | DNS | Validates DNS clients via challenge-response |
| **DNS NXDomain Rate Limiting** | DNS | Limits rate of NXDOMAIN responses |
| **DNS Rate Limiting** | DNS | Limits overall DNS query rate per source |
| **DNS Regular Expression** | DNS | Blocks DNS queries matching regex patterns |
| **Flexible Rate-based Blocking** | Multi-vector | Custom rate-based rules using FCAP |
| **Fragment Detection** | Network | Detects and blocks IP fragment-based attacks |
| **HTTP Header Regex** | HTTP | Blocks HTTP requests matching header patterns |
| **HTTP Rate Limiting** | HTTP | Limits HTTP request rate per source |
| **HTTP Reporting** | HTTP | Reports on HTTP transactions without blocking |
| **ICMP Flood Detection** | Network | Detects and limits ICMP flood attacks |
| **Malformed HTTP Filtering** | HTTP | Drops malformed HTTP requests |
| **Multicast Blocking** | Network | Blocks multicast traffic |
| **Payload Regex** | Multi-vector | Blocks packets matching payload patterns |
| **Private Address Blocking** | Network | Blocks RFC 1918 and other private addresses |
| **Rate-based Blocking** | Multi-vector | Rate limits traffic per source (bps/pps thresholds) |
| **SIP Request Limiting** | VoIP | Limits SIP request rate per source |
| **Spoofed SYN Flood Prevention** | TCP | Validates TCP SYN via proxy/challenge |
| **TCP Connection Limiting** | TCP | Limits concurrent connections per source |
| **TCP Connection Reset** | TCP | Resets suspicious TCP connections |
| **TCP SYN Flood Detection** | TCP | Detects SYN flood rate anomalies |
| **TLS Attack Prevention** | TLS/SSL | Protects against TLS-based attacks |
| **Traffic Shaping** | Multi-vector | Rate-limits traffic per protection group |
| **UDP Flood Detection** | UDP | Detects and limits UDP flood attacks |

---

## Protection Levels

Each server type has **three protection levels** with increasing strictness:

| Level | When to Use | Typical Thresholds |
|---|---|---|
| **Low** | Normal operations, minimal false positives | Highest thresholds (most permissive) |
| **Medium** | Moderate attack detected | Balanced thresholds |
| **High** | Active attack, maximum protection | Lowest thresholds (most aggressive) |

> **Best Practice**: Start with **Low** and increase only when an attack is confirmed. Use **traffic profiling** to set baseline thresholds.

---

## Server Types

### Standard Server Types (Built-in)

| Server Type | Optimized For | Key Countermeasures |
|---|---|---|
| **Generic** | All traffic types | Full countermeasure set |
| **DNS** | DNS servers | DNS Authentication, DNS Rate Limiting, NXDomain |
| **HTTP** | Web servers | HTTP Rate Limiting, Malformed HTTP, SYN Flood |
| **SMTP** | Email servers | Rate-based, Connection Limiting |
| **VoIP/SIP** | SIP servers | SIP Request Limiting, Malformed SIP |
| **Generic IPv6** | IPv6 traffic | IPv6-aware countermeasures |

### Custom Server Types
- Created by cloning a standard server type
- Custom thresholds per protection level
- Maximum 50 protection groups total (including default)

---

## Protection Groups

A **protection group** = IP prefixes + server type + protection level.

### Configuration

```
Protection Group: "Web Servers"
├── Server Type: HTTP
├── Protection Level: Low (normal) → Medium (alert) → High (attack)
├── Protected Hosts: 203.0.113.0/24
├── Bandwidth Alert: 1 Gbps warning, 2 Gbps critical
└── Mode: Active (blocking) or Inactive (monitoring)
```

### Protection Mode

| Mode | Traffic Action | Use When |
|---|---|---|
| **Active** | Monitor + Block | Production — actively mitigating attacks |
| **Inactive** | Monitor only | Trial deployment, tuning phase |

> **Workflow**: Deploy in **Inactive** mode first → observe alerts for 1-2 weeks → tune thresholds → switch to **Active**.

---

## Traffic Profiling

Use traffic profiling to **auto-tune thresholds** based on observed traffic patterns.

### Profiling Workflow

```
1. Start capture: Protect > Inbound Protection > Server Type Configuration
2. Capture duration: minimum 24 hours (recommended: 7 days)
3. Review histogram: shows traffic distribution per countermeasure
4. Apply recommended thresholds:
   - Click "Auto" to apply APS-recommended values
   - Or manually adjust using histogram markers
5. Save settings
```

### Histogram Markers
- **L** (Low), **M** (Medium), **H** (High) markers show threshold positions
- Drag markers to adjust thresholds visually
- Shows percentage of traffic that would be passed vs blocked

---

## Filter Lists & FCAP Expressions

### Master Filter Lists
Apply to **all protection groups** globally:

```
# Pass SSH from trusted network, block all other SSH
pass port 22 and src 192.0.2.0/24
drop port 22
```

### Per-Server-Type Filter Lists
Apply only to protection groups with that server type, per protection level.

### FCAP Expression Syntax

```
# Basic syntax
<action> <expression>

# Actions
pass    — allow traffic without further inspection
drop    — block traffic without further inspection

# Examples
drop src 10.0.0.0/8                          # Block RFC1918
pass dst port 443 and src 203.0.113.0/24     # Allow HTTPS from trusted
drop proto udp and dst port 53               # Block UDP DNS
pass src country US                           # Allow traffic from US
drop payload regex ".*malicious.*"           # Block payload match
```

### Evaluation Order
- Expressions evaluated **top to bottom**
- First matching rule wins
- If no rule matches → normal countermeasure processing

---

## Blacklists & Whitelists

| List | Scope | Items Supported |
|---|---|---|
| **Inbound Blacklist** | Block incoming traffic | IPv4/IPv6 hosts, countries, domains |
| **Inbound Whitelist** | Allow incoming traffic | IPv4/IPv6 hosts, countries, domains |
| **Outbound Blacklist** | Block outgoing traffic | IPv4 hosts |
| **Outbound Whitelist** | Allow outgoing traffic | IPv4 hosts |

### Processing Order
```
1. Whitelist check (if match → PASS immediately)
2. Blacklist check (if match → DROP immediately)
3. Master Filter List
4. Server-type Filter List
5. Countermeasure processing
```

> **Key point**: Whitelist takes priority over blacklist. Use whitelists for critical services (monitoring systems, known partners).
