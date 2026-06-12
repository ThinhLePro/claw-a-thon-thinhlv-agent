# JunOS Routing — OSPF, BGP, Static & Aggregate Routes

## 1. Static Routes

```junos
# Basic static route
set routing-options static route 10.1.0.0/16 next-hop 10.0.1.1

# Discard route (null route / blackhole)
set routing-options static route 10.1.0.0/16 discard

# Static route with preference (lower = preferred, default static = 5)
set routing-options static route 0.0.0.0/0 next-hop 10.0.1.1 preference 10

# No-readvertise (don't redistribute into dynamic routing)
set routing-options static route 0.0.0.0/0 next-hop 10.0.1.1 no-readvertise

# Qualified next-hop (backup path)
set routing-options static route 0.0.0.0/0 next-hop 10.0.1.1 preference 5
set routing-options static route 0.0.0.0/0 qualified-next-hop 10.0.2.1 preference 10

# BFD-tracked static route
set routing-options static route 10.1.0.0/16 next-hop 10.0.1.1 bfd-liveness-detection minimum-interval 300 multiplier 3
```

## 2. Aggregate Routes

Aggregate routes summarize multiple specific routes into one broader announcement:

```junos
# Aggregate route (only active if contributing routes exist)
set routing-options aggregate route 10.1.0.0/16

# With policy to control which contributors are included
set routing-options aggregate route 10.1.0.0/16 policy CONTRIBUTOR-FILTER

# As-path for the aggregate (used in BGP announcements)
set routing-options aggregate route 10.1.0.0/16 as-path path "65001"

# Aggregate generates a discard route + is redistributable via BGP
```

## 3. OSPF (Open Shortest Path First)

### Basic OSPF Configuration
```junos
set routing-options router-id 10.0.0.11          # Must be unique

set protocols ospf area 0.0.0.0 interface xe-0/0/0.0    # Backbone area
set protocols ospf area 0.0.0.0 interface xe-0/0/1.0
set protocols ospf area 0.0.0.0 interface lo0.0 passive  # Loopback = passive

# Point-to-point (for /31 links — avoids DR/BDR election)
set protocols ospf area 0.0.0.0 interface xe-0/0/0.0 interface-type p2p

# BFD for fast convergence
set protocols ospf area 0.0.0.0 interface xe-0/0/0.0 bfd-liveness-detection minimum-interval 300
set protocols ospf area 0.0.0.0 interface xe-0/0/0.0 bfd-liveness-detection multiplier 3

# Authentication
set protocols ospf area 0.0.0.0 interface xe-0/0/0.0 authentication md5 1 key "OspfKey123"

# Reference bandwidth (for proper cost calculation at high speeds)
set protocols ospf reference-bandwidth 100g      # Set to highest link speed in network
```

### OSPF Areas
| Area | Type | Description |
|---|---|---|
| 0.0.0.0 (Area 0) | Backbone | All areas must connect to Area 0 |
| Stub | Stub | No external routes (replaced with default) |
| NSSA | Not-So-Stubby | Like stub, but allows local external redistribution |
| Totally Stubby | Totally Stub | No external + no inter-area summaries (default only) |

### OSPF Verification
```junos
show ospf neighbor                         # Adjacencies (must show FULL)
show ospf interface                        # OSPF-enabled interfaces
show ospf database                         # Link-State Database
show ospf route                            # OSPF-derived routes
show ospf statistics                       # Packet counters
show ospf neighbor detail                  # Detailed adjacency info
```

## 4. BGP Configuration

### eBGP (External BGP)
```junos
set routing-options autonomous-system 65001
set routing-options router-id 10.0.0.11

set protocols bgp group EBGP-UNDERLAY type external
set protocols bgp group EBGP-UNDERLAY family inet unicast
set protocols bgp group EBGP-UNDERLAY export EXPORT-LOOPBACK
set protocols bgp group EBGP-UNDERLAY multipath multiple-as    # ECMP

# Neighbor with specific peer-AS
set protocols bgp group EBGP-UNDERLAY neighbor 10.0.1.0 peer-as 65000

# BFD for fast failover
set protocols bgp group EBGP-UNDERLAY bfd-liveness-detection minimum-interval 300
set protocols bgp group EBGP-UNDERLAY bfd-liveness-detection multiplier 3
```

### iBGP (Internal BGP)
```junos
set protocols bgp group IBGP-OVERLAY type internal
set protocols bgp group IBGP-OVERLAY local-address 10.0.0.11   # Loopback IP
set protocols bgp group IBGP-OVERLAY family evpn signaling      # For EVPN overlay
set protocols bgp group IBGP-OVERLAY neighbor 10.0.0.1          # Route reflector (spine)
set protocols bgp group IBGP-OVERLAY neighbor 10.0.0.2          # Route reflector (spine)
```

### BGP Address Families
| Family | Use |
|---|---|
| `inet unicast` | IPv4 routes |
| `inet6 unicast` | IPv6 routes |
| `evpn signaling` | EVPN (MAC/IP routes) |
| `inet-vpn unicast` | L3VPN (MPLS) |
| `route-target` | RT filtering |
| `inet flow` | BGP Flowspec |

## 5. BFD (Bidirectional Forwarding Detection)

BFD provides sub-second failure detection for routing protocols:

```junos
# BFD on OSPF interface
set protocols ospf area 0 interface xe-0/0/0.0 bfd-liveness-detection minimum-interval 300
set protocols ospf area 0 interface xe-0/0/0.0 bfd-liveness-detection multiplier 3
# Detection time = 300ms × 3 = 900ms

# BFD on BGP
set protocols bgp group UNDERLAY bfd-liveness-detection minimum-interval 300
set protocols bgp group UNDERLAY bfd-liveness-detection multiplier 3

# Verification
show bfd session                            # All BFD sessions
show bfd session extensive                  # Detailed stats
show bfd session address 10.0.1.0           # Specific session
```

### BFD Timers
| Interval | × Multiplier | Detection Time | Use Case |
|---|---|---|---|
| 300ms × 3 | 900ms | Standard DC (recommended) |
| 100ms × 3 | 300ms | Aggressive (higher CPU) |
| 1000ms × 3 | 3s | Conservative (WAN links) |

> **DC recommendation**: 300ms × 3 = 900ms detection. Fast enough for sub-second failover without excessive CPU load on the routing engine.
