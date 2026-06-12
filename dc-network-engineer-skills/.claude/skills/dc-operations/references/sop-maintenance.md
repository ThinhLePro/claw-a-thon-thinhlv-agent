# Quy Định: Bảo Trì Định Kỳ (Scheduled Maintenance)

Quy định và quy trình bảo trì định kỳ cho hệ thống DC network.

## 1. Lịch Bảo Trì

### Bảo trì hàng ngày (Automated)
| Thời gian | Task | Phương thức |
|---|---|---|
| 00:00 | Backup running config | Script tự động |
| 06:00 | Health check report | NMS auto-report |
| Liên tục | Syslog monitoring | SIEM real-time |

### Bảo trì hàng tuần
| Thời gian | Task | Người thực hiện |
|---|---|---|
| Thứ 2, 09:00 | Review weekly health report | NOC |
| Thứ 4, 10:00 | Review capacity utilization | Network Engineer |
| Thứ 7, 01:00-05:00 | Maintenance window (nếu có CR) | Network Engineer |

### Bảo trì hàng tháng
| Tuần | Task |
|---|---|
| Tuần 1 | Firmware vulnerability scan |
| Tuần 2 | Interface error report & cleanup |
| Tuần 3 | Capacity planning review |
| Tuần 4 | Configuration compliance audit |

### Bảo trì hàng quý
| Q | Task |
|---|---|
| Mỗi quý | Firmware upgrade (nếu cần) |
| Mỗi quý | DR drill / Failover test |
| Mỗi quý | Security audit |
| Mỗi quý | Cable plant inspection |

## 2. Health Check Commands

### Daily Health Check Script
```
# System health
show chassis alarms
show chassis environment
show chassis routing-engine
show system alarms
show system storage

# Interface health
show interfaces terse | match "down" | except "\.0"
show interfaces error-summary

# Protocol health
show bgp summary | match "Estab|Active"
show ospf neighbor | match "Full"
show lacp interfaces | match "Active|Down"
show evpn database summary

# Performance
show chassis forwarding-table summary
show pfe statistics traffic

# Logs
show log messages | last 50 | match "error|warning|critical"
```

### Interface Error Check
```
# Kiểm tra CRC, input/output errors
show interfaces extensive | match "Physical|CRC|Input errors|Output errors|Framing"

# Kiểm tra optical levels
show interfaces diagnostics optics | match "interface|Laser|Module"

# Kiểm tra flapping
show log messages | match "LINK|SNMP_TRAP_LINK" | last 100
```

### Threshold Alert Levels

| Metric | Warning | Critical |
|---|---|---|
| CPU utilization | > 70% | > 90% |
| Memory utilization | > 75% | > 90% |
| Storage utilization | > 80% | > 95% |
| Interface utilization | > 70% | > 85% |
| Optical Rx power | < -10 dBm | < -14 dBm |
| CRC errors | > 10/hour | > 100/hour |
| Temperature | > 55°C | > 65°C |

## 3. Configuration Backup

### Tự động (Recommended)
```bash
#!/bin/bash
# backup_configs.sh — chạy qua cron daily
DEVICES="switch1 switch2 switch3"
BACKUP_DIR="/backup/network/$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR

for DEVICE in $DEVICES; do
    ssh netops@$DEVICE "show configuration | display set" > "$BACKUP_DIR/${DEVICE}.conf"
    # So sánh với backup hôm trước
    diff "$BACKUP_DIR/${DEVICE}.conf" "/backup/network/$(date -d yesterday +%Y%m%d)/${DEVICE}.conf" > "$BACKUP_DIR/${DEVICE}.diff" 2>/dev/null
done
```

### Thủ công
```
# Trên switch
show configuration | save /var/tmp/backup_$(hostname)_$(date +%Y%m%d).conf

# Rescue configuration
request system configuration rescue save
```

### Retention Policy
| Loại | Giữ lại |
|---|---|
| Daily backup | 30 ngày |
| Weekly backup | 12 tuần |
| Monthly backup | 12 tháng |
| Pre-change backup | Vĩnh viễn |

## 4. Firmware Management

### Quy trình upgrade
1. **Check release notes** — security fixes, bug fixes, known issues
2. **Test trên lab** — verify compatibility
3. **Backup config** trước khi upgrade
4. **Schedule maintenance window**
5. **Upgrade từng thiết bị** (rolling upgrade)
6. **Verify** sau mỗi upgrade

### Firmware Upgrade Commands
```
# Download firmware
request system software add /var/tmp/<firmware.tgz> no-validate reboot

# Dual RE upgrade
request system software add /var/tmp/<firmware.tgz> re0
request system software add /var/tmp/<firmware.tgz> re1

# ISSU (In-Service Software Upgrade) — nếu supported
request system software in-service-upgrade /var/tmp/<firmware.tgz>

# Verify
show version
show system software
show chassis hardware
```

## 5. Cable Plant Maintenance

### Kiểm tra hàng quý
- [ ] Fiber patch panel: clean connectors
- [ ] DAC/AOC cables: kiểm tra bending radius
- [ ] Cable management: verify labeling
- [ ] Optical power levels: log và compare trend
- [ ] Spare cable inventory: verify counts

---
*Liên quan: [sop-change-management.md](sop-change-management.md) | [sop-monitoring.md](sop-monitoring.md)*
