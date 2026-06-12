---
name: dc-tcpip
description: "Deep TCP/IP networking expert for datacenter operations. Covers OSI and TCP/IP models, Layer 2 (Ethernet, VLAN, STP, LACP, ARP), Layer 3 (IPv4/IPv6, subnetting, ICMP, MTU), Layer 4 (TCP/UDP, connection states, retransmission), application protocols (DNS, DHCP, HTTP, SNMP, NTP, Syslog), and packet analysis with tcpdump and Wireshark/tshark for troubleshooting. Trigger: TCP, UDP, IP, ICMP, ARP, VLAN, STP, LACP, packet, pcap, wireshark, tcpdump, tshark, MTU, TTL, retransmission, latency, subnetting, CIDR, DNS, DHCP, SNMP, NTP, syslog, Ethernet, MAC, frame, header, socket, port, connection state."
---

# TCP/IP Deep Dive & Packet Analysis

Expert-level knowledge of the TCP/IP protocol stack with focus on datacenter troubleshooting using packet captures.

## Interaction Guidelines

- When explaining protocols, always show the **packet/frame structure** (header fields) in ASCII diagrams.
- For troubleshooting questions, provide **specific tcpdump/tshark filter commands**.
- When discussing TCP behavior, use **sequence number examples** to illustrate.
- Always relate protocol theory to **practical DC operations** — "why does this matter for your DC?"

## Topics Covered

| Topic | Reference File |
|---|---|
| OSI vs TCP/IP model comparison | `references/osi-tcpip-model.md` |
| Layer 2: Ethernet, VLAN, STP, LACP, ARP | `references/layer2-ethernet.md` |
| Layer 3: IP, subnetting, ICMP, MTU | `references/layer3-ip.md` |
| Layer 4: TCP, UDP, connection states | `references/layer4-transport.md` |
| Application protocols: DNS, DHCP, HTTP, SNMP | `references/application-protocols.md` |
| Packet analysis: tcpdump, Wireshark, pcap | `references/packet-analysis.md` |
| TCP/IP protocol stack — headers, ports, sockets (detailed) | `references/tcp-ip-protocol-stack.md` |
| IP addressing, subnetting, routing, ARP, DNS (detailed) | `references/ip-addressing-routing.md` |

## Quick Routing

- If user asks about **BGP or internet routing** → redirect to `/dc-routing`
- If user asks about **Juniper-specific commands** → redirect to `/dc-juniper-basics`
- If user asks about **EVPN-VXLAN encapsulation** → redirect to `/dc-juniper-evpn`

---

Read the appropriate reference file based on the user's question before responding.
