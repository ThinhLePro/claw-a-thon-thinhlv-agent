# Packet Analysis — tcpdump, Wireshark & tshark

## 1. tcpdump Cheat Sheet

### Basic Capture
```bash
# Capture on interface eth0, 100 packets
tcpdump -i eth0 -c 100

# Capture and save to pcap file
tcpdump -i eth0 -c 1000 -w /tmp/capture.pcap

# Read a pcap file
tcpdump -r /tmp/capture.pcap

# Verbose output with timestamps
tcpdump -i eth0 -nn -vv -tttt
```

### Important Flags
| Flag | Meaning |
|---|---|
| `-i <iface>` | Interface to capture on (`any` for all) |
| `-c <count>` | Stop after N packets |
| `-w <file>` | Write to pcap file |
| `-r <file>` | Read from pcap file |
| `-nn` | Don't resolve hostnames or port names (faster, clearer) |
| `-v` / `-vv` / `-vvv` | Increasing verbosity |
| `-tttt` | Full timestamp with date |
| `-s <snaplen>` | Capture N bytes per packet (`-s 0` = full packet) |
| `-e` | Show Ethernet header (MAC addresses) |
| `-X` | Show hex + ASCII dump |
| `-A` | Show ASCII dump (for HTTP inspection) |

### Capture Filters (BPF syntax — applied at capture time)

```bash
# By host
tcpdump -i eth0 host 10.0.1.100
tcpdump -i eth0 src host 10.0.1.100
tcpdump -i eth0 dst host 10.0.1.100

# By network
tcpdump -i eth0 net 10.0.1.0/24

# By port
tcpdump -i eth0 port 80
tcpdump -i eth0 src port 22
tcpdump -i eth0 portrange 8000-9000

# By protocol
tcpdump -i eth0 tcp
tcpdump -i eth0 udp
tcpdump -i eth0 icmp
tcpdump -i eth0 arp

# Combinations
tcpdump -i eth0 'host 10.0.1.100 and port 443'
tcpdump -i eth0 'src host 10.0.1.100 and dst port 80'
tcpdump -i eth0 '(host 10.0.1.100 or host 10.0.1.200) and port 22'
tcpdump -i eth0 'tcp[tcpflags] & (tcp-syn|tcp-fin) != 0'  # SYN or FIN packets only

# VXLAN traffic (UDP port 4789)
tcpdump -i eth0 'udp port 4789' -s 0 -w vxlan.pcap

# BGP traffic
tcpdump -i eth0 'tcp port 179'

# ARP only
tcpdump -i eth0 arp

# ICMP only (ping, unreachable, etc.)
tcpdump -i eth0 icmp
```

### On Juniper Devices
```junos
# Juniper uses 'monitor traffic' instead of tcpdump
monitor traffic interface xe-0/0/0
monitor traffic interface xe-0/0/0 matching "host 10.0.1.100"
monitor traffic interface xe-0/0/0 matching "port 179" detail
monitor traffic interface xe-0/0/0 write-file /var/tmp/capture.pcap size 10m count 1000

# Copy pcap file off the device
# From another machine:
scp user@switch:/var/tmp/capture.pcap .
```

---

## 2. Wireshark / tshark

### tshark (Command-Line Wireshark)

```bash
# Read pcap file with display filters
tshark -r capture.pcap

# Apply display filter
tshark -r capture.pcap -Y "tcp.analysis.retransmission"
tshark -r capture.pcap -Y "http.response.code == 500"
tshark -r capture.pcap -Y "ip.addr == 10.0.1.100 && tcp.port == 443"

# Show specific fields
tshark -r capture.pcap -T fields -e ip.src -e ip.dst -e tcp.port -e tcp.flags.str

# Statistics
tshark -r capture.pcap -z conv,tcp        # TCP conversations
tshark -r capture.pcap -z io,stat,1       # Packets per second
tshark -r capture.pcap -z endpoints,ip    # Top talkers
```

### Essential Wireshark Display Filters

| Filter | Purpose |
|---|---|
| `tcp.analysis.retransmission` | TCP retransmissions (packet loss) |
| `tcp.analysis.fast_retransmission` | Fast retransmissions (3 dup ACKs) |
| `tcp.analysis.duplicate_ack` | Duplicate ACKs (out-of-order or loss) |
| `tcp.analysis.zero_window` | Receiver buffer full (application slow) |
| `tcp.analysis.window_full` | Sender limited by receiver window |
| `tcp.analysis.reset` | TCP RST (connection reset) |
| `tcp.flags.syn == 1 && tcp.flags.ack == 0` | SYN packets only (new connections) |
| `tcp.flags.fin == 1` | FIN packets (connection close) |
| `dns` | DNS queries and responses |
| `icmp.type == 3` | ICMP Destination Unreachable |
| `arp` | ARP requests and replies |
| `vxlan` | VXLAN encapsulated traffic |
| `bgp` | BGP messages |
| `frame.len > 1518` | Jumbo frames / oversized |
| `tcp.stream eq 5` | Follow specific TCP stream |

---

## 3. Common Troubleshooting Patterns

### Pattern 1: TCP Retransmissions (Packet Loss)

**Symptoms**: Slow application, timeouts, intermittent connectivity

**tcpdump capture**:
```bash
tcpdump -i eth0 -nn -w retransmit.pcap 'host 10.0.1.100 and port 443' -c 10000
```

**Analysis in tshark**:
```bash
# Count retransmissions
tshark -r retransmit.pcap -Y "tcp.analysis.retransmission" | wc -l

# Show retransmissions with timestamps
tshark -r retransmit.pcap -Y "tcp.analysis.retransmission" -T fields -e frame.time -e ip.src -e ip.dst -e tcp.seq
```

**What to check**:
1. Which direction has retransmissions? (client→server or server→client)
2. Is loss random or bursty? (bursty = congestion; random = bad link)
3. Check interface error counters: `show interfaces xe-0/0/0 extensive | match "error|CRC|drop"`

---

### Pattern 2: TCP RST (Connection Reset)

**Symptoms**: "Connection refused", abrupt disconnection

**Analysis**:
```bash
tshark -r capture.pcap -Y "tcp.flags.reset == 1" -T fields -e frame.time -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport
```

**Common causes**:
| Source of RST | Meaning |
|---|---|
| Server sends RST after SYN | Port closed / service not running |
| Firewall sends RST | Connection blocked by security policy |
| Server sends RST during session | Application crash, timeout, or intentional close |
| RST after idle period | Firewall session timeout (stateful inspection) |

---

### Pattern 3: TCP Window Zero (Application Backpressure)

**Symptoms**: Slow throughput, application appears stuck

**Analysis**:
```bash
tshark -r capture.pcap -Y "tcp.analysis.zero_window" -T fields -e frame.time -e ip.src -e tcp.window_size
```

**Meaning**: The **receiver** is telling the sender to stop — its receive buffer is full. The application is not reading data fast enough.

**Fix**: Investigate the receiving application (slow processing, disk I/O, database bottleneck).

---

### Pattern 4: DNS Resolution Failures

**Capture DNS only**:
```bash
tcpdump -i eth0 -nn port 53 -w dns.pcap -c 500
```

**Analysis**:
```bash
# Show DNS queries and responses
tshark -r dns.pcap -Y "dns" -T fields -e frame.time -e ip.src -e dns.qry.name -e dns.flags.rcode

# NXDOMAIN responses (name not found)
tshark -r dns.pcap -Y "dns.flags.rcode == 3"

# Slow DNS (response > 100ms after query)
tshark -r dns.pcap -Y "dns.time > 0.1"
```

---

### Pattern 5: ARP Issues

**Capture ARP**:
```bash
tcpdump -i eth0 arp -nn -e -c 100
```

**What to look for**:
- **ARP Request with no Reply**: Target host is down or in different VLAN
- **Gratuitous ARP**: Host announcing its own IP→MAC mapping (normal during failover, suspicious if excessive)
- **ARP from unexpected MAC**: Possible ARP spoofing or duplicate IP

---

## 4. Packet Capture Best Practices

### DO
- Always use `-nn` (no DNS/port name resolution) — faster and avoids DNS-induced artifacts
- Capture with `-s 0` (full packet) when analyzing application data
- Write to file (`-w`) for detailed analysis — don't try to read everything in real-time
- Apply capture filters to reduce noise (e.g., filter by host or port)
- Capture on **both ends** simultaneously when troubleshooting — compare to identify where loss occurs

### DON'T
- Don't capture for too long without a filter — disk fills up quickly at high speed
- Don't capture on production interfaces without a packet limit (`-c`) or file size limit
- Don't capture plaintext credentials (SNMP v1/v2 community strings, HTTP basic auth) — handle pcap files securely
- Don't leave `monitor traffic` running indefinitely on a Juniper device — it consumes CPU

### Capture File Management
```bash
# Rotate captures: 10 files × 100MB each
tcpdump -i eth0 -w /tmp/capture.pcap -C 100 -W 10

# Compress old captures
gzip /tmp/capture.pcap

# Merge multiple captures
mergecap -w merged.pcap capture1.pcap capture2.pcap
```

> **DC tip**: When troubleshooting intermittent issues, set up a rolling capture on the relevant interface with rotation (`-C -W`), then trigger the issue and analyze the pcap afterward. This is much more effective than trying to catch the issue live.
