# Cable Management & Labeling Best Practices

## 1. Cable Management Principles

### The Golden Rules

1. **Every cable must be traceable** — from source port to destination port, without ambiguity
2. **Every cable must be labeled** — both ends, immediately upon installation
3. **Every cable must follow a defined path** — no "spaghetti" / random routing
4. **Every unused port must be capped** — dust caps for fiber, blank inserts for copper panels
5. **Service loops** — leave 1-2m extra cable neatly coiled at each end for future re-termination

### Cable Routing Rules

| Rule | Rationale |
|---|---|
| Route cables through cable managers, never across open space | Prevents damage, maintains airflow |
| Use **velcro straps**, not cable ties (zip ties) | Velcro is reusable, doesn't crush cables, easier to modify |
| Maintain **minimum bend radius** (typically 4× OD for copper, 10× OD for fiber) | Prevents signal degradation and cable damage |
| Keep copper and fiber **separated** in the cable manager | Different bend radius requirements, easier identification |
| Keep **power and data cables separated** | EMI from power cables can affect data signals (especially for Cat5e/Cat6 UTP) |
| **Waterfall** cables down the vertical manager — don't force horizontal turns | Natural bend, easier to manage |
| Remove all **dead cables** immediately | Dead cables waste space, create confusion, obstruct airflow |

### Horizontal Cable Management

Between every patch panel and switch, install a **1U horizontal cable manager**:

```
┌──────────────────────────────────────┐
│  Patch Panel (24-port Cat6a)         │  ← 1U
├──────────────────────────────────────┤
│  Horizontal Cable Manager            │  ← 1U (brush panel or D-ring)
├──────────────────────────────────────┤
│  Switch (e.g., QFX5110-48S)          │  ← 1U
└──────────────────────────────────────┘
```

**Types**:
- **Brush panel**: Has brush strips — cables pass through, dust blocked. Simple, cheap.
- **D-ring panel**: Metal D-rings for securing cable bundles. More structured.
- **Finger panel**: Plastic fingers that separate individual cables. Best organization.

### Vertical Cable Management

On **both sides** of every rack:

- Use **finger-style** vertical managers (plastic fingers that open/close)
- Route left-side for data, right-side for power (or any consistent convention)
- Do not over-fill — maintain 50% capacity for future additions
- Use velcro wraps every 30-50cm to bundle cables neatly

---

## 2. Cable Labeling Standards

### Label Format

The most practical format for DC environments:

```
<Source-Device>:<Source-Port> → <Dest-Device>:<Dest-Port>
```

**Examples**:
```
LEAF-A01-01:xe-0/0/0 → SPINE-01:xe-0/0/0     (switch-to-switch fiber)
LEAF-A01-01:ge-0/0/24 → SRV-A01-U20:eth0      (switch-to-server copper)
PP-A01:F01 → ODF-ROW-A:P01                      (patch panel to ODF)
```

### Simplified Label (for the cable itself)

Since labels on cables have limited space, use a shortened format:

```
<Rack>-<Port> ↔ <Rack>-<Port>
```

**Example on the cable label**:
```
A01-xe0/0/0 ↔ SPINE1-xe0/0/0
```

### What to Label

| Component | Label Content | Label Location |
|---|---|---|
| **Patch cord (both ends)** | Source:Port → Dest:Port | Wrap-around flag label, 15cm from connector |
| **Trunk cable (both ends)** | Cable ID, fiber count, source ODF → dest ODF | Wrap-around label near entry point |
| **Patch panel port** | Port number + connected device | Below/above each port on the panel |
| **Switch port** | Usually pre-labeled by manufacturer | Add custom labels if using aliases |
| **Power cable (both ends)** | PDU-A or PDU-B, circuit number | Wrap-around flag label |
| **Rack PDU** | "PDU-A" / "PDU-B", feed source | Front label on the PDU |
| **Rack itself** | Cabinet coordinate (e.g., A01) | Top of rack, both front and rear |

### Label Types

| Type | Material | Use | Durability |
|---|---|---|---|
| **Self-laminating wrap-around** | Vinyl with clear laminate | Patch cords, trunk cables | Excellent (5+ years) |
| **Flag label** | Vinyl flag that wraps around cable | Best for round cables | Excellent |
| **Adhesive label** | Paper/vinyl stick-on | Patch panel ports, rack labels | Good (may peel in heat) |
| **Heat-shrink label** | Printed heat-shrink tubing | Permanent cables | Excellent |
| **Printed cable tie** | Nylon with print area | Bundle labels | Good |

### Label Colors (Convention)

Using color-coded labels helps quick visual identification:

| Color | Meaning |
|---|---|
| **Blue** | Production network / data plane |
| **Yellow** | Management network / OOB |
| **Red** | Power / A-feed |
| **Orange** | Power / B-feed |
| **Green** | Customer / colocation |
| **White** | General / unclassified |
| **Purple** | Storage network (FC, iSCSI) |

### Label Printer
- **Brother P-Touch** (e.g., PT-E550W) — most common in DC environments
- **Brady BMP21** — industrial grade, excellent for harsh environments
- Use **TZe** tapes for Brother, **cartridges** for Brady
- Always use **laminated** tape for DC environments (heat, humidity)

---

## 3. Cable Management Step-by-Step (New Installation)

### Before Installing Cables
1. **Plan the cable path**: Document source, destination, path, cable type, label
2. **Pre-label both ends** of every cable before pulling
3. **Verify cable length**: Measure the path (including vertical drops and slack), add 1-2m for service loop
4. **Check inventory**: Ensure correct cable type and connector for the speed required

### During Installation
1. Route cable through the **designated pathway** (cable tray → vertical manager → horizontal manager → port)
2. **Maintain bend radius** at every turn
3. **Dress cables neatly**: Use velcro to bundle, leave consistent slack
4. **Connect both ends** and verify link light / status

### After Installation
1. **Verify connectivity**: `show interfaces terse` on Juniper, check link status
2. **Test the cable**: For fiber, check DOM values (`show interfaces diagnostics optics`); for copper, check error counters
3. **Update documentation**: Record in cable database / spreadsheet / DCIM
4. **Take a photo**: Before-and-after for audit trail

---

## 4. Cable Organization Patterns

### The "Waterfall" Pattern
Cables drop vertically from the cable tray into the rack through the vertical manager, then route horizontally to the equipment.

```
Cable Tray (overhead)
═══════════════════════
        │
        ▼ (cables drop down)
   ┌─────────┐
   │Vertical │
   │Cable    │
   │Manager  │ ← Cables waterfall down
   │         │
   └────┬────┘
        │
   ┌────┴────┐
   │Horizontal│ ← Cables route to ports
   │Manager   │
   └─────────┘
```

### The "Service Loop"
Extra cable coiled neatly at the top or bottom of the rack, secured with velcro. Allows re-termination or rack repositioning without re-pulling.

```
Service loop (coiled, secured with velcro)
   ╭───────╮
   │ ○○○○○ │  ← 1-2m extra, neatly coiled
   ╰───┬───╯
       │
       ▼ (to equipment)
```

### Fiber vs Copper Separation

```
┌──────────────────────────────┐
│  Left Vertical Manager       │  ← Fiber cables (to ODF, other racks)
│                              │
│         [RACK]               │
│                              │
│  Right Vertical Manager      │  ← Copper cables (to servers)
└──────────────────────────────┘
```

Or alternatively:
- Front of vertical manager = Data cables
- Rear of vertical manager = Power cables

---

## 5. Common Cable Management Mistakes

| Mistake | Problem | Fix |
|---|---|---|
| Using zip ties instead of velcro | Crushes cables, hard to modify, cuts skin | Switch to velcro wraps |
| Unlabeled cables | Impossible to trace, causes wrong disconnections | Label both ends during installation |
| Dead cables left in place | Wastes space, confusion, blocks airflow | Remove immediately when decommissioned |
| Cables crossing the hot/cold aisle on floor | Trip hazard, blocks airflow | Route through overhead tray |
| Exceeding minimum bend radius | Signal loss, CRC errors, physical damage | Re-route with proper radius |
| Mixing A-feed and B-feed cables together | Confusion during maintenance, risk of disconnecting both feeds | Use separate paths and color coding |
| No service loop | Cannot re-terminate or move equipment | Always leave 1-2m slack |
| Patch cords too long (excess bundled behind rack) | Blocks airflow, messy | Use correct-length cables |
| No documentation | No one knows what connects where | Update DCIM / spreadsheet after every change |
