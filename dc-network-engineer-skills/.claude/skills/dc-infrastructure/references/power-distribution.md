# Power Distribution Principles

## 1. Redundancy: A-Feed / B-Feed

The fundamental principle of DC power distribution is **dual-feed redundancy**: every piece of critical equipment receives power from **two independent power paths** (A-feed and B-feed).

```
Utility A ──→ ATS-A ──→ UPS-A ──→ PDU-A ──→ Rack PDU-A ──→ Equipment (PSU-A)
                ↑                                                    
             Genset-A                                               
                                                                    
Utility B ──→ ATS-B ──→ UPS-B ──→ PDU-B ──→ Rack PDU-B ──→ Equipment (PSU-B)
                ↑
             Genset-B
```

### Rules
1. **Equipment with dual PSU**: Connect PSU-A to Rack PDU-A, PSU-B to Rack PDU-B. **Never connect both PSUs to the same feed.**
2. **Equipment with single PSU**: Connect to either A or B feed. Document which feed. Consider using a rack-level STS (Static Transfer Switch) for automatic failover.
3. **Load balancing**: Distribute equipment evenly across A and B feeds to avoid overloading one side.

## 2. Power Budget Per Rack

| Density Level | Power Per Rack | Typical Use |
|---|---|---|
| Low density | 2-4 kW | Network equipment, light server loads |
| Medium density | 5-8 kW | General-purpose servers |
| High density | 8-15 kW | Compute-intensive, GPU servers |
| Ultra-high density | 15-30+ kW | AI/ML, HPC |

### Calculation Example
```
Rack has 20 servers × 500W + 2 switches × 150W = 10,300W (10.3 kW)

Per feed (assuming balanced A/B):
  A-feed: ~5.15 kW
  B-feed: ~5.15 kW

Rack PDU (per feed): Need at least 5.15 kW capacity
  → At 230V single-phase: 5150W / 230V ≈ 22.4A per feed
  → A 32A rack PDU per feed provides sufficient headroom
```

### Safety Margin
- **Never exceed 80% of rated capacity** on any PDU or circuit breaker.
- Example: A 32A breaker should carry no more than 25.6A sustained.

## 3. Power Connector Standards

| Connector | Rating | Use |
|---|---|---|
| **C13/C14** | 10A / 250V (2.5 kW) | Standard servers, switches |
| **C19/C20** | 16A / 250V (4.0 kW) | High-power servers, UPS, PDU input |
| **C21/C22** | 16A / 250V (high-temp) | Rarely used in DC |
| **IEC 60309** | 16A-125A / 250-400V | Industrial, PDU input |

## 4. Power Phases

| Phase | Voltage (typical) | Use |
|---|---|---|
| **Single-phase** | 230V (L-N) | Small PDUs, individual rack circuits |
| **Three-phase** | 400V (L-L), 230V (L-N) | Floor PDUs, RPPs, large UPS |

### Three-Phase Load Balancing
- In a three-phase PDU, distribute rack PDU circuits evenly across L1, L2, L3.
- Unbalanced phases cause neutral current and reduced efficiency.

## 5. Power Cable Best Practices

1. **Label both ends** of every power cable (see `/dc-cabling` for labeling standards).
2. **Color coding** (common convention):
   - Red/Orange cable = A-feed
   - Blue cable = B-feed
   - Black = general/unlabeled (avoid in production)
3. **Route A and B feeds separately**: Use different cable managers or tray sides.
4. **Avoid daisy-chaining**: Each device gets its own power cable from the rack PDU.
5. **Secure cables**: Use velcro (not cable ties) for power cables so they can be re-routed without cutting.
6. **Minimum bend radius**: Follow manufacturer specs. Typical minimum is 4× cable diameter.

## 6. Network Equipment Power Considerations

| Equipment | Typical Power | PSU | Notes |
|---|---|---|---|
| Access switch (1G, 24-48 port) | 50-150W | Single or dual | PoE models: add 15-30W per PoE port |
| Aggregation switch (10G/25G) | 150-350W | Dual | Always use dual PSU |
| Spine switch (100G) | 400-800W | Dual | High airflow, check cooling |
| Router (core) | 300-1500W | Dual | Depends on line cards |
| Firewall (SRX) | 200-600W | Dual | Clustering doubles power |
| Patch panel / ODF | 0W | N/A | Passive equipment |

### Power Rule for Network Racks
- Network racks are typically **low-to-medium density** (2-6 kW).
- Always provision dual-feed even if the total power is low — network equipment failure impacts many servers.
- Reserve 20% headroom for future expansion.

> **Tip for network engineers**: When planning a new rack, calculate total power draw including worst-case (all PoE ports active, all line cards installed) and verify against the available PDU capacity. Oversubscription is acceptable for servers but **never for network infrastructure**.
