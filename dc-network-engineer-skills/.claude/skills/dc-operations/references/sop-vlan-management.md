# SOP: VLAN Management

Quy trình chuẩn quản lý VLAN trên hệ thống DC network (Juniper Junos).

## 1. Thêm VLAN Mới

### Pre-check
```
show vlans
show vlans brief
show configuration vlans | display set
```

### Configuration
```
set vlans <VLAN_NAME> vlan-id <VID>
set vlans <VLAN_NAME> description "<Mô tả mục đích>"
set vlans <VLAN_NAME> l3-interface irb.<VID>

# Gán VLAN vào interface access
set interfaces <INTF> unit 0 family ethernet-switching vlan members <VLAN_NAME>

# Gán VLAN vào trunk
set interfaces <INTF> unit 0 family ethernet-switching interface-mode trunk
set interfaces <INTF> unit 0 family ethernet-switching vlan members <VLAN_NAME>
```

### Post-check
```
show vlans <VLAN_NAME>
show vlans <VLAN_NAME> extensive
show ethernet-switching table vlan <VLAN_NAME>
show interfaces <INTF> | match "Physical|Logical|VLAN"
```

### Rollback
```
rollback 1
commit
```

## 2. Thay Đổi VLAN (Rename, Thêm/Xóa Member)

### Thêm interface vào VLAN
```
# Pre-check
show vlans <VLAN_NAME> extensive

# Config
set interfaces <INTF> unit 0 family ethernet-switching vlan members <VLAN_NAME>

# Post-check
show ethernet-switching table vlan <VLAN_NAME>
```

### Xóa interface khỏi VLAN
```
# Pre-check
show ethernet-switching table interface <INTF>

# Config
delete interfaces <INTF> unit 0 family ethernet-switching vlan members <VLAN_NAME>

# Post-check
show ethernet-switching table interface <INTF>
```

## 3. Xóa VLAN

> ⚠️ **CẢNH BÁO**: Xóa VLAN sẽ disconnect toàn bộ thiết bị đang sử dụng VLAN đó. Phải confirm không còn host nào active.

### Pre-check
```
show vlans <VLAN_NAME> extensive
show ethernet-switching table vlan <VLAN_NAME>
# Kiểm tra MAC count — nếu > 0, CÒN host active
show ethernet-switching table vlan <VLAN_NAME> count
```

### Checklist trước khi xóa
- [ ] Không còn MAC address active trong VLAN
- [ ] Không còn ARP entry trên IRB interface
- [ ] Đã thông báo cho team Application/Server
- [ ] Đã có Change Request được approve
- [ ] Đã backup cấu hình hiện tại

### Configuration
```
# Xóa VLAN assignments từ interfaces trước
delete interfaces <INTF> unit 0 family ethernet-switching vlan members <VLAN_NAME>

# Xóa IRB interface (nếu có)
delete interfaces irb unit <VID>

# Xóa VLAN definition
delete vlans <VLAN_NAME>

commit confirmed 5
# Confirm sau khi verify OK
commit
```

### Post-check
```
show vlans brief | match <VLAN_NAME>
# Phải trả về empty — VLAN đã bị xóa
```

## 4. VLAN Trunk Management

### Thêm VLAN vào Trunk
```
# Pre-check
show interfaces <TRUNK_INTF> unit 0 family ethernet-switching

# Config
set interfaces <TRUNK_INTF> unit 0 family ethernet-switching vlan members <VLAN_NAME>

# Post-check
show interfaces <TRUNK_INTF> unit 0 family ethernet-switching
show ethernet-switching table interface <TRUNK_INTF>
```

### Xóa VLAN khỏi Trunk
```
# Pre-check
show ethernet-switching table interface <TRUNK_INTF> vlan <VLAN_NAME>

# Config
delete interfaces <TRUNK_INTF> unit 0 family ethernet-switching vlan members <VLAN_NAME>

# Post-check
show interfaces <TRUNK_INTF> unit 0 family ethernet-switching
```

### Native VLAN trên Trunk
```
set interfaces <TRUNK_INTF> native-vlan-id <VID>
```

## 5. Quy Tắc Đặt Tên VLAN

| Loại | Format | Ví dụ |
|---|---|---|
| Server VLAN | `SRV-<DC>-<ZONE>-<VID>` | `SRV-DC1-DMZ-100` |
| Management | `MGMT-<DC>-<VID>` | `MGMT-DC1-999` |
| Storage | `STO-<DC>-<VID>` | `STO-DC1-200` |
| Backup | `BKP-<DC>-<VID>` | `BKP-DC1-300` |
| Interconnect | `ICL-<DC>-<VID>` | `ICL-DC1-4000` |

## 6. VLAN ID Allocation

| Range | Mục đích |
|---|---|
| 1-99 | Reserved (management, native) |
| 100-999 | Server VLANs |
| 1000-1999 | DMZ VLANs |
| 2000-2999 | Storage VLANs |
| 3000-3999 | Backup/Replication |
| 4000-4093 | Infrastructure (ICL, peering) |
| 4094 | Reserved |

---
*Liên quan: [sop-change-management.md](sop-change-management.md) | [sop-acl-security.md](sop-acl-security.md)*
