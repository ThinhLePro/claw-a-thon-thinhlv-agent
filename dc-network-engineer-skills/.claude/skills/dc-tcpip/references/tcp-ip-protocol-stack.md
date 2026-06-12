# TCP/IP Protocol Stack — Comprehensive Reference

> Source: TCP/IP Network Administration, 3rd Ed — Craig Hunt (O'Reilly)

## TCP/IP Protocol Architecture (4-Layer Model)

```
┌─────────────────────────────────────┐
│      Application Layer              │  ← HTTP, DNS, SMTP, SSH, FTP, SNMP
├─────────────────────────────────────┤
│      Transport Layer                │  ← TCP, UDP
├─────────────────────────────────────┤
│      Internet Layer                 │  ← IP, ICMP, ARP, IGMP
├─────────────────────────────────────┤
│      Network Access Layer           │  ← Ethernet, 802.11, PPP, Frame Relay
└─────────────────────────────────────┘
```

### Layer Comparison with OSI

| TCP/IP Layer | OSI Layers | Function |
|---|---|---|
| **Application** | 5-7 (Session, Presentation, Application) | User services, data formatting |
| **Transport** | 4 (Transport) | End-to-end delivery, reliability |
| **Internet** | 3 (Network) | Addressing, routing, fragmentation |
| **Network Access** | 1-2 (Physical, Data Link) | Physical transmission, framing |

---

## Internet Layer Protocols

### IP (Internet Protocol v4)

**Characteristics**:
- **Connectionless**: No handshake before sending data
- **Unreliable**: No error detection/recovery (relies on upper layers)
- **Best-effort delivery**: Routes packets independently

**IP Datagram Header (20 bytes minimum)**:

| Field | Bits | Description |
|---|---|---|
| **Version** | 4 | IP version (4 for IPv4) |
| **IHL** | 4 | Header length in 32-bit words (min 5) |
| **Type of Service (ToS)** | 8 | QoS marking (DSCP + ECN in modern use) |
| **Total Length** | 16 | Entire datagram size in bytes (max 65535) |
| **Identification** | 16 | Fragment group identifier |
| **Flags** | 3 | DF (Don't Fragment), MF (More Fragments) |
| **Fragment Offset** | 13 | Position in fragmented datagram |
| **TTL** | 8 | Hop limit (decremented at each router) |
| **Protocol** | 8 | Upper-layer protocol (6=TCP, 17=UDP, 1=ICMP) |
| **Header Checksum** | 16 | Header integrity check |
| **Source Address** | 32 | Sender's IP address |
| **Destination Address** | 32 | Recipient's IP address |

### ICMP (Internet Control Message Protocol)

Used for network diagnostics and error reporting:

| Type | Code | Message | Use |
|---|---|---|---|
| 0 | 0 | Echo Reply | Response to ping |
| 3 | 0-15 | Destination Unreachable | Network/host/port unreachable |
| 5 | 0-3 | Redirect | Better route available |
| 8 | 0 | Echo Request | Ping |
| 11 | 0-1 | Time Exceeded | TTL expired (traceroute) |

### ARP (Address Resolution Protocol)

Maps IP addresses to MAC addresses on local network:

```
1. Host A needs MAC for 192.168.1.10
2. Host A broadcasts ARP Request: "Who has 192.168.1.10?"
3. Host with 192.168.1.10 replies: "I'm at AA:BB:CC:DD:EE:FF"
4. Host A caches the mapping in ARP table
```

```bash
# View ARP table
arp -a

# Clear ARP entry
arp -d 192.168.1.10
```

---

## Transport Layer Protocols

### TCP (Transmission Control Protocol)

**Characteristics**:
- **Connection-oriented**: 3-way handshake before data transfer
- **Reliable**: Sequencing, acknowledgments, retransmission
- **Stream-oriented**: Treats data as continuous byte stream
- **Flow control**: Sliding window mechanism

**3-Way Handshake**:
```
Client                    Server
  │                         │
  │── SYN (seq=x) ─────────→│
  │                         │
  │←── SYN-ACK (seq=y,ack=x+1)│
  │                         │
  │── ACK (ack=y+1) ────────→│
  │                         │
  │    Connection Established │
```

**TCP Header (20 bytes minimum)**:

| Field | Bits | Description |
|---|---|---|
| Source Port | 16 | Sender's port number |
| Destination Port | 16 | Recipient's port number |
| Sequence Number | 32 | Byte position in stream |
| Acknowledgment Number | 32 | Next expected byte |
| Data Offset | 4 | Header length |
| Flags | 6 | SYN, ACK, FIN, RST, PSH, URG |
| Window Size | 16 | Receiver's buffer capacity |
| Checksum | 16 | Header + data integrity |

**Connection Termination (4-way)**:
```
Client                    Server
  │── FIN ──────────────────→│
  │←── ACK ──────────────────│
  │←── FIN ──────────────────│
  │── ACK ──────────────────→│
```

### UDP (User Datagram Protocol)

**Characteristics**:
- **Connectionless**: No handshake
- **Unreliable**: No sequencing, no retransmission
- **Message-oriented**: Each send = one datagram
- **Low overhead**: 8-byte header only

**UDP Header (8 bytes)**:

| Field | Bits | Description |
|---|---|---|
| Source Port | 16 | Sender's port |
| Destination Port | 16 | Recipient's port |
| Length | 16 | Header + data length |
| Checksum | 16 | Integrity check (optional in IPv4) |

### TCP vs UDP

| Feature | TCP | UDP |
|---|---|---|
| Connection | Required (3-way handshake) | None |
| Reliability | Guaranteed (ACK, retransmit) | Best-effort |
| Ordering | Guaranteed (sequence numbers) | No guarantee |
| Overhead | High (20+ byte header) | Low (8 byte header) |
| Speed | Slower (connection + ACKs) | Faster (no overhead) |
| Use cases | HTTP, SSH, FTP, SMTP, BGP | DNS, SNMP, TFTP, VXLAN, syslog |

---

## Well-Known Ports

| Port | Protocol | Service |
|---|---|---|
| 20/21 | TCP | FTP (data/control) |
| 22 | TCP | SSH |
| 23 | TCP | Telnet |
| 25 | TCP | SMTP |
| 53 | TCP/UDP | DNS |
| 67/68 | UDP | DHCP (server/client) |
| 69 | UDP | TFTP |
| 80 | TCP | HTTP |
| 110 | TCP | POP3 |
| 123 | UDP | NTP |
| 143 | TCP | IMAP |
| 161/162 | UDP | SNMP (agent/trap) |
| 179 | TCP | BGP |
| 443 | TCP | HTTPS |
| 514 | UDP | Syslog |
| 520 | UDP | RIP |
| 830 | TCP | NETCONF |
| 4789 | UDP | VXLAN |

---

## Sockets

A **socket** = IP address + port number. A socket pair uniquely identifies a connection:

```
(Source IP : Source Port) ↔ (Dest IP : Dest Port)
(192.168.1.10 : 45321) ↔ (203.0.113.5 : 443)
```

- Ports 0-1023: **Well-known** (privileged, requires root)
- Ports 1024-49151: **Registered** (assigned by IANA)
- Ports 49152-65535: **Dynamic/Ephemeral** (client-side)
