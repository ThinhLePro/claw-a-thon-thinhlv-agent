# Quy Định: Giám Sát & Cảnh Báo (Monitoring & Alerting)

Quy định chuẩn về giám sát hạ tầng DC network và ngưỡng cảnh báo.

## 1. Monitoring Stack

| Layer | Tool | Mục đích |
|---|---|---|
| **SNMP Polling** | LibreNMS / Zabbix / PRTG | Interface utilization, CPU, memory, temperature |
| **Syslog** | Rsyslog → ELK / Graylog | Log aggregation, event correlation |
| **Flow** | sFlow / NetFlow → ntopng / Kentik | Traffic analysis, DDoS detection |
| **Streaming Telemetry** | gRPC → InfluxDB → Grafana | Real-time metrics |
| **Synthetic** | Smokeping / ThousandEyes | Latency, packet loss |

## 2. SNMP Configuration

### Junos SNMP Setup
```
set snmp description "<HOSTNAME> - <ROLE>"
set snmp location "<DC>-<ROOM>-<RACK>-<U>"
set snmp contact "noc@company.com"

# SNMPv2c (Legacy)
set snmp community <COMMUNITY> authorization read-only
set snmp community <COMMUNITY> clients <NMS_IP_1>/32
set snmp community <COMMUNITY> clients <NMS_IP_2>/32

# SNMPv3 (Recommended)
set snmp v3 usm local-engine user SNMPV3USER authentication-sha authentication-password <AUTH_PASS>
set snmp v3 usm local-engine user SNMPV3USER privacy-aes128 privacy-password <PRIV_PASS>
set snmp v3 vacm security-to-group security-model usm security-name SNMPV3USER group SNMPV3GROUP
set snmp v3 vacm access group SNMPV3GROUP default-context-prefix security-model usm security-level privacy read-view ALL
set snmp view ALL oid .1 include

# SNMP Traps
set snmp trap-group TRAPS version v2
set snmp trap-group TRAPS categories chassis
set snmp trap-group TRAPS categories link
set snmp trap-group TRAPS categories routing
set snmp trap-group TRAPS categories startup
set snmp trap-group TRAPS targets <TRAP_RECEIVER>
```

## 3. Syslog Configuration

### Junos Syslog
```
# Remote syslog
set system syslog host <SYSLOG_SERVER> any warning
set system syslog host <SYSLOG_SERVER> authorization info
set system syslog host <SYSLOG_SERVER> change-log info
set system syslog host <SYSLOG_SERVER> interactive-commands info
set system syslog host <SYSLOG_SERVER> daemon warning
set system syslog host <SYSLOG_SERVER> kernel warning
set system syslog host <SYSLOG_SERVER> firewall any
set system syslog host <SYSLOG_SERVER> structured-data
set system syslog host <SYSLOG_SERVER> source-address <LOOPBACK_IP>
set system syslog host <SYSLOG_SERVER> port 514

# Local file logging
set system syslog file messages any warning
set system syslog file messages authorization info
set system syslog file interactive-commands interactive-commands any
set system syslog file security authorization info
```

## 4. Alerting Thresholds

### Infrastructure Alerts

| Metric | Warning | Critical | Action |
|---|---|---|---|
| **CPU** | > 70% (5 min avg) | > 90% (5 min avg) | Check processes, consider upgrade |
| **Memory** | > 75% | > 90% | Check routing table, clear caches |
| **Temperature** | > 55°C | > 65°C | Check cooling, check fans |
| **Fan** | 1 fan fail | > 1 fan fail | Replace fan tray |
| **PSU** | 1 PSU fail | All PSU degraded | Replace PSU immediately |
| **Storage** | > 80% | > 95% | Clean logs, remove core dumps |

### Interface Alerts

| Metric | Warning | Critical | Action |
|---|---|---|---|
| **Utilization** | > 70% | > 85% | Capacity planning, add links |
| **Errors (CRC)** | > 10/hour | > 100/hour | Check cable, SFP, clean fiber |
| **Discards** | > 100/hour | > 1000/hour | Check QoS, buffer sizing |
| **Optical Rx** | < -10 dBm | < -14 dBm | Clean fiber, check SFP |
| **Optical Tx** | < -5 dBm | < -8 dBm | Replace SFP |
| **Flapping** | > 3/hour | > 10/hour | Check cable, disable auto-neg |

### Protocol Alerts

| Metric | Warning | Critical | Action |
|---|---|---|---|
| **BGP session down** | 1 peer down | > 1 peer down | Check link, check config |
| **BGP prefix count** | ±10% sudden change | ±30% sudden change | Check route leak, check filter |
| **OSPF adjacency** | 1 neighbor lost | Multiple lost | Check interface, check area config |
| **LACP member down** | 1 member | > 1 member | Check cable, check server NIC |
| **VXLAN tunnel down** | 1 VTEP unreachable | Multiple VTEPs | Check underlay, check loopback |

### Availability Alerts

| Metric | Warning | Critical |
|---|---|---|
| **Ping loss** | > 1% (5 min) | > 5% (5 min) |
| **Latency** | > 2ms (intra-DC) | > 10ms (intra-DC) |
| **Jitter** | > 1ms | > 5ms |

## 5. Dashboard Requirements

### NOC Overview Dashboard
- Tổng quan tất cả devices: UP/DOWN count
- Top 10 interfaces by utilization
- BGP session summary (Established vs Total)
- Recent alarms (last 24h)
- Fabric topology health map

### Per-Device Dashboard
- CPU / Memory / Temperature trends
- Interface utilization (all ports)
- BGP neighbor status
- EVPN database stats
- Error counters trend

### Capacity Dashboard
- Interface utilization trend (30 days)
- Port usage ratio (used / total / available)
- VLAN utilization
- Routing table growth trend

## 6. Monitoring Checklist for New Device

Khi thêm device mới, phải configure đầy đủ:
- [ ] SNMP community / SNMPv3 credentials
- [ ] Syslog forwarding
- [ ] NMS discovery (add to monitoring)
- [ ] Dashboard creation
- [ ] Alert rules configuration
- [ ] Synthetic monitoring (ping, traceroute)
- [ ] sFlow/NetFlow export (nếu applicable)

---
*Liên quan: [sop-incident-response.md](sop-incident-response.md) | [sop-maintenance.md](sop-maintenance.md)*
