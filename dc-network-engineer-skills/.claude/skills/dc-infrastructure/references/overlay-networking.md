# Overlay Networking — VXLAN Fundamentals for DC

> Source: Day One: Data Center Fundamentals — Colin Wrightson (Juniper Networks)

## Underlay vs Overlay

| Layer | Function | Protocol | What It Carries |
|---|---|---|---|
| **Underlay** | Physical IP network (spine-leaf) | BGP, OSPF | Encapsulated tunnel traffic |
| **Overlay** | Virtual network on top of underlay | VXLAN, EVPN | Tenant/application L2 traffic |

```
┌─────────────────────────────────────────────────┐
│ Overlay (VXLAN tunnels, VNIs, tenant networks)  │
├─────────────────────────────────────────────────┤
│ Underlay (IP Fabric, BGP, physical links)       │
└─────────────────────────────────────────────────┘
```

---

## VXLAN (Virtual Extensible LAN)

### Key Concepts

| Component | Description |
|---|---|
| **VTEP** | VXLAN Tunnel Endpoint — where encapsulation/decapsulation occurs (on leaf switches) |
| **VNI** | VXLAN Network Identifier — 24-bit ID (up to 16 million segments vs 4096 VLANs) |
| **Outer header** | UDP port 4789, source/dest VTEP IP addresses |
| **Inner frame** | Original Ethernet frame (preserved intact) |

### VXLAN Packet Format

```
┌───────────────────────────────────────────────────────────────┐
│ Outer Ethernet │ Outer IP │ Outer UDP │ VXLAN │ Inner Ethernet│
│ (switch MACs)  │(VTEP IPs)│(port 4789)│Header │(original frame│
│  14 bytes      │ 20 bytes │ 8 bytes   │8 bytes│ + payload)    │
└───────────────────────────────────────────────────────────────┘
                                         │
                                    ┌────┴────┐
                                    │ VNI     │ ← 24-bit network ID
                                    │ Flags   │
                                    └─────────┘
```

**MTU impact**: VXLAN adds 50 bytes overhead → set underlay MTU to **9216** (jumbo frames) to avoid fragmentation.

---

## MAC Learning in VXLAN

### Data Plane Learning (Flood & Learn)

Without a control plane (basic VXLAN), VTEPs learn MACs like traditional Ethernet:

1. **VTEP receives frame** → records source VTEP IP + source MAC + VNI in forwarding table
2. **Unknown destination** → flood via multicast group assigned to that VNI
3. **Reply received** → unicast path established for future traffic

### Packet Walkthrough: VTEP Flood & Learn

```
VM1 (192.168.0.10) → wants to reach VM2 (192.168.0.11)
Both in VNI 100, multicast group 239.1.1.100

1. VM1 sends ARP request for 192.168.0.11
2. VTEP1 encapsulates ARP into multicast packet → 239.1.1.100
3. All VTEPs in group receive, check VNI=100
   - If local VNI matches → forward ARP to local segment
   - All VTEPs learn: VTEP1 IP → VM1 MAC (VNI 100)
4. VM2 receives ARP, responds with its MAC
5. VTEP2 encapsulates response → unicast to VTEP1
6. VTEP1 learns: VTEP2 IP → VM2 MAC (VNI 100)
7. Future traffic: direct unicast between VTEPs ✅
```

> **Problem with multicast**: Requires multicast-capable underlay. Solution: **EVPN** provides a control plane that eliminates flood-and-learn entirely.

---

## VXLAN Routing (Inter-VNI)

When traffic needs to move between different VNIs (different subnets), you need a **Layer 3 gateway**.

### Where to Route

| Location | Device | Advantage | Limitation |
|---|---|---|---|
| **At the leaf** | QFX5110, QFX5200 | Low latency, local routing | Requires hardware support |
| **At the spine** | QFX10000, MX, EX9200 | Custom silicon, always supported | Extra hops, potential bottleneck |

> **Trend**: Modern merchant silicon (QFX5110+) supports native VXLAN routing at the leaf — preferred for new designs.

### Routing Process (Single Switch)

```
Switch has:
- VTEP with VLAN 100, VNI 1000, IRB 100 (gateway 10.1.100.1)
- VTEP with VLAN 101, VNI 1001, IRB 101 (gateway 10.1.101.1)
- L3 VRF connecting both IRBs

Packet: Server A (10.1.100.10) → Server B (10.1.101.10)

1. Receive VXLAN packet → decapsulate (native frame)
2. Destination MAC = local IRB VIP MAC → L3 lookup
3. L3 VRF routing table → route to IRB 101
4. ARP lookup for 10.1.101.10 → resolve destination MAC
5. Re-encapsulate with VXLAN (VNI 1001) → send to remote VTEP
```

### Symmetric vs Asymmetric IRB

| Model | Description | Use When |
|---|---|---|
| **Asymmetric** | Routing only at ingress VTEP; requires all VNIs on all leaves | Small scale, few VNIs |
| **Symmetric** | Routing at both ingress and egress; uses L3 VNI for transit | Large scale, many VNIs (preferred) |

> See `/dc-juniper-evpn` for full symmetric IRB configuration.

---

## Controller-Based vs Protocol-Based Overlay

| Approach | Control Plane | Example | Pros | Cons |
|---|---|---|---|---|
| **Controller-based** | SDN controller pushes VTEP state | Juniper Contrail, VMware NSX | Centralized policy, multi-vendor | Controller = SPOF, complexity |
| **Protocol-based** | EVPN via BGP distributes MAC/IP | Juniper EVPN-VXLAN | Distributed, resilient, standard | More per-device config |
| **Static** | Manual VTEP mapping | Manual config | Simple, no dependencies | Doesn't scale |

> **Recommendation**: Use **EVPN (protocol-based)** for production DC — distributed, resilient, and industry standard. Use controller for multi-cloud or policy-heavy environments.
