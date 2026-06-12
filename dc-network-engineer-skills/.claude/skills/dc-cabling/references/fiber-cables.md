# Fiber Optic Cables — Types, Specifications & Applications

## 1. Single-Mode vs Multi-Mode

| Feature | Single-Mode (SMF) | Multi-Mode (MMF) |
|---|---|---|
| Core diameter | 9 µm (8-10 µm) | 50 µm (OM3/OM4/OM5) or 62.5 µm (OM1/OM2) |
| Light source | Laser (1310nm, 1550nm) | LED or VCSEL (850nm, 1300nm) |
| Bandwidth | Very high (virtually unlimited) | Limited by modal dispersion |
| Max distance | Up to 80+ km | 100m - 550m (depending on speed/grade) |
| Cost (cable) | Similar to MMF | Similar to SMF |
| Cost (transceiver) | **More expensive** | **Less expensive** |
| Typical use in DC | **Inter-building**, DCI, long runs | **Intra-DC**, ToR to aggregation, ≤300m |
| Jacket color (convention) | **Yellow** | **Aqua** (OM3/OM4), **Lime green** (OM5), Orange (OM1/OM2) |

### DC Rule of Thumb
- **Multi-mode (OM4)** for intra-DC connections ≤ 300m (most datacenter links)
- **Single-mode (OS2)** for inter-building, DCI, and connections > 300m

---

## 2. Multi-Mode Fiber Grades

| Grade | Core | Bandwidth (850nm) | 1G (1000BASE-SX) | 10G (10GBASE-SR) | 25G (25GBASE-SR) | 40G (40GBASE-SR4) | 100G (100GBASE-SR4) | Jacket Color |
|---|---|---|---|---|---|---|---|---|
| **OM1** | 62.5µm | 200 MHz·km | 275m | 33m | — | — | — | Orange |
| **OM2** | 50µm | 500 MHz·km | 550m | 82m | — | — | — | Orange |
| **OM3** | 50µm | 2000 MHz·km | 550m | 300m | 70m | 100m | 70m | **Aqua** |
| **OM4** | 50µm | 4700 MHz·km | 550m | 400m | 100m | 150m | 100m | **Aqua** |
| **OM5** | 50µm | 4700 MHz·km | 550m | 400m | 100m | 150m | 150m | **Lime Green** |

### Recommendations

| Use Case | Recommended Grade | Reason |
|---|---|---|
| New DC build, general use | **OM4** | Best price/performance for 10G-100G within DC distances |
| 400G future-proofing | **OM5** | Supports SWDM (Short Wavelength Division Multiplexing) for 400G |
| Legacy / existing infrastructure | **OM3** | Still adequate for 10G up to 300m |
| Long-distance / DCI | **OS2 (Single-mode)** | Required for distances > 400m |
| **Avoid** | OM1, OM2 | Obsolete for modern DC speeds. Replace if possible. |

---

## 3. Single-Mode Fiber (OS2)

| Standard | Core | Wavelength | Max Distance (typical) | Use |
|---|---|---|---|---|
| **OS2** | 9µm | 1310nm (O-band) | 10 km (10GBASE-LR) | Standard intra-metro |
| **OS2** | 9µm | 1550nm (C-band) | 40-80 km (10GBASE-ER/ZR) | Long-haul, DCI |
| **OS2** | 9µm | CWDM/DWDM | Hundreds of km | WAN, carrier |

---

## 4. Fiber Connector Types

| Connector | Size | Latch Type | Typical Use | Fiber Count |
|---|---|---|---|---|
| **LC** | Small (1.25mm ferrule) | Push-pull | **Most common in DC** — SFP/SFP+/SFP28/QSFP | 1 fiber per connector (duplex = 2 LC) |
| **SC** | Medium (2.5mm ferrule) | Push-pull | Older installations, telecom | 1 fiber per connector |
| **MPO/MTP** | Multi-fiber (ribbon) | Push-pull | **40G/100G/400G parallel optics** — QSFP+, QSFP28 | 8, 12, or 24 fibers |
| **ST** | Medium (2.5mm ferrule) | Bayonet twist | Legacy, avoid in new builds | 1 fiber per connector |
| **FC** | Medium | Screw | Telecom, rarely in DC | 1 fiber per connector |

### LC — The DC Standard
- **Duplex LC**: Two LC connectors in a clip — standard for SFP-based connections (1G, 10G, 25G)
- **LC Uniboot**: Single cable with both fibers, switchable polarity — saves space, recommended for high-density
- **LC-LC patch cord**: The most common cable you'll handle in a DC

### MPO/MTP — For Parallel Optics
- Used for 40G (SR4 = 4 lanes × 10G) and 100G (SR4 = 4 lanes × 25G)
- **MTP**: Brand name (US Conec) for MPO with better performance — use MTP for DC
- **12-fiber MPO**: Standard for 40G/100G SR4
- **24-fiber MPO**: For 100G SR10, future 400G
- **Breakout cables**: MPO to 4× LC duplex (for connecting 40G QSFP to 4× 10G SFP)

### Connector Polish Types

| Polish | Return Loss | Use |
|---|---|---|
| **UPC** (Ultra Physical Contact) | ≥-50 dB | **Multi-mode** (standard) |
| **APC** (Angled Physical Contact) | ≥-60 dB | **Single-mode** (long distance, DWDM) |

> ⚠️ **Never mix UPC and APC connectors** — the angled ferrule of APC will not mate properly with flat UPC, causing high insertion loss and potential damage. UPC = blue connector, APC = green connector.

---

## 5. Fiber Cable Types

### Patch Cord (Jumper Cable)
- **What**: Short fiber cable with connectors on both ends, for patching between devices/panels.
- **Lengths**: Typically 1m, 2m, 3m, 5m (custom lengths available).
- **Use**: Equipment port ↔ patch panel, patch panel ↔ patch panel.

### Trunk Cable (Distribution Cable)
- **What**: Multi-fiber cable (12, 24, 48, 72, 96 fibers) with MPO/MTP connectors on both ends.
- **Use**: Connects two patch panel/ODF locations. Pre-terminated in factory.
- **Advantage**: Fast deployment, consistent quality, reduced splice points.

### Loose Tube Cable (Outdoor/Plant)
- **What**: Multi-fiber cable with individual fiber tubes inside a protective jacket.
- **Use**: Outdoor, underground conduit, between buildings.
- **Needs**: Field splicing (fusion splice) at each end to pigtails/patch panels.

### Fiber Polarity (MPO)
| Type | Pin 1 → | Use |
|---|---|---|
| **Type A** (Straight) | Pin 1 (key up → key up) | Standard, flip at every connection |
| **Type B** (Reversed) | Pin 12 (key up → key down) | Most common for 40G/100G SR4 trunk |
| **Type C** (Pairs flipped) | Adjacent pair swap | Duplex LC breakout compatibility |

> **DC standard**: Use **Type B polarity** for MPO trunk cables (key up ↔ key down). This ensures correct Tx/Rx alignment with standard MPO-to-LC breakout cables.

---

## 6. Pricing Reference

Prices from [fs.com](https://www.fs.com) (third-party, compatible with Juniper/Cisco/Arista). Prices are approximate and subject to change.

### Fiber Patch Cords

| Type | Length | Connector | Price (approx.) |
|---|---|---|---|
| OM4 MM duplex | 1m | LC-LC | $3-5 |
| OM4 MM duplex | 3m | LC-LC | $4-7 |
| OM4 MM duplex | 5m | LC-LC | $5-9 |
| OS2 SM duplex | 1m | LC-LC UPC | $3-5 |
| OS2 SM duplex | 3m | LC-LC UPC | $4-7 |
| OS2 SM duplex | 5m | LC-LC APC | $5-9 |
| OM4 MPO-12 trunk | 3m | MTP-MTP | $30-50 |
| OM4 MPO-12 trunk | 10m | MTP-MTP | $50-80 |
| OM4 MPO to 4×LC breakout | 1m | MTP to 4×LC | $25-40 |

### Copper Patch Cords

| Type | Length | Connector | Price (approx.) |
|---|---|---|---|
| Cat6a STP | 1m | RJ45 | $3-5 |
| Cat6a STP | 3m | RJ45 | $5-8 |
| Cat6a STP | 5m | RJ45 | $7-12 |

> **Budget tip**: Third-party optics and cables from fs.com, Fluxlight, or 10Gtek are typically 80-90% cheaper than vendor-branded (Juniper/Cisco) with equivalent performance. Most modern switches support third-party optics. Verify compatibility before bulk ordering.
