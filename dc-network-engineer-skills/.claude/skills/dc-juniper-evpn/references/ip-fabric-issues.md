# IP Fabric Issues & Troubleshooting

> Source: Juniper EVPN User Guide (Official Documentation)

## Common IP Fabric Issues

### 1. Unknown Unicast Flooding in CRB Overlay

**Symptom**: Excessive unknown unicast flooding across VXLAN overlay in Centrally-Routed Bridging (CRB) design.

**Root Cause**: IRB MAC vs Virtual Gateway MAC mismatch. When spine router sends ARP reply:
- Outer Ethernet header uses **IRB MAC** (physical MAC)
- Inner ARP reply uses **Virtual Gateway MAC** (00:00:5e:00:01:xx)
- Intermediary L2 switches learn IRB MAC but not Virtual MAC
- Traffic destined to Virtual MAC gets flooded as unknown unicast

**Solution**:
```junos
# Explicitly configure virtual gateway MAC on IRB
set interfaces irb unit 100 virtual-gateway-v4-mac 00:00:5e:00:01:01
```

> **Note**: This issue does NOT affect ERB (Edge-Routed Bridging) overlays where each leaf has its own IRB with a static anycast MAC.

---

### 2. MAC Mobility / Duplicate MAC Detection

**Symptom**: MAC address flapping between VTEPs, triggering duplicate MAC detection.

**Root Cause**: VM migration, misconfigured bonding, or network loops causing same MAC to appear from different VTEPs.

**Verification**:
```junos
show evpn database | match "duplicate"
show evpn mac-table | match "DUP"
show log messages | match "MAC_MOVE_LIMIT"
```

**Configuration**:
```junos
# Adjust duplicate MAC detection thresholds
set protocols evpn duplicate-mac-detection detection-threshold 10
set protocols evpn duplicate-mac-detection detection-window 180
set protocols evpn duplicate-mac-detection auto-recovery-time 5

# Enable loop detection for duplicate MACs
set protocols evpn duplicate-mac-detection action-on-detection disable-learning
```

---

### 3. VTEP Tunnel Issues

**Symptom**: VXLAN tunnels not establishing or traffic not flowing between leaves.

**Verification**:
```junos
# Check VTEP source (loopback)
show l2-learning vxlan-tunnel-end-point source

# Check remote VTEPs discovered
show l2-learning vxlan-tunnel-end-point remote

# Check VTEP interface status
show interfaces vtep

# Verify underlay reachability to remote VTEP
ping <remote-vtep-ip> source <local-vtep-ip> size 8000 do-not-fragment
```

**Common Causes**:
- Underlay BGP not advertising loopback routes
- MTU too small (VXLAN adds 50 bytes overhead)
- Firewall filters blocking UDP 4789
- Ingress replication not configured

---

### 4. IRB / Inter-VXLAN Routing Failures

**Symptom**: Traffic within same VNI works, but inter-VNI routing fails.

**Verification**:
```junos
# Check IRB interface status
show interfaces irb

# Check routing table for VRF
show route table <vrf-name>.inet.0

# Verify ARP entries on IRB
show arp interface irb.100

# Check EVPN Type 5 routes
show route table <instance>.evpn.0 match-prefix "5:*"
```

**Common Causes**:
- IRB interface not in correct VRF
- Missing Type 5 route export/import
- Virtual gateway address mismatch between leaves (ERB)
- L3 VNI not configured for symmetric routing

---

### 5. BUM Traffic Issues

**Symptom**: Broadcast/multicast not reaching all hosts, or excessive BUM flooding.

**Verification**:
```junos
# Check ingress replication list
show evpn instance extensive | match "replication"

# Check EVPN Type 3 (Inclusive Multicast) routes
show route table <instance>.evpn.0 match-prefix "3:*"

# Check multicast groups if using multicast underlay
show pim join
```

**Common Causes**:
- Ingress replication not enabled
- Missing Type 3 routes from some VTEPs
- ARP suppression not enabled (causes unnecessary ARP floods)

---

### 6. EVPN Multihoming Issues

**Symptom**: Traffic blackholing or loops with dual-homed hosts.

**Verification**:
```junos
# Check ESI status
show evpn instance extensive | match "esi"

# Check DF election results
show evpn instance designated-forwarder

# Check Type 1 (Auto-Discovery) routes
show route table <instance>.evpn.0 match-prefix "1:*"

# Check Type 4 (ES) routes
show route table <instance>.evpn.0 match-prefix "4:*"

# Verify LACP on ae interface
show lacp interfaces ae0
```

**Common Causes**:
- ESI mismatch between PEs
- LACP system-id not matching
- Split horizon filtering not working (causes loops)
- DF election not converging (causes duplicate BUM)

---

## Troubleshooting Workflow

```
Step 1: Check underlay connectivity
  → ping between loopbacks, verify BGP underlay
  → show bgp summary, show route table inet.0

Step 2: Check overlay BGP (EVPN)
  → show bgp summary instance <evpn-instance>
  → show route table bgp.evpn.0 summary

Step 3: Check VTEP tunnels
  → show l2-learning vxlan-tunnel-end-point source/remote
  → show interfaces vtep

Step 4: Check EVPN database
  → show evpn database
  → show evpn database extensive | match "type"

Step 5: Check MAC/ARP tables
  → show ethernet-switching table
  → show arp interface irb.*

Step 6: Check for errors/drops
  → show interfaces extensive | match "error|drop"
  → show pfe statistics traffic
```

---

## Key Show Commands Reference

| Command | What It Shows |
|---|---|
| `show evpn instance` | EVPN instance status, VNI, interfaces |
| `show evpn database` | All MAC/IP entries learned via EVPN |
| `show evpn database extensive` | Detailed EVPN entries with route types |
| `show l2-learning vxlan-tunnel-end-point source` | Local VTEP info |
| `show l2-learning vxlan-tunnel-end-point remote` | Remote VTEPs discovered |
| `show ethernet-switching table` | MAC table with VTEP info |
| `show route table *.evpn.0` | EVPN routing table |
| `show interfaces vtep` | VTEP interface stats |
| `show evpn instance designated-forwarder` | DF election status per VLAN |
