# SOP: New Switch Deployment

Quy trình chuẩn triển khai switch mới vào hạ tầng DC network.

## 1. Checklist Trước Khi Triển Khai

### Hardware
- [ ] Đúng model switch theo thiết kế (QFX5120, QFX5130, EX4400...)
- [ ] Đúng số lượng và loại SFP/QSFP transceivers
- [ ] Đúng loại cáp (DAC, AOC, hoặc fiber patch cord)
- [ ] Đủ power cables (2 PSU cho redundancy)
- [ ] Console cable (USB-C hoặc RJ45)
- [ ] Label máy (hostname, management IP, rack position)

### Network Planning
- [ ] Hostname theo naming convention: `<DC>-<ROLE>-<RACK>-<POS>`
- [ ] Management IP đã allocate trong IPAM
- [ ] Loopback IP đã allocate
- [ ] Fabric IP (P2P links) đã allocate
- [ ] BGP AS number đã assign
- [ ] VLAN list cần thiết đã xác định
- [ ] Uplink ports đã xác định

### Approval
- [ ] Change Request đã được approve
- [ ] Maintenance window đã schedule
- [ ] Team Server/Application đã thông báo

## 2. Lắp Đặt Phần Cứng

### Quy trình
1. **Rack & Stack**: Lắp switch vào đúng vị trí trong rack (U position)
2. **Power**: Kết nối 2 PSU vào 2 nguồn điện khác nhau (A/B feed)
3. **Console**: Kết nối console cable
4. **Management**: Kết nối management port (me0 hoặc em0)
5. **Uplinks**: Kết nối uplink vào spine switches
6. **Labeling**: Dán label 2 đầu cáp (switch port + patch panel port)

### Verify Power
```
show chassis environment
show chassis power
show chassis routing-engine
```

## 3. Base Configuration (Day 0)

### Initial Setup via Console
```
# Junos factory default
request system zeroize

# Set root password
set system root-authentication plain-text-password

# Hostname
set system host-name <HOSTNAME>

# Management interface
set interfaces em0 unit 0 family inet address <MGMT_IP>/24

# Default route for management
set routing-instances MGMT instance-type virtual-router
set routing-instances MGMT interface em0.0
set routing-instances MGMT routing-options static route 0.0.0.0/0 next-hop <MGMT_GW>

# DNS
set system name-server <DNS_1>
set system name-server <DNS_2>

# NTP
set system ntp server <NTP_1>
set system ntp server <NTP_2>

# Syslog
set system syslog host <SYSLOG_SERVER> any warning
set system syslog host <SYSLOG_SERVER> authorization info
set system syslog host <SYSLOG_SERVER> interactive-commands info
set system syslog host <SYSLOG_SERVER> change-log info
set system syslog file messages any warning
set system syslog file messages authorization info

# SSH
set system services ssh root-login deny
set system services ssh protocol-version v2
set system services ssh max-sessions-per-connection 5
set system services ssh connection-limit 10

# SNMP
set snmp community <COMMUNITY> authorization read-only
set snmp community <COMMUNITY> clients <SNMP_MANAGERS>/32

# Login banner
set system login message "\\n*** AUTHORIZED ACCESS ONLY ***\\n*** All activities are monitored and logged ***\\n"

# Local user accounts
set system login user netops class super-user authentication plain-text-password

# Commit
commit confirmed 10
commit
```

## 4. Fabric Configuration (Day 1)

### Loopback Interface
```
set interfaces lo0 unit 0 family inet address <LOOPBACK_IP>/32
set interfaces lo0 unit 0 family inet filter input PROTECT-RE
```

### Uplink Interfaces (to Spine)
```
set interfaces <UPLINK_1> description "TO-<SPINE_1>-<PORT>"
set interfaces <UPLINK_1> mtu 9216
set interfaces <UPLINK_1> unit 0 family inet address <P2P_IP_1>/31

set interfaces <UPLINK_2> description "TO-<SPINE_2>-<PORT>"
set interfaces <UPLINK_2> mtu 9216
set interfaces <UPLINK_2> unit 0 family inet address <P2P_IP_2>/31
```

### BGP Underlay (eBGP)
```
set protocols bgp group UNDERLAY type external
set protocols bgp group UNDERLAY local-as <LEAF_ASN>
set protocols bgp group UNDERLAY multipath multiple-as
set protocols bgp group UNDERLAY neighbor <SPINE_1_IP> peer-as <SPINE_1_ASN>
set protocols bgp group UNDERLAY neighbor <SPINE_1_IP> description "TO-<SPINE_1>"
set protocols bgp group UNDERLAY neighbor <SPINE_2_IP> peer-as <SPINE_2_ASN>
set protocols bgp group UNDERLAY neighbor <SPINE_2_IP> description "TO-<SPINE_2>"
set protocols bgp group UNDERLAY family inet unicast
set protocols bgp group UNDERLAY export EXPORT-LOOPBACK

set policy-options policy-statement EXPORT-LOOPBACK term LO0 from interface lo0.0
set policy-options policy-statement EXPORT-LOOPBACK term LO0 then accept
set policy-options policy-statement EXPORT-LOOPBACK term DEFAULT then reject
```

### BGP EVPN Overlay (iBGP)
```
set protocols bgp group EVPN-OVERLAY type internal
set protocols bgp group EVPN-OVERLAY local-address <LOOPBACK_IP>
set protocols bgp group EVPN-OVERLAY family evpn signaling
set protocols bgp group EVPN-OVERLAY neighbor <SPINE_1_LOOPBACK>
set protocols bgp group EVPN-OVERLAY neighbor <SPINE_2_LOOPBACK>
```

### EVPN + VXLAN
```
set protocols evpn encapsulation vxlan
set protocols evpn default-gateway no-gateway-community

set switch-options vtep-source-interface lo0.0
set switch-options route-distinguisher <LOOPBACK_IP>:1
set switch-options vrf-target target:<ASN>:1
```

## 5. Post-Deployment Verification

### Checklist
```
# Hardware health
show chassis alarms
show chassis environment
show system alarms

# Interface status
show interfaces terse | match "up|down"
show interfaces diagnostics optics

# BGP underlay
show bgp summary
show bgp neighbor | match "Peer|State|Active"

# BGP overlay
show bgp summary group EVPN-OVERLAY

# EVPN
show evpn database
show ethernet-switching table summary

# Routing
show route summary
show route table bgp.evpn.0 summary

# NTP sync
show ntp associations
show ntp status

# System
show system uptime
show system storage
show system core-dumps
```

### Acceptance Criteria
- [ ] Tất cả uplink interfaces UP
- [ ] BGP underlay sessions ESTABLISHED
- [ ] BGP EVPN overlay sessions ESTABLISHED
- [ ] VTEP tunnel đã lên
- [ ] NTP synchronized
- [ ] Syslog đang gửi logs
- [ ] SNMP accessible
- [ ] SSH accessible từ management network
- [ ] RE protection filter đã áp dụng
- [ ] Không có chassis alarms

## 6. Handover & Documentation

- [ ] Cập nhật IPAM với tất cả IP đã sử dụng
- [ ] Cập nhật network diagram
- [ ] Cập nhật inventory database
- [ ] Backup running config lên config server
- [ ] Thông báo team monitoring thêm device mới
- [ ] Close Change Request với kết quả

---
*Liên quan: [sop-change-management.md](sop-change-management.md) | [sop-acl-security.md](sop-acl-security.md)*
