# DC Switch Products — Juniper QFX & EX Series

> Source: Day One: Data Center Fundamentals — Colin Wrightson (Juniper Networks)

## QFX Series — Purpose-Built for Data Centers

The QFX Series is specifically designed for low latency, high availability, high port density, and flexibility to support different architectures.

### QFX5100 Series (Access/Leaf Layer)

| Model | Ports | Uplinks | Throughput | Form | Use Cases |
|---|---|---|---|---|---|
| **QFX5100-48S** | 48x SFP+ (10GbE) | 6x QSFP+ (40GbE) | 1.44 Tbps | 1U | ToR leaf, spine in small fabric, VC member |
| **QFX5100-48T** | 48x 10GBASE-T | 6x QSFP+ (40GbE) | 1.44 Tbps | 1U | ToR leaf (copper servers) |
| **QFX5100-24Q** | 24x QSFP+ (40GbE) | +8 via expansion | 2.56 Tbps | 1U | Spine, aggregation, high-density 40G |
| **QFX5100-96S** | 96x SFP+ (10GbE) | 8x QSFP+ (40GbE) | 2.56 Tbps | 2U | High-density ToR, EoR |

- SFP+ ports can operate as 100MB/1GbE with appropriate optics
- QSFP+ ports support 4x10GbE breakout cables
- Available in front-to-back or back-to-front airflow
- AC or DC power options with redundant PSU/fans

### QFX5200 Series (High-Density 25/100GbE)

| Model | Ports | Throughput | Form | Use Cases |
|---|---|---|---|---|
| **QFX5200-32C** | 32x QSFP28 (100GbE) | 6.4 Tbps | 1U | Spine, 100G leaf |
| **QFX5200-48Y** | 48x SFP28 (25GbE) + 6x QSFP28 | 3.6 Tbps | 1U | 25GbE ToR leaf |

- QSFP28 supports 100GbE native or 4x25GbE breakout
- Ideal for next-gen DC with 25/100GbE adoption

### QFX10000 Series (Spine/Core/EoR)

| Model | Slots | Max Ports | Throughput | Form | Use Cases |
|---|---|---|---|---|---|
| **QFX10002** | Fixed | 72x QSFP+ or 12x QSFP28 | 4 Tbps | 2U | Small spine, collapsed core |
| **QFX10008** | 8 slots | Up to 240x 100GbE | 96 Tbps | 13U | Large spine, EoR, DCI gateway |
| **QFX10016** | 16 slots | Up to 480x 100GbE | 192 Tbps | 21U | Mega-scale spine |

**Key Line Cards for QFX10008:**

| Line Card | Ports | Best For |
|---|---|---|
| **60S-6Q** | 60x 10GbE SFP+ + 6x 40GbE QSFP+ (or 2x 100GbE) | EoR access |
| **36Q** | 36x 40GbE QSFP+ (or 12x 100GbE) | Spine uplinks |
| **30C** | 30x 100GbE QSFP28 | High-density spine |

---

## Silicon Types — Merchant vs Custom

| Aspect | Merchant Silicon | Custom Silicon (Juniper) |
|---|---|---|
| **Used in** | Leaf/ToR (QFX5100, QFX5200) | Spine/Core (QFX10000, MX) |
| **Strengths** | Lower cost, innovation in SW, open standards | Higher bandwidth, larger buffers, advanced features |
| **L2/L3 throughput** | ✅ Excellent | ✅ Excellent |
| **Buffering** | Minimal (shallow buffers) | Large (deep buffers) |
| **Advanced features** | Limited (VXLAN routing, analytics) | Full (EVPN DCI, analytics, NFV) |
| **Port density** | High | Very high |

> **Design principle**: Use merchant silicon at the leaf where throughput/latency matters most, custom silicon at the spine where aggregation, large buffers, and advanced protocols (EVPN DCI, analytics) are needed.

---

## EX Series — Enterprise/Campus (DC-adjacent)

| Model | Purpose in DC |
|---|---|
| **EX4300** | 1GbE access layer when 10GbE migration is unlikely |
| **EX9200** | Large chassis for aggregation, supports VXLAN routing |

> **Tip**: If servers are 1GbE today but may migrate to 10GbE, keep QFX5100 with 1GbE SFP optics rather than EX4300 — avoids full switch swap later.

---

## Product Selection Decision Framework

```
Server Speed?
├── 1GbE only, no upgrade plan → EX4300
├── 1GbE with future 10GbE → QFX5100-48S (with 1G SFP)
├── 10GbE → QFX5100-48S (SFP+) or QFX5100-48T (copper)
├── 25GbE → QFX5200-48Y
└── 40/100GbE → QFX5200-32C or QFX10002

Spine Selection?
├── Small DC (< 10 racks) → QFX5100-24Q or QFX10002
├── Medium DC (10-50 racks) → QFX10008
└── Large DC (50+ racks) → QFX10016
```
