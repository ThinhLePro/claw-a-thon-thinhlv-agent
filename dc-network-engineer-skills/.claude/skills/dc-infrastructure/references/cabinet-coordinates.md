# Cabinet Coordinate System

## Standard Naming Convention

Datacenter cabinets are identified using a **row-column coordinate system**, similar to a grid. The exact convention varies by DC operator, but the following is the most common approach.

### Format: `<Row><Column>`

- **Row**: Identified by a **letter** (A, B, C, …) or a **number** (01, 02, 03, …)
- **Column**: Identified by a **number** (01, 02, 03, …) indicating position within the row

### Examples
```
A01  A02  A03  A04  A05  ...  A20      ← Row A
B01  B02  B03  B04  B05  ...  B20      ← Row B
C01  C02  C03  C04  C05  ...  C20      ← Row C
...
```

### Alternate Formats
Some DCs use:
- `Row.Cabinet`: e.g., `A.01`, `B.15`
- `Hall-Row-Cabinet`: e.g., `H1-A-01` (Hall 1, Row A, Cabinet 01)
- `Floor-Room-Row-Cabinet`: e.g., `2F-R1-A-01`

## Numbering Direction

- **Rows**: Usually lettered from one end of the hall to the other (e.g., A closest to the entrance, Z furthest).
- **Columns**: Numbered from left to right (when facing the front of the row), starting from 01.
- **Odd cabinets** often face one direction, **even cabinets** face the other — this creates the hot aisle / cold aisle alternation.

## Network Operations Relevance

Knowing cabinet coordinates is essential for:
1. **Cabling documentation**: "Patch cable from `A05` port Gi0/1 to `B03` port Gi0/24"
2. **Incident response**: "Device in cabinet `C12` showing high temperature alarm"
3. **Capacity planning**: "Remaining power capacity in row D"
4. **Physical access**: Directing field engineers to the correct location

## Typical DC Floor Plan (Simplified)

```
┌──────────────────────────────────────────────────────────────┐
│  ENTRANCE                                                     │
│                                                               │
│  [MDF]    ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐              │
│           │A01│ │A02│ │A03│ │A04│ │A05│ │A06│  Row A         │
│  [ODF]    └───┘ └───┘ └───┘ └───┘ └───┘ └───┘              │
│           ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐              │
│           │B01│ │B02│ │B03│ │B04│ │B05│ │B06│  Row B         │
│           └───┘ └───┘ └───┘ └───┘ └───┘ └───┘              │
│  [CRAC]   ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐ ┌───┐              │
│           │C01│ │C02│ │C03│ │C04│ │C05│ │C06│  Row C         │
│           └───┘ └───┘ └───┘ └───┘ └───┘ └───┘              │
│                                                    [CRAC]    │
│  [PDU/RPP]                                                    │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

> [VNG-SPECIFIC] The specific coordinate system, row naming, and floor plan layout for VNG's DC TTEPZ should be documented here when available.
