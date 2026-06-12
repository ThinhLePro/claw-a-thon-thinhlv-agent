# EVPN-VXLAN Advanced — Multihoming, ARP Suppression, HA

> Source: Juniper EVPN User Guide (Official Documentation)

## EVPN Multihoming Overview

EVPN multihoming enables connecting a CE device (host/switch) to **two or more PE devices** for redundant connectivity.

### Multihoming Modes

| Mode | Description | Traffic | Use Case |
|---|---|---|---|
| **Active-Active** | All links forwarding simultaneously | Load-balanced across PEs | High throughput, server dual-homing |
| **Active-Standby** | Only one PE forwards; others standby | Single active path | Legacy devices, protocol constraints |

### Ethernet Segment Identifier (ESI)

ESI is a **10-byte identifier** that uniquely identifies a multihomed Ethernet segment.

```
ESI Format: XX:XX:XX:XX:XX:XX:XX:XX:XX:XX
Example:    00:11:22:33:44:55:66:77:88:99
```

- All PEs connected to the same CE must share the **same ESI**
- ESI enables the EVPN control plane to coordinate between PEs
- **ESI 0** (all zeros) = single-homed segment (no redundancy)

### Auto-generated ESI

Starting from certain Junos releases, ESIs can be **automatically generated** from LACP system ID + port key, eliminating manual ESI configuration.

```junos
# Manual ESI configuration
set interfaces ae0 esi 00:11:22:33:44:55:66:77:88:99
set interfaces ae0 esi all-active    # or single-active

# Auto-ESI (from LACP)
set interfaces ae0 esi auto-derive lacp
```

### EZ-LAG (Easy EVPN LAG)

Simplified multihoming configuration that auto-derives ESI from LACP parameters:

```junos
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 aggregated-ether-options lacp system-id 00:00:00:00:00:01
set interfaces ae0 esi auto-derive lacp
set interfaces ae0 esi all-active
```

---

## Designated Forwarder (DF) Election

When multiple PEs share an Ethernet segment, one is elected as the **Designated Forwarder** for BUM traffic.

### Why DF Election?
- Prevents **duplicate BUM frames** reaching the CE device
- Without DF: every PE would forward BUM → loops and duplicates

### Election Process

1. Each PE advertises **EVPN Type 4 (ES route)** containing the ESI
2. All PEs in the same ES build a candidate list sorted by IP address
3. DF is elected per-VLAN using modulo arithmetic:
   ```
   DF for VLAN V = PE at position (V mod N)
   where N = number of PEs in the ES
   ```
4. Only the DF forwards BUM traffic; non-DF PEs drop BUM

### DF Election Algorithms

| Algorithm | Description | Junos Config |
|---|---|---|
| **Default (mod)** | V mod N — simple, balanced | Default (no config needed) |
| **Preference** | Manual priority-based | `set protocols evpn df-election-type preference` |

---

## Split Horizon and Aliasing

### Split Horizon Rule
- Traffic received from an ESI **must not** be forwarded back to the same ESI
- Prevents loops in active-active multihoming
- Implemented via **split horizon label** in EVPN-MPLS or **split horizon filtering** in EVPN-VXLAN

### Aliasing (Load Balancing)
- Remote PEs learn that multiple PEs serve the same ESI via **Type 1 (Auto-Discovery) routes**
- Remote PE can **load-balance** traffic across all PEs in the ES
- Even if MAC was learned from only one PE, traffic can be sent to any PE in the ES

```
Remote PE sees:
  Type 1 route from PE1 for ESI 00:11:22:... → label 100
  Type 1 route from PE2 for ESI 00:11:22:... → label 200
  → Can ECMP traffic to both PE1 and PE2
```

---

## EVPN Proxy ARP / ARP Suppression

### Purpose
Reduces broadcast traffic in EVPN-VXLAN by having the **leaf switch answer ARP requests locally** from its EVPN MAC/IP database.

### How It Works

```
1. Host A sends ARP request for Host B (broadcast)
2. Leaf switch checks EVPN database for Host B's MAC+IP
3. If found → Leaf replies directly with Host B's MAC (unicast)
   If not found → Flood ARP as normal
4. Result: ARP broadcast never crosses VXLAN overlay
```

### Configuration

```junos
# Enable ARP suppression per VLAN/VNI
set protocols evpn default-gateway no-gateway-community
set switch-options vtep-source-interface lo0.0
set vlans VLAN100 vxlan vni 10100
set vlans VLAN100 vxlan ingress-node-replication
```

### Benefits
- Reduces **BUM (Broadcast, Unknown unicast, Multicast)** traffic
- Faster ARP resolution (local response vs remote round-trip)
- Scales better with large number of hosts

### Proxy NDP (IPv6)
Same concept for IPv6 Neighbor Discovery Protocol — leaf answers NS (Neighbor Solicitation) locally.

---

## High Availability in EVPN

### Nonstop Active Routing (NSR)

For dual Routing Engine platforms:

```junos
# Enable GRES (Graceful RE Switchover)
set chassis redundancy graceful-switchover

# Enable NSR
set routing-options nonstop-routing

# For EVPN-VXLAN: set phantom route hold-time (recommended: 300s)
set routing-options nsr-phantom-holdtime 300

# Enable commit synchronize
set system commit synchronize
```

**What gets mirrored to standby RE:**
- MAC route labels (per-EVI and per-ESI)
- Inclusive multicast (IM) route labels (per-VLAN)
- Split horizon labels
- Aliasing labels
- ETREE leaf labels

### Graceful Restart

For non-NSR environments or single RE:

```junos
set routing-options graceful-restart
```

- Informs BGP neighbors of restart condition
- Reduces traffic loss during convergence

### Unified ISSU

Supported for EVPN-VXLAN on MX Series (dual RE):
- Enables software upgrade with **minimal traffic disruption**
- Requires GRES + NSR enabled

> **Recommendation**: For production EVPN-VXLAN, always configure GRES + NSR with `nsr-phantom-holdtime 300`.
