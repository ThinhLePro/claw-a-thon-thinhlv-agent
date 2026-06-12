# EVPN Route Types — Fundamentals Reference

> Source: Day One: Data Center Fundamentals — Colin Wrightson (Juniper Networks)

## EVPN Protocol Overview

EVPN uses **BGP** as its control plane to distribute MAC and IP reachability information across the fabric, replacing traditional flood-and-learn.

### Why EVPN?
- **Eliminates flood-and-learn**: MACs distributed via BGP, not data-plane flooding
- **Optimal forwarding**: Known unicast uses direct path (no unnecessary flooding)
- **Active-active multihoming**: Multiple uplinks, all forwarding simultaneously
- **MAC mobility**: Supports VM migration across racks seamlessly
- **Multi-tenancy**: Per-tenant isolation via EVPN instances

---

## EVPN Route Types

### Type 1 — Ethernet Auto-Discovery (AD)

**Purpose**: Advertises Ethernet segments and enables aliasing + fast convergence.

| Subtype | Function |
|---|---|
| **Per-ES** | Advertises ESI for a multihomed segment → enables aliasing (load-balancing across PEs) |
| **Per-EVI** | Advertises ESI per EVPN instance → fast withdrawal on failure |

```
When a PE comes up with ESI 00:11:22:...:
  → Advertises Type 1 (per-ES) to all peers
  → Remote PEs learn: "ESI 00:11:22 is reachable via this PE"
  → Remote PEs can ECMP traffic to multiple PEs for same ESI

When a PE link fails:
  → Withdraws Type 1 (per-EVI) for affected instances
  → Remote PEs immediately remove that PE from ECMP set
```

### Type 2 — MAC/IP Advertisement

**Purpose**: Distributes MAC addresses (and optionally IPs) learned locally.

```
Fields:
  - RD (Route Distinguisher)
  - ESI (Ethernet Segment Identifier)
  - Ethernet Tag
  - MAC Address (48-bit)
  - IP Address (optional, 32 or 128 bit)
  - MPLS Label / VNI
```

- Replaces flood-and-learn entirely
- When a leaf learns a local MAC → advertises Type 2 via BGP
- Remote leaves install MAC→VTEP mapping in forwarding table
- Supports both L2 (MAC only) and L3 (MAC+IP) advertisement

### Type 3 — Inclusive Multicast Ethernet Tag

**Purpose**: Sets up BUM (Broadcast, Unknown unicast, Multicast) traffic handling.

```
Each PE advertises Type 3 to indicate:
  "I'm interested in BUM traffic for this EVPN instance"

Other PEs learn:
  → Build ingress replication list for BUM traffic
  → Or join multicast group for this VNI
```

**Ingress Replication**: Each VTEP sends a unicast copy to every other VTEP in the VNI — no multicast required in underlay.

### Type 4 — Ethernet Segment (ES)

**Purpose**: Designated Forwarder (DF) election for multihomed segments.

```
1. All PEs sharing same ESI exchange Type 4 routes
2. Build candidate list sorted by IP address
3. DF elected per VLAN: DF = PE at position (VLAN_ID mod N)
4. Only DF forwards BUM traffic → prevents duplicates

Split Horizon Rule:
  Traffic received from an ESI → MUST NOT be forwarded back to same ESI
  Prevents loops in active-active multihoming
```

### Type 5 — IP Prefix Route

**Purpose**: Distributes IP prefix routes for inter-subnet routing (especially DCI).

```
Example: DC1 Gateway knows subnet 10.1.0.0/24 (local DC)
  → Advertises Type 5: 10.1.0.0/24 via BGP to DC2 Gateway
  → DC2 Gateway can route traffic to 10.1.0.0/24 via VXLAN/MPLS tunnel

Used for:
  - Inter-DC L3 routing (DCI)
  - External prefix advertisement
  - Asymmetric/symmetric IRB routing
```

---

## Route Type Summary Table

| Type | Name | BGP NLRI | Main Use |
|---|---|---|---|
| **1** | Ethernet Auto-Discovery | Per-ES / Per-EVI | Aliasing, fast convergence |
| **2** | MAC/IP Advertisement | MAC ± IP | MAC learning, ARP suppression |
| **3** | Inclusive Multicast | Originator IP | BUM handling (ingress replication) |
| **4** | Ethernet Segment | ESI + Originator IP | DF election, split horizon |
| **5** | IP Prefix | IP prefix + GW IP | Inter-subnet routing, DCI |

---

## VXLAN ↔ EVPN Mapping

| VXLAN Concept | EVPN Concept |
|---|---|
| **VNI** | EVI (EVPN Instance) or mapped to VLAN |
| **VTEP** | PE (Provider Edge) advertising Type 3 |
| **MAC learning** | Type 2 routes (control plane) |
| **BUM handling** | Type 3 + ingress replication |
| **Multihoming** | ESI + Type 1/4 routes |
| **Encapsulation** | Extended community: VXLAN or MPLS |

---

## Distributed Layer 3 Gateway

EVPN-based fabrics distribute the L3 gateway across multiple switches:

```
Spine A (IRB: 10.0.1.254, MAC: 00:01:8d:00:01:02)
Spine B (IRB: 10.0.1.254, MAC: 00:01:8d:00:01:02)  ← Same VIP + VMAC

Both advertise:
  Type 1 (ESI) → aliasing/ECMP
  Type 2 (VMAC) → MAC reachability

Leaf sees equal-cost paths to same MAC/ESI → load-balances to both spines
```

### CRB vs ERB

| Design | L3 Gateway Location | Pros | Cons |
|---|---|---|---|
| **CRB** (Centrally-Routed Bridging) | Spine only | Fewer IRBs, simpler leaf | All inter-VLAN goes to spine |
| **ERB** (Edge-Routed Bridging) | Every leaf (anycast) | Local routing, low latency | More IRBs to manage |

> **Modern preference**: ERB with anycast gateway — same IRB IP + MAC on every leaf → traffic routes locally.
