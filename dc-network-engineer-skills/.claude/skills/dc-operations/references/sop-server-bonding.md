# SOP: Server Bonding (LACP)

Quy trình cấu hình LACP bonding cho kết nối server đến switch trên Juniper Junos.

## 1. Single-Homed LACP (1 Switch)

### Pre-check
```
show interfaces terse | match "xe-|et-|ge-"
show lacp interfaces
show configuration interfaces ae<N>
```

### Configuration

#### Trên Switch
```
# Tạo ae interface
set chassis aggregated-devices ethernet device-count 10

# Cấu hình ae interface
set interfaces ae<N> description "LACP to <SERVER_NAME>"
set interfaces ae<N> aggregated-ether-options lacp active
set interfaces ae<N> aggregated-ether-options lacp periodic fast
set interfaces ae<N> unit 0 family ethernet-switching interface-mode trunk
set interfaces ae<N> unit 0 family ethernet-switching vlan members <VLAN_LIST>

# Gán member interfaces
set interfaces <INTF_1> ether-options 802.3ad ae<N>
set interfaces <INTF_2> ether-options 802.3ad ae<N>
set interfaces <INTF_1> description "LACP member ae<N> - <SERVER_NAME> NIC1"
set interfaces <INTF_2> description "LACP member ae<N> - <SERVER_NAME> NIC2"
```

#### Trên Server (Linux)
```bash
# Tạo bond interface
cat > /etc/sysconfig/network-scripts/ifcfg-bond0 << 'EOF'
DEVICE=bond0
TYPE=Bond
BONDING_MASTER=yes
BOOTPROTO=none
ONBOOT=yes
IPADDR=<IP>
NETMASK=<MASK>
GATEWAY=<GW>
BONDING_OPTS="mode=4 miimon=100 lacp_rate=fast xmit_hash_policy=layer3+4"
EOF

# Cấu hình slave interfaces
for NIC in eth0 eth1; do
cat > /etc/sysconfig/network-scripts/ifcfg-$NIC << EOF
DEVICE=$NIC
TYPE=Ethernet
BOOTPROTO=none
ONBOOT=yes
MASTER=bond0
SLAVE=yes
EOF
done

systemctl restart network
```

### Post-check
```
# Switch
show lacp interfaces ae<N>
show lacp statistics interfaces ae<N>
show interfaces ae<N> extensive | match "Physical|Logical|Speed|LACP"
show interfaces ae<N> | match "Physical|Input|Output"

# Server
cat /proc/net/bonding/bond0
```

## 2. Dual-Homed LACP (MC-LAG / ESI-LAG)

### Khi server kết nối đến 2 switch khác nhau (HA):

#### MC-LAG Mode
```
# Switch A
set interfaces ae<N> aggregated-ether-options lacp active
set interfaces ae<N> aggregated-ether-options lacp system-id <SHARED_MAC>
set interfaces ae<N> aggregated-ether-options lacp admin-key <KEY>
set interfaces ae<N> aggregated-ether-options mc-ae mc-ae-id <ID>
set interfaces ae<N> aggregated-ether-options mc-ae chassis-id 0
set interfaces ae<N> aggregated-ether-options mc-ae mode active-active
set interfaces ae<N> aggregated-ether-options mc-ae status-control active

# Switch B
set interfaces ae<N> aggregated-ether-options lacp active
set interfaces ae<N> aggregated-ether-options lacp system-id <SHARED_MAC>
set interfaces ae<N> aggregated-ether-options lacp admin-key <KEY>
set interfaces ae<N> aggregated-ether-options mc-ae mc-ae-id <ID>
set interfaces ae<N> aggregated-ether-options mc-ae chassis-id 1
set interfaces ae<N> aggregated-ether-options mc-ae mode active-active
set interfaces ae<N> aggregated-ether-options mc-ae status-control standby
```

#### EVPN ESI-LAG Mode (Recommended cho IP Fabric)
```
# Switch A & B (cùng ESI)
set interfaces ae<N> esi <ESI_VALUE>
set interfaces ae<N> esi all-active
set interfaces ae<N> aggregated-ether-options lacp active
set interfaces ae<N> aggregated-ether-options lacp system-id <SHARED_MAC>
```

## 3. Quy Tắc Đánh Số ae Interface

| Range | Mục đích |
|---|---|
| ae0-ae9 | Infrastructure (ICL, uplink spine) |
| ae10-ae49 | Server bonding |
| ae50-ae99 | Storage / Backup |

## 4. Troubleshooting LACP

| Vấn đề | Kiểm tra | Nguyên nhân thường gặp |
|---|---|---|
| LACP không UP | `show lacp interfaces` | LACP mode mismatch (active/passive) |
| Chỉ 1 link active | `show lacp statistics` | Cáp lỗi, SFP lỗi, hoặc LACP timeout |
| Traffic không cân bằng | `show interfaces ae<N> extensive` | Hash algorithm không phù hợp |
| ae interface flapping | `show log messages | match ae` | Member link unstable |

### Debug Commands
```
show lacp interfaces ae<N> detail
show lacp statistics interfaces ae<N>
show interfaces ae<N> extensive
show interfaces ae<N> diagnostics optics
monitor interface ae<N>
```

## 5. Checklist LACP Deployment

- [ ] Xác nhận đúng physical port trên cả switch và server
- [ ] LACP mode: active trên cả 2 phía
- [ ] LACP rate: fast (1s) cho production
- [ ] VLAN members trên ae interface đã đúng
- [ ] MTU consistent giữa ae, member interfaces, và server
- [ ] Đã test failover (rút 1 cáp, verify traffic vẫn chạy)
- [ ] Đã verify load balancing
- [ ] Description rõ ràng trên tất cả interfaces

---
*Liên quan: [sop-new-switch.md](sop-new-switch.md) | [sop-vlan-management.md](sop-vlan-management.md)*
