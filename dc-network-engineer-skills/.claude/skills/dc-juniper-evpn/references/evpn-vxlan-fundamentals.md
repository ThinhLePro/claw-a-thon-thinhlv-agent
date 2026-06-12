# EVPN-VXLAN Fundamentals

## 1. VXLAN (Virtual Extensible LAN)

### Problem It Solves
- **VLAN limit**: 802.1Q only supports 4094 VLANs — not enough for multi-tenant DC.
- **L2 spanning**: Traditional VLANs require STP, which blocks redundant paths. VXLAN enables L2 connectivity over L3 underlay with ECMP.
- **Mobility**: VMs can move across racks without stretching VLANs.

### How VXLAN Works
VXLAN encapsulates the original L2 frame inside a UDP packet:

```
Original Frame:  [Eth Hdr][IP][TCP][Data]

After VXLAN encap:
[Outer Eth][Outer IP][UDP:4789][VXLAN Hdr][Original Eth][IP][TCP][Data]
                                 │
                            VNI (24-bit) = Virtual Network Identifier
```

### Key Concepts

| Concept | Description |
|---|---|
| **VNI** (Virtual Network Identifier) | 24-bit identifier — supports ~16 million virtual networks (vs 4094 VLANs) |
| **VTEP** (VXLAN Tunnel Endpoint) | The device that encapsulates/decapsulates VXLAN. In IP Fabric = leaf switch |
| **NVE** (Network Virtualization Edge) | The interface representing the VTEP (loopback IP) |
| **Underlay** | The L3 network connecting VTEPs (eBGP/OSPF, physical spine-leaf) |
| **Overlay** | The virtual L2 network carried inside VXLAN tunnels |

### VXLAN Header (8 bytes)
```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|R|R|R|R|I|R|R|R|            Reserved                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                VXLAN Network Identifier (VNI) |   Reserved    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### MTU Impact
- VXLAN adds **50 bytes** overhead:
  - Outer Ethernet: 14 bytes
  - Outer IP: 20 bytes
  - UDP: 8 bytes
  - VXLAN: 8 bytes
- **Underlay MTU must be ≥ 9216** (to support 9000-byte jumbo inner frames + 50 bytes overhead)

---

## 2. EVPN (Ethernet VPN — RFC 7432/8365)

### What Is EVPN?
EVPN is a **BGP address family** that provides the control plane for VXLAN. Instead of flood-and-learn, EVPN distributes MAC/IP information via BGP.

### EVPN Benefits
| Feature | Flood-and-Learn (no EVPN) | EVPN |
|---|---|---|
| MAC learning | Data-plane flooding | BGP control plane (no flooding) |
| BUM traffic | Flood everywhere | Optimized (ingress replication or multicast) |
| ARP resolution | Broadcast ARP requests | **ARP suppression** (local proxy) |
| Multi-homing | MC-LAG only | **ESI** (Ethernet Segment Identifier) |
| L3 routing | External router needed | **Integrated IRB** (distributed gateway) |
| Mobility | Manual | **MAC mobility** (automatic re-convergence) |

### EVPN Route Types

| Type | Name | What It Carries | Use |
|---|---|---|---|
| **Type 1** | Ethernet Auto-Discovery | ESI, RD | Multi-homing, mass withdrawal |
| **Type 2** | MAC/IP Advertisement | MAC, IP, VNI, VTEP IP | **Main route type** — MAC/IP learning |
| **Type 3** | Inclusive Multicast | VTEP IP, VNI | BUM traffic handling (ingress replication list) |
| **Type 4** | Ethernet Segment | ESI, VTEP IP | DF (Designated Forwarder) election for multi-homing |
| **Type 5** | IP Prefix | IP prefix, VNI | **Inter-VNI L3 routing** (like L3VPN) |

### Type 2 Example (MAC/IP Route)
```junos
user@leaf-01> show route table default-switch.evpn.0 evpn-mac-address aa:bb:cc:dd:ee:ff

*[BGP/170] 00:05:23, localpref 100, from 10.0.0.1
      AS path: I
    > to 10.0.1.1 via xe-0/0/0.0, Push 10100  ← VNI 10100
      Route target: 65001:10100
      EVPN Type: 2
      ESI: 00:00:00:00:00:00:00:00:00:00
      MAC: aa:bb:cc:dd:ee:ff
      IP: 10.1.100.50
```

### Type 5 Example (IP Prefix Route)
```junos
user@leaf-01> show route table TENANT-A.evpn.0 match-prefix "5:*"

5:65001:100::0::10.1.200.0::24/248
      *[EVPN/170] 00:10:45
        > to 10.0.1.3 via xe-0/0/1.0, Push 5100  ← L3 VNI
```

---

## 3. Juniper EVPN-VXLAN Configuration (Leaf Switch)

### Step 1: VXLAN Interface (NVE)
```junos
# VTEP source IP (use loopback)
set interfaces lo0 unit 0 family inet address 10.0.0.11/32

# No explicit NVE config needed on Juniper — it uses switch-options
set switch-options vtep-source-interface lo0.0
```

### Step 2: VLAN + VNI Mapping
```junos
# Create VLAN with VXLAN VNI
set vlans PROD vlan-id 100
set vlans PROD vxlan vni 10100

set vlans MGMT vlan-id 200
set vlans MGMT vxlan vni 10200
```

### Step 3: Access Port Configuration
```junos
# Server-facing port (access)
set interfaces xe-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces xe-0/0/1 unit 0 family ethernet-switching vlan members PROD

# Server-facing port (trunk)
set interfaces xe-0/0/2 unit 0 family ethernet-switching interface-mode trunk
set interfaces xe-0/0/2 unit 0 family ethernet-switching vlan members [PROD MGMT]
```

### Step 4: IRB (Integrated Routing and Bridging)
```junos
# L3 gateway for VLAN 100
set interfaces irb unit 100 family inet address 10.1.100.1/24
set interfaces irb unit 100 virtual-gateway-address 10.1.100.254  # Anycast gateway (same on all leaves)
set interfaces irb unit 100 virtual-gateway-accept-data            # Accept traffic to anycast GW

# Associate IRB with VLAN
set vlans PROD l3-interface irb.100
```

### Step 5: Overlay BGP (iBGP EVPN)
```junos
set protocols bgp group EVPN-OVERLAY type internal
set protocols bgp group EVPN-OVERLAY local-address 10.0.0.11
set protocols bgp group EVPN-OVERLAY family evpn signaling
set protocols bgp group EVPN-OVERLAY neighbor 10.0.0.1           # Spine-1 (RR)
set protocols bgp group EVPN-OVERLAY neighbor 10.0.0.2           # Spine-2 (RR)
```

### Step 6: EVPN Protocol
```junos
set protocols evpn encapsulation vxlan
set protocols evpn extended-vni-list all       # All VNIs participate in EVPN
set protocols evpn default-gateway do-not-advertise  # Use anycast GW instead
```

### Step 7: Route Distinguisher & Route Target
```junos
set switch-options route-distinguisher 10.0.0.11:1
set switch-options vrf-target target:65001:1
```

### Verification
```junos
show evpn database                             # EVPN MAC/IP entries
show evpn instance                             # EVPN instances
show ethernet-switching vxlan-tunnel-end-point remote  # Remote VTEPs
show route table default-switch.evpn.0         # EVPN routes
show route table :vxlan.inet.0                 # VXLAN routes
```
