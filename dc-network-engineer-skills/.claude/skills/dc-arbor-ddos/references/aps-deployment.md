# APS Deployment & Architecture

> Source: NETSCOUT Arbor APS 6.4 User Guide

## APS Deployment Models

### Network Connectivity Models

| Model | Description | Traffic Path | Use Case |
|---|---|---|---|
| **Inline** | APS sits in traffic path | All traffic passes through APS | Active mitigation, production |
| **Monitor (Span/TAP)** | APS receives copy of traffic | Traffic not affected by APS | Trial, monitoring, forensics |

### Inline Deployment

```
Internet ──→ [Router] ──→ [APS] ──→ [Firewall] ──→ [Internal Network]
                            │  │
                        inbound outbound
                       interface interface
```

- APS deployed **external to all security devices** (upstream of firewalls, IPS)
- Protects downstream devices from volumetric attacks
- Protection interfaces operate in **transparent bridge mode** (no IP addresses)
- Bypass capability: fail-open (hardware bypass) or fail-closed

### Monitor Mode (Span/TAP)

```
Internet ──→ [Router] ──→ [Firewall] ──→ [Internal Network]
                │
                └──→ [SPAN/TAP] ──→ [APS] (monitoring only)
```

- APS receives traffic copy via SPAN port or network TAP
- No traffic blocking — detection and reporting only
- Use for: trial deployments, threat assessment, tuning before inline

---

## Deployment Modes

### Layer 2 Mode (Default)
- Protection interfaces are **transparent L2 bridge**
- No IP addresses on protection interfaces
- APS invisible to network — no routing changes needed

### Layer 3 Mode (vAPS)
- Protection interfaces have **IP addresses**
- Used for virtual APS (vAPS) deployments
- Requires static routes for traffic steering

---

## Network Placement

### Upstream of Router

```
Internet ──→ [APS] ──→ [Router] ──→ [Network]
```

- APS cleans traffic before it reaches router
- Router sees only clean traffic
- Best for: protecting router itself from attacks

### Downstream of Router (Recommended)

```
Internet ──→ [Router] ──→ [APS] ──→ [Firewall] ──→ [Network]
```

- Router handles BGP, routing decisions
- APS protects firewall and internal infrastructure
- Most common deployment

---

## Redundancy Deployments

### Active-Passive HA

```
Internet ──→ [Router] ──┬──→ [APS Primary] ──→ [Firewall]
                        │
                        └──→ [APS Backup]  ──→ (standby)
```

### Dual APS (Active-Active)

```
Internet ──→ [Router 1] ──→ [APS 1] ──→ [Firewall]
                              │
Internet ──→ [Router 2] ──→ [APS 2] ──→ [Firewall]
```

---

## Hardware & Software Bypass

| Feature | Default | Description |
|---|---|---|
| **Hardware bypass** | Fail-open | Power/hardware failure → traffic passes through |
| **Software bypass** | Enabled | Software failure → traffic passes through |
| **Fail-closed** | Optional | All traffic blocked on failure (high security) |

```
# CLI: Check bypass status
/ services aed bypass show

# CLI: Configure bypass
/ services aed bypass hardware fail-open
/ services aed bypass software enable
```

---

## Cloud Signaling

Cloud Signaling connects APS to upstream **cloud-based DDoS scrubbing** (Arbor Cloud) for volumetric attacks that exceed APS capacity.

### How It Works

```
Normal: Internet → [APS] → Network (APS handles)

Under volumetric attack:
1. APS detects attack exceeding capacity
2. APS triggers Cloud Signal to Arbor Cloud
3. BGP/DNS reroutes traffic through Arbor Cloud
4. Arbor Cloud scrubs volumetric component
5. Clean traffic sent back through GRE/tunnel to APS
6. APS handles remaining application-layer attacks
```

### Cloud Signaling Deployment

```
                    ┌──────────────┐
                    │ Arbor Cloud  │ ← Upstream scrubbing (volumetric)
                    │ (Cloud SCB)  │
                    └──────┬───────┘
                           │ GRE tunnel (clean return)
                           │
Internet ──→ [Router] ──→ [APS] ──→ [Network]
                            │
                    Cloud Signal │ ← Triggers scrubbing when
                    (out-of-band)     attack exceeds capacity
```

> **Best Practice**: Provision a **separate out-of-band management network** for Cloud Signaling so it remains available even when data links are saturated.

---

## APS Licensing

### License Types

| License | Description |
|---|---|
| **Throughput License** | Determines max clean traffic forwarded (e.g., 1G, 2G, 10G) |
| **ATLAS Intelligence Feed (AIF)** | Subscription for threat intelligence updates |
| **SSL Inspection** | License for decrypting/inspecting HTTPS traffic |

### Throughput Limit Behavior
- License enforces limit on **clean traffic** (traffic that passes countermeasures)
- 90% utilization → license warning alert
- Exceeding limit + buffer → APS may **drop clean traffic**
- Monitor via: About page → Throughput for Clean Traffic graph

---

## vAPS (Virtual APS)

Virtual deployment for hypervisor/cloud environments:

| Feature | Physical APS | vAPS |
|---|---|---|
| **Deployment** | Hardware appliance | VMware/KVM/cloud VM |
| **Max Protection Groups** | Varies by model | 50 (or 10 for minimum config) |
| **Licensing** | Cloud-based or traditional | Cloud-based licensing supported |
| **Network Mode** | Layer 2 (transparent) | Layer 3 (requires static routes) |
| **Bypass** | Hardware + Software | Software only |

### Cloud-Based Licensing for vAPS
- Licenses managed via NETSCOUT cloud portal
- vAPS checks license server periodically
- Supports temporary offline operation with grace period
