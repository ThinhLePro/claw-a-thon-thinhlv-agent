# Arbor Troubleshooting — Common Issues & Solutions

## 1. Sightline Issues

### Issue: Flow Ingestion Dropped / No Flow Data

**Symptoms**: Sightline dashboard shows 0 flows or significantly reduced flow rate. Alerts stop generating.

**Impact**: 🔴 **CRITICAL** — Sightline cannot detect attacks without flow data.

**Diagnostic Steps**:
```bash
# On Sightline CLI
/ services sp status                    # Overall health
/ services sp flow collectors           # Collector status
/ services sp flow stats                # Flow ingestion rate over time

# On the router sending flows
show sflow collector                    # sFlow collector status (Juniper)
show services flow-monitoring status    # J-Flow status (Juniper MX)
```

**Common Causes & Fixes**:

| Cause | Verification | Fix |
|---|---|---|
| **Router stopped sending flows** | `show sflow` on router — collector unreachable | Check routing to Sightline, verify sFlow config |
| **Firewall blocking flow packets** | tcpdump on Sightline management interface for UDP 6343/9996 | Open firewall for sFlow (UDP 6343) or NetFlow (UDP 9996) |
| **Sightline collector process crashed** | `/ services sp status` shows collector DOWN | Restart collector: `/ services sp restart collector` |
| **Disk full** | `/ system disk usage` | Purge old data, increase retention settings |
| **Network MTU issue** | sFlow/NetFlow packets fragmented and dropped | Ensure path MTU allows large flow packets (typically 1500 is fine) |
| **Wrong source IP on router** | Sightline expects flows from specific IP | Verify `agent-id` / `source-address` matches Sightline config |

---

### Issue: BGP Peer Down with Sightline

**Symptoms**: Sightline shows BGP peer status as DOWN. Traffic can't be attributed to Managed Objects.

**Impact**: 🟡 **HIGH** — Without BGP table, Sightline can't correctly classify traffic to customers/services.

**Diagnostic Steps**:
```bash
# On Sightline
/ services sp bgp peers                # Peer status
/ services sp bgp summary              # BGP summary

# On the router
show bgp summary | match <sightline-ip>
show bgp neighbor <sightline-ip> | match "State|Last"
```

**Common Causes & Fixes**:

| Cause | Fix |
|---|---|
| Router BGP config changed/deleted | Re-add BGP peer config on router |
| Sightline IP changed | Update BGP neighbor IP on router |
| TCP/179 blocked by firewall | Open TCP/179 between router and Sightline |
| AS number mismatch | Verify both sides use correct ASN |
| Authentication key mismatch | Verify TCP-MD5 key matches on both sides |

---

### Issue: False Positive Alerts (Alert gây nhiễu)

**Symptoms**: Sightline generates alerts for legitimate traffic (game launch, marketing campaign, CDN burst, backup job).

**Fixes** (in order of preference):

1. **Adjust MO threshold**: Increase bps/pps threshold to account for known legitimate spikes
2. **Adjust baseline learning**: Re-train baseline during a period that includes the legitimate spike
3. **Create alert filter**: Suppress alerts for known patterns (time-based, source-based)
4. **Whitelist sources**: Add known legitimate sources to whitelist
5. **Split Managed Object**: Create separate MOs for different services with different baselines

```
Sightline → Administration → Managed Objects → Edit "PROD-WEB"
→ Alert Settings → Severity Thresholds:
  - Auto detection: OFF (use manual thresholds)
  - bps High: 8 Gbps (was 5 Gbps — increase to match legitimate peak)
  - pps High: 5 Mpps (was 2 Mpps)
```

---

## 2. AED Issues

### Issue: AED Blocking Legitimate Traffic (False Positive)

**Symptoms**: Users report service unavailable. AED shows traffic being dropped. Service works when AED is bypassed.

**Impact**: 🔴 **CRITICAL** — Worse than a DDoS — AED itself is causing the outage!

**Immediate Actions**:
```
Option 1: Switch Protection Group to Monitor mode
  AED UI → Protection Groups → "PROD-WEB" → Mode: Monitor
  (Traffic passes through un-inspected)

Option 2: Disable specific countermeasure causing false positive
  AED UI → Protection Groups → "PROD-WEB" → Countermeasures
  → Find the triggered countermeasure → Disable or adjust threshold

Option 3: Bypass AED entirely (emergency — inline mode only)
  AED UI → System → Bypass → Enable bypass
  ⚠️ This passes ALL traffic un-inspected — use only in emergency
```

**Root Cause Investigation**:
```bash
# On AED CLI
services aed countermeasures stats "PROD-WEB"     # Which countermeasure is dropping most?
services aed blocked hosts "PROD-WEB"              # Which IPs are blocked?
services aed traffic top-sources "PROD-WEB"        # Are blocked sources legitimate?
```

**Common False Positive Causes**:

| Countermeasure | False Positive Scenario | Fix |
|---|---|---|
| **TCP SYN Auth** | Clients behind NAT/proxy can't complete SYN challenge | Whitelist NAT/proxy IPs, reduce SYN Auth aggressiveness |
| **HTTP Auth (JS Challenge)** | API clients, bots, curl — can't execute JavaScript | Whitelist API client IPs, use Cookie-based auth instead |
| **DNS Auth (Force TCP)** | Some DNS resolvers can't handle TCP retry | Whitelist known DNS resolvers |
| **Per-Source Rate Limit** | Legitimate high-volume source (CDN, backup server) | Increase per-source limit or whitelist the source |
| **GeoIP Blocking** | Legitimate users from blocked country | Refine GeoIP list, whitelist specific IPs |
| **Botnet Signatures** | Legitimate IP wrongly listed in threat intelligence | Whitelist the IP, report false positive to NETSCOUT |

---

### Issue: AED HA Failover Not Working

**Symptoms**: Primary AED fails but traffic doesn't switch to secondary. Dual outage.

**Diagnostic Steps**:
```bash
# On both AED nodes
system show ha                          # HA status on each node
system show ha history                  # Failover history
system show interfaces                  # HA interface UP?
```

**Common Causes & Fixes**:

| Cause | Fix |
|---|---|
| HA link DOWN (cable disconnected) | Check physical HA cable between AED units |
| HA config mismatch | Verify both nodes have same HA config (peer IP, virtual IP) |
| Split-brain (both think they're Active) | Fix HA link, restart HA service on one node |
| Config not synced | Manual sync: `system ha sync-config` |
| Software version mismatch | Both nodes must run same software version |

---

### Issue: AED Throughput Exceeds License

**Symptoms**: AED passes traffic un-inspected. `system show license` shows exceeded.

**Impact**: 🟡 **HIGH** — Unmitigated traffic during attack.

**Fixes**:
1. **Short-term**: Reduce monitored traffic (remove low-priority PGs, narrow protected prefixes)
2. **Medium-term**: Request license upgrade from NETSCOUT
3. **Long-term**: Supplement with router-based Flowspec/RTBH for volumetric attacks (AED handles application-layer attacks)

---

## 3. Integration Issues

### Issue: Sightline Cannot Trigger TMS/AED Diversion

**Symptoms**: Alert fires, auto-mitigation configured, but no diversion happens.

**Diagnostic Steps**:
```bash
# On Sightline
/ services sp mitigations list           # Is mitigation listed? What status?
/ services sp tms status                 # TMS/AED connectivity
/ services sp bgp peers                  # BGP peer for diversion route UP?
```

**Common Causes**:

| Cause | Fix |
|---|---|
| TMS/AED not registered in Sightline | Sightline Admin → TMS/AED Devices → Add device |
| BGP diversion route not being announced | Check BGP session between Sightline and edge router |
| Edge router not accepting diversion route | Check import policy on edge router for Sightline BGP |
| GRE tunnel down (return path) | Check GRE tunnel config and status on AED and router |
| Wrong mitigation template | Verify template matches the service type |

---

### Issue: GRE Return Tunnel Not Working (Out-of-Band)

In out-of-band mode, clean traffic returns from AED to the router via GRE tunnel.

**Symptoms**: Traffic diverted to AED but clean traffic doesn't reach the server. Black hole.

**Diagnostic Steps**:
```bash
# On AED
services aed diversion status               # Diversion state
services aed tunnel status                   # GRE tunnel status

# On Router
show interfaces gr-0/0/0                     # GRE tunnel interface UP?
show route <destination-prefix>              # Is route pointing to GRE tunnel?
ping <aed-gre-ip> source <router-gre-ip>    # Can reach AED via GRE?
```

**Common Causes**:

| Cause | Fix |
|---|---|
| GRE tunnel not configured on router | Configure GRE tunnel interface on router |
| MTU mismatch (GRE overhead) | Set GRE interface MTU to 1476 (1500 - 24 bytes GRE header) |
| Routing loop (diverted traffic re-diverted) | Ensure return route bypasses BGP diversion (use static route or routing instance) |
| Firewall blocking GRE (protocol 47) | Open GRE between AED and router |

---

## 4. Escalation Matrix

| Level | Condition | Action | Who |
|---|---|---|---|
| **L1** | Low/Medium alert, no service impact | Monitor, acknowledge alert | NOC / On-duty engineer |
| **L2** | High alert, potential service impact | Investigate, manual mitigation if needed | Senior network engineer |
| **L3** | Critical alert, confirmed service impact | Immediate mitigation (AED + RTBH), escalate to L4 if AED can't handle | Senior engineer + Team lead |
| **L4** | Attack exceeds AED capacity (>40 Gbps) | ISP upstream filtering, cloud scrubbing | Team lead + ISP contact |
| **Vendor** | AED/Sightline malfunction, software bug | Open TAC case with NETSCOUT | Senior engineer |

### NETSCOUT TAC Contact
```
NETSCOUT Support Portal: https://support.netscout.com
Phone (APAC): +65-6439-0200
Email: support@netscout.com
When opening a case, provide:
  - Serial number / device ID
  - Software version
  - Problem description + timestamps
  - Relevant logs (system logs, CLI output)
  - Network topology diagram
```

> **Quy tắc vàng (Golden rule)**: Khi AED gây false positive và block traffic hợp lệ, **ưu tiên khôi phục dịch vụ trước** (bypass AED hoặc switch PG to Monitor), sau đó mới điều tra và fix root cause. Đừng bao giờ để AED block production traffic trong khi đang troubleshoot.
