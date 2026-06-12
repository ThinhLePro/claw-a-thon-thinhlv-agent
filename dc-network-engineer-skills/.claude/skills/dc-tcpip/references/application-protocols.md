# Application Layer Protocols in DC Operations

## 1. DNS (Domain Name System)

### Port: 53 (UDP for queries, TCP for zone transfers and large responses)

### How DNS Works in DC
```
Server app → "resolve api.internal.example.com"
  → Local resolver (/etc/resolv.conf) → Recursive DNS server (DC internal)
    → If cached: return immediately
    → If not: query root → TLD → authoritative → cache → return
```

### DC DNS Architecture
- **Internal DNS**: Resolves internal hostnames (servers, services, management IPs)
- **External DNS**: Resolves public names (for outbound traffic)
- **Split DNS**: Internal queries go to internal DNS; external queries go to external DNS

### DNS Troubleshooting
```bash
# Basic lookup
dig api.internal.example.com
nslookup api.internal.example.com

# Query specific DNS server
dig @10.254.0.53 api.internal.example.com

# Check DNS response time
dig api.internal.example.com | grep "Query time"

# Reverse DNS lookup
dig -x 10.0.1.100

# Check SOA (Start of Authority)
dig SOA example.com
```

### Common DNS Issues in DC
| Issue | Cause | Fix |
|---|---|---|
| Slow DNS resolution | DNS server overloaded, network latency | Add caching, check DNS server health |
| NXDOMAIN for internal names | Wrong DNS server configured, zone not loaded | Check `/etc/resolv.conf`, verify zone config |
| DNS timeout | DNS server unreachable, firewall blocking UDP/53 | Check route, firewall rules |

---

## 2. DHCP (Dynamic Host Configuration Protocol)

### Ports: 67 (server), 68 (client) — UDP

### DHCP Process (DORA)
```
Client                          Server
  │──── DISCOVER (broadcast) ──→ │  "I need an IP"
  │←──── OFFER ──────────────── │  "Here's 10.0.1.100/24"
  │──── REQUEST ───────────────→ │  "I'll take 10.0.1.100"
  │←──── ACK ───────────────── │  "Confirmed, lease for 24h"
```

### DHCP Relay in DC
Servers in different VLANs need DHCP from a centralized server. The leaf switch acts as DHCP relay:

```junos
# Juniper DHCP relay configuration
set forwarding-options dhcp-relay group SERVERS interface irb.100
set forwarding-options dhcp-relay group SERVERS interface irb.200
set forwarding-options dhcp-relay server-group DHCP-SERVERS 10.254.0.10
set forwarding-options dhcp-relay active-server-group DHCP-SERVERS
```

### DHCP Troubleshooting on Juniper
```junos
show dhcp relay binding                          # Active DHCP leases via relay
show dhcp relay statistics                       # DHCP packet counters
show log messages | match dhcp                   # DHCP-related log entries
```

---

## 3. NTP (Network Time Protocol)

### Port: 123 — UDP

### Why NTP Matters in DC
- **Log correlation**: Timestamps must be synchronized across all devices for incident investigation
- **Certificate validation**: TLS certificates are time-sensitive
- **BGP/OSPF**: Some protocol timers are sensitive to clock drift
- **Compliance**: Audit logs require accurate timestamps

### NTP Architecture in DC
```
Stratum 0: GPS/atomic clock
    ↓
Stratum 1: DC NTP servers (e.g., 10.254.0.123, 10.254.0.124)
    ↓
Stratum 2: All network devices + servers → sync from DC NTP servers
```

### Juniper NTP Configuration
```junos
set system ntp server 10.254.0.123 prefer
set system ntp server 10.254.0.124
set system ntp source-address 10.255.0.11    # Use management IP as source
```

### NTP Verification
```junos
show ntp associations                    # NTP peers and sync status
show ntp status                          # Clock offset, stratum
show system uptime                       # System clock
```

| Field | Meaning |
|---|---|
| `*` prefix | Currently synced peer |
| `+` prefix | Candidate peer (good quality) |
| `offset` | Time difference (ms) — should be < 10ms in DC |
| `stratum` | Distance from reference clock (lower = better) |

---

## 4. SNMP (Simple Network Management Protocol)

### Ports: 161 (polling), 162 (traps) — UDP

### SNMP Versions
| Version | Auth | Encryption | Use in DC |
|---|---|---|---|
| **v1** | Community string (plaintext) | None | ❌ Legacy, avoid |
| **v2c** | Community string (plaintext) | None | ⚠️ Common but insecure |
| **v3** | Username + auth (MD5/SHA) | DES/AES | ✅ Recommended |

### SNMP in DC Operations
- **Polling (GET)**: Monitoring tools (Cacti, CheckMK, LibreNMS) poll devices every 5 min for interface counters, CPU, memory
- **Traps (TRAP/INFORM)**: Devices send unsolicited alerts to monitoring server (link down, fan fail, etc.)

### Juniper SNMP Configuration
```junos
# SNMPv2c (basic — for Cacti/CheckMK polling)
set snmp community "READONLY-COMMUNITY" authorization read-only
set snmp community "READONLY-COMMUNITY" clients 10.254.0.0/24  # Restrict to monitoring subnet

# SNMPv3 (secure)
set snmp v3 usm local-engine user monitor authentication-sha authentication-password "AuthPass123"
set snmp v3 usm local-engine user monitor privacy-aes128 privacy-password "PrivPass456"
set snmp v3 vacm access group monitor-group default-context-prefix security-model usm security-level privacy read-view all

# Trap target
set snmp trap-group MONITORING targets 10.254.0.50
set snmp trap-group MONITORING categories link
set snmp trap-group MONITORING categories chassis
```

### Key SNMP OIDs for Network Monitoring
| OID | Description |
|---|---|
| `.1.3.6.1.2.1.2.2.1.10` | ifInOctets (interface input bytes) |
| `.1.3.6.1.2.1.2.2.1.16` | ifOutOctets (interface output bytes) |
| `.1.3.6.1.2.1.2.2.1.8` | ifOperStatus (1=up, 2=down) |
| `.1.3.6.1.4.1.2636.3.1.13` | Juniper CPU utilization |
| `.1.3.6.1.4.1.2636.3.1.15` | Juniper memory utilization |

---

## 5. Syslog

### Port: 514 — UDP (or TCP for reliable syslog)

### Syslog Severity Levels
| Level | Name | Description |
|---|---|---|
| 0 | Emergency | System unusable |
| 1 | Alert | Immediate action required |
| 2 | Critical | Critical conditions |
| 3 | Error | Error conditions |
| 4 | Warning | Warning conditions |
| 5 | Notice | Normal but significant |
| 6 | Informational | Informational messages |
| 7 | Debug | Debug-level messages |

### Juniper Syslog Configuration
```junos
# Send to remote syslog server
set system syslog host 10.254.0.51 any warning
set system syslog host 10.254.0.51 authorization info
set system syslog host 10.254.0.51 interactive-commands info
set system syslog host 10.254.0.51 source-address 10.255.0.11

# Local file logging
set system syslog file messages any warning
set system syslog file messages authorization info
set system syslog file interactive-commands interactive-commands any
```

### View Logs on Juniper
```junos
show log messages                           # Main log file
show log messages | last 50                 # Last 50 lines
show log messages | match "error|warning"   # Filter by pattern
show log messages | match "xe-0/0/0"        # Filter by interface
monitor start messages                      # Live log streaming (Ctrl+C to stop)
```

---

## 6. SSH (Secure Shell)

### Port: 22 — TCP

### SSH in DC Operations
- **Primary management protocol** — used for all CLI access to network devices
- **Key-based auth preferred** over password (more secure, automatable)
- **Jump host**: Access production devices through a bastion/jump host, never directly from the internet

### Juniper SSH Configuration
```junos
# Enable SSH
set system services ssh protocol-version v2
set system services ssh rate-limit 5                    # Max 5 connections per minute
set system services ssh connection-limit 10             # Max concurrent sessions
set system services ssh root-login deny                 # Never allow root SSH

# SSH key authentication
set system login user netops class super-user
set system login user netops authentication ssh-rsa "ssh-rsa AAAA..."
```

### SSH Best Practices for DC
1. **Use SSH keys** — disable password auth where possible
2. **Jump host** — all device access through a managed bastion
3. **Session logging** — record all SSH sessions for audit
4. **Idle timeout** — disconnect idle sessions after 15 min
5. **Rate limiting** — prevent brute force attempts
