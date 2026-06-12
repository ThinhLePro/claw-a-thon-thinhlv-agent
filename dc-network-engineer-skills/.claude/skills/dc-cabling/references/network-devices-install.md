# Network Devices in the DC — Types & Installation Principles

## 1. Network Device Types in a Standard DC

### IP Fabric Architecture Devices

| Device Role | Typical Hardware (Juniper) | Ports | Location | Quantity |
|---|---|---|---|---|
| **Spine switch** | QFX5220-32CD (32×400G) or QFX5210-64C (64×100G) | 100G/400G | Dedicated spine rack(s), central | 2-4 per DC |
| **Leaf switch (ToR)** | QFX5110-48S (48×10G + 4×40G/100G) or QFX5120-48Y (48×25G + 8×100G) | 10G/25G down, 100G up | Top of each equipment row | 2 per row (redundant) |
| **Border leaf / Edge** | QFX5120 or MX204 | 100G | MDF area or edge rack | 2 (redundant pair) |
| **Core router** | MX204, MX304, MX480 | 100G/400G | Core rack near MDF | 2 (redundant pair) |
| **Firewall** | SRX1500, SRX4100, SRX4200 | 1G/10G | Security zone rack | 2 (cluster pair) |
| **Management switch** | EX2300-24T, EX3400-48T | 1G | Management rack | 1-2 |
| **Console server** | Opengear, Avocent | Serial | Management rack | 1-2 |
| **Out-of-band (OOB) switch** | EX2300-24T | 1G | Management rack | 1 |

### Other DC Network Equipment

| Device | Function | Location |
|---|---|---|
| **Load balancer** | Distributes traffic across servers | Near spine or border leaf |
| **DDoS scrubber** | Cleans malicious traffic | Inline near border/edge |
| **DNS server** | Name resolution | Server rack |
| **NTP server** | Time synchronization | Management rack |
| **Syslog/SNMP collector** | Log aggregation, monitoring | Management rack |

---

## 2. Installation Principles

### Pre-Installation Checklist

| Step | Action | Verify |
|---|---|---|
| 1 | **Rack survey** | Available U-space, power capacity (A+B feed), cooling capacity |
| 2 | **Power check** | Each device's PSU requirements vs available PDU outlets (C13 or C19) |
| 3 | **Cable planning** | Identify uplink ports, downstream ports, management port, console port |
| 4 | **Label preparation** | Pre-print labels for all cables (data + power + console) |
| 5 | **IP allocation** | Management IP, loopback IP, interface IPs (from IPAM) |
| 6 | **Configuration preparation** | Base config ready (hostname, management, NTP, syslog, SNMP, AAA) |
| 7 | **Change approval** | Change ticket approved, maintenance window confirmed |

### Physical Installation

#### Racking
1. **Mount position**: Network switches typically go at the **top of rack** (ToR) for shortest cable runs to servers below
2. **Rails**: Use manufacturer rails. If rack mount ears only, use a shelf for support
3. **Airflow direction**: Verify device airflow matches rack orientation
   - Juniper QFX: **front-to-back** (intake from cold aisle, exhaust to hot aisle) ← Standard
   - Some models offer **back-to-front** option (for reverse airflow racks)
   - ⚠️ **Never mix airflow directions in the same rack**
4. **Secure with cage nuts and screws** (both sides, all 4 mounting points)

#### Power Connection
1. Connect **PSU-0 to PDU-A** (A-feed)
2. Connect **PSU-1 to PDU-B** (B-feed)
3. Verify both PSUs show green LED
4. Check power draw: `show chassis environment` (Juniper) should show both PSUs `OK`
5. Label power cables with `PDU-A: <circuit>` and `PDU-B: <circuit>`

#### Console Connection
1. Connect console port (RJ45 or USB-C) to **console server** (Opengear/Avocent)
2. Or directly to a laptop with serial adapter (9600 8N1 default for Juniper)
3. Console access is critical for initial configuration and recovery

#### Network Cabling
1. **Management port** (em0/me0 or fxp0 on Juniper): Connect to **management/OOB switch** using Cat6a
2. **Uplink ports**: Connect to spine/aggregation using **fiber** (SR4/LR4) or **DAC**
3. **Downlink ports**: Connect to patch panel (structured cabling) or directly to servers
4. **Cable labeling**: Label both ends of every cable immediately

### Post-Installation Verification

```junos
# Basic hardware check
show chassis hardware                  # Verify all components detected
show chassis environment               # Check power, temp, fans
show chassis alarms                    # Any hardware alarms?

# Interface check
show interfaces terse                  # All expected ports up?
show interfaces diagnostics optics     # Fiber/optic health (DOM values)

# Software check
show version                           # Correct JunOS version?
show system uptime                     # Boot time, system clock

# Management connectivity
ping <management-gateway>              # Can reach management network?
ping <ntp-server>                      # Can reach NTP?
show ntp associations                  # NTP synced?
show system syslog                     # Syslog configured?
```

---

## 3. Airflow Considerations

### Juniper Device Airflow

| Model | Default Airflow | Reversible? | Fan Modules |
|---|---|---|---|
| QFX5110-48S | Front-to-Back (AFO) | Yes (AFI available) | Hot-swappable |
| QFX5120-48Y | Front-to-Back (AFO) | Yes (AFI available) | Hot-swappable |
| QFX5220-32CD | Front-to-Back (AFO) | Yes | Hot-swappable |
| EX2300-24T | Side-to-back | No | Fixed |
| EX3400-48T | Front-to-Back | Yes | Hot-swappable |
| MX204 | Front-to-Back | No (fixed) | Fixed |
| SRX1500 | Front-to-Back | No | Fixed |
| SRX4200 | Front-to-Back | No | Fixed |

> **AFO** = Airflow Out (front-to-back, standard hot/cold aisle)
> **AFI** = Airflow In (back-to-front, reverse — for racks where hot aisle is in front)

### Fan Module Alarms
```junos
show chassis environment
# Look for: Fan status, temperature sensors
# Alarm if any fan fails or temperature exceeds threshold

show chassis alarms
# "Major" alarm if fan tray removed or failed
# "Minor" alarm if temperature approaching threshold
```

---

## 4. Device Naming Convention

A consistent naming convention is critical for operations:

### Format
```
<Role>-<Location>-<Number>
```

### Examples

| Name | Role | Location | Number |
|---|---|---|---|
| `SPINE-DC1-01` | Spine switch | DC 1 | First spine |
| `LEAF-A01-01` | Leaf switch | Rack A01 | First leaf in that rack |
| `BORDER-DC1-01` | Border leaf / edge router | DC 1 | First border |
| `FW-DC1-01` | Firewall (SRX) | DC 1 | First firewall |
| `MGMT-DC1-01` | Management switch | DC 1 | First management switch |
| `MX-DC1-01` | Core router | DC 1 | First MX |

### Rules
1. **All uppercase** for device names
2. **Consistent separators** (hyphen `-` preferred)
3. **No special characters** other than hyphen
4. **Include location** (DC ID, row, or rack) for physical identification
5. **Match hostname** (`set system host-name LEAF-A01-01`)
