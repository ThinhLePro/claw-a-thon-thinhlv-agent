# SOP: ACL & Security Policy

Quy trình cấu hình firewall filter, prefix-list, và security policy trên Juniper Junos.

## 1. Firewall Filter (Stateless ACL)

### Tạo Filter Mới

#### Pre-check
```
show configuration firewall | display set
show firewall filter <FILTER_NAME>
```

#### Configuration
```
# Tạo filter với term cho phép
set firewall family inet filter <FILTER_NAME> term ALLOW_SSH from source-address <SRC_IP>/32
set firewall family inet filter <FILTER_NAME> term ALLOW_SSH from protocol tcp
set firewall family inet filter <FILTER_NAME> term ALLOW_SSH from destination-port ssh
set firewall family inet filter <FILTER_NAME> term ALLOW_SSH then accept
set firewall family inet filter <FILTER_NAME> term ALLOW_SSH then count ALLOW_SSH_COUNT

# Term deny + log
set firewall family inet filter <FILTER_NAME> term DENY_ALL then discard
set firewall family inet filter <FILTER_NAME> term DENY_ALL then count DENY_ALL_COUNT
set firewall family inet filter <FILTER_NAME> term DENY_ALL then log
set firewall family inet filter <FILTER_NAME> term DENY_ALL then syslog

# Áp dụng vào interface
set interfaces <INTF> unit 0 family inet filter input <FILTER_NAME>
```

#### Post-check
```
show firewall filter <FILTER_NAME>
show firewall filter <FILTER_NAME> counter
show firewall log
```

### Thêm Term vào Filter Hiện Tại

> ⚠️ **Thứ tự term RẤT QUAN TRỌNG** — Junos đánh giá từ trên xuống, term đầu tiên match sẽ được thực thi.

```
# Chèn term trước term DENY_ALL
insert firewall family inet filter <FILTER_NAME> term NEW_TERM before term DENY_ALL

set firewall family inet filter <FILTER_NAME> term NEW_TERM from source-address <IP>
set firewall family inet filter <FILTER_NAME> term NEW_TERM from protocol tcp
set firewall family inet filter <FILTER_NAME> term NEW_TERM from destination-port <PORT>
set firewall family inet filter <FILTER_NAME> term NEW_TERM then accept
set firewall family inet filter <FILTER_NAME> term NEW_TERM then count NEW_TERM_COUNT
```

### Xóa Term
```
delete firewall family inet filter <FILTER_NAME> term <TERM_NAME>
```

## 2. Prefix List

### Tạo Prefix List
```
set policy-options prefix-list MGMT-NETWORKS 10.0.0.0/8
set policy-options prefix-list MGMT-NETWORKS 172.16.0.0/12
set policy-options prefix-list MGMT-NETWORKS 192.168.0.0/16

# Sử dụng trong filter
set firewall family inet filter PROTECT-RE term ALLOW-MGMT from source-prefix-list MGMT-NETWORKS
set firewall family inet filter PROTECT-RE term ALLOW-MGMT then accept
```

### Prefix List Cho RE Protection
```
# Prefix list cho NTP servers
set policy-options prefix-list NTP-SERVERS <NTP_IP_1>/32
set policy-options prefix-list NTP-SERVERS <NTP_IP_2>/32

# Prefix list cho SNMP managers
set policy-options prefix-list SNMP-MANAGERS <SNMP_IP>/32

# Prefix list cho BGP neighbors
set policy-options prefix-list BGP-NEIGHBORS <NEIGHBOR_IP>/32
```

## 3. RE Protection Filter (Bắt buộc)

Mọi switch/router production PHẢI có RE protection filter:

```
# Cho phép BGP
set firewall family inet filter PROTECT-RE term ALLOW-BGP from source-prefix-list BGP-NEIGHBORS
set firewall family inet filter PROTECT-RE term ALLOW-BGP from protocol tcp
set firewall family inet filter PROTECT-RE term ALLOW-BGP from destination-port bgp
set firewall family inet filter PROTECT-RE term ALLOW-BGP then accept

# Cho phép SSH từ management
set firewall family inet filter PROTECT-RE term ALLOW-SSH from source-prefix-list MGMT-NETWORKS
set firewall family inet filter PROTECT-RE term ALLOW-SSH from protocol tcp
set firewall family inet filter PROTECT-RE term ALLOW-SSH from destination-port ssh
set firewall family inet filter PROTECT-RE term ALLOW-SSH then accept
set firewall family inet filter PROTECT-RE term ALLOW-SSH then count SSH-ACCESS

# Cho phép SNMP
set firewall family inet filter PROTECT-RE term ALLOW-SNMP from source-prefix-list SNMP-MANAGERS
set firewall family inet filter PROTECT-RE term ALLOW-SNMP from protocol udp
set firewall family inet filter PROTECT-RE term ALLOW-SNMP from destination-port snmp
set firewall family inet filter PROTECT-RE term ALLOW-SNMP then accept

# Cho phép NTP
set firewall family inet filter PROTECT-RE term ALLOW-NTP from source-prefix-list NTP-SERVERS
set firewall family inet filter PROTECT-RE term ALLOW-NTP from protocol udp
set firewall family inet filter PROTECT-RE term ALLOW-NTP from source-port ntp
set firewall family inet filter PROTECT-RE term ALLOW-NTP then accept

# Cho phép ICMP (giới hạn)
set firewall family inet filter PROTECT-RE term ALLOW-ICMP from protocol icmp
set firewall family inet filter PROTECT-RE term ALLOW-ICMP from icmp-type echo-request
set firewall family inet filter PROTECT-RE term ALLOW-ICMP then policer ICMP-POLICER
set firewall family inet filter PROTECT-RE term ALLOW-ICMP then accept

# Cho phép OSPF/IS-IS (nếu dùng)
set firewall family inet filter PROTECT-RE term ALLOW-OSPF from protocol ospf
set firewall family inet filter PROTECT-RE term ALLOW-OSPF then accept

# Deny all khác
set firewall family inet filter PROTECT-RE term DENY-ALL then discard
set firewall family inet filter PROTECT-RE term DENY-ALL then count DENIED-TO-RE
set firewall family inet filter PROTECT-RE term DENY-ALL then log
set firewall family inet filter PROTECT-RE term DENY-ALL then syslog

# Policer cho ICMP
set firewall policer ICMP-POLICER if-exceeding bandwidth-limit 1m burst-size-limit 15k
set firewall policer ICMP-POLICER then discard

# Áp dụng vào loopback
set interfaces lo0 unit 0 family inet filter input PROTECT-RE
```

## 4. Quy Tắc Đặt Tên Filter

| Loại | Format | Ví dụ |
|---|---|---|
| RE protection | `PROTECT-RE` | `PROTECT-RE` |
| Interface ACL (inbound) | `ACL-<ZONE>-IN` | `ACL-DMZ-IN` |
| Interface ACL (outbound) | `ACL-<ZONE>-OUT` | `ACL-PROD-OUT` |
| Rate limiter | `RL-<PURPOSE>` | `RL-ICMP-LIMIT` |

## 5. Checklist Trước Khi Áp Dụng ACL

- [ ] Đã test trên lab/staging trước
- [ ] Đã review term ordering (deny không đứng trước allow cần thiết)
- [ ] Có counter trên mỗi term (để monitor)
- [ ] Có term log/syslog trên deny rule
- [ ] Dùng `commit confirmed 5` khi áp dụng lần đầu
- [ ] Đã confirm không block traffic production
- [ ] Có rollback plan rõ ràng

---
*Liên quan: [sop-change-management.md](sop-change-management.md) | [sop-vlan-management.md](sop-vlan-management.md)*
