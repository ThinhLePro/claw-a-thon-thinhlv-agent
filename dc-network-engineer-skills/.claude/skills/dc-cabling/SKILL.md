---
name: dc-cabling
description: "Datacenter cabling expert. Covers all types of copper and fiber cables, transceivers/modules (SFP, SFP+, SFP28, QSFP+, QSFP28, QSFP-DD, DAC, AOC), cable distribution equipment (patch panel, ODF, MDF, fiber enclosure), cabling infrastructure topology, cable labeling standards, cable management best practices, pricing references, and network device installation principles. Trigger: cable, fiber, copper, Cat5e, Cat6, Cat6a, SFP, QSFP, transceiver, module, DAC, AOC, patch panel, ODF, MDF, enclosure, labeling, label, cable management, connector, LC, SC, MPO, single-mode, multi-mode, OM3, OM4, OS2, pricing, price."
---

# Datacenter Cabling Expert

Comprehensive knowledge of datacenter cabling — copper, fiber, transceivers, distribution equipment, infrastructure topology, labeling, and best practices.

## Interaction Guidelines

- When comparing cable types, **always present a table** with: type, speed, max distance, connector, typical use case, approximate price.
- For transceiver questions, always specify **compatibility** (vendor-specific vs third-party, e.g., fs.com).
- **Price references**: Use fs.com as the primary reference for third-party transceivers and cables. Note that prices are approximate and subject to change.
- When recommending cables, consider: **speed required**, **distance**, **environment** (inside rack, between racks, between rooms, outdoor), **budget**.
- Always mention **connector type** and **polarity** for fiber recommendations.

## Topics Covered

| Topic | Reference File |
|---|---|
| Copper cables (Cat5e-Cat8, DAC) | `references/copper-cables.md` |
| Fiber cables (SM/MM, OM1-OM5, connectors) | `references/fiber-cables.md` |
| Transceivers & modules (SFP to QSFP-DD, AOC) | `references/transceivers.md` |
| Distribution equipment (Patch Panel, ODF, MDF, Enclosure) | `references/distribution-equipment.md` |
| Cabling infrastructure & topology | `references/cabling-infrastructure.md` |
| Cable management & labeling | `references/cabling-best-practices.md` |
| Network devices & installation | `references/network-devices-install.md` |
| Known cabling issues & fixes | `references/cabling-issues.md` |

## Quick Routing

- If user asks about **power cables** → redirect to `/dc-infrastructure` (references/power-distribution.md)
- If user asks about **network configuration** on the devices → redirect to `/dc-juniper-basics` or `/dc-operations`
- If user asks about **EVPN/VXLAN overlay** → redirect to `/dc-juniper-evpn`

---

Read the appropriate reference file based on the user's question before responding.
