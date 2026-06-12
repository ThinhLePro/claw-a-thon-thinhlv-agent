# ISP Connectivity & Peering — Standard DC Architecture

## 1. Physical Connectivity to ISPs

### Standard DC Edge Architecture

```
                    ┌─────────────┐     ┌─────────────┐
                    │  ISP-A CPE  │     │  ISP-B CPE  │
                    │ (provider   │     │ (provider   │
                    │  equipment) │     │  equipment) │
                    └──────┬──────┘     └──────┬──────┘
                           │ (fiber)           │ (fiber)
                    ┌──────┴──────┐     ┌──────┴──────┐
   MDF Room         │  Demarcation│     │  Demarcation│
                    │  ODF        │     │  ODF        │
                    └──────┬──────┘     └──────┴──────┘
                           │                   │
              ═════════════╪═══════════════════╪══════════
                           │     Core Network  │
                    ┌──────┴──────┐     ┌──────┴──────┐
                    │   EDGE-01   │     │   EDGE-02   │
                    │ (MX204/304) │─────│ (MX204/304) │
                    │  Border RTR │     │  Border RTR │
                    └──────┬──────┘     └──────┬──────┘
                           │                   │
                    ┌──────┴───────────────────┴──────┐
                    │         Spine Layer              │
                    │    (QFX5220 / QFX5210)           │
                    └──────┬───────────────────┬──────┘
                           │                   │
                    ┌──────┴──────┐     ┌──────┴──────┐
                    │   Leaf-01   │     │   Leaf-02   │
                    │ (QFX5120)   │     │ (QFX5120)   │
                    └─────────────┘     └─────────────┘
```

### Physical Interface Provisioning

| Connection | Interface Speed | Cable Type | Typical |
|---|---|---|---|
| ISP CPE → Edge router | 1G / 10G / 100G | Single-mode fiber (OS2), LC-LC | 10G most common |
| Edge router → Spine | 40G / 100G | MM fiber (OM4) or DAC | 100G preferred |
| Spine → Leaf | 40G / 100G | MM fiber (OM4) or DAC | 100G |

### Redundancy Requirements

1. **Dual ISP** minimum — never rely on a single provider
2. **Diverse paths** — ISP-A and ISP-B should enter the DC building via different conduit/entry points
3. **Dual edge routers** — each ISP connects to a different edge router (or both ISPs connect to both edge routers for maximum redundancy)
4. **Separate power feeds** — edge routers on different A/B power paths

---

## 2. BGP Session Setup with ISPs

### Standard eBGP Session Configuration

```junos
# Edge router configuration for ISP-A
set routing-options autonomous-system 65001                    # Our AS number

# ISP-A peering (full transit)
set protocols bgp group ISP-A-TRANSIT type external
set protocols bgp group ISP-A-TRANSIT description "Transit - ISP Alpha"
set protocols bgp group ISP-A-TRANSIT peer-as 7552
set protocols bgp group ISP-A-TRANSIT local-address 203.0.113.2     # Our side of the /30 or /31
set protocols bgp group ISP-A-TRANSIT neighbor 203.0.113.1           # ISP's side
set protocols bgp group ISP-A-TRANSIT import IMPORT-ISP-A
set protocols bgp group ISP-A-TRANSIT export EXPORT-TO-ISP-A
set protocols bgp group ISP-A-TRANSIT authentication-key "BGP-Secret-ISP-A"
set protocols bgp group ISP-A-TRANSIT family inet unicast prefix-limit maximum 900000
set protocols bgp group ISP-A-TRANSIT family inet unicast prefix-limit teardown 90

# ISP-B peering (full transit, backup)
set protocols bgp group ISP-B-TRANSIT type external
set protocols bgp group ISP-B-TRANSIT description "Transit - ISP Bravo (backup)"
set protocols bgp group ISP-B-TRANSIT peer-as 45899
set protocols bgp group ISP-B-TRANSIT local-address 198.51.100.2
set protocols bgp group ISP-B-TRANSIT neighbor 198.51.100.1
set protocols bgp group ISP-B-TRANSIT import IMPORT-ISP-B
set protocols bgp group ISP-B-TRANSIT export EXPORT-TO-ISP-B
set protocols bgp group ISP-B-TRANSIT authentication-key "BGP-Secret-ISP-B"
set protocols bgp group ISP-B-TRANSIT family inet unicast prefix-limit maximum 900000
set protocols bgp group ISP-B-TRANSIT family inet unicast prefix-limit teardown 90
```

### Import Policy (from ISP)
```junos
# ISP-A import: accept full table, tag with community, set local-preference
set policy-options policy-statement IMPORT-ISP-A term REJECT-BOGONS from prefix-list BOGONS
set policy-options policy-statement IMPORT-ISP-A term REJECT-BOGONS then reject

set policy-options policy-statement IMPORT-ISP-A term RPKI-INVALID from validation-database invalid
set policy-options policy-statement IMPORT-ISP-A term RPKI-INVALID then reject

set policy-options policy-statement IMPORT-ISP-A term ACCEPT-ROUTES then local-preference 200
set policy-options policy-statement IMPORT-ISP-A term ACCEPT-ROUTES then community add FROM-ISP-A
set policy-options policy-statement IMPORT-ISP-A term ACCEPT-ROUTES then accept

# ISP-B import: similar but with lower local-preference (backup)
set policy-options policy-statement IMPORT-ISP-B term REJECT-BOGONS from prefix-list BOGONS
set policy-options policy-statement IMPORT-ISP-B term REJECT-BOGONS then reject
set policy-options policy-statement IMPORT-ISP-B term ACCEPT-ROUTES then local-preference 100
set policy-options policy-statement IMPORT-ISP-B term ACCEPT-ROUTES then community add FROM-ISP-B
set policy-options policy-statement IMPORT-ISP-B term ACCEPT-ROUTES then accept
```

### Export Policy (to ISP)
```junos
# Only announce our own prefixes (not transit)
set policy-options prefix-list OUR-PREFIXES 203.0.113.0/24
set policy-options prefix-list OUR-PREFIXES 198.51.100.0/24

set policy-options policy-statement EXPORT-TO-ISP-A term OUR-ROUTES from prefix-list OUR-PREFIXES
set policy-options policy-statement EXPORT-TO-ISP-A term OUR-ROUTES then accept
set policy-options policy-statement EXPORT-TO-ISP-A term REJECT-ALL then reject
```

---

## 3. Peering vs Transit

### Private Peering Setup
```junos
# Peering with a content provider (e.g., CDN, cloud)
set protocols bgp group PEERING type external
set protocols bgp group PEERING peer-as 13335           # Example: Cloudflare
set protocols bgp group PEERING neighbor 10.100.0.1     # Peering link IP
set protocols bgp group PEERING import IMPORT-PEERING
set protocols bgp group PEERING export EXPORT-PEERING

# Import from peer: accept only their routes (not transit)
set policy-options policy-statement IMPORT-PEERING term ACCEPT then local-preference 300  # Higher than transit!
set policy-options policy-statement IMPORT-PEERING term ACCEPT then community add FROM-PEER
set policy-options policy-statement IMPORT-PEERING term ACCEPT then accept

# Export to peer: only our routes (not transit routes from ISPs)
set policy-options policy-statement EXPORT-PEERING term OUR-ROUTES from prefix-list OUR-PREFIXES
set policy-options policy-statement EXPORT-PEERING term OUR-ROUTES then accept
set policy-options policy-statement EXPORT-PEERING term REJECT then reject
```

### Local Preference Strategy
| Source | Local Preference | Rationale |
|---|---|---|
| Peering | 300 | Preferred — direct, free, low latency |
| Primary transit (ISP-A) | 200 | Normal transit path |
| Backup transit (ISP-B) | 100 | Backup only — when ISP-A is down |

---

## 4. Verification Checklist After ISP Turn-Up

```junos
# 1. Physical layer
show interfaces xe-0/0/0                         # Link up? Speed correct?
show interfaces xe-0/0/0 extensive | match error  # Any errors?

# 2. BGP session
show bgp summary | match 203.0.113.1             # Session ESTABLISHED?
show bgp neighbor 203.0.113.1 | match "State|Peer|Active|Received|Accepted"

# 3. Routes received
show route receive-protocol bgp 203.0.113.1 | count  # How many routes received?
show route protocol bgp | count                        # How many routes in RIB?

# 4. Routes advertised
show route advertising-protocol bgp 203.0.113.1        # What are we sending?

# 5. End-to-end reachability
ping 8.8.8.8 source 203.0.113.2                       # Can we reach the internet?
traceroute 8.8.8.8 source 203.0.113.2                  # Which path?

# 6. Reverse path — have the ISP verify they can reach our prefixes
```
