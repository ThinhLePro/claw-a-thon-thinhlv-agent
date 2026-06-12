# Quy Định: Xử Lý Sự Cố (Incident Response)

Quy trình chuẩn xử lý sự cố hạ tầng DC network.

## 1. Phân Loại Sự Cố

| Severity | Mô tả | Response Time | Resolution Target |
|---|---|---|---|
| **P1 — Critical** | Mất kết nối toàn DC, core switch down, fabric failure | 5 phút | 1 giờ |
| **P2 — High** | Mất kết nối 1 rack, spine down, MC-LAG failover failure | 15 phút | 2 giờ |
| **P3 — Medium** | 1 server mất kết nối, LACP partial, single link down | 30 phút | 4 giờ |
| **P4 — Low** | CRC errors tăng, optical degradation, non-critical alarm | 2 giờ | Next business day |

## 2. Escalation Matrix

```
┌─────────┐   5 phút    ┌──────────┐   15 phút   ┌────────────┐
│  NOC    │────────────▶│ Network  │────────────▶│ Team Lead  │
│  L1     │             │ Engineer │             │ Senior NE  │
│         │             │ L2       │             │ L3         │
└─────────┘             └──────────┘             └─────┬──────┘
                                                       │ 30 phút
                                                 ┌─────▼──────┐
                                                 │ Manager /  │
                                                 │ Vendor TAC │
                                                 └────────────┘
```

| Severity | L1 (NOC) | L2 (Network Engineer) | L3 (Senior NE / Manager) |
|---|---|---|---|
| P1 | Notify ngay | On-call join ngay | Auto-escalate 15 phút |
| P2 | Notify ngay | Respond 15 phút | Escalate nếu 30 phút chưa resolve |
| P3 | Tạo ticket | Respond 30 phút | Escalate theo request |
| P4 | Tạo ticket | Schedule fix | Review weekly |

## 3. Incident Response Procedure

### Phase 1: Detection & Triage (0-5 phút)

```
# 1. Xác nhận scope of impact
show chassis alarms
show system alarms
show interfaces terse | match "down"
show bgp summary | match "Active|Connect"

# 2. Xác nhận severity
# P1: Multiple devices/services affected
# P2: Single device or single service affected
# P3: Single interface or single server

# 3. Notify stakeholders (theo severity)
```

### Phase 2: Diagnosis (5-15 phút)

```
# Interface issues
show interfaces <INTF> extensive
show interfaces <INTF> diagnostics optics
show log messages | match "<INTF>" | last 50

# BGP issues
show bgp neighbor <IP> | match "State|Last|Receive|Active"
show bgp neighbor <IP> | match "error|notification"
show log messages | match "BGP|bgp" | last 50

# EVPN/VXLAN issues
show evpn database
show ethernet-switching table summary
show route table bgp.evpn.0 summary

# LACP issues
show lacp interfaces
show lacp statistics interfaces <ae>

# General
show system processes extensive | match "CPU|MEM"
show chassis routing-engine
show route summary
```

### Phase 3: Remediation

#### Quick Fixes
```
# Interface bounce
set interfaces <INTF> disable
commit
delete interfaces <INTF> disable
commit

# Clear BGP neighbor
clear bgp neighbor <IP>

# Clear ARP/MAC
clear arp
clear ethernet-switching table

# Restart process (last resort)
restart routing immediately
```

#### Failover Verification
```
# MC-LAG failover
show multichassis multi-chassis-protection
show interfaces mc-ae<N>

# EVPN multi-homing
show evpn instance
show evpn esi

# Routing convergence
show route 0.0.0.0/0 table inet.0
show bgp summary
```

### Phase 4: Resolution & Recovery

```
# Verify full recovery
show chassis alarms            # Phải trống
show interfaces terse | match "down"  # Chỉ còn admin down
show bgp summary | match "Estab"      # Tất cả BGP established
show lacp interfaces                   # Tất cả LACP active

# Monitor 30 phút sau fix
monitor interface traffic
show interfaces <INTF> | match "Input|Output"
```

### Phase 5: Post-Incident

- [ ] Root Cause Analysis (RCA) — bắt buộc cho P1/P2
- [ ] Timeline documentation
- [ ] Configuration change (nếu có) → tạo CR retro
- [ ] Update runbook nếu có quy trình mới
- [ ] Lessons learned → chia sẻ team
- [ ] Preventive actions → tạo task/ticket

## 4. RCA Template

```
## Incident Report: INC-XXXX

### Summary
- Thời gian phát hiện:
- Thời gian khắc phục:
- Duration:
- Severity:
- Services affected:

### Timeline
| Thời gian | Sự kiện |
|---|---|
| HH:MM | Phát hiện sự cố |
| HH:MM | Bắt đầu xử lý |
| HH:MM | Root cause identified |
| HH:MM | Fix applied |
| HH:MM | Service restored |
| HH:MM | Full verification complete |

### Root Cause
<Mô tả chi tiết nguyên nhân gốc>

### Resolution
<Các bước đã thực hiện để khắc phục>

### Preventive Actions
| Action | Owner | Due Date |
|---|---|---|
| <Action 1> | <Name> | <Date> |

### Lessons Learned
<Bài học rút ra>
```

## 5. On-Call Rotation

| Vai trò | Trách nhiệm |
|---|---|
| Primary On-Call | Respond đầu tiên, xử lý P3/P4, triage P1/P2 |
| Secondary On-Call | Backup cho Primary, join P1/P2 |
| Manager On-Call | Escalation point cho P1, communication với leadership |

### Quy định On-Call
- Rotation: Weekly (handover thứ 2, 09:00)
- Response time: 15 phút cho phone call
- Tools: Laptop, VPN, console access, phone
- Handover: Document tất cả open issues khi chuyển ca

---
*Liên quan: [sop-change-management.md](sop-change-management.md) | [sop-monitoring.md](sop-monitoring.md)*
