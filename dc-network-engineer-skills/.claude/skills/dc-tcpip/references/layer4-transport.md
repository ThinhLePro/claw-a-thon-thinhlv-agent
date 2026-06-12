# Layer 4 — TCP & UDP Deep Dive

## 1. TCP Header

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Source Port          |       Destination Port        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        Sequence Number                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Acknowledgment Number                      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Data |       |C|E|U|A|P|R|S|F|                               |
| Offset| Rsvd  |W|C|R|C|S|S|Y|I|            Window             |
|       |       |R|E|G|K|H|T|N|N|                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           Checksum            |         Urgent Pointer        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### TCP Flags
| Flag | Name | Meaning |
|---|---|---|
| **SYN** | Synchronize | Initiate connection (3-way handshake step 1 & 2) |
| **ACK** | Acknowledge | Acknowledges received data |
| **FIN** | Finish | Graceful connection close |
| **RST** | Reset | Abrupt connection termination (error, port closed, firewall reject) |
| **PSH** | Push | Send data immediately (don't buffer) |
| **URG** | Urgent | Urgent data pointer is valid |
| **CWR** | Congestion Window Reduced | Sender reduced its sending rate |
| **ECE** | ECN Echo | Congestion experienced notification |

---

## 2. TCP 3-Way Handshake

```
Client                          Server
  │                                │
  │──── SYN (seq=100) ──────────→ │  Step 1: Client initiates
  │                                │
  │←── SYN-ACK (seq=300,ack=101)──│  Step 2: Server acknowledges + syncs
  │                                │
  │──── ACK (seq=101,ack=301) ──→ │  Step 3: Client acknowledges
  │                                │
  │        Connection ESTABLISHED  │
```

### Connection Teardown (4-Way)
```
Client                          Server
  │──── FIN ────────────────────→ │  Client done sending
  │←──── ACK ───────────────────  │  Server acknowledges
  │←──── FIN ───────────────────  │  Server done sending
  │──── ACK ────────────────────→ │  Client acknowledges
  │        Connection CLOSED       │
```

---

## 3. TCP Connection States

| State | Description | Common in DC Troubleshooting |
|---|---|---|
| `LISTEN` | Server waiting for connections | Normal — service is running |
| `SYN_SENT` | Client sent SYN, waiting for SYN-ACK | If stuck here: firewall blocking, server not listening |
| `SYN_RECEIVED` | Server received SYN, sent SYN-ACK | If many stuck here: possible SYN flood (DDoS) |
| `ESTABLISHED` | Connection active, data flowing | Normal |
| `FIN_WAIT_1` | Initiator sent FIN, waiting for ACK | Closing connection |
| `FIN_WAIT_2` | Initiator got ACK for FIN, waiting for peer's FIN | Waiting for other side |
| `TIME_WAIT` | Connection closed, waiting 2×MSL before socket reuse | If many: high connection churn (short-lived connections) |
| `CLOSE_WAIT` | Received FIN from peer, waiting for app to close | If many: application not closing sockets — **bug** |
| `LAST_ACK` | Sent FIN, waiting for final ACK | Closing |

### Check Connection States (Linux)
```bash
# Count connections by state
ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn

# Or with netstat
netstat -ant | awk '{print $6}' | sort | uniq -c | sort -rn
```

### Troubleshooting by State
| Many connections in state | Likely cause | Action |
|---|---|---|
| `SYN_SENT` | Remote host not responding, firewall blocking | Check route, firewall, target service |
| `SYN_RECEIVED` | SYN flood attack or slow application accept() | Check DDoS, tune backlog |
| `TIME_WAIT` | Many short-lived connections (e.g., HTTP 1.0) | Normal for high-traffic servers, tune `tcp_tw_reuse` |
| `CLOSE_WAIT` | Application not closing sockets | **Application bug** — fix the app |
| `ESTABLISHED` (too many) | Connection leak or legitimate high load | Check application connection pooling |

---

## 4. TCP Retransmission & Congestion

### Retransmission
When a TCP segment is lost (no ACK received within RTO), the sender retransmits it.

**Key indicators in packet capture**:
- **Retransmission**: Same data re-sent after timeout
- **Fast Retransmission**: Triggered by 3 duplicate ACKs (faster recovery)
- **Duplicate ACK**: Receiver says "I got packet N but I'm still waiting for packet M"
- **Spurious Retransmission**: Retransmit of already-ACKed data (often MTU/timing issue)

### Window Size
- **Receive Window (rwnd)**: How much data the receiver can buffer
- **Congestion Window (cwnd)**: How much data the sender thinks the network can handle
- **Effective window**: `min(rwnd, cwnd)` — actual sending rate
- **Window Zero**: Receiver's buffer is full — sender must stop until window opens

### Congestion Control Algorithms
| Algorithm | Description | Common in |
|---|---|---|
| **Cubic** | Default Linux, aggressive | Linux servers |
| **BBR** | Google's, bandwidth-based | Google, high-latency links |
| **New Reno** | Classic, conservative | Older systems |

---

## 5. UDP (User Datagram Protocol)

### UDP Header
```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Source Port          |       Destination Port        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|            Length             |           Checksum            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### TCP vs UDP

| Feature | TCP | UDP |
|---|---|---|
| Connection | Connection-oriented (handshake) | Connectionless |
| Reliability | Guaranteed delivery (ACK, retransmit) | Best effort (no ACK) |
| Ordering | Ordered delivery | No ordering guarantee |
| Flow control | Window-based | None |
| Overhead | Higher (20+ byte header) | Lower (8 byte header) |
| Use in DC | HTTP, SSH, database, API calls | DNS, NTP, SNMP, syslog, **VXLAN**, TFTP |

> **DC critical**: VXLAN uses **UDP port 4789** as the transport for overlay encapsulation. Understanding UDP behavior is essential for VXLAN troubleshooting.

---

## 6. Common Port Numbers in DC

| Port | Protocol | Service | DC Context |
|---|---|---|---|
| 22 | TCP | SSH | Device management, jump host |
| 23 | TCP | Telnet | Legacy (avoid — unencrypted) |
| 53 | TCP/UDP | DNS | Name resolution |
| 67/68 | UDP | DHCP | Server IP assignment |
| 69 | UDP | TFTP | Device firmware/config transfer |
| 80 | TCP | HTTP | Web management, monitoring |
| 123 | UDP | NTP | Time synchronization |
| 161/162 | UDP | SNMP | Monitoring (polling / traps) |
| 179 | TCP | BGP | Routing peering sessions |
| 443 | TCP | HTTPS | Secure web management |
| 514 | UDP | Syslog | Log collection |
| 830 | TCP | NETCONF | Juniper automation |
| 4789 | UDP | VXLAN | VXLAN overlay encapsulation |
| 6784 | TCP | BFD (multihop) | Bidirectional Forwarding Detection |
