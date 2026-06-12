# Standard IP Fabric Design — Underlay + Overlay

## 1. IP Fabric Topology

### Standard 2-Tier (Spine-Leaf)

```
                    ┌──────────┐   ┌──────────┐
                    │ SPINE-01 │   │ SPINE-02 │
                    │ AS 65000 │   │ AS 65000 │
                    │10.0.0.1  │   │10.0.0.2  │
                    └─┬──┬──┬──┘   └─┬──┬──┬──┘
                      │  │  │        │  │  │
         ┌────────────┘  │  │   ┌────┘  │  └───────────────┐
         │     ┌─────────┘  │   │  ┌────┘                  │
         │     │    ┌───────┘   │  │     ┌─────────────────┘
         │     │    │           │  │     │
    ┌────┴─┐ ┌┴────┴─┐    ┌───┴──┴┐ ┌──┴──────┐
    │LEAF-1│ │LEAF-2 │    │LEAF-3 │ │LEAF-4   │
    │AS6501│ │AS65012│    │AS65013│ │AS65014  │
    │ 1    │ │       │    │       │ │         │
    │10.0. │ │10.0.  │    │10.0.  │ │10.0.    │
    │0.11  │ │0.12   │    │0.13   │ │0.14     │
    └──┬───┘ └──┬────┘    └──┬────┘ └──┬──────┘
       │        │            │         │
    Servers  Servers      Servers   Servers
    VLAN 100 VLAN 100    VLAN 200  VLAN 200
```

### Design Rules
1. **Every leaf connects to every spine** (full mesh between tiers)
2. **No leaf-to-leaf links** (all inter-leaf traffic goes via spines)
3. **No spine-to-spine links** (spines don't communicate directly)
4. **ECMP**: Multiple equal-cost paths via different spines
5. **Scalability**: Add more leaves for more ports, add more spines for more bandwidth

---

## 2. Underlay Design (eBGP)

### Why eBGP for Underlay?
- **Simple**: Each device has its own AS — no iBGP full mesh or RR needed for underlay
- **Fast convergence**: With BFD, sub-second failover
- **ECMP**: Built-in multipath support
- **No OSPF complexity**: No areas, LSA flooding, DR/BDR election

### ASN Assignment Strategy

| Device | ASN | Note |
|---|---|---|
| All Spines | `65000` | Same AS — they don't peer with each other |
| Leaf-01 | `65011` | Unique per leaf |
| Leaf-02 | `65012` | Unique per leaf |
| Leaf-03 | `65013` | Unique per leaf |
| ... | `650xx` | Pattern: 650 + rack number |

### IP Addressing

| Network | CIDR | Allocation |
|---|---|---|
| Loopbacks (spine) | `10.0.0.1/32`, `10.0.0.2/32` | One per spine |
| Loopbacks (leaf) | `10.0.0.11/32`, `10.0.0.12/32`, ... | One per leaf (= VTEP IP) |
| P2P links | `10.0.1.0/31`, `10.0.1.2/31`, `10.0.1.4/31`, ... | One `/31` per link |

### Spine Configuration (Complete)
```junos
# === SPINE-01 ===
set system host-name SPINE-01

# Loopback
set interfaces lo0 unit 0 family inet address 10.0.0.1/32

# Underlay interfaces (to leaves)
set interfaces et-0/0/0 unit 0 family inet address 10.0.1.0/31    # → LEAF-01
set interfaces et-0/0/1 unit 0 family inet address 10.0.1.2/31    # → LEAF-02
set interfaces et-0/0/2 unit 0 family inet address 10.0.1.4/31    # → LEAF-03
set interfaces et-0/0/3 unit 0 family inet address 10.0.1.6/31    # → LEAF-04

# MTU (jumbo frames for VXLAN)
set interfaces et-0/0/0 mtu 9216
set interfaces et-0/0/1 mtu 9216
set interfaces et-0/0/2 mtu 9216
set interfaces et-0/0/3 mtu 9216

# Routing
set routing-options router-id 10.0.0.1
set routing-options autonomous-system 65000

# eBGP underlay (to all leaves)
set protocols bgp group UNDERLAY type external
set protocols bgp group UNDERLAY family inet unicast
set protocols bgp group UNDERLAY export EXPORT-LOOPBACK
set protocols bgp group UNDERLAY multipath multiple-as
set protocols bgp group UNDERLAY bfd-liveness-detection minimum-interval 300
set protocols bgp group UNDERLAY bfd-liveness-detection multiplier 3

set protocols bgp group UNDERLAY neighbor 10.0.1.1 peer-as 65011   # LEAF-01
set protocols bgp group UNDERLAY neighbor 10.0.1.3 peer-as 65012   # LEAF-02
set protocols bgp group UNDERLAY neighbor 10.0.1.5 peer-as 65013   # LEAF-03
set protocols bgp group UNDERLAY neighbor 10.0.1.7 peer-as 65014   # LEAF-04

# iBGP overlay (EVPN — spine is Route Reflector)
set protocols bgp group EVPN-OVERLAY type internal
set protocols bgp group EVPN-OVERLAY local-address 10.0.0.1
set protocols bgp group EVPN-OVERLAY family evpn signaling
set protocols bgp group EVPN-OVERLAY cluster 10.0.0.1              # RR cluster ID
set protocols bgp group EVPN-OVERLAY neighbor 10.0.0.11            # LEAF-01
set protocols bgp group EVPN-OVERLAY neighbor 10.0.0.12            # LEAF-02
set protocols bgp group EVPN-OVERLAY neighbor 10.0.0.13            # LEAF-03
set protocols bgp group EVPN-OVERLAY neighbor 10.0.0.14            # LEAF-04

# Export policy for underlay
set policy-options policy-statement EXPORT-LOOPBACK term LO from protocol direct
set policy-options policy-statement EXPORT-LOOPBACK term LO from route-filter 10.0.0.1/32 exact
set policy-options policy-statement EXPORT-LOOPBACK term LO then accept
set policy-options policy-statement EXPORT-LOOPBACK term REJECT then reject

# Enable forwarding for overlay (spine doesn't participate in EVPN, just reflects)
set protocols evpn encapsulation vxlan
```

### Leaf Configuration (Complete)
```junos
# === LEAF-01 ===
set system host-name LEAF-01

# Loopback (= VTEP IP)
set interfaces lo0 unit 0 family inet address 10.0.0.11/32

# Underlay interfaces (to spines)
set interfaces et-0/0/30 unit 0 family inet address 10.0.1.1/31   # → SPINE-01
set interfaces et-0/0/31 unit 0 family inet address 10.0.2.1/31   # → SPINE-02
set interfaces et-0/0/30 mtu 9216
set interfaces et-0/0/31 mtu 9216

# Routing
set routing-options router-id 10.0.0.11
set routing-options autonomous-system 65011
set routing-options forwarding-table export ECMP-POLICY

# ECMP
set policy-options policy-statement ECMP-POLICY term 1 then load-balance per-packet

# eBGP underlay
set protocols bgp group UNDERLAY type external
set protocols bgp group UNDERLAY family inet unicast
set protocols bgp group UNDERLAY export EXPORT-LOOPBACK
set protocols bgp group UNDERLAY multipath multiple-as
set protocols bgp group UNDERLAY bfd-liveness-detection minimum-interval 300
set protocols bgp group UNDERLAY bfd-liveness-detection multiplier 3
set protocols bgp group UNDERLAY neighbor 10.0.1.0 peer-as 65000   # SPINE-01
set protocols bgp group UNDERLAY neighbor 10.0.2.0 peer-as 65000   # SPINE-02

# iBGP overlay (EVPN)
set protocols bgp group EVPN-OVERLAY type internal
set protocols bgp group EVPN-OVERLAY local-address 10.0.0.11
set protocols bgp group EVPN-OVERLAY family evpn signaling
set protocols bgp group EVPN-OVERLAY neighbor 10.0.0.1             # SPINE-01 (RR)
set protocols bgp group EVPN-OVERLAY neighbor 10.0.0.2             # SPINE-02 (RR)

# EXPORT for underlay
set policy-options policy-statement EXPORT-LOOPBACK term LO from protocol direct
set policy-options policy-statement EXPORT-LOOPBACK term LO from route-filter 10.0.0.11/32 exact
set policy-options policy-statement EXPORT-LOOPBACK term LO then accept
set policy-options policy-statement EXPORT-LOOPBACK term REJECT then reject

# === OVERLAY / VXLAN ===

# VTEP source
set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher 10.0.0.11:1
set switch-options vrf-target target:65001:1

# VLANs + VNI mapping
set vlans PROD vlan-id 100
set vlans PROD vxlan vni 10100
set vlans PROD l3-interface irb.100

set vlans MGMT vlan-id 200
set vlans MGMT vxlan vni 10200
set vlans MGMT l3-interface irb.200

# IRB (Anycast Gateway)
set interfaces irb unit 100 family inet address 10.1.100.1/24
set interfaces irb unit 100 virtual-gateway-address 10.1.100.254
set interfaces irb unit 100 virtual-gateway-accept-data

set interfaces irb unit 200 family inet address 10.1.200.1/24
set interfaces irb unit 200 virtual-gateway-address 10.1.200.254
set interfaces irb unit 200 virtual-gateway-accept-data

# VRF for inter-VNI routing
set routing-instances TENANT-A instance-type vrf
set routing-instances TENANT-A route-distinguisher 10.0.0.11:100
set routing-instances TENANT-A vrf-target target:65001:100
set routing-instances TENANT-A interface irb.100
set routing-instances TENANT-A interface irb.200
set routing-instances TENANT-A routing-options auto-export

# EVPN
set protocols evpn encapsulation vxlan
set protocols evpn extended-vni-list all
set protocols evpn default-gateway do-not-advertise

# Access ports (server-facing)
set interfaces xe-0/0/0 unit 0 family ethernet-switching interface-mode access
set interfaces xe-0/0/0 unit 0 family ethernet-switching vlan members PROD
set interfaces xe-0/0/0 description "Server-A01-U20 eth0"
```

---

## 3. Verification Checklist

```junos
# 1. Underlay BGP
show bgp summary                                    # All peers ESTABLISHED?
show route protocol bgp                             # Loopbacks learned?
show route 10.0.0.12/32                            # Can reach other leaf loopbacks?
ping 10.0.0.12 source 10.0.0.11                    # VTEP-to-VTEP reachability?

# 2. Overlay EVPN
show bgp summary group EVPN-OVERLAY                 # EVPN session ESTABLISHED?
show evpn database                                   # MACs learned via EVPN?
show evpn instance                                   # EVPN instances active?

# 3. VXLAN tunnels
show ethernet-switching vxlan-tunnel-end-point remote # Remote VTEPs discovered?

# 4. MAC/IP learning
show ethernet-switching table                        # Local + remote MACs
show arp interface irb.100                           # ARP entries on gateway

# 5. End-to-end
# Ping from server on LEAF-01 to server on LEAF-02 (same VLAN, different rack)
```
