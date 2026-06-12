# SOP: Change Management Process

Quy trình quản lý thay đổi (Change Request) cho hạ tầng DC network.

## 1. Phân Loại Change

| Loại | Mô tả | Approval | Window |
|---|---|---|---|
| **Standard** | Thay đổi đã template sẵn (add VLAN, add server port) | Pre-approved | Business hours |
| **Normal** | Thay đổi cần review (BGP policy, ACL, firmware upgrade) | CAB approval | Maintenance window |
| **Emergency** | Khắc phục sự cố ảnh hưởng production | Manager approval (verbal OK → written sau) | Ngay lập tức |

## 2. Workflow Change Request

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Requester  │───▶│  Team Lead   │───▶│  CAB Review  │
│   Tạo CR     │    │  Review      │    │  Approve     │
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
                    ┌──────────────┐    ┌───────▼──────┐
                    │   Verify &   │◀───│  Implement   │
                    │   Close CR   │    │  Change      │
                    └──────────────┘    └──────────────┘
```

### Thông tin bắt buộc trong CR
- **Summary**: Mô tả ngắn gọn thay đổi
- **Justification**: Lý do cần thay đổi
- **Impact Assessment**: Ảnh hưởng đến service nào
- **Risk Level**: Low / Medium / High / Critical
- **Device List**: Danh sách thiết bị bị ảnh hưởng
- **Implementation Plan**: Từng bước thực hiện
- **Rollback Plan**: Kế hoạch khôi phục nếu thất bại
- **Test Plan**: Cách verify sau khi thay đổi
- **Schedule**: Thời gian thực hiện (trong maintenance window)
- **Notifications**: Danh sách stakeholders cần thông báo

## 3. Risk Assessment Matrix

| Impact ↓ / Probability → | Thấp | Trung bình | Cao |
|---|---|---|---|
| **Thấp** (1 server) | Low | Low | Medium |
| **Trung bình** (1 rack/VLAN) | Low | Medium | High |
| **Cao** (nhiều rack/fabric) | Medium | High | Critical |
| **Rất cao** (toàn DC) | High | Critical | Critical |

## 4. Maintenance Window

| Window | Thời gian | Loại change |
|---|---|---|
| Weekly MW | Thứ 7, 01:00-05:00 | Normal changes |
| Emergency MW | Any time | Emergency changes |
| Quarterly MW | Q1/Q2/Q3/Q4 Sunday 01:00-09:00 | Firmware upgrade, major changes |

## 5. Implementation Procedure

### Trước khi thay đổi (T-30 phút)
```
# 1. Backup configuration
show configuration | save /var/tmp/backup_$(hostname)_$(date +%Y%m%d_%H%M).conf

# 2. Snapshot hệ thống
show chassis alarms
show system alarms
show bgp summary | match "Estab"
show interfaces terse | match "up" | count
show lacp interfaces | match "Active"

# 3. Lưu kết quả pre-check
# Copy output vào CR ticket
```

### Trong khi thay đổi
```
# LUÔN dùng commit confirmed cho production
configure
<thực hiện thay đổi>
commit confirmed 5

# Verify changes
<chạy post-check commands>

# Nếu OK → confirm
commit

# Nếu NOK → đợi auto-rollback hoặc
rollback 1
commit
```

### Sau khi thay đổi (T+15 phút)
```
# 1. Post-check = Pre-check (so sánh kết quả)
show chassis alarms
show system alarms
show bgp summary | match "Estab"
show interfaces terse | match "up" | count
show lacp interfaces | match "Active"

# 2. Verify specific change
<commands tùy theo loại change>

# 3. Monitor 15-30 phút
# Kiểm tra Grafana/NMS dashboards
# Kiểm tra syslog cho errors mới
```

## 6. Rollback Procedure

### Rollback tự động (commit confirmed)
```
# Nếu không confirm trong thời gian specified
# → Junos tự rollback về config trước đó
```

### Rollback thủ công
```
# Xem các commit gần đây
show system commit

# Rollback về commit trước
configure
rollback 1
show | compare
commit

# Hoặc rollback về rescue config
request system configuration rescue
```

### Emergency Rollback
```
# Khi không SSH được → dùng console
# Load rescue configuration
request system configuration rescue

# Hoặc boot từ backup partition
request system reboot slice alternate
```

## 7. Communication Template

### Trước thay đổi (T-24h)
```
Subject: [Network Change] CR-XXXX - <Mô tả> - <Date> <Time>

Team,

Sẽ có thay đổi network theo lịch:
- CR: CR-XXXX
- Thời gian: <Date> <Start>-<End>
- Thiết bị: <Device list>
- Impact: <Mô tả ảnh hưởng>
- Người thực hiện: <Name>

Vui lòng báo nếu có concern.
```

### Sau thay đổi
```
Subject: [Network Change] CR-XXXX - COMPLETED/FAILED

Team,

Kết quả change CR-XXXX:
- Status: COMPLETED / FAILED / ROLLED BACK
- Duration: <Start>-<End>
- Issues: <Nếu có>
- Action items: <Nếu có>
```

## 8. Post-Implementation Review (PIR)

Bắt buộc cho Medium/High/Critical changes:
- [ ] So sánh pre-check vs post-check
- [ ] Monitoring dashboards bình thường
- [ ] Không có incident mới liên quan
- [ ] Documentation đã cập nhật
- [ ] Close CR ticket

---
*Liên quan: [sop-incident-response.md](sop-incident-response.md) | [sop-maintenance.md](sop-maintenance.md)*
