# Common Cabling Issues & Solutions

## 1. Fiber Issues

### Issue: High CRC / FCS Errors on Fiber Link

**Symptoms**: `show interfaces extensive` shows increasing `Input errors`, `FCS errors`, or `CRC errors`. Link may be up but with degraded performance.

**Common Causes**:
1. **Dirty connector** — most common cause (80%+ of fiber issues)
2. **Bent fiber** — exceeding minimum bend radius
3. **Bad splice** — high loss at a fusion splice point
4. **Incompatible transceivers** — wrong wavelength, wrong fiber type (SM optic on MM fiber)
5. **Damaged fiber** — crushed, stretched, or broken fiber core

**Diagnostic Steps**:
```junos
# 1. Check error counters
show interfaces xe-0/0/0 extensive | match "error|CRC|FCS"

# 2. Check DOM (Digital Optical Monitoring)
show interfaces diagnostics optics xe-0/0/0
# Key values:
#   Rx Power: should be within transceiver spec (e.g., -1 to -18 dBm for 10G SR)
#   If Rx Power is very low (e.g., < -20 dBm): dirty/broken fiber or bad connector
#   If Rx Power is "- Inf" or 0: no light received — fiber disconnected or broken

# 3. Compare both ends
# Check DOM on BOTH ends of the link — if one end has low Rx, the OTHER end's Tx or the fiber in between is the problem
```

**Resolution**:
1. **Clean connectors** — use a fiber cleaning pen (IBC One-Click) on both connectors and transceiver ports
2. **Inspect with scope** — use a fiber inspection microscope to check connector end-face for contamination, scratches, or cracks
3. **Swap transceiver** — try a known-good transceiver to rule out optic failure
4. **Test fiber** — use OTDR or optical power meter to test the fiber path
5. **Re-route** — if fiber is physically damaged, replace the patch cord or re-splice the trunk

---

### Issue: Link Flapping on Fiber

**Symptoms**: Interface alternates between Up and Down. Syslog shows rapid `LINK_UP`/`LINK_DOWN` events.

**Common Causes**:
1. **Marginal Rx power** — just at the edge of receiver sensitivity (intermittent detection)
2. **Loose connector** — not fully seated in the transceiver cage
3. **Failing transceiver** — degraded laser output
4. **Fiber microbend** — cable pinched by cable tray cover or heavy cable bundle

**Resolution**:
1. Verify Rx power stability — if it's near the receiver sensitivity limit, clean connectors or replace fiber
2. Re-seat the transceiver and fiber connectors firmly
3. Check for physical pressure on the fiber (remove any pinch points)
4. Swap transceiver to a known-good unit

---

## 2. Copper Issues

### Issue: Link Down or Stuck at Lower Speed

**Symptoms**: 10G Cat6a link comes up at 1G, or doesn't come up at all.

**Common Causes**:
1. **Wrong cable category** — Cat5e or Cat6 used instead of Cat6a for 10G (Cat6 only supports 10G to 55m)
2. **Cable length exceeds spec** — over 100m for Cat6a, or over 55m for Cat6 at 10G
3. **Bad crimp / punch-down** — one or more wire pairs not making contact
4. **Crosstalk** — unshielded cable in a high-density bundle

**Resolution**:
1. Verify cable category — check the jacket printing (e.g., "CAT6A F/UTP")
2. Measure cable length — use cable tester or TDR
3. Re-terminate — re-crimp or re-punch the connector/panel
4. For Cat6a shielded: verify grounding at both ends

---

### Issue: PoE Not Working

**Symptoms**: PoE device (IP phone, camera, AP) doesn't power on.

**Common Causes**:
1. **PoE not enabled on port** — configuration missing
2. **Power budget exceeded** — switch PoE budget fully allocated
3. **Wrong cable** — PoE requires all 4 pairs; some old cables only have 2 pairs wired
4. **Cable too long** — PoE voltage drops over distance, may not reach device

**Resolution**:
1. Enable PoE: `set poe interface ge-0/0/X` (Juniper EX)
2. Check power budget: `show poe controller` / `show poe interface`
3. Use Cat6a (all 4 pairs, better power delivery characteristics)

---

## 3. Labeling & Documentation Issues

### Issue: Cables Not Labeled → Wrong Disconnection

**Symptoms**: During maintenance, the wrong cable is disconnected, causing an outage for an unrelated system.

**Prevention**:
1. **Label every cable at installation** — both ends, immediately
2. **Use color-coded labels** — visually distinguish production, management, power
3. **Trace before disconnect** — always visually trace and verify at both ends before unplugging
4. **Update documentation** — cable database/DCIM must reflect reality

### Issue: Cable Documentation Doesn't Match Reality

**Symptoms**: DCIM/spreadsheet says port X connects to device Y, but physically it connects to device Z.

**Root Cause**: Documentation not updated after moves/adds/changes (MAC operations).

**Fix**:
1. **Audit cables periodically** — walk-through verification quarterly
2. **Enforce documentation updates** as part of every change ticket
3. **Use discovery tools** — LLDP, CDP, `show lldp neighbors` to verify logical vs physical mapping

```junos
# Verify what's connected to a port via LLDP
show lldp neighbors interface xe-0/0/0
# Shows: Remote system name, port, chassis ID
```

---

## 4. Environmental Issues

### Issue: Equipment Overheating Due to Cabling

**Symptoms**: High temperature alarms on switches. Fans running at max speed.

**Common Causes**:
1. **Cable bundles blocking airflow** — large cable bundles in front of air intakes
2. **Missing blanking panels** — hot air recirculating through empty U spaces
3. **Cable density too high** in vertical manager — blocking side airflow

**Resolution**:
1. Re-route cables to avoid blocking air intake/exhaust
2. Install blanking panels in all unused U spaces
3. Upgrade to wider vertical cable managers if density is high
4. Use thinner cables (slim-fit Cat6a, or switch to fiber/DAC for less bulk)

---

## 5. Lessons Learned (Standard DC Context)

| Issue | Impact | Root Cause | Prevention |
|---|---|---|---|
| Dirty fiber connector on spine uplink | 50% of leaf lost connectivity | No cleaning during installation | Mandate fiber inspection before every connection |
| Wrong polarity on MPO trunk | 40G link down between ODF | Type A trunk used where Type B expected | Standardize on Type B, verify polarity before deployment |
| Cat6 used for 10G link >55m | Link flapping, CRC errors | Installer used Cat6 instead of Cat6a | Verify cable category on jacket, test with certifier |
| Power cable labeled incorrectly | Wrong device powered off during maintenance | Labels swapped at installation | Double-verify labels at both ends before signing off |
| No service loop on trunk fiber | Could not re-terminate after connector damage | Installer pulled cable tight with no slack | Always leave 10-15m slack at each end |
| Outdoor fiber cut during construction | Multi-ISP outage | Fiber duct not documented in site drawings | Maintain accurate as-built drawings, use duct markers |
| Transceiver overheating in top-of-rack position | Intermittent link flaps on hottest days | Top of rack is hottest spot, no additional cooling | Move optic-heavy equipment lower in rack, improve cooling |

> **Key takeaway**: The majority of cabling issues (especially fiber) are caused by **contamination**, **documentation gaps**, or **wrong cable/optic selection**. A disciplined process for cleaning, labeling, and documentation prevents 90% of cabling incidents.
