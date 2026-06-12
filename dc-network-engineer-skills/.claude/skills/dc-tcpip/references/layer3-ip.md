# Layer 3 — IP, Subnetting, ICMP, MTU

## 1. IPv4 Header

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|Version|  IHL  |    DSCP   |ECN|          Total Length         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|         Identification        |Flags|      Fragment Offset    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Time to Live |    Protocol   |         Header Checksum       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Source Address                          |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Destination Address                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Key Fields for Troubleshooting

| Field | Size | DC Relevance |
|---|---|---|
| **TTL** | 8 bits | Decrements at each hop. TTL=0 → packet dropped. Useful for traceroute. Default: 64 (Linux), 128 (Windows), 255 (network devices) |
| **Protocol** | 8 bits | 1=ICMP, 6=TCP, 17=UDP, 47=GRE, 89=OSPF |
| **DSCP** | 6 bits | QoS marking. Important for traffic prioritization in DC |
| **Total Length** | 16 bits | Max 65535 bytes. If > MTU, fragmentation occurs |
| **DF flag** | 1 bit | Don't Fragment. If set and packet > MTU → ICMP "need to frag" returned |

---

## 2. IP Addressing & Subnetting

### CIDR Notation Quick Reference

| CIDR | Netmask | Hosts | Use in DC |
|---|---|---|---|
| `/30` | 255.255.255.252 | 2 usable | Point-to-point links (spine↔leaf) |
| `/31` | 255.255.255.254 | 2 usable (RFC 3021) | Point-to-point links (preferred, no waste) |
| `/32` | 255.255.255.255 | 1 (host route) | Loopback addresses |
| `/27` | 255.255.255.224 | 30 usable | Small server VLANs |
| `/24` | 255.255.255.0 | 254 usable | Standard server VLANs |
| `/23` | 255.255.254.0 | 510 usable | Large server VLANs |
| `/22` | 255.255.252.0 | 1022 usable | Very large VLANs (avoid if possible) |
| `/16` | 255.255.0.0 | 65534 usable | Campus/site supernet |

### RFC 1918 Private Ranges

| Range | CIDR | Size | Typical DC Use |
|---|---|---|---|
| `10.0.0.0` – `10.255.255.255` | `10.0.0.0/8` | 16M addresses | **Primary DC range** — underlay, overlay, management |
| `172.16.0.0` – `172.31.255.255` | `172.16.0.0/12` | 1M addresses | Secondary / VPN / DMZ |
| `192.168.0.0` – `192.168.255.255` | `192.168.0.0/16` | 65K addresses | Lab / small deployments |

### DC IP Allocation Scheme (Standard IP Fabric)

| Network | CIDR | Purpose | Example |
|---|---|---|---|
| **Loopbacks** | `10.0.0.0/24` | Device loopback IPs (VTEP, router-id) | Spine: `10.0.0.1-4`, Leaf: `10.0.0.11-50` |
| **P2P underlay** | `10.0.1.0/24` | Point-to-point links (spine↔leaf) | Each link gets a `/31` |
| **Server VLANs** | `10.1.0.0/16` | Tenant/service VLANs | VLAN 100: `10.1.100.0/24` |
| **Management** | `10.255.0.0/24` | OOB management network | `10.255.0.1` = mgmt switch |
| **Infrastructure** | `10.254.0.0/24` | NTP, DNS, syslog, monitoring | `10.254.0.1` = NTP |

---

## 3. ICMP (Internet Control Message Protocol)

### Common ICMP Types

| Type | Code | Name | Meaning |
|---|---|---|---|
| 0 | 0 | **Echo Reply** | Ping response |
| 3 | 0 | **Destination Unreachable: Network** | No route to network |
| 3 | 1 | **Destination Unreachable: Host** | ARP failed / host down |
| 3 | 3 | **Destination Unreachable: Port** | UDP port closed |
| 3 | 4 | **Need to Fragment (DF set)** | Packet too large, DF flag set — **MTU issue** |
| 3 | 13 | **Administratively Prohibited** | Firewall/ACL blocking |
| 8 | 0 | **Echo Request** | Ping request |
| 11 | 0 | **Time Exceeded: TTL** | TTL reached 0 — used by traceroute |

### Ping on Juniper
```junos
ping 10.0.1.1 count 5 rapid                    # Quick ping test
ping 10.0.1.1 size 9000 do-not-fragment         # Test MTU (jumbo frame)
ping 10.0.1.1 source 10.0.0.11                  # Specify source IP
ping 10.0.1.1 routing-instance MGMT             # Ping from specific VRF
```

### Traceroute on Juniper
```junos
traceroute 10.0.2.1                             # Standard traceroute
traceroute 10.0.2.1 source 10.0.0.11            # From specific source
traceroute 10.0.2.1 as-number-lookup            # Show AS numbers (for internet paths)
```

---

## 4. MTU & Path MTU Discovery (PMTUD)

### MTU Chain in VXLAN DC

```
Server (MTU 1500) → Leaf (underlay MTU 9216) → Spine (underlay MTU 9216) → Leaf → Server
                         │                                                   │
                    VXLAN encap                                         VXLAN decap
                    adds 50 bytes                                       removes 50 bytes
                    Inner: 1500                                         Delivered: 1500
                    Outer: 1550
```

### MTU Values to Configure

| Interface Type | MTU | Reason |
|---|---|---|
| **Server-facing (access)** | 1500 (default) or 9000 (if server supports jumbo) | Match server NIC MTU |
| **Underlay (spine↔leaf)** | **9216** | Must accommodate VXLAN overhead (50 bytes) + jumbo frames |
| **IRB (gateway)** | 1500 or 9000 | Match the VLAN's server MTU |
| **Management** | 1500 | Standard |

### MTU Troubleshooting
```junos
# Check interface MTU
show interfaces xe-0/0/0 | match mtu

# Test with large ping (DF set)
ping 10.0.1.1 size 9000 do-not-fragment
# If this fails with "Message too long", there's an MTU mismatch in the path

# Check for PMTUD issues — look for ICMP type 3 code 4 being blocked
```

> **Common MTU issue**: If the underlay MTU is only 1500 and VXLAN is used, any inner packet > 1450 bytes will be dropped or fragmented. **Always set underlay MTU to 9216** in an IP Fabric.

---

## 5. IPv6 in DC (Overview)

### Why IPv6 in DC?
- Server applications increasingly use IPv6 (especially cloud-native)
- Dual-stack is common: IPv4 for underlay, IPv6 for some overlay services
- Link-local addresses (`fe80::/10`) are used automatically by many protocols

### Key IPv6 Addresses
| Address | Purpose |
|---|---|
| `::1/128` | Loopback |
| `fe80::/10` | Link-local (auto-configured on every interface) |
| `fc00::/7` (fd00::/8)| Unique Local Address (ULA) — private, like RFC 1918 |
| `2000::/3` | Global Unicast (public) |
| `ff02::1` | All nodes multicast |
| `ff02::2` | All routers multicast |

### Juniper IPv6
```junos
# Enable IPv6 on an interface
set interfaces xe-0/0/0 unit 0 family inet6 address 2001:db8::1/64

# Show IPv6 neighbors (equivalent of ARP table)
show ipv6 neighbors

# Show IPv6 routes
show route table inet6.0
```
