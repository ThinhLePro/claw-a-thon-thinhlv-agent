# DC Architectures — ToR vs EoR Design

> Source: Day One: Data Center Fundamentals — Colin Wrightson (Juniper Networks)

## Top-of-Rack (ToR) Architecture

One or two Ethernet switches installed **inside each rack** for local server connectivity.

```
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  Rack 1         │ │  Rack 2         │ │  Rack 3         │
│ ┌─────────────┐ │ │ ┌─────────────┐ │ │ ┌─────────────┐ │
│ │ ToR Switch  │─┼─┼─│ ToR Switch  │─┼─┼─│ ToR Switch  │ │──→ Spine
│ │ (Leaf)      │ │ │ │ (Leaf)      │ │ │ │ (Leaf)      │ │
│ ├─────────────┤ │ │ ├─────────────┤ │ │ ├─────────────┤ │
│ │ Server 1    │ │ │ │ Server 1    │ │ │ │ Server 1    │ │
│ │ Server 2    │ │ │ │ Server 2    │ │ │ │ Server 2    │ │
│ │ ...         │ │ │ │ ...         │ │ │ │ ...         │ │
│ └─────────────┘ │ │ └─────────────┘ │ │ └─────────────┘ │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

### Advantages
- **Simplified cabling**: All servers connect to in-rack switch, only fiber uplinks leave the rack
- **Modular deployment**: Each rack can be pre-built with switches and cabling, deployed as a unit
- **Easy upgrades**: Rack-by-rack approach — upgrade 1GbE→10GbE→40GbE by changing optics/switch only
- **Fault isolation**: Server swaps and upgrades affect only one rack
- **ISSU support**: In-service software upgrade on ToR switches minimizes disruption

### Limitations
- **Port waste**: 2x 48-port switches = 96 ports per rack; rarely fully utilized
- **Management sprawl**: 10 rows × 10 racks × 2 switches = 200 individually managed devices
- **Higher OpEx**: Each switch needs independent monitoring, config management

### Mitigations
- **Port waste** → Cross-connect servers between adjacent racks (24 ports each rack)
- **Management sprawl** → Use Virtual Chassis Fabric or Junos Fusion to virtualize control plane

### Uplinks
- Dual 10GbE or 40GbE fiber to spine/aggregation layer
- **Use fiber over copper** — supports future bandwidth upgrades without re-cabling
- QFX5100-48S: 6x QSFP+ (40GbE) uplinks, each breakable to 4x10GbE

---

## End-of-Row (EoR) Architecture

Two centralized switch cabinets at the **end of a row** aggregate server connections from all racks in that row.

```
┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐     ┌──────────────┐
│Rack 1 │ │Rack 2 │ │Rack 3 │ │Rack N │     │ EoR Cabinet  │
│ Srv 1 ├─┤ Srv 1 ├─┤ Srv 1 ├─┤ Srv 1 ├─────┤ QFX10008     │──→ Spine
│ Srv 2 │ │ Srv 2 │ │ Srv 2 │ │ Srv 2 │     │ (Leaf/Agg)   │
│ ...   │ │ ...   │ │ ...   │ │ ...   │     └──────────────┘
└───────┘ └───────┘ └───────┘ └───────┘
            Patch panels or direct cabling
```

### Advantages
- **Better port utilization**: Central switches serve all racks — fewer wasted ports
- **Fewer management points**: 2 switches per row vs 2 per rack
- **Easier to scale**: Add line cards to chassis vs replacing fixed switches
- **Richer features**: Chassis switches (QFX10008) support custom silicon, deeper buffers

### Limitations
- **Complex cabling**: Long cable runs from each server rack to EoR cabinet
- **Patch panels needed**: Intermediate structured cabling adds infrastructure cost
- **Single point of impact**: EoR switch issue affects entire row

### Best Product Fit
- **QFX10008** with 60S-6Q line cards: 60x 10GbE per card + 100GbE uplinks
- **QFX10016** for very large deployments

---

## Architecture Comparison

| Criteria | Top-of-Rack (ToR) | End-of-Row (EoR) |
|---|---|---|
| **Cabling complexity** | Low (in-rack only) | High (cross-rack runs) |
| **Port utilization** | Lower (unused ports per rack) | Higher (shared across racks) |
| **Management points** | Many (2 per rack) | Few (2 per row) |
| **Scalability model** | Add new rack = add new switches | Add line card to existing chassis |
| **CapEx per port** | Lower (fixed switches) | Higher (chassis switches) |
| **Resilience** | Per-rack isolation | Per-row scope |
| **Future-proofing** | Good (optics swap) | Better (line card swap) |
| **Recommended for** | Standard server racks, 10/25GbE | High-density racks, 40/100GbE |

---

## Spine-Leaf Topology (applies to both ToR and EoR)

Regardless of access architecture, the logical design follows **spine-leaf**:

```
        ┌─────────┐       ┌─────────┐
        │ Spine 1 │       │ Spine 2 │
        └─┬─┬─┬─┬─┘       └─┬─┬─┬─┬─┘
          │ │ │ │             │ │ │ │
    ┌─────┘ │ │ └────┐  ┌────┘ │ │ └─────┐
    │       │ │      │  │      │ │       │
  ┌─┴──┐ ┌─┴──┐  ┌──┴──┴─┐ ┌─┴──┐  ┌──┴──┐
  │Leaf│ │Leaf│  │ Leaf   │ │Leaf│  │Leaf │
  │ 1  │ │ 2  │  │  3     │ │ 4  │  │ 5   │
  └────┘ └────┘  └────────┘ └────┘  └─────┘
```

- **Leaf = ToR switch** (in ToR design) or **EoR chassis** (in EoR design)
- **Spine** = Aggregation — all leaf switches connect to all spines
- **Every leaf connects to every spine** — full mesh at aggregation layer
- **No leaf-to-leaf direct links** — all inter-leaf traffic goes through spines

> **Key principle**: The spine-leaf model stays the same regardless of ToR or EoR — only the leaf device type and cabling change.
