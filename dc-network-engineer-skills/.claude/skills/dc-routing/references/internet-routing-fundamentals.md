# Internet Routing Fundamentals & BGP Path Selection

## 1. How the Internet Routes Traffic

The internet is a collection of **Autonomous Systems (AS)**, each identified by a unique **ASN** (Autonomous System Number). BGP (Border Gateway Protocol) is the protocol that connects these ASes and determines how traffic flows between them.

### Key Concepts

| Concept | Description |
|---|---|
| **AS (Autonomous System)** | A network under a single administrative domain (e.g., a company, ISP, DC operator) |
| **ASN** | Unique identifier: 2-byte (1-65535) or 4-byte (65536-4294967295). Private: 64512-65534, 4200000000-4294967294 |
| **Prefix** | An IP network announced via BGP (e.g., `203.0.113.0/24`) |
| **AS-PATH** | The list of ASes a prefix has traversed — used for loop detection and path selection |
| **NLRI** | Network Layer Reachability Information — the prefix being announced |
| **RIB** | Routing Information Base — the full BGP table |
| **FIB** | Forwarding Information Base — the actual forwarding table in hardware |

### Relationship Types

| Type | Description | Money Flow | Routes Exchanged |
|---|---|---|---|
| **Transit** | Provider gives full internet access | Customer pays provider | Provider sends full table; customer sends own + customer routes |
| **Peering** | Two networks exchange traffic directly | Usually free (settlement-free) | Only own + customer routes (no transit) |
| **Customer** | You are the provider, they pay you | Customer pays you | You send full table; they send own routes |

```
            ┌─────────┐
            │ Tier 1   │ ← Full internet transit providers
            │ ISP      │   (e.g., NTT, Lumen, Telia)
            └────┬────┘
                 │ Transit ($)
            ┌────┴────┐
            │ Tier 2   │ ← Regional ISPs
            │ ISP      │   (e.g., VNPT, Viettel, FPT)
            └────┬────┘
           ╱     │      ╲
    Transit     Peering   Transit
         │       │         │
    ┌────┴──┐ ┌──┴───┐ ┌──┴────┐
    │ Your  │ │ CDN  │ │Cloud  │
    │ DC    │ │      │ │Provider│
    └───────┘ └──────┘ └───────┘
```

---

## 2. BGP Protocol Basics

### eBGP vs iBGP

| Feature | eBGP (External) | iBGP (Internal) |
|---|---|---|
| Between | Different ASes | Same AS |
| TTL | 1 (directly connected) or multihop | 255 (any reachable) |
| AS-PATH | Prepends local AS | No AS prepend |
| Next-hop | Changed to self by default | **Not changed** (must use `next-hop self`) |
| Loop detection | AS-PATH (reject if own AS seen) | Cluster-ID / originator-ID |
| Full mesh required | No | Yes (or use route reflectors) |
| Typical use in DC | ISP peering, DCI | Internal DC routing, route reflectors |

### BGP Message Types

| Message | Purpose |
|---|---|
| **OPEN** | Establish BGP session (AS number, hold time, router-id) |
| **UPDATE** | Announce new routes or withdraw old ones |
| **KEEPALIVE** | Maintain session (default every 60 sec) |
| **NOTIFICATION** | Error — session will be closed |

### BGP Session States

```
IDLE → CONNECT → OPEN_SENT → OPEN_CONFIRM → ESTABLISHED
```

| State | Meaning | If Stuck Here |
|---|---|---|
| **Idle** | Not trying to connect | Check config, admin down, prefix-limit exceeded |
| **Active** | Trying TCP to peer | Peer unreachable, firewall blocking TCP/179, wrong IP |
| **OpenSent** | TCP connected, OPEN sent | Waiting for peer's OPEN — AS mismatch, auth failure |
| **OpenConfirm** | OPEN exchange done | Waiting for KEEPALIVE — rare to get stuck |
| **Established** | Session up, routes exchanging | Normal ✅ |

### Juniper BGP Configuration (eBGP Example)
```junos
set routing-options autonomous-system 65001
set routing-options router-id 10.0.0.1

set protocols bgp group ISP-TRANSIT type external
set protocols bgp group ISP-TRANSIT peer-as 7552              # ISP's AS number
set protocols bgp group ISP-TRANSIT neighbor 203.0.113.1
set protocols bgp group ISP-TRANSIT import IMPORT-FROM-ISP    # Import policy
set protocols bgp group ISP-TRANSIT export EXPORT-TO-ISP      # Export policy
set protocols bgp group ISP-TRANSIT family inet unicast
```

### Juniper BGP Verification
```junos
show bgp summary                                   # Session status, prefixes received
show bgp neighbor 203.0.113.1                      # Detailed neighbor info
show route protocol bgp                            # Routes learned via BGP
show route advertising-protocol bgp 203.0.113.1    # Routes sent TO peer
show route receive-protocol bgp 203.0.113.1        # Routes received FROM peer (pre-policy)
show bgp neighbor 203.0.113.1 | match "State|Peer|Active|Received"
```

---

## 3. BGP Path Selection Algorithm

When BGP receives the same prefix from multiple peers, it selects the **best path** using this decision process (in order of priority):

| Priority | Attribute | Prefer | Juniper Config |
|---|---|---|---|
| 1 | **Highest Local Preference** | Higher = preferred | `set local-preference 200` (in policy) |
| 2 | **Shortest AS-PATH** | Fewer AS hops = preferred | (natural), or prepend to make longer |
| 3 | **Lowest Origin** | IGP < EGP < Incomplete | Usually don't manipulate |
| 4 | **Lowest MED** | Lower = preferred (across same neighbor AS) | `set metric 100` (in policy) |
| 5 | **eBGP over iBGP** | eBGP preferred | (natural) |
| 6 | **Lowest IGP metric to next-hop** | Closest exit point | (natural — hot potato routing) |
| 7 | **Oldest route** | Stability | (natural) |
| 8 | **Lowest Router ID** | Tiebreaker | (natural) |
| 9 | **Lowest Peer IP** | Final tiebreaker | (natural) |

### Traffic Engineering Using BGP Attributes

| Goal | Technique | Where Applied |
|---|---|---|
| **Prefer ISP-A for outbound** | Set higher `local-preference` on routes from ISP-A | Import policy from ISP-A |
| **Make ISP prefer our path** | `AS-PATH prepend` (make path look longer via other ISP) | Export policy to the ISP to de-prefer |
| **Influence peer's routing to us** | Set MED (lower = preferred) | Export policy to ISP |
| **Backup path** | Low local-preference on backup ISP | Import policy on backup ISP |

---

## 4. BGP Communities

Communities are **tags** attached to routes to signal routing intent. Format: `ASN:VALUE` (standard) or extended.

### Well-Known Communities

| Community | Meaning |
|---|---|
| `no-export` | Don't export outside this AS |
| `no-advertise` | Don't advertise to any peer |
| `no-export-subconfed` | Don't export outside confederation sub-AS |

### Common Operational Communities (Examples)

| Community | Meaning |
|---|---|
| `65001:100` | Learned from ISP-A |
| `65001:200` | Learned from ISP-B |
| `65001:1000` | Domestic route |
| `65001:2000` | International route |
| `65001:666` | Blackhole this prefix |
| `65001:0` | Do not announce to any peer |

### Juniper Community Configuration
```junos
# Define communities
set policy-options community ISP-A-LEARNED members 65001:100
set policy-options community DOMESTIC members 65001:1000
set policy-options community BLACKHOLE members 65001:666

# Tag routes in import policy
set policy-options policy-statement IMPORT-FROM-ISP-A term TAG then community add ISP-A-LEARNED
set policy-options policy-statement IMPORT-FROM-ISP-A term TAG then accept

# Match community in export policy
set policy-options policy-statement EXPORT-POLICY term DOMESTIC from community DOMESTIC
set policy-options policy-statement EXPORT-POLICY term DOMESTIC then accept
```

---

## 5. Route Reflectors

In iBGP, **every iBGP speaker must peer with every other** (full mesh). This doesn't scale. Route Reflectors (RR) solve this.

```
Without RR (N=4):                    With RR (N=4):
┌──┐  ┌──┐                          ┌──┐  ┌──┐
│R1├──┤R2│                          │R1├──┤RR│
├──┤╲╱├──┤      6 sessions          ├──┤  ├──┤      3 sessions
│R3├──┤R4│                          │R3├──┤R4│
└──┘  └──┘                          └──┘  └──┘
```

### Juniper Route Reflector Config
```junos
# On the Route Reflector
set protocols bgp group iBGP-CLIENTS type internal
set protocols bgp group iBGP-CLIENTS cluster 10.0.0.1        # Cluster ID (usually RR's loopback)
set protocols bgp group iBGP-CLIENTS neighbor 10.0.0.11      # Client 1
set protocols bgp group iBGP-CLIENTS neighbor 10.0.0.12      # Client 2
set protocols bgp group iBGP-CLIENTS neighbor 10.0.0.13      # Client 3

# Clients don't need special config — they just peer with the RR
```

### Route Reflector in DC
- In an IP Fabric, **spine switches** often serve as iBGP EVPN route reflectors
- Leaf switches peer with spines (RR clients) — no full mesh between leaves needed
