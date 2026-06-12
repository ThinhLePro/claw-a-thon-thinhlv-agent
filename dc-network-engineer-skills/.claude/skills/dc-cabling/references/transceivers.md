# Transceivers & Optical Modules — SFP to QSFP-DD

## 1. Transceiver Form Factors

| Form Factor | Speeds | Lanes | Fiber Pairs | Typical Port |
|---|---|---|---|---|
| **SFP** | 1G | 1 | 1 (duplex) | 1G switch ports |
| **SFP+** | 10G | 1 | 1 (duplex) | 10G switch/server ports |
| **SFP28** | 25G | 1 | 1 (duplex) | 25G switch/server ports |
| **QSFP+** | 40G | 4×10G | 4 (MPO-12) or 1 (BiDi) | 40G uplinks |
| **QSFP28** | 100G | 4×25G | 4 (MPO-12) or 1 (duplex) | 100G spine-leaf |
| **QSFP56** | 200G | 4×50G | 4 | 200G (emerging) |
| **QSFP-DD** | 400G | 8×50G | 8 (MPO-16) or 4 | 400G spine |
| **OSFP** | 400G/800G | 8×50G/100G | 8 | 400G/800G (future) |

### Backward Compatibility
- **SFP28 port** accepts: SFP28 (25G), SFP+ (10G), SFP (1G) — auto-negotiates down
- **QSFP28 port** accepts: QSFP28 (100G), QSFP+ (40G) — auto-negotiates down
- **QSFP-DD port** accepts: QSFP-DD (400G), QSFP28 (100G), QSFP+ (40G)

---

## 2. SFP / SFP+ / SFP28 Modules

### 1G SFP

| Module | Fiber | Wavelength | Max Distance | Connector | Price (3rd party) |
|---|---|---|---|---|---|
| **1000BASE-SX** | OM3/OM4 MM | 850nm | 550m | LC duplex | $8-15 |
| **1000BASE-LX** | OS2 SM | 1310nm | 10 km | LC duplex | $10-20 |
| **1000BASE-ZX** | OS2 SM | 1550nm | 80 km | LC duplex | $30-50 |
| **1000BASE-T** | Cat5e/Cat6 copper | — | 100m | RJ45 | $15-30 |

### 10G SFP+

| Module | Fiber | Wavelength | Max Distance | Connector | Price (3rd party) |
|---|---|---|---|---|---|
| **10GBASE-SR** | OM3/OM4 MM | 850nm | 300m (OM3) / 400m (OM4) | LC duplex | $10-20 |
| **10GBASE-LR** | OS2 SM | 1310nm | 10 km | LC duplex | $15-30 |
| **10GBASE-ER** | OS2 SM | 1550nm | 40 km | LC duplex | $50-100 |
| **10GBASE-ZR** | OS2 SM | 1550nm | 80 km | LC duplex | $80-150 |
| **10GBASE-T** | Cat6a copper | — | 30m | RJ45 | $30-50 |
| **10G BiDi** | OS2 SM | 1270/1330nm | 10-40 km | LC simplex | $40-80 |

### 25G SFP28

| Module | Fiber | Wavelength | Max Distance | Connector | Price (3rd party) |
|---|---|---|---|---|---|
| **25GBASE-SR** | OM3/OM4 MM | 850nm | 70m (OM3) / 100m (OM4) | LC duplex | $15-30 |
| **25GBASE-LR** | OS2 SM | 1310nm | 10 km | LC duplex | $30-50 |

---

## 3. QSFP+ / QSFP28 / QSFP-DD Modules

### 40G QSFP+

| Module | Fiber | Lanes | Max Distance | Connector | Price (3rd party) |
|---|---|---|---|---|---|
| **40GBASE-SR4** | OM3/OM4 MM | 4×10G | 100m (OM3) / 150m (OM4) | MPO-12 | $30-50 |
| **40GBASE-LR4** | OS2 SM | 4×10G (WDM) | 10 km | LC duplex | $80-150 |
| **40GBASE-ER4** | OS2 SM | 4×10G (WDM) | 40 km | LC duplex | $200-400 |
| **40G BiDi** | OM3/OM4 MM | 2×20G | 100m (OM3) / 150m (OM4) | LC duplex | $50-80 |

### 100G QSFP28

| Module | Fiber | Lanes | Max Distance | Connector | Price (3rd party) |
|---|---|---|---|---|---|
| **100GBASE-SR4** | OM3/OM4 MM | 4×25G | 70m (OM3) / 100m (OM4) | MPO-12 | $40-80 |
| **100GBASE-LR4** | OS2 SM | 4×25G (WDM) | 10 km | LC duplex | $100-200 |
| **100GBASE-ER4** | OS2 SM | 4×25G (WDM) | 40 km | LC duplex | $400-800 |
| **100GBASE-ZR4** | OS2 SM | 4×25G (WDM) | 80 km | LC duplex | $800-1500 |
| **100GBASE-CWDM4** | OS2 SM | 4×25G (CWDM) | 2 km | LC duplex | $60-120 |
| **100GBASE-PSM4** | OS2 SM | 4×25G | 500m | MPO-12 | $50-100 |

### 400G QSFP-DD

| Module | Fiber | Lanes | Max Distance | Connector | Price (3rd party) |
|---|---|---|---|---|---|
| **400GBASE-SR8** | OM3/OM4 MM | 8×50G | 70m (OM3) / 100m (OM4) | MPO-16 | $200-400 |
| **400GBASE-DR4** | OS2 SM | 4×100G | 500m | MPO-12 | $300-600 |
| **400GBASE-FR4** | OS2 SM | 4×100G (WDM) | 2 km | LC duplex | $400-800 |
| **400GBASE-LR4** | OS2 SM | 4×100G (WDM) | 10 km | LC duplex | $800-1500 |

---

## 4. AOC (Active Optical Cable)

AOC = fiber cable with transceivers permanently attached on both ends (like DAC but using fiber optics).

| Type | Speed | Max Distance | Typical Use | Price (approx.) |
|---|---|---|---|---|
| SFP+ AOC | 10G | 1-100m | Server ↔ ToR (>5m) | $20-40 |
| SFP28 AOC | 25G | 1-100m | Server ↔ ToR (>5m) | $30-60 |
| QSFP+ AOC | 40G | 1-100m | Switch ↔ switch | $40-80 |
| QSFP28 AOC | 100G | 1-100m | Switch ↔ switch | $60-120 |

### AOC vs DAC vs Transceiver + Fiber

| Factor | Passive DAC | Active DAC | AOC | Transceiver + Fiber |
|---|---|---|---|---|
| Max distance | 1-5m | 5-10m | 1-100m | Up to 80km |
| Cost | Lowest | Low-Medium | Medium | Highest |
| Power | 0W | 0.5-1W | 1-2W | 1-3W |
| Weight/flexibility | Heavy, stiff | Heavy, stiff | Light, flexible | Light, flexible |
| Swappable parts | No (integrated) | No (integrated) | No (integrated) | Yes (separate) |
| Use case | Same rack | Adjacent rack | Same row | Cross-DC / inter-DC |

### Decision Matrix

```
Distance ≤ 3m → Passive DAC (cheapest, zero power)
Distance 3-7m → Active DAC (still cheaper than fiber)
Distance 7-100m → AOC or Transceiver + MMF (AOC if you don't need re-patching)
Distance > 100m → Transceiver + SMF (only option)
```

---

## 5. Breakout Modules & Cables

For splitting higher-speed ports into multiple lower-speed connections:

| From | To | Cable/Module | Use Case |
|---|---|---|---|
| QSFP+ (40G) | 4× SFP+ (10G) | Breakout cable (MPO to 4×LC) | Leaf → 4 servers at 10G |
| QSFP28 (100G) | 4× SFP28 (25G) | Breakout cable (MPO to 4×LC) | Leaf → 4 servers at 25G |
| QSFP28 (100G) | 2× QSFP28 (50G) | Breakout cable | Emerging |
| QSFP-DD (400G) | 4× QSFP28 (100G) | Breakout cable | Spine → 4 leaf at 100G |

---

## 6. Vendor Compatibility

### Third-Party Optics
Most modern switches (Juniper QFX/EX, Cisco Nexus, Arista) support third-party optics from vendors like:
- **fs.com** — Most popular, widest range, good quality
- **Fluxlight** — Juniper-focused
- **10Gtek** — Budget option
- **Flexoptix** — Programmable optics (can set any vendor code)

### Juniper-Specific Notes
- Juniper QFX/EX series supports third-party optics by default (no `no-validate` needed in most cases)
- Use `show chassis hardware` to verify optic detection
- Use `show interfaces diagnostics optics` to check DOM (Digital Optical Monitoring) values:
  - **Rx Power**: Should be within optic's sensitivity range (typically -3 to -18 dBm for SR)
  - **Tx Power**: Should match optic's specification
  - **Temperature**: Should be < 70°C
  - **Alarms**: Check for `Laser bias current high`, `Rx power low`, etc.

```
user@switch> show interfaces diagnostics optics xe-0/0/0
```

> **Troubleshooting tip**: If a third-party optic is not recognized, check `show chassis hardware` for the port. If it shows "UNKNOWN", the optic may be incompatible or defective. Try a different optic from the same batch. If the issue persists, the port may be damaged — check for physical debris in the port cage using a fiber scope.
