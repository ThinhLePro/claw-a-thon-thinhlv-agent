# Fabric Architecture — Juniper Logical Solutions

> Source: Day One: Data Center Fundamentals — Colin Wrightson (Juniper Networks)

## Why Fabric Architecture?

Traditional STP-based networks have fundamental limitations:
- **Single active path** — at least half of bandwidth is idle (blocked ports)
- **Slow convergence** — topology changes take seconds to resolve (even RSTP)
- **Point-to-point LAG** — standard 802.3ad link aggregation is between two devices only

Juniper's fabric architectures solve these by **eliminating STP** and **utilizing 100% of available bandwidth**.

---

## Five Logical Architectures

Juniper offers 5 logical architectures on the same QFX physical platform:

| # | Architecture | Type | STP? | Management | Best For |
|---|---|---|---|---|---|
| 1 | **MC-LAG** | Open standard | Optional | Per-device | Simple HA, dual-homed servers |
| 2 | **Virtual Chassis** | Juniper | No | Single virtual device | Small DC, 2-10 switches |
| 3 | **Virtual Chassis Fabric (VCF)** | Juniper | No | Single virtual device | Medium DC, spine-leaf |
| 4 | **Junos Fusion** | Juniper | No | Single control point | Large DC, satellite model |
| 5 | **IP Clos Fabric** | Open standard | No (L3) | Per-device (automation) | Large DC, max scalability |

---

## 1. MC-LAG (Multi-Chassis LAG)

**Concept**: Two independent switches present a **single LAG endpoint** to downstream devices.

```
          ┌──────────┐
          │  Server   │
          └──┬────┬───┘
             │    │     ← Single LAG (ae0) from server perspective
        ┌────┘    └────┐
    ┌───┴───┐     ┌───┴───┐
    │Leaf A │─ICL─│Leaf B │  ← Two independent switches
    │       │     │       │     synchronized via ICCP
    └───────┘     └───────┘
```

- **ICCP** (Inter-Chassis Control Protocol) synchronizes state between peers
- **ICL** (Inter-Chassis Link) carries traffic between peers when needed
- Each switch is independently managed — separate configs, separate OS
- Use when: **dual-homed servers need active-active links** without full fabric

> See `/dc-juniper-mclag` for detailed MC-LAG configuration.

---

## 2. Virtual Chassis (VC)

**Concept**: Multiple switches behave as a **single logical switch** with one management IP.

```
    ┌──────────────────────────────────────┐
    │        Virtual Chassis (1 device)    │
    │  ┌────────┐ ┌────────┐ ┌────────┐   │
    │  │ Master │ │ Backup │ │ Line   │   │
    │  │(RE)    │ │(Standby│ │ Card   │   │
    │  │ QFX5100│ │ QFX5100│ │ QFX5100│   │
    │  └────────┘ └────────┘ └────────┘   │
    └──────────────────────────────────────┘
```

- One switch = **master** (routing engine), one = **backup**, rest = **line cards**
- Connected via **VC ports** (dedicated or repurposed uplinks)
- Max members: typically 10 switches
- Single configuration, single software image
- Use when: **small DC, few racks**, simplified management

### Limitations
- Software upgrades affect entire VC (unless ISSU supported)
- Failure domain is the entire VC
- Limited scale (10 members max)

---

## 3. Virtual Chassis Fabric (VCF)

**Concept**: Extends Virtual Chassis to a **spine-leaf topology** with automatic role assignment.

```
    ┌──────────────────────────────────────────────┐
    │             Virtual Chassis Fabric            │
    │                                               │
    │   ┌────────┐         ┌────────┐               │
    │   │ Spine  │ ←─VCF──→│ Spine  │   (auto-spine)│
    │   └──┬──┬──┘         └──┬──┬──┘               │
    │      │  │               │  │                   │
    │   ┌──┴──┴──┐ ┌─────┐┌──┴──┴──┐               │
    │   │ Leaf 1 │ │Leaf2││ Leaf 3 │  (auto-leaf)   │
    │   └────────┘ └─────┘└────────┘               │
    └──────────────────────────────────────────────┘
```

- Automatically detects **spine** and **leaf** roles based on connectivity
- Single management plane across all switches
- Eliminates STP entirely — uses ECMP across all spine paths
- Use when: **medium DC**, want spine-leaf benefits with simplified management

---

## 4. Junos Fusion

**Concept**: One **master switch** (aggregation device) controls multiple **satellite switches**.

```
                ┌──────────────┐
                │ Master       │
                │ (QFX10008)   │  ← Single control plane
                └──┬──┬──┬──┬─┘
                   │  │  │  │
    ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
    │Sat 1 │ │Sat 2 │ │Sat 3 │ │Sat N │  ← Satellites (QFX5100)
    └──────┘ └──────┘ └──────┘ └──────┘     act as remote line cards
```

- Satellites appear as **remote line cards** of the master
- All configuration, management, and forwarding decisions at the master
- Satellites run minimal firmware — upgraded from master
- Scales to **large numbers of satellite devices**
- Use when: **large DC**, want minimal satellite management, central control

---

## 5. IP Clos Fabric (IP Fabric)

**Concept**: Pure **Layer 3 spine-leaf** with BGP as the control protocol.

```
    ┌────────┐    ┌────────┐    ┌────────┐
    │Spine 1 │    │Spine 2 │    │Spine 3 │
    │  (BGP) │    │  (BGP) │    │  (BGP) │
    └┬─┬─┬─┬┘    └┬─┬─┬─┬┘    └┬─┬─┬─┬┘
     │ │ │ │      │ │ │ │      │ │ │ │
    eBGP sessions (point-to-point /31 links)
     │ │ │ │      │ │ │ │      │ │ │ │
    ┌┴─┴─┴─┴┐    ┌┴─┴─┴─┴┐    ┌┴─┴─┴─┴┐
    │ Leaf 1 │    │ Leaf 2 │    │ Leaf 3 │
    │  (BGP) │    │  (BGP) │    │  (BGP) │
    └────────┘    └────────┘    └────────┘
```

- **Every link is Layer 3** — no STP, no Layer 2 loops
- **eBGP** for underlay routing (point-to-point /31 links)
- **ECMP** across all spine paths — full bandwidth utilization
- Each device independently managed (automate with Ansible/Salt/Contrail)
- **VXLAN overlay** for Layer 2 extension across L3 underlay
- **EVPN** for MAC learning in overlay
- Use when: **large-scale DC**, maximum scalability, standard protocols

> See `/dc-juniper-evpn` for detailed EVPN-VXLAN configuration over IP Fabric.

---

## Architecture Selection Decision Tree

```
Scale?
├── Small (< 10 switches) → Virtual Chassis
├── Medium (10-50 switches)
│   ├── Want single management? → VCF or Junos Fusion
│   └── Want open standards? → IP Clos Fabric
├── Large (50-200+ switches) → IP Clos Fabric
└── Need dual-homing only? → MC-LAG (on any architecture)

Key Requirements?
├── Simplified management → VC, VCF, Junos Fusion
├── Maximum scale → IP Clos Fabric
├── Vendor-neutral → MC-LAG or IP Clos (open standards)
├── Multi-tenancy → IP Clos + EVPN-VXLAN
└── DCI (inter-DC) → IP Clos + EVPN-MPLS
```
