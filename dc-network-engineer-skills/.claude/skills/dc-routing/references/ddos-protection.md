# DDoS Protection Network

## 1. DDoS Attack Types

| Category | Examples | Target Layer | Volume |
|---|---|---|---|
| **Volumetric** | UDP flood, ICMP flood, DNS amplification, NTP amplification | L3/L4 | High (Gbps-Tbps) |
| **Protocol** | SYN flood, TCP RST flood, fragmentation attack | L4 | Medium |
| **Application** | HTTP flood, Slowloris, DNS query flood | L7 | Low volume but high impact |

---

## 2. DDoS Mitigation Techniques in DC

### RTBH (Remote Triggered Black Hole)

**What**: Announce the attacked IP with a special community to upstream ISPs, causing them to **drop all traffic to that IP** at their edge — before it reaches your network.

**Pros**: Immediate, simple, effective for volumetric attacks
**Cons**: Drops ALL traffic to the target IP (legitimate + malicious) — essentially takes the target offline

```
Normal traffic flow:
Internet → ISP → Your Edge → Target Server

During RTBH:
Internet → ISP (drops traffic here) ✗→ Your Edge ✗→ Target Server
```

### Juniper RTBH Configuration

```junos
# 1. Define blackhole community (agreed with ISP — e.g., ISP uses 7552:666)
set policy-options community BLACKHOLE members 65001:666

# 2. Static route to discard (null route)
set routing-options static route 203.0.113.100/32 discard
set routing-options static route 203.0.113.100/32 tag 666
set routing-options static route 203.0.113.100/32 no-readvertise

# 3. Policy to redistribute blackhole routes to ISPs
set policy-options policy-statement EXPORT-BLACKHOLE term BH from tag 666
set policy-options policy-statement EXPORT-BLACKHOLE term BH then community add BLACKHOLE
set policy-options policy-statement EXPORT-BLACKHOLE term BH then next-hop 192.0.2.1  # RFC 5635 discard next-hop
set policy-options policy-statement EXPORT-BLACKHOLE term BH then accept

# 4. Apply to BGP export (combined with normal export)
set protocols bgp group ISP-TRANSIT export [ EXPORT-BLACKHOLE EXPORT-TO-ISP ]

# To activate blackhole for an IP under attack:
set routing-options static route <attacked-ip>/32 discard tag 666
commit

# To remove blackhole:
delete routing-options static route <attacked-ip>/32
commit
```

### Destination-Based vs Source-Based RTBH

| Type | What Gets Blocked | Use Case |
|---|---|---|
| **Destination RTBH** | All traffic TO the attacked IP | Sacrifice one IP to save the network |
| **Source RTBH** (uRPF-based) | All traffic FROM the attacker IP | Block known attacker source (requires ISP support + uRPF) |

---

### BGP Flowspec (RFC 5575)

**What**: Granular traffic filtering distributed via BGP. Instead of blackholing an entire IP, you can drop/rate-limit traffic matching specific criteria (src/dst IP, protocol, port, packet size, etc.).

**Pros**: Surgical — block only attack traffic, not legitimate
**Cons**: Requires ISP support, more complex to implement

### Juniper Flowspec Configuration

```junos
# Enable flowspec on BGP
set protocols bgp group ISP-TRANSIT family inet flow

# Create a flow route (example: block UDP floods to port 53 on our DNS server)
set routing-options flow route BLOCK-DNS-FLOOD match destination 203.0.113.53/32
set routing-options flow route BLOCK-DNS-FLOOD match protocol udp
set routing-options flow route BLOCK-DNS-FLOOD match destination-port 53
set routing-options flow route BLOCK-DNS-FLOOD match packet-length 512-65535  # Large DNS responses (amplification)
set routing-options flow route BLOCK-DNS-FLOOD then discard

# Rate-limit instead of block
set routing-options flow route RATELIMIT-NTP match destination 203.0.113.0/24
set routing-options flow route RATELIMIT-NTP match protocol udp
set routing-options flow route RATELIMIT-NTP match source-port 123  # NTP amplification
set routing-options flow route RATELIMIT-NTP then rate-limit 1m     # Limit to 1 Mbps
```

### Flowspec Verification
```junos
show route table inetflow.0                        # Active flow routes
show firewall filter __flowspec_default_inet__      # Auto-generated firewall filter
```

---

### Scrubbing Center

**What**: An external (or on-premise) service that receives diverted traffic, removes malicious packets, and forwards clean traffic back to your network.

```
Normal: Internet → ISP → Your Edge → Servers

Under attack (with scrubbing):
Internet → ISP → Scrubbing Center → Clean traffic → Your Edge → Servers
                     ↓
              Malicious traffic dropped
```

### Integration Methods

| Method | How | Latency Impact |
|---|---|---|
| **BGP diversion** | Announce attacked prefix via scrubber's AS, scrubber returns clean traffic via GRE/direct link | Moderate (traffic detours) |
| **DNS diversion** | Change DNS to point to scrubber | Only works for HTTP/DNS-based services |
| **Inline** | Scrubber sits physically inline | Minimal (always-on) |

---

## 3. On-Device Protection (Edge Router)

### Firewall Filters for Control Plane Protection (CoPP)

Protect the router's CPU from DoS:

```junos
# Rate-limit common attack vectors hitting the router itself
set firewall filter PROTECT-RE term ALLOW-BGP from protocol tcp
set firewall filter PROTECT-RE term ALLOW-BGP from port bgp
set firewall filter PROTECT-RE term ALLOW-BGP from source-prefix-list BGP-NEIGHBORS
set firewall filter PROTECT-RE term ALLOW-BGP then accept

set firewall filter PROTECT-RE term ALLOW-OSPF from protocol ospf
set firewall filter PROTECT-RE term ALLOW-OSPF then accept

set firewall filter PROTECT-RE term ALLOW-SSH from protocol tcp
set firewall filter PROTECT-RE term ALLOW-SSH from destination-port ssh
set firewall filter PROTECT-RE term ALLOW-SSH from source-prefix-list MGMT-NETWORKS
set firewall filter PROTECT-RE term ALLOW-SSH then accept

set firewall filter PROTECT-RE term ALLOW-ICMP from protocol icmp
set firewall filter PROTECT-RE term ALLOW-ICMP then policer ICMP-POLICER
set firewall filter PROTECT-RE term ALLOW-ICMP then accept

set firewall filter PROTECT-RE term RATE-LIMIT-ALL then policer DEFAULT-POLICER
set firewall filter PROTECT-RE term RATE-LIMIT-ALL then accept

# Apply to loopback (protects RE)
set interfaces lo0 unit 0 family inet filter input PROTECT-RE

# Define policers
set firewall policer ICMP-POLICER if-exceeding bandwidth-limit 1m burst-size-limit 15k
set firewall policer ICMP-POLICER then discard

set firewall policer DEFAULT-POLICER if-exceeding bandwidth-limit 5m burst-size-limit 50k
set firewall policer DEFAULT-POLICER then discard
```

---

## 4. DDoS Detection & Response Workflow

```
1. DETECTION
   ├─ Monitoring alerts: unusual traffic spike on edge interfaces (Cacti/Grafana)
   ├─ ISP notification: upstream ISP detects volumetric attack
   ├─ Application team: service degradation reported
   └─ Automated: flow analysis (NetFlow/sFlow) detects anomaly

2. IDENTIFICATION
   ├─ What is being attacked? (dst IP, dst port)
   ├─ What type of attack? (volumetric, protocol, application)
   ├─ What is the attack volume? (bps, pps)
   └─ Source IPs? (single source or distributed)

3. MITIGATION (escalating)
   ├─ Level 1: On-device firewall filter (for small, targeted attacks)
   ├─ Level 2: BGP Flowspec (for medium attacks, if ISP supports)
   ├─ Level 3: RTBH (for large volumetric attacks — sacrifice target IP)
   ├─ Level 4: Scrubbing center diversion (for sustained attacks)
   └─ Level 5: ISP upstream filtering (request ISP to filter at their edge)

4. VERIFICATION
   ├─ Traffic volume returned to normal?
   ├─ Service restored?
   ├─ No collateral damage (legitimate traffic not blocked)?
   └─ Monitor for attack resumption

5. POST-INCIDENT
   ├─ Document: attack vector, duration, mitigation applied
   ├─ Review: could detection be faster? Mitigation more surgical?
   └─ Update: firewall rules, flowspec templates, playbooks
```

> **Key principle**: Start with the **least disruptive** mitigation and escalate only if needed. RTBH is the nuclear option — it blocks ALL traffic, including legitimate. Use flowspec or scrubbing when possible to maintain service availability.
