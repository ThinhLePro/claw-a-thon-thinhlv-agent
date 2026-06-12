# Quy Định: Quản Lý IP / IPAM

Quy trình chuẩn quản lý IP addressing và subnet planning trong DC network.

## 1. IP Address Allocation Schema

### DC Network IP Plan

| Block | Mục đích | Subnet Size |
|---|---|---|
| `10.0.0.0/16` | DC1 — All networks |  |
| `10.0.0.0/24` | Management network | /24 |
| `10.0.1.0/24` | Out-of-band management | /24 |
| `10.0.10.0/23` | Loopback addresses | /32 per device |
| `10.0.12.0/22` | P2P fabric links | /31 per link |
| `10.0.16.0/20` | Server VLANs (VLAN 100-999) | /24 per VLAN |
| `10.0.32.0/20` | DMZ VLANs (VLAN 1000-1999) | /24 per VLAN |
| `10.0.48.0/21` | Storage VLANs | /24 per VLAN |
| `10.0.56.0/21` | Backup/Replication | /24 per VLAN |
| `10.0.64.0/22` | Infrastructure services | /24 per service |

### Loopback Allocation

| Device Type | Range | Example |
|---|---|---|
| Spine switches | `10.0.10.1 - 10.0.10.10` | Spine-1: `10.0.10.1/32` |
| Leaf switches | `10.0.10.11 - 10.0.10.100` | Leaf-1: `10.0.10.11/32` |
| Border leaf | `10.0.10.101 - 10.0.10.120` | BL-1: `10.0.10.101/32` |
| Service leaf | `10.0.10.121 - 10.0.10.140` | SL-1: `10.0.10.121/32` |

### P2P Link Allocation

| Link | Subnet | Side A | Side B |
|---|---|---|---|
| Spine1-Leaf1 | `10.0.12.0/31` | `.0` (Spine) | `.1` (Leaf) |
| Spine1-Leaf2 | `10.0.12.2/31` | `.2` (Spine) | `.3` (Leaf) |
| Spine2-Leaf1 | `10.0.12.4/31` | `.4` (Spine) | `.5` (Leaf) |
| Spine2-Leaf2 | `10.0.12.6/31` | `.6` (Spine) | `.7` (Leaf) |

> 💡 **Convention**: Spine luôn lấy IP chẵn (even), Leaf lấy IP lẻ (odd) trên /31 links.

## 2. IP Request Process

### Workflow
```
1. Requestor submit IP request (form/ticket)
2. Network Engineer verify yêu cầu:
   - Mục đích sử dụng
   - Số lượng IP cần
   - VLAN / subnet mong muốn
   - Duration (permanent / temporary)
3. Allocate từ IPAM
4. Update IPAM database
5. Configure trên switch (nếu cần subnet mới)
6. Confirm cho requestor
```

### IP Request Form

| Field | Ví dụ |
|---|---|
| Requestor | Nguyễn Văn A |
| Team | Server Team |
| Purpose | New web server cluster |
| IP count | 10 |
| VLAN | SRV-DC1-WEB-100 |
| Duration | Permanent |
| Gateway required? | Yes |
| DNS records needed? | Yes |

## 3. Subnet Sizing Guide

| Hosts Needed | Recommended Subnet | Usable IPs | Notes |
|---|---|---|---|
| 1-2 | /30 | 2 | P2P links |
| 1 | /31 | 2 | P2P links (RFC 3021) |
| 1-5 | /29 | 6 | Small server group |
| 6-14 | /28 | 14 | Medium server group |
| 15-30 | /27 | 30 | Standard server VLAN |
| 31-62 | /26 | 62 | Large server VLAN |
| 63-126 | /25 | 126 | Very large VLAN |
| 127-254 | /24 | 254 | Maximum single VLAN |

> ⚠️ **Không nên dùng subnet lớn hơn /24** cho server VLANs — broadcast domain quá lớn ảnh hưởng performance.

## 4. Reserved IP Addresses Per Subnet

| Offset | IP | Mục đích |
|---|---|---|
| .0 | Network address | Network ID |
| .1 | First usable | Default Gateway (VIP/IRB) |
| .2 | Second | Gateway - Node 0 (Active) |
| .3 | Third | Gateway - Node 1 (Standby) |
| .4-.9 | | Reserved for infrastructure |
| .10-.250 | | Server / Device allocation |
| .251-.254 | | Reserved for future use |
| .255 | Last | Broadcast |

## 5. IPAM Tool Requirements

### Mandatory Fields
- IP Address
- Subnet
- VLAN
- Device hostname
- Device role (server, switch, firewall...)
- Status (Allocated, Reserved, Available, Deprecated)
- Allocated date
- Owner / Team
- Description / Purpose

### IPAM Best Practices
- **Mỗi IP phải có owner** — không có IP "vô chủ"
- **Review quarterly** — thu hồi IP không sử dụng
- **DNS sync** — forward + reverse DNS phải match
- **Audit trail** — log tất cả thay đổi (who, when, what)
- **Automation** — tích hợp IPAM với provisioning workflow

## 6. IP Decommission Process

Khi thu hồi IP:
1. Confirm device/service đã decommission
2. Remove DNS records (A + PTR)
3. Remove DHCP reservation (nếu có)
4. Update IPAM status → "Available"
5. Remove từ ACL/firewall rules (nếu có)
6. Document reason trong IPAM notes

## 7. IPv6 Planning (Future-Ready)

| Block | Mục đích |
|---|---|
| `fd00:dc1::/48` | ULA — DC1 internal |
| `fd00:dc1:0::/64` | Management |
| `fd00:dc1:1::/64` | Loopback |
| `fd00:dc1:10::/60` | Server VLANs |

---
*Liên quan: [sop-vlan-management.md](sop-vlan-management.md) | [sop-new-switch.md](sop-new-switch.md)*
