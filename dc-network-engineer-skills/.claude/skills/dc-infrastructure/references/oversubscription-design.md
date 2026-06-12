# Oversubscription Design — Bandwidth Planning for DC Networks

> Source: Day One: Data Center Fundamentals — Colin Wrightson (Juniper Networks)

## What Is Oversubscription?

**Oversubscription ratio** = Total bandwidth of incoming connections / Total bandwidth of uplinks

It defines how much bandwidth is shared among downstream ports competing for upstream capacity.

```
Example: 48 servers × 10GbE = 480 Gbps downstream
         4 uplinks × 40GbE  = 160 Gbps upstream
         Ratio = 480/160 = 3:1
```

---

## Common Oversubscription Ratios

| Ratio | Meaning | Typical Use |
|---|---|---|
| **1:1** (non-blocking) | Every port has full upstream bandwidth | Financial trading, HPC, storage |
| **2:1** | Half the ports can burst at full speed | High-performance web, database |
| **3:1** | Standard enterprise | General-purpose DC, mixed workloads |
| **4:1** | Moderate sharing | Email, file servers, low-priority apps |
| **8:1 or higher** | Heavy sharing | Dev/test environments, cold storage |

> **Rule of thumb**: Start with 3:1 at leaf-to-spine. Adjust based on actual traffic patterns. Monitor utilization and plan for growth.

---

## Design Example: DC1 (ToR, Small-Medium)

**Requirements**:
- Multiple rows, 10-20 racks each
- Servers at 10GbE
- Target: 3:1 oversubscription

### Leaf Layer (QFX5100-48S)
- 48x 10GbE server ports = **480 Gbps** downstream
- 6x 40GbE uplinks = **240 Gbps** upstream (but not all used)
- Using 4x 40GbE uplinks = **160 Gbps** upstream
- Ratio: 480/160 = **3:1** ✅

### Spine Layer
- Each spine aggregates all leaf uplinks from a row
- With 10 racks/row × 4 uplinks = 40x 40GbE per spine
- QFX5100-24Q (24x 40GbE) or QFX10002 for spine role

---

## Design Example: DC2 (EoR, Large)

**Requirements**:
- 10 rows, 10 racks each, 100 servers per rack (blade chassis)
- Servers at 10GbE
- Target: **2.5:1** (high performance)

### Leaf Layer (QFX10008 at EoR)
- 100 servers × 10GbE = **1000 Gbps** per row (across multiple racks)
- Using 60S-6Q line cards: 2 cards per leaf = 120x 10GbE ports
- Uplinks: 2x 100GbE per line card = **400 Gbps** per leaf
- Ratio: 500/200 = **2.5:1** ✅

### Spine Layer (QFX10008)
- 10 rows × 4 × 100GbE = 40× 100GbE per spine
- Line card options:
  - **36Q**: 12x 100GbE per card (cost-effective, need 4 cards)
  - **30C**: 30x 100GbE per card (performance, need 2 cards)

---

## Oversubscription at WAN Layer

Apply the **75/25 traffic split** rule:
- **75% traffic stays local** (east-west, within the DC)
- **25% traffic exits to WAN** (north-south)

```
If spine-to-spine bandwidth = 800 Gbps
WAN uplink needed = 800 × 0.25 = 200 Gbps
Options: 5× 40GbE or 2× 100GbE to WAN routers
```

---

## Calculation Framework

```
Step 1: Count server connections and speeds
        → Total downstream bandwidth

Step 2: Define target oversubscription ratio
        → Required upstream bandwidth = downstream / ratio

Step 3: Select uplink speed and count
        → E.g., 160 Gbps = 4× 40GbE or 2× 100GbE (with headroom)

Step 4: Select switch models that support those port counts
        → Match line cards and form factors

Step 5: Plan for growth (add years × growth rate)
        → Ensure switch supports higher speed optics for future
```

### Key Considerations

| Factor | Impact on Ratio |
|---|---|
| **Burst traffic patterns** | Lower ratio needed (2:1 or less) |
| **East-west heavy** (VM-to-VM) | May need 1:1 at leaf, less at spine |
| **North-south heavy** (client-server) | Higher ratios acceptable at leaf |
| **Storage traffic** (iSCSI, NFS) | Dedicated low-ratio paths recommended |
| **Future growth** | Plan for 2-3x capacity within switch platform |

> **Anti-pattern**: Don't design for peak theoretical throughput — design for actual traffic patterns. Measure first, then set ratios.

---

## Quick Reference: Port Speed vs Breakout

| Native Port | Breakout Options |
|---|---|
| QSFP+ (40GbE) | 4× 10GbE (with breakout cable) |
| QSFP28 (100GbE) | 4× 25GbE or 2× 50GbE |
| QSFP56-DD (400GbE) | 4× 100GbE or 8× 50GbE |

Breakout cables are critical for matching server speeds to uplink capacity without wasting high-speed ports.
