# IP Addressing, Subnetting & Routing — Reference

> Source: TCP/IP Network Administration, 3rd Ed — Craig Hunt (O'Reilly)

## IP Address Structure

An IPv4 address is **32 bits**, written as four decimal octets (dotted-decimal notation):

```
192.168.1.100  =  11000000.10101000.00000001.01100100
```

### Address Classes (Historical — pre-CIDR)

| Class | Leading Bits | Network Bits | Host Bits | Range | Networks | Hosts/Network |
|---|---|---|---|---|---|---|
| **A** | 0 | 8 | 24 | 1.0.0.0 – 126.255.255.255 | 126 | ~16.7M |
| **B** | 10 | 16 | 16 | 128.0.0.0 – 191.255.255.255 | 16,384 | 65,534 |
| **C** | 110 | 24 | 8 | 192.0.0.0 – 223.255.255.255 | 2,097,152 | 254 |
| **D** | 1110 | — | — | 224.0.0.0 – 239.255.255.255 | Multicast | — |
| **E** | 1111 | — | — | 240.0.0.0 – 255.255.255.255 | Reserved | — |

> **Note**: Classful addressing is largely obsolete. Modern networks use **CIDR** (Classless Inter-Domain Routing).

### Special Addresses

| Address | Purpose |
|---|---|
| **0.0.0.0/8** | "This network" (default route, DHCP) |
| **10.0.0.0/8** | Private (RFC 1918) |
| **127.0.0.0/8** | Loopback |
| **169.254.0.0/16** | Link-local (auto-configured) |
| **172.16.0.0/12** | Private (RFC 1918) |
| **192.168.0.0/16** | Private (RFC 1918) |
| **224.0.0.0/4** | Multicast |
| **255.255.255.255** | Limited broadcast |

---

## CIDR and Subnetting

### CIDR Notation

```
192.168.1.0/24  →  24 bits for network, 8 bits for hosts
                    Subnet mask: 255.255.255.0
                    Usable hosts: 2^8 - 2 = 254
```

### Common Subnet Masks

| CIDR | Mask | Hosts | Use Case |
|---|---|---|---|
| /30 | 255.255.255.252 | 2 | Point-to-point links |
| /31 | 255.255.255.254 | 2 | Point-to-point (RFC 3021) |
| /27 | 255.255.255.224 | 30 | Small server subnet |
| /24 | 255.255.255.0 | 254 | Standard LAN subnet |
| /22 | 255.255.252.0 | 1022 | Large server farm |
| /20 | 255.255.240.0 | 4094 | DC leaf subnet |
| /16 | 255.255.0.0 | 65534 | Campus segment |

### Subnetting Formula

```
Usable hosts = 2^(32 - prefix_length) - 2

Subnet address = first address (network ID)
Broadcast address = last address
First usable = subnet + 1
Last usable = broadcast - 1

Example: 10.1.100.0/24
  Subnet:    10.1.100.0
  First:     10.1.100.1
  Last:      10.1.100.254
  Broadcast: 10.1.100.255
```

### Subnet Calculation Quick Reference

| /prefix | # Subnets (from /24) | Hosts per Subnet | Increment |
|---|---|---|---|
| /25 | 2 | 126 | 128 |
| /26 | 4 | 62 | 64 |
| /27 | 8 | 30 | 32 |
| /28 | 16 | 14 | 16 |
| /29 | 32 | 6 | 8 |
| /30 | 64 | 2 | 4 |

---

## Routing Fundamentals

### Routing Decision Logic

```
For each packet:
1. Extract destination IP from packet header
2. Look up in routing table (longest prefix match)
3. If match found → forward to next-hop or interface
4. If no match → use default route (0.0.0.0/0)
5. If no default → drop packet (ICMP Destination Unreachable)
```

### Routing Table Fields

| Field | Description |
|---|---|
| **Destination** | Network prefix to match |
| **Gateway/Next-hop** | IP of next router (0.0.0.0 = directly connected) |
| **Genmask/Prefix** | Subnet mask for the destination |
| **Interface** | Outgoing network interface |
| **Metric** | Cost/priority (lower = preferred) |
| **Flags** | U=up, G=gateway, H=host, S=static |

### Types of Routes

| Route Type | Description | Example |
|---|---|---|
| **Direct** | Directly connected network | 10.1.1.0/24 via eth0 |
| **Static** | Manually configured | 10.2.0.0/16 via 10.1.1.1 |
| **Default** | Catch-all route | 0.0.0.0/0 via 10.1.1.1 |
| **Dynamic** | Learned via routing protocol | via OSPF, BGP |

---

## Routing Protocols

### Interior Gateway Protocols (IGP)

For routing **within** an autonomous system (AS):

| Protocol | Type | Metric | Convergence | Use Case |
|---|---|---|---|---|
| **RIP** | Distance-vector | Hop count (max 15) | Slow | Small networks, legacy |
| **OSPF** | Link-state | Cost (bandwidth-based) | Fast | Enterprise, SP, DC underlay |
| **IS-IS** | Link-state | Metric (configurable) | Fast | SP backbone, large DC |
| **EIGRP** | Hybrid | Composite (BW, delay) | Fast | Cisco-only environments |

### Exterior Gateway Protocol (EGP)

**BGP (Border Gateway Protocol)** — for routing **between** autonomous systems:

| Feature | Description |
|---|---|
| **Protocol** | TCP port 179 |
| **Type** | Path-vector |
| **Metric** | AS path, local preference, MED, etc. |
| **Use in DC** | eBGP for underlay (leaf↔spine), iBGP for overlay (EVPN) |

### BGP in DC (IP Fabric)

```
Spine AS 65000          Spine AS 65000
    │                       │
    │ eBGP                  │ eBGP
    │                       │
Leaf AS 65001          Leaf AS 65002
```

- Each leaf gets unique AS number (or uses ASN override)
- eBGP on point-to-point /31 links between leaf and spine
- ECMP across all spine paths
- EVPN address family for MAC/IP route distribution

---

## Address Resolution Protocol (ARP)

### ARP Process

```
1. Host checks ARP cache for target MAC
2. If not found → broadcast ARP Request (ff:ff:ff:ff:ff:ff)
3. Target responds with ARP Reply (unicast)
4. Host caches result (typical timeout: 300s)
```

### ARP Table Commands

```bash
# Linux
arp -a                          # Show ARP table
ip neigh show                   # Modern equivalent
ip neigh flush all              # Clear ARP cache

# Junos
show arp                        # Show ARP table
show arp interface irb.100      # Show ARP for specific interface
clear arp                       # Clear ARP cache
```

### Proxy ARP
- Router answers ARP requests **on behalf of** hosts on other networks
- Allows hosts without a default gateway to reach remote networks
- In EVPN-VXLAN: leaf switches answer ARP from EVPN database (ARP suppression)

---

## DNS (Domain Name System)

### DNS Hierarchy

```
. (root)
├── com
│   ├── example.com
│   │   ├── www.example.com
│   │   └── mail.example.com
│   └── google.com
├── net
├── org
└── io
```

### DNS Record Types

| Record | Purpose | Example |
|---|---|---|
| **A** | IPv4 address | www.example.com → 93.184.216.34 |
| **AAAA** | IPv6 address | www.example.com → 2606:2800:220:1:... |
| **CNAME** | Alias | blog.example.com → www.example.com |
| **MX** | Mail server | example.com → mail.example.com (pri 10) |
| **NS** | Name server | example.com → ns1.example.com |
| **PTR** | Reverse lookup | 34.216.184.93 → www.example.com |
| **SOA** | Zone authority | Primary NS, admin email, serial, timers |
| **SRV** | Service location | _sip._tcp.example.com → sip.example.com |
| **TXT** | Text data | SPF records, domain verification |

### DNS Resolution Types

| Type | Description |
|---|---|
| **Recursive** | Server follows all pointers and returns final answer |
| **Iterative** | Server returns best known answer or referral |

### DNS Server Types

| Type | Description |
|---|---|
| **Master (Primary)** | Authoritative, loads zone from file |
| **Slave (Secondary)** | Authoritative, receives zone via transfer |
| **Caching-only** | Non-authoritative, caches answers from others |
| **Forwarder** | Forwards queries to upstream resolver |
