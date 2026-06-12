# Datacenter Components — Cooling, Power, Racks & Tier Classification

## 1. Cooling Systems

### Chiller (Water Chiller)
- **What**: A large refrigeration system that produces chilled water (typically 7°C/45°F supply, 12°C/54°F return).
- **Function**: Removes heat from the datacenter by circulating chilled water through CRAC/CRAH units or In-Row coolers.
- **Location**: Typically on the roof or in a mechanical yard outside the DC building.
- **Types**:
  - **Air-cooled chiller**: Uses fans to dissipate heat to outdoor air. Simpler, no cooling tower needed.
  - **Water-cooled chiller**: Uses a cooling tower for heat rejection. More efficient at scale, common in large DCs.
- **Capacity**: Measured in kW or tons of refrigeration (1 ton ≈ 3.517 kW).
- **Redundancy**: N+1 or 2N depending on Tier level.

### CRAC (Computer Room Air Conditioning)
- **What**: A precision air conditioning unit designed specifically for datacenter environments.
- **Function**: Takes chilled water from the chiller (or has its own DX compressor) and blows cold air into the DC floor, typically through a raised floor plenum.
- **Location**: Along the perimeter of the data hall (perimeter cooling), on the raised floor.
- **Key specs**: Temperature (18-27°C set point per ASHRAE), humidity (40-60% RH), airflow (CFM).
- **CRAC vs CRAH**:
  - CRAC = Computer Room Air Conditioning (DX, has own compressor)
  - CRAH = Computer Room Air Handler (uses chilled water from chiller, no compressor)

### In-Row Cooling
- **What**: Cooling units placed between server racks in a row, drawing hot air from the hot aisle and blowing cold air into the cold aisle.
- **Advantages**: More efficient than perimeter CRAC — shorter air path, higher cooling density.
- **Use case**: High-density deployments (>10kW/rack).

### Cooling Distribution
```
Chiller → Chilled water piping → CRAH/CRAC/In-Row → Cold air → Servers → Hot air → Return to CRAH/CRAC
                                                                                          ↓
                                                                              Hot water return → Chiller
```

---

## 2. Power Systems

### Utility Power (Grid)
- **What**: Primary power from the electric utility company.
- **Voltage**: Typically medium voltage (e.g., 22kV in Vietnam) stepped down via transformers to 400V/230V.

### Genset (Generator Set)
- **What**: Diesel or gas-powered generator providing backup power during utility outages.
- **Function**: Kicks in when utility power fails, after UPS batteries bridge the gap.
- **Startup time**: Typically 10-15 seconds for diesel generators.
- **Fuel**: On-site diesel storage, typically 24-72 hours at full load.
- **Redundancy**: N+1 or 2N depending on Tier level.
- **Testing**: Monthly load testing is standard practice.

### ATS (Automatic Transfer Switch)
- **What**: Automatically switches between utility power and generator power.
- **Function**: Detects utility failure → signals genset to start → transfers load to genset → transfers back when utility returns (with delay).
- **Transfer time**: Typically 100-500ms (UPS covers this gap).
- **Types**: Open transition (brief interruption) vs Closed transition (no interruption, momentary paralleling).

### UPS (Uninterruptible Power Supply)
- **What**: Battery-backed power system that provides continuous power during the gap between utility failure and genset startup.
- **Function**: Bridges the 10-15 second gap + provides power conditioning (voltage/frequency regulation, surge protection).
- **Types**:
  - **Online (Double Conversion)**: Always running through inverter. Best protection. Standard for DC. Input AC → Rectifier → DC (charges battery) → Inverter → Output AC.
  - **Line-Interactive**: Less common in DCs.
  - **Offline/Standby**: Not used in DCs.
- **Battery runtime**: Typically 5-15 minutes at full load (enough for genset startup + transfer).
- **Battery types**: VRLA (Valve Regulated Lead Acid) most common, Lithium-ion emerging.

### PDU (Power Distribution Unit)
- **What**: Distributes power from the UPS/panel to individual racks.
- **Types**:
  - **Floor PDU (Main PDU)**: Large unit, typically 100-400A, distributes to multiple racks via whips.
  - **Rack PDU (In-Rack PDU)**: Mounted inside the rack, distributes power to individual equipment via C13/C19 outlets.
    - Basic: No monitoring
    - Metered: Shows current/power per PDU
    - Monitored: Per-outlet monitoring via SNMP/web
    - Switched: Per-outlet on/off control + monitoring
- **Common connectors**:
  - **C13/C14**: Standard server power (up to 10A/250V)
  - **C19/C20**: High-power devices (up to 16A/250V)

### RPP (Remote Power Panel)
- **What**: A secondary power distribution panel, receives power from the main PDU/panel and distributes to a group of racks.
- **Location**: On the data hall floor, closer to the racks than the main PDU.

### Power Distribution Chain
```
Utility (Grid) → Transformer → ATS → UPS → Floor PDU/RPP → Rack PDU → Equipment
                                 ↑
                              Genset (backup)
```

---

## 3. Racks & Cabinets

### Standard Rack Sizes
| Type | Width | Depth | Height | Use |
|---|---|---|---|---|
| Full-size (42U) | 600mm | 1000-1200mm | 2000mm (42U) | Servers, network |
| Half-size (22-24U) | 600mm | 600-1000mm | ~1100mm | Network, distribution |
| Open frame | 600mm | varies | 42U | Cabling, patching |

- **U (Rack Unit)**: 1U = 1.75 inches = 44.45mm
- **Standard 42U rack**: ~2000mm total height, ~1829mm usable (42 × 44.45mm)

### Rack Types in DC
| Type | Purpose | Typical Equipment |
|---|---|---|
| **Network rack** | Network infrastructure | Switches, routers, firewalls, patch panels |
| **Server rack** | Compute | Servers, storage arrays |
| **Colocation rack** | Customer equipment | Mixed — depends on customer |
| **Distribution rack** | Cabling distribution | ODF, patch panels, cable management |

### Rack Components
- **Rack PDU** (left and right rails for A/B power)
- **Cable management** (vertical cable managers on sides)
- **Blanking panels** (fill unused U spaces for airflow)
- **Shelf** (for non-rackmount equipment)
- **Rails** (for servers and switches)

---

## 4. Tier Classification (Uptime Institute)

| Tier | Redundancy | Uptime | Downtime/Year | Key Characteristics |
|---|---|---|---|---|
| **Tier I** | N (no redundancy) | 99.671% | 28.8 hours | Single path for power/cooling |
| **Tier II** | N+1 | 99.741% | 22.7 hours | Redundant components |
| **Tier III** | N+1, dual path | 99.982% | 1.6 hours | Concurrently maintainable |
| **Tier IV** | 2N+1 or 2(N+1) | 99.995% | 0.4 hours | Fault tolerant |

### TIA-942 vs Uptime Institute
- **TIA-942**: ANSI/TIA standard, defines DC infrastructure tiers (Rated 1-4), focuses on physical infrastructure and cabling.
- **Uptime Institute**: Certifies DC tier level (Tier I-IV), focuses on redundancy and availability.
- Both use similar tier concepts but with different certification processes.

---

## 5. Environmental Standards (ASHRAE)

| Parameter | Recommended | Allowable (A1) |
|---|---|---|
| Temperature (inlet) | 18-27°C | 15-32°C |
| Humidity (RH) | 40-60% | 20-80% |
| Dew point | 5.5-15°C | -12 to 17°C |

> **Why this matters for network ops**: Equipment overheating due to cooling failure is a common cause of network outages. Understanding the cooling chain helps troubleshoot thermal events.
