# Cabling Infrastructure & Topology in the Datacenter

## 1. End-to-End Cable Path

The complete cable path from an external provider to a server port:

```
                     OUTDOOR                              INDOOR
┌──────────────┐    ┌──────────┐    ┌──────┐    ┌──────┐    ┌──────┐    ┌──────────┐
│ ISP / Carrier │───→│ Handhole │───→│ MDF  │───→│ ODF  │───→│Patch │───→│ Equipment│
│ (fiber plant) │    │ / Vault  │    │ Room │    │(rack)│    │Panel │    │  (switch) │
└──────────────┘    └──────────┘    └──────┘    └──────┘    └──────┘    └──────────┘
      │                   │              │           │           │            │
   Loose tube        Underground     Fusion      Trunk/      Patch         Port
   fiber cable       conduit/duct    splice to   pre-term    cord
   (outdoor)                         pigtails    fiber       (LC-LC)
```

### Component Connections

| Segment | Cable Type | Termination | Notes |
|---|---|---|---|
| Carrier → Handhole | Loose tube, armored | Splice closure | Underground or aerial |
| Handhole → MDF | Loose tube, riser-rated | Splice to ODF pigtails | Through conduit, fire-rated |
| MDF ODF → Rack ODF | Pre-terminated trunk (MPO or LC) | Plug-in connectors | Through cable tray/ladder |
| Rack ODF → Switch | Patch cord (LC-LC or MPO) | Plug-in connectors | Short, 1-3m typically |
| Switch → Server (copper) | Cat6a patch cord | RJ45 plug | Through patch panel |
| Switch → Server (fiber/DAC) | DAC, AOC, or fiber patch | SFP/QSFP | Direct or through fiber panel |

---

## 2. Cable Pathway Infrastructure

### Cable Tray (Overhead)

The most common cable pathway in modern DCs. Trays run above the racks.

```
        Cable Tray (overhead, above racks)
═══════════════════════════════════════════════
   │         │         │         │         │
   ▼         ▼         ▼         ▼         ▼
┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
│Rack │  │Rack │  │Rack │  │Rack │  │Rack │
│ A01 │  │ A02 │  │ A03 │  │ A04 │  │ A05 │
└─────┘  └─────┘  └─────┘  └─────┘  └─────┘
```

**Types**:
- **Ladder tray**: Open rungs — best airflow, easy cable laying, most common in DC
- **Basket tray (wire mesh)**: Open mesh — flexible routing, lighter weight
- **Solid bottom tray**: For EMI protection or outdoor — restricts airflow

**Rules**:
1. **Separate power and data cables** — use different trays or different sides of the same tray
2. **Fill ratio**: Never exceed 50% fill capacity (leave room for future cables and airflow)
3. **Bend radius**: Maintain minimum bend radius at turns (typically 10× cable OD for copper, specific to fiber type for optics)
4. **Fire rating**: Use plenum-rated cables (CMP/OFNP) if running above suspended ceiling; riser-rated (CMR/OFNR) for vertical runs

### Under-Floor (Raised Floor)

Some DCs route cables under a raised floor (legacy approach, less common in new builds).

**Considerations**:
- Cables can obstruct airflow from CRAC units (cold air passes through the raised floor plenum)
- Use cable troughs or baskets under the floor to keep organized
- **Modern DCs prefer overhead tray** to keep the floor plenum clear for airflow

### Vertical Cable Management

Cables enter/exit racks through vertical cable managers on the sides of the rack.

- **Finger-style**: Plastic fingers that hold cables — easy to add/remove
- **D-ring style**: Metal D-rings welded to a channel — sturdy, high capacity
- **Full-height**: Dedicated vertical channel with cover — best organization

---

## 3. Outdoor Cable Entry

### How Contractors Bring Fiber Into the DC

```
Carrier POP / Street ──→ Underground conduit ──→ Handhole/Vault ──→ Building entry ──→ MDF
                              │                        │                   │
                        Duct bank               Splice or pull          Fire-stop
                        (PVC/HDPE)              through point           penetration
```

**Step-by-step**:

1. **Duct bank / Conduit**: Underground PVC or HDPE conduit system connects the DC to external provider POPs or the street. Multiple conduits (typically 2-4" each) for redundancy.

2. **Handhole / Vault**: Underground access points where cables can be spliced, pulled, or re-directed. Located at turns, intersections, or every ~100m.

3. **Building penetration**: Cables enter the building through a sealed penetration in the wall/foundation.
   - Must be **fire-stopped** (firestop putty, foam, or mortar) per code (NFPA 70/75)
   - Must be **water-sealed** for underground entries

4. **Cable tray to MDF**: Inside the building, cables route through riser trays to the MDF room.

5. **MDF termination**: Cables are terminated (fusion spliced to pigtails) in the MDF's ODF frames.

### Redundancy
- **Diverse entry**: Critical DCs have **two or more physically separated cable entry points** from different sides of the building
- **Diverse paths**: External conduits should follow different physical routes to avoid single-point-of-failure (e.g., different streets)

---

## 4. Cable Distribution Layout in the DC

### Typical Layout

```
┌──────────────────────────────────────────────────────────────┐
│                        DATA HALL                              │
│                                                               │
│  ┌─────┐                                          ┌─────┐   │
│  │ MDF │ ═══════════ Main Cable Tray ══════════════│ MDF │   │
│  │     │         (overhead, running E-W)           │(2nd)│   │
│  └─────┘              │    │    │    │              └─────┘   │
│                       │    │    │    │                         │
│     Row trays (N-S)   ▼    ▼    ▼    ▼                       │
│                    ┌────┐┌────┐┌────┐┌────┐                  │
│  Distribution  ──→ │ODF ││ODF ││ODF ││ODF │ ← End-of-Row    │
│  Racks             │/PP ││/PP ││/PP ││/PP │    Distribution  │
│                    └────┘└────┘└────┘└────┘    Racks          │
│                       │    │    │    │                         │
│                    ┌────┐┌────┐┌────┐┌────┐                  │
│                    │ A01││ A02││ A03││ A04│ ← Equipment Racks │
│                    └────┘└────┘└────┘└────┘                  │
│                    ┌────┐┌────┐┌────┐┌────┐                  │
│                    │ B01││ B02││ B03││ B04│                   │
│                    └────┘└────┘└────┘└────┘                  │
│                       ...                                     │
└──────────────────────────────────────────────────────────────┘
```

### Distribution Models

| Model | Description | Pros | Cons |
|---|---|---|---|
| **Top-of-Row (ToR)** | Each rack has its own switch; fiber runs to aggregation | Simple, short copper runs | Many switches, many fiber runs |
| **End-of-Row (EoR)** | Switches in dedicated racks at row ends; copper runs to equipment racks | Fewer switches, centralized | Long copper runs (may exceed Cat6a limits) |
| **Middle-of-Row (MoR)** | Switches in the middle of the row | Balanced cable lengths | Less common |
| **Structured cabling** | All cables terminate to patch panels/ODF; patching provides flexibility | Most flexible, clean | More patch panels, more cross-connects |

### Position of Distribution Equipment

| Equipment | Location | Purpose |
|---|---|---|
| **MDF** | Dedicated room near building entrance | External cable termination, ISP hand-off |
| **Core/Spine ODF** | Central location or MDF room | Terminates backbone fiber (spine ↔ leaf) |
| **Row ODF** | End-of-row distribution rack (or first rack in row) | Terminates fiber within a row |
| **Rack patch panel** | Inside each equipment rack | Copper termination for servers in that rack |
| **Meet-me room** | Adjacent to MDF or separate | Where multiple carriers interconnect |

---

## 5. Inter-Building / Campus Cabling

For multi-building DC campuses:

| Path | Cable Type | Typical Count | Protection |
|---|---|---|---|
| Building A → Building B | OS2 single-mode, armored | 48-144 fibers | Underground conduit, armored jacket |
| Building → Guard house | Cat6a or fiber | 2-12 fibers + copper | Conduit |
| Building → Generator yard | Copper (control) + fiber | Varies | Conduit, weather-rated |

### Rules for Outdoor Fiber
1. Use **armored loose-tube cable** (rodent protection, moisture barrier)
2. Always **pull extra slack** at each end (10-15m loop inside building for re-termination)
3. **Label both ends** of every fiber strand
4. **Document the path** in an as-built drawing
5. **Test with OTDR** after installation to verify splice loss and detect faults
