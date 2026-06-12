# OSI vs TCP/IP Model

## Side-by-Side Comparison

```
   OSI Model (7 layers)          TCP/IP Model (4 layers)       DC Relevance
┌─────────────────────┐      ┌─────────────────────────┐
│ 7. Application      │      │                         │
│ 6. Presentation     │ ───→ │ 4. Application          │   DNS, DHCP, HTTP, SNMP, NTP
│ 5. Session          │      │    (HTTP, DNS, SSH...)   │   Syslog, SSH, TFTP
│─────────────────────│      │─────────────────────────│
│ 4. Transport        │ ───→ │ 3. Transport            │   TCP (reliable), UDP (fast)
│                     │      │    (TCP, UDP)            │   Port numbers, connection states
│─────────────────────│      │─────────────────────────│
│ 3. Network          │ ───→ │ 2. Internet             │   IP addressing, routing
│                     │      │    (IP, ICMP, ARP*)      │   Subnetting, TTL, fragmentation
│─────────────────────│      │─────────────────────────│
│ 2. Data Link        │ ───→ │ 1. Network Access       │   Ethernet, VLAN, MAC addresses
│ 1. Physical         │      │    (Ethernet, WiFi...)   │   Cables, connectors, signals
└─────────────────────┘      └─────────────────────────┘
```

*Note: ARP is sometimes considered L2/L3 boundary. In TCP/IP model, it sits in the Network Access layer but resolves L3→L2 mappings.*

## PDU (Protocol Data Unit) at Each Layer

| OSI Layer | PDU Name | Key Identifiers | DC Example |
|---|---|---|---|
| 7-5. Application | Data / Message | URL, hostname | `GET /health HTTP/1.1` |
| 4. Transport | **Segment** (TCP) / **Datagram** (UDP) | Port number (src, dst) | `:443` (HTTPS), `:22` (SSH) |
| 3. Network | **Packet** | IP address (src, dst) | `10.0.1.100 → 10.0.2.50` |
| 2. Data Link | **Frame** | MAC address (src, dst), VLAN | `aa:bb:cc:dd:ee:ff`, VLAN 100 |
| 1. Physical | **Bits** | Voltage, light, radio | 10GBASE-SR, Cat6a |

## Encapsulation Process

```
Application data:   [HTTP GET /health]
                         ↓ + TCP header
TCP segment:        [TCP HDR][HTTP GET /health]
                         ↓ + IP header
IP packet:          [IP HDR][TCP HDR][HTTP GET /health]
                         ↓ + Ethernet header + trailer
Ethernet frame:     [ETH HDR][IP HDR][TCP HDR][HTTP GET /health][FCS]
                         ↓ + preamble
On the wire:        [PREAMBLE][ETH HDR][IP HDR][TCP HDR][DATA][FCS]
```

## Maximum Frame/Packet Sizes

| Type | MTU | Total Frame | Use in DC |
|---|---|---|---|
| Standard Ethernet | 1500 bytes | 1518 bytes (+ 4 VLAN = 1522) | Default |
| Jumbo frames | 9000 bytes | 9018 bytes | Storage (iSCSI), NFS, VXLAN underlay |
| Baby giant | 1600 bytes | 1618 bytes | VXLAN (adds 50-byte header to standard frames) |

> **DC critical**: VXLAN adds a 50-byte overhead (outer Ethernet 14 + outer IP 20 + UDP 8 + VXLAN 8). For standard 1500-byte inner payload to pass through VXLAN without fragmentation, the **underlay MTU must be ≥ 1550** (preferably **9000** / jumbo frames). This is why IP Fabric designs typically enable jumbo frames on all underlay interfaces.
