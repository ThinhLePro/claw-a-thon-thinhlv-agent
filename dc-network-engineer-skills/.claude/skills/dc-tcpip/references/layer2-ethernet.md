# Layer 2 — Ethernet, VLAN, STP, LACP, ARP

## 1. Ethernet Frame Structure

```
┌──────────┬──────────┬──────────┬──────────┬──────────────────────┬─────┐
│ Preamble │ Dest MAC │ Src MAC  │ Type/Len │      Payload         │ FCS │
│ 8 bytes  │ 6 bytes  │ 6 bytes  │ 2 bytes  │   46-1500 bytes      │4 B  │
└──────────┴──────────┴──────────┴──────────┴──────────────────────┴─────┘
```

### 802.1Q VLAN Tagged Frame
```
┌──────────┬──────────┬──────┬──────────┬──────────────────────┬─────┐
│ Dest MAC │ Src MAC  │ TPID │EtherType │      Payload         │ FCS │
│ 6 bytes  │ 6 bytes  │ 4 B  │ 2 bytes  │   46-1500 bytes      │4 B  │
└──────────┴──────────┴──────┴──────────┴──────────────────────┴─────┘
                        │
                  ┌─────┴─────┐
                  │ TPID=0x8100│  ← Identifies as VLAN-tagged
                  │ PRI (3b)  │  ← 802.1p priority (CoS)
                  │ DEI (1b)  │  ← Drop Eligible Indicator
                  │ VID (12b) │  ← VLAN ID (0-4095)
                  └───────────┘
```

### Key EtherType Values
| EtherType | Protocol |
|---|---|
| `0x0800` | IPv4 |
| `0x0806` | ARP |
| `0x86DD` | IPv6 |
| `0x8100` | 802.1Q VLAN tag |
| `0x88A8` | 802.1ad QinQ (S-Tag) |
| `0x8847` | MPLS |

---

## 2. MAC Addressing

### Format
`AA:BB:CC:DD:EE:FF` (6 bytes = 48 bits)
- First 3 bytes: **OUI** (Organizationally Unique Identifier) — identifies manufacturer
- Last 3 bytes: **NIC** — unique per device

### Special Addresses
| Address | Purpose |
|---|---|
| `FF:FF:FF:FF:FF:FF` | Broadcast — all devices in the VLAN |
| `01:80:C2:00:00:00` | STP BPDUs |
| `01:80:C2:00:00:0E` | LLDP |
| `01:00:5E:xx:xx:xx` | IPv4 Multicast |
| `33:33:xx:xx:xx:xx` | IPv6 Multicast |

### MAC Table on Juniper
```junos
show ethernet-switching table          # Show MAC address table
show ethernet-switching table vlan 100 # Filter by VLAN
show ethernet-switching table interface xe-0/0/1  # Filter by port
show ethernet-switching table count    # Count MACs per VLAN
```

---

## 3. VLAN (Virtual LAN — 802.1Q)

### Concepts
- **Access port**: Belongs to one VLAN, frames sent untagged
- **Trunk port**: Carries multiple VLANs, frames sent tagged (802.1Q)
- **Native VLAN**: Untagged traffic on a trunk is assigned this VLAN (default: VLAN 1 — change it!)
- **VLAN range**: 1-4094 (VLAN 0 reserved, VLAN 4095 reserved)

### Juniper VLAN Configuration
```junos
# Create VLAN
set vlans PRODUCTION vlan-id 100
set vlans MANAGEMENT vlan-id 200

# Access port (server-facing)
set interfaces xe-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces xe-0/0/1 unit 0 family ethernet-switching vlan members PRODUCTION

# Trunk port (switch-to-switch)
set interfaces xe-0/0/10 unit 0 family ethernet-switching interface-mode trunk
set interfaces xe-0/0/10 unit 0 family ethernet-switching vlan members [PRODUCTION MANAGEMENT]
set interfaces xe-0/0/10 native-vlan-id 999  # Set native VLAN (don't use VLAN 1)
```

### QinQ (802.1ad) — Double Tagging
Used in service provider / multi-tenant DC environments:
```
[Outer S-Tag (provider VLAN)][Inner C-Tag (customer VLAN)][Payload]
```

---

## 4. STP (Spanning Tree Protocol)

### Purpose
Prevents **Layer 2 loops** (broadcast storms, MAC flapping, duplicate frames) in networks with redundant paths.

### Variants
| Protocol | Standard | Convergence | VLAN Support | Recommended |
|---|---|---|---|---|
| STP | 802.1D | 30-50 sec | Single instance | ❌ Legacy |
| RSTP | 802.1w | 1-5 sec | Single instance | ⚠️ Basic |
| MSTP | 802.1s | 1-5 sec | Multiple instances | ⚠️ Complex |
| VSTP | Juniper proprietary | 1-5 sec | Per-VLAN (like PVST+) | ✅ Juniper DC |

### STP Port States (RSTP)
| State | Forwards? | Learns MAC? | Description |
|---|---|---|---|
| **Discarding** | No | No | Port blocked or initializing |
| **Learning** | No | Yes | Learning MACs, not yet forwarding |
| **Forwarding** | Yes | Yes | Active, normal operation |

### STP in Modern DC (IP Fabric)
> **Important**: In EVPN-VXLAN IP Fabric designs, **STP is typically NOT used on underlay (L3)** interfaces. STP only applies to **L2 segments** (access/server-facing VLANs at the leaf). The leaf switch is the STP root bridge for its directly connected L2 segments.

### Juniper STP Commands
```junos
show spanning-tree bridge                    # Bridge ID, root info
show spanning-tree interface                 # Port roles and states
show spanning-tree mstp configuration        # MSTP region config
```

---

## 5. LACP (Link Aggregation Control Protocol — 802.3ad)

### Purpose
Bundles multiple physical links into a single logical link (LAG / AE interface) for:
- **Increased bandwidth** (aggregate throughput)
- **Redundancy** (if one link fails, others continue)

### LACP Modes
| Mode | Behavior |
|---|---|
| **Active** | Actively sends LACPDU to negotiate with partner |
| **Passive** | Responds to LACPDU but doesn't initiate |
| **Force-up** (static/no LACP) | No LACP, link assumed up — **not recommended** |

> **Best practice**: Always use **LACP active** on both sides. Detect misconfigurations immediately.

### Juniper AE Configuration
```junos
# Create aggregated Ethernet interface
set chassis aggregated-devices ethernet device-count 10

# Assign physical interfaces to ae0
set interfaces xe-0/0/0 ether-options 802.3ad ae0
set interfaces xe-0/0/1 ether-options 802.3ad ae0

# Configure ae0
set interfaces ae0 aggregated-ether-options lacp active
set interfaces ae0 aggregated-ether-options lacp periodic fast  # Fast timers (1 sec)
set interfaces ae0 unit 0 family ethernet-switching interface-mode trunk
set interfaces ae0 unit 0 family ethernet-switching vlan members [PRODUCTION MANAGEMENT]
```

### Load Balancing
```junos
# Configure hash algorithm for LAG load balancing
set forwarding-options hash-key family inet layer-3
set forwarding-options hash-key family inet layer-4
# Adds L4 (port) to hash — better distribution for many flows between same IP pair
```

### Verification
```junos
show lacp interfaces                    # LACP status per interface
show lacp statistics interfaces ae0     # LACPDU counters
show interfaces ae0 extensive           # Aggregate stats
show interfaces ae0 | match "Link"      # Member link status
```

---

## 6. ARP (Address Resolution Protocol)

### Purpose
Resolves **IPv4 address → MAC address** mapping within the same L2 broadcast domain.

### How It Works
```
1. Host A wants to reach 10.0.1.50 but doesn't know its MAC
2. Host A sends ARP Request (broadcast): "Who has 10.0.1.50? Tell 10.0.1.10"
3. Host B (10.0.1.50) responds: "10.0.1.50 is at aa:bb:cc:dd:ee:ff"
4. Host A caches the mapping in its ARP table
```

### ARP Table on Juniper
```junos
show arp                              # Full ARP table
show arp hostname                     # With DNS resolution
show arp interface irb.100            # ARP for a specific IRB interface
show arp no-resolve | match 10.0.1    # Filter by subnet, no DNS lookup
```

### ARP Issues in DC
| Issue | Cause | Fix |
|---|---|---|
| ARP storm | Too many hosts in one VLAN, broadcast amplification | Limit VLAN size, use `/24` or smaller subnets |
| ARP timeout | Device ARP entry expires faster than neighbor's | Align ARP timeout on both ends |
| Gratuitous ARP flood | VM migration, VRRP failover | Expected behavior — monitor rate |
| ARP spoofing | Malicious or misconfigured host | Enable DAI (Dynamic ARP Inspection), DHCP snooping |

> **EVPN note**: In EVPN-VXLAN, **ARP suppression** allows the VTEP (leaf switch) to answer ARP requests locally from its EVPN database, reducing broadcast traffic across the VXLAN overlay. See `/dc-juniper-evpn` for details.

---

## 7. LLDP (Link Layer Discovery Protocol)

### Purpose
Discovers directly connected neighbors. Essential for DC operations — verifying cabling matches documentation.

### Juniper LLDP
```junos
# Enable LLDP (usually enabled by default)
set protocols lldp interface all

# View neighbors
show lldp neighbors              # Summary: port, neighbor name, neighbor port
show lldp neighbors interface xe-0/0/0  # Specific port
show lldp local-information      # What this device advertises

# Very useful for cable verification:
# "Is xe-0/0/0 really connected to SPINE-01 xe-0/0/3?" → check LLDP
```
