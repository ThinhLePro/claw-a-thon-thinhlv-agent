# Containment — Hot Aisle / Cold Aisle & Airflow Management

## 1. The Problem: Mixing Hot and Cold Air

Without containment, hot exhaust air from servers mixes with cold supply air in the data hall. This:
- **Reduces cooling efficiency** (CRAC/CRAH must work harder)
- **Creates hot spots** (some racks don't get enough cold air)
- **Wastes energy** (PUE increases)

## 2. Hot Aisle / Cold Aisle Layout

The fundamental principle: arrange racks so that all server **intakes face the cold aisle** and all **exhausts face the hot aisle**.

```
                    Cold Aisle                Hot Aisle               Cold Aisle
                 ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
  Perforated     │  ← intake   │          │  exhaust →  │          │  ← intake   │
  floor tiles    │   [Server]  │          │  [Server]   │          │   [Server]  │
  deliver cold   │   [Server]  │          │  [Server]   │          │   [Server]  │
  air here       │   [Server]  │          │  [Server]   │          │   [Server]  │
                 │  ← intake   │          │  exhaust →  │          │  ← intake   │
                 └─────────────┘          └─────────────┘          └─────────────┘
                    Row A (front)            Row A (back)  Row B (back)   Row B (front)
```

### Rules
- Racks in the **same row** face the **same direction**.
- **Adjacent rows** face **opposite directions** (front-to-front = cold aisle, back-to-back = hot aisle).
- Perforated floor tiles go **only in cold aisles**.
- Solid floor tiles go **in hot aisles** (no cold air wasted here).

## 3. Containment Types

### Cold Aisle Containment (CAC)
- **What**: Enclose the cold aisle with doors/roof panels so cold air stays contained.
- **How**: End-of-row doors + roof panels (or curtains) seal the cold aisle.
- **Result**: Cold supply air goes directly to server intakes with minimal mixing.
- **Advantages**:
  - Data hall ambient becomes the hot return temperature (~35°C)
  - Allows higher CRAH return temperature → more efficient
  - Simple to implement
- **Disadvantages**:
  - Walking in hot ambient can be uncomfortable
  - Fire suppression considerations (contained space)

### Hot Aisle Containment (HAC)
- **What**: Enclose the hot aisle with doors/roof panels, ducting hot air directly back to CRAH return.
- **How**: End-of-row doors + roof/chimney panels seal the hot aisle, often with ductwork to CRAH.
- **Result**: Hot exhaust is captured at source, data hall remains cool.
- **Advantages**:
  - Data hall ambient stays cool (comfortable to work in)
  - Most efficient (hot air goes directly to CRAH)
- **Disadvantages**:
  - More complex to build (ductwork)
  - Higher upfront cost

### Comparison

| Aspect | Cold Aisle Containment | Hot Aisle Containment |
|---|---|---|
| Data hall temperature | Hot (~30-35°C) | Cool (~20-25°C) |
| Comfort for staff | Less comfortable | More comfortable |
| Cooling efficiency | Good | Best |
| Implementation cost | Lower | Higher |
| Complexity | Simpler | More complex |
| Common in | Most DCs | Premium / high-density DCs |

## 4. Blanking Panels

- **What**: Filler panels that cover unused U spaces in a rack.
- **Why critical**: Without blanking panels, hot exhaust air from the back of the rack **recirculates through empty U spaces** to the front (intake) side, causing:
  - Hot spots on equipment above the gap
  - Reduced cooling effectiveness
  - Potential equipment overheating
- **Rule**: **Every unused U space must have a blanking panel installed.**
- **Types**: Snap-in (tool-less), screw-mount, ventilated (rare — usually solid).

## 5. Airflow Best Practices

1. **No gaps in rack front**: Use blanking panels for all unused U spaces.
2. **Cable management**: Cables should not obstruct airflow. Use vertical cable managers, not bundles across the front of equipment.
3. **Perforated tiles**: Place only in cold aisles, directly in front of high-heat equipment.
4. **No floor penetrations in hot aisle**: Prevents cold air bypass.
5. **Seal cable cutouts**: Use brush grommets or foam to seal openings in raised floor around cable penetrations.
6. **Equipment orientation**: All equipment must have front-to-back airflow in standard DC layout. Side-to-side airflow equipment needs special accommodation.

## 6. PUE (Power Usage Effectiveness)

```
PUE = Total Facility Power / IT Equipment Power
```

| PUE | Rating | Typical Setup |
|---|---|---|
| 1.0 | Perfect (theoretical) | — |
| 1.2-1.4 | Excellent | Modern DCs with containment, efficient cooling |
| 1.4-1.6 | Good | Most enterprise DCs |
| 1.6-2.0 | Average | Older DCs, no containment |
| >2.0 | Poor | Legacy, inefficient cooling |

> **Impact on network ops**: Poor airflow management leads to hot spots, which cause network equipment to throttle or fail. Understanding containment helps network engineers identify environmental causes of intermittent device issues.
