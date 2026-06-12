# Copper Cables — Types, Specifications & Applications

## 1. Twisted Pair Cables (RJ45)

### Comparison Table

| Category | Standard | Max Speed | Max Distance | Frequency | Shielding | Typical Use in DC | Price (per meter, approx.) |
|---|---|---|---|---|---|---|---|
| **Cat5e** | TIA/EIA-568-C.2 | 1 Gbps | 100m | 100 MHz | UTP | Legacy management networks | $0.15-0.30 |
| **Cat6** | TIA/EIA-568-C.2 | 1 Gbps (10G @ 55m) | 100m (55m for 10G) | 250 MHz | UTP/STP | Management, OOB, iDRAC/iLO | $0.20-0.40 |
| **Cat6a** | TIA/EIA-568-C.2 | 10 Gbps | 100m | 500 MHz | STP/FTP | **Most common in modern DC** — server connectivity, management | $0.40-0.80 |
| **Cat7** | ISO/IEC 11801 | 10 Gbps | 100m | 600 MHz | S/FTP | Rarely used in DC (non-RJ45 connector: TERA/GG45) | $0.80-1.50 |
| **Cat8** | TIA-568.2-D | 25/40 Gbps | 30m | 2000 MHz | S/FTP | Short-run, same-rack connections | $1.50-3.00 |

### Recommendations for DC

| Use Case | Recommended Cable | Why |
|---|---|---|
| Server management (iDRAC/iLO/IPMI) | **Cat6a** | 10G capable, future-proof, full 100m reach |
| Out-of-band management network | **Cat6a** | Reliable, shielded, good for management switches |
| Console port connections | **Cat5e/Cat6** (rollover) | Low speed, short distance, cost-effective |
| PoE devices (cameras, APs, phones) | **Cat6a** | Better heat dissipation for PoE, 10G ready |
| Legacy 1G server connectivity | **Cat6** | Sufficient for 1G, cheaper than Cat6a |

### Key Details

**Cat6a (Augmented Category 6)** — The DC workhorse:
- Supports 10GBASE-T up to **100 meters** (vs Cat6 which is limited to 55m for 10G)
- **STP/FTP shielding** reduces crosstalk — important in high-density DC environments with many cables bundled together
- Thicker than Cat6 (~7.5mm vs ~6mm diameter) — impacts cable management density
- Requires shielded connectors and proper grounding for shielding effectiveness
- **Recommended for all new DC deployments**

**Cat5e** — Still functional but:
- Limited to 1 Gbps
- No shielding in most variants
- Acceptable only for legacy or temporary use
- Being phased out in modern DCs

---

## 2. DAC (Direct Attach Copper) Cables

DAC cables are **pre-terminated copper cables with transceivers built into both ends**. They provide a low-cost, low-power alternative to optical transceivers + fiber for short-distance connections.

### DAC Types

| Type | Speed | Max Distance | Connector | Typical Use | Price (approx.) |
|---|---|---|---|---|---|
| **SFP+ DAC** | 10 Gbps | 1-7m (passive), 10m (active) | SFP+ to SFP+ | ToR switch ↔ server (10G) | $15-30 (passive), $30-60 (active) |
| **SFP28 DAC** | 25 Gbps | 1-5m (passive), 7m (active) | SFP28 to SFP28 | ToR switch ↔ server (25G) | $20-40 (passive), $50-80 (active) |
| **QSFP+ DAC** | 40 Gbps | 1-5m (passive), 7m (active) | QSFP+ to QSFP+ | Switch ↔ switch (40G) | $30-60 (passive), $60-100 (active) |
| **QSFP28 DAC** | 100 Gbps | 1-3m (passive), 5m (active) | QSFP28 to QSFP28 | Switch ↔ switch (100G) | $50-100 (passive), $100-200 (active) |
| **QSFP-DD DAC** | 400 Gbps | 1-3m (passive) | QSFP-DD to QSFP-DD | Spine ↔ spine (400G) | $200-500 |

### Passive vs Active DAC

| Feature | Passive DAC | Active DAC |
|---|---|---|
| Power consumption | 0W (no electronics) | 0.5-1W per end |
| Max distance | 1-5m (depends on speed) | 5-10m |
| Latency | Lowest | Slightly higher (signal processing) |
| Cost | Lowest | Higher |
| Recommendation | **Prefer passive** for same-rack/adjacent-rack | Use active only when passive can't reach |

### DAC vs Fiber (Decision Guide)

| Factor | DAC | Fiber + Transceiver |
|---|---|---|
| Distance | ≤5m (passive), ≤10m (active) | Up to 10km+ |
| Cost | Lower (cable + transceiver integrated) | Higher (separate transceiver + cable) |
| Power | Lower (passive: 0W) | Higher (transceiver power) |
| Flexibility | Less (fixed length, can't re-patch) | More (change cable length easily) |
| Bend radius | Stiffer (copper) | More flexible (fiber) |
| Cable density | Thicker, heavier | Thinner, lighter |

### Breakout DAC Cables

Split a high-speed port into multiple lower-speed ports:

| Type | Splits to | Use Case |
|---|---|---|
| QSFP+ to 4× SFP+ | 40G → 4×10G | Aggregate switch → 4 servers |
| QSFP28 to 4× SFP28 | 100G → 4×25G | Leaf switch → 4 servers |
| QSFP-DD to 2× QSFP28 | 400G → 2×100G | Spine breakout |

> **DC best practice**: Use **passive DAC** for all connections under 3 meters (same rack or adjacent rack). Use **fiber** for everything else. This minimizes cost and power while maximizing reliability.
