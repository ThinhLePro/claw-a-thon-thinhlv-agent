# DCI — Data Center Interconnect with EVPN

> Source: Juniper EVPN User Guide (Official Documentation)

## DCI Overview

Data Center Interconnect (DCI) extends Layer 2/Layer 3 connectivity between geographically separated data centers using EVPN as the control plane.

### DCI Architecture

```
   Data Center 1                          Data Center 2
┌──────────────────┐      WAN         ┌──────────────────┐
│  ┌────┐  ┌────┐  │                  │  ┌────┐  ┌────┐  │
│  │Leaf│  │Leaf│  │                  │  │Leaf│  │Leaf│  │
│  └─┬──┘  └─┬──┘  │                  │  └─┬──┘  └─┬──┘  │
│    │       │     │                  │    │       │     │
│  ┌─┴───────┴──┐  │    EVPN-MPLS     │  ┌─┴───────┴──┐  │
│  │DC Gateway  │──┼──────────────────┼──│DC Gateway  │  │
│  │(MX/QFX10K) │  │   lt- interface   │  │(MX/QFX10K) │  │
│  └────────────┘  │                  │  └────────────┘  │
│  EVPN-VXLAN      │                  │  EVPN-VXLAN      │
└──────────────────┘                  └──────────────────┘
```

### DCI Transport Options

| Method | Encapsulation | WAN Type | Use Case |
|---|---|---|---|
| **EVPN-VXLAN over VXLAN** | VXLAN end-to-end | IP/L3 WAN | Simple, same fabric extended |
| **EVPN-VXLAN over EVPN-MPLS** | VXLAN→MPLS at gateway | MPLS WAN | Enterprise WAN, multi-vendor |
| **EVPN-VXLAN with multicast** | VXLAN + PIM | L3 WAN + multicast | BUM traffic across DCI |

---

## DCI via EVPN-MPLS WAN

### Logical Tunnel (lt-) Interface

The DC gateway bridges EVPN-VXLAN and EVPN-MPLS domains using a **logical tunnel (lt-) interface**:

```
         DC Gateway (MX Series)
    ┌─────────────────────────────┐
    │                             │
    │  EVPN-VXLAN  ──lt-──  EVPN-MPLS
    │  (DC side)              (WAN side)
    │                             │
    └─────────────────────────────┘
```

- **lt- interface** acts as a back-to-back connection between two routing instances
- DC-facing side: EVPN-VXLAN routing instance
- WAN-facing side: EVPN-MPLS routing instance
- Gateway translates between VXLAN and MPLS encapsulations

### Key Components

| Component | Role |
|---|---|
| **DC Gateway** | MX Series or QFX10000 at DC edge |
| **ToR (Leaf)** | QFX5100/5110/5200 inside DC |
| **WAN PE** | MX Series running EVPN-MPLS |
| **CE Devices** | Servers/hosts connected to leaf |

### Multihoming at DC Gateway

- DC gateways support **active-active multihoming** toward the DC fabric
- Uses ESI on the lt- interface for redundancy
- DF election determines which gateway forwards BUM traffic
- Aliasing enables load-balancing across multiple gateways

---

## EVPN Route Types in DCI

| Type | Name | DCI Role |
|---|---|---|
| **Type 1** | Ethernet Auto-Discovery | Signals multihomed segments at gateway |
| **Type 2** | MAC/IP Advertisement | Carries MAC+IP across DCI |
| **Type 3** | Inclusive Multicast | Sets up BUM traffic handling between DCs |
| **Type 4** | Ethernet Segment | DF election at gateway |
| **Type 5** | IP Prefix | Inter-subnet routing between DCs |

### Type 5 DCI Walkthrough

```
1. Server 1 in DC1 sends traffic to Server 2 in DC2
2. Leaf in DC1 encapsulates in VXLAN → forwards to DC1 Gateway
3. DC1 Gateway:
   a. Strips VXLAN header
   b. Does L3 lookup via IRB interface
   c. Uses Type 5 route learned from DC2 Gateway via BGP
   d. Encapsulates in MPLS → sends over WAN
4. DC2 Gateway:
   a. Strips MPLS encapsulation
   b. Routes IP packet via IRB
   c. Re-encapsulates in VXLAN → forwards to DC2 Leaf
5. DC2 Leaf delivers to Server 2
```

---

## DCI Verification Commands

```junos
# Verify VXLAN tunnel endpoints
show l2-learning vxlan-tunnel-end-point source
show l2-learning vxlan-tunnel-end-point remote

# Verify VTEP interfaces
show interfaces vtep

# Verify EVPN routes across DCI
show route table default-switch.evpn.0
show route table bgp.evpn.0

# Verify BGP sessions with remote DC gateways
show bgp summary

# Verify EVPN database for remote MACs
show evpn database
show evpn database extensive | match "remote"

# Verify lt- interface status
show interfaces lt-*
```

---

## DCI Best Practices

1. **Use VLAN-Aware Bundle Service** for DCI to efficiently map multiple VLANs over single EVPN instance
2. **Deploy dual DC gateways** with ESI multihoming for redundancy
3. **Set appropriate BUM handling**: ingress replication preferred over multicast for DCI
4. **Monitor DCI tunnel health**: Use CFM (802.1ag) end-to-end between DCs
5. **Type 5 for inter-subnet**: Use IP prefix routes to avoid MAC learning overhead across WAN
6. **MTU planning**: Ensure WAN supports VXLAN+MPLS overhead (min 9216 recommended)
