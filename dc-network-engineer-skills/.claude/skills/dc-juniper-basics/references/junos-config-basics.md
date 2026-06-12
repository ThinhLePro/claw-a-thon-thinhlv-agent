# JunOS Configuration Basics

## 1. Configuration Hierarchy

JunOS config is a **tree structure** with named nodes:

```
root
├── system
│   ├── host-name
│   ├── domain-name
│   ├── services (ssh, netconf, etc.)
│   ├── syslog
│   ├── ntp
│   └── login
├── interfaces
│   ├── xe-0/0/0
│   │   └── unit 0
│   │       ├── family inet (address)
│   │       └── family inet6
│   └── lo0
├── routing-options
│   ├── autonomous-system
│   ├── router-id
│   └── static
├── protocols
│   ├── bgp
│   ├── ospf
│   ├── evpn
│   └── lldp
├── policy-options
│   ├── prefix-list
│   ├── community
│   ├── as-path
│   └── policy-statement
├── firewall
│   └── family inet filter
├── vlans
├── routing-instances
└── switch-options
```

## 2. Interface Naming

### Physical Interfaces
Format: `<type>-<FPC>/<PIC>/<port>`

| Prefix | Type | Speed |
|---|---|---|
| `ge-` | Gigabit Ethernet | 1G |
| `xe-` | 10-Gigabit Ethernet | 10G |
| `et-` | 25G/40G/100G/400G Ethernet | 25G+ |
| `ae` | Aggregated Ethernet (LAG) | Bundle |
| `lo0` | Loopback | Virtual |
| `irb` | Integrated Routing and Bridging | L3 gateway for VLANs |
| `em0` / `me0` / `fxp0` | Management Ethernet | OOB management |
| `vme` | Virtual Management Ethernet | Virtual mgmt |

### Units (Logical Interfaces)
```junos
# Physical interface + unit = logical interface
set interfaces xe-0/0/0 unit 0 family inet address 10.0.1.1/31
# xe-0/0/0.0 is the logical interface

# Multiple units for sub-interfaces (VLAN tagging)
set interfaces xe-0/0/0 unit 100 vlan-id 100
set interfaces xe-0/0/0 unit 100 family inet address 10.1.100.1/24
```

## 3. Configuration Groups

Groups define reusable configuration templates:

```junos
# Define a group
set groups BASE-CONFIG system time-zone Asia/Ho_Chi_Minh
set groups BASE-CONFIG system ntp server 10.254.0.123
set groups BASE-CONFIG system syslog host 10.254.0.51 any warning
set groups BASE-CONFIG system login user netops class super-user

# Apply the group
set apply-groups BASE-CONFIG

# Apply to specific section only
set interfaces xe-0/0/0 apply-groups IF-DEFAULTS
```

### Apply-Path (Dynamic Prefix Lists)
```junos
# Auto-generate prefix-list from config
set policy-options prefix-list BGP-NEIGHBORS apply-path "protocols bgp group <*> neighbor <*>"
# This automatically includes all configured BGP neighbor IPs
```

## 4. Rescue Configuration

A saved "known-good" config you can revert to in emergency:

```junos
# Save current config as rescue
request system configuration rescue save

# Revert to rescue config
rollback rescue
commit

# Delete rescue config
request system configuration rescue delete
```

## 5. Configuration Archival

Automatically back up config on every commit:

```junos
set system archival configuration transfer-on-commit
set system archival configuration archive-sites "scp://user@10.254.0.60:/config-archive/"
```

## 6. Base Configuration Template

Recommended starting config for a new DC switch:

```junos
# System
set system host-name LEAF-A01-01
set system domain-name dc1.example.com
set system time-zone Asia/Ho_Chi_Minh
set system root-authentication encrypted-password "<hash>"

# Management
set system services ssh protocol-version v2
set system services ssh rate-limit 5
set system services ssh root-login deny
set system services netconf ssh

# Users
set system login user netops class super-user
set system login user netops authentication ssh-rsa "ssh-rsa AAAA..."
set system login user readonly class read-only

# NTP
set system ntp server 10.254.0.123 prefer
set system ntp server 10.254.0.124

# Syslog
set system syslog host 10.254.0.51 any warning
set system syslog host 10.254.0.51 authorization info
set system syslog host 10.254.0.51 interactive-commands info
set system syslog file messages any warning
set system syslog file messages authorization info
set system syslog file interactive-commands interactive-commands any

# SNMP
set snmp community "READONLY" authorization read-only
set snmp community "READONLY" clients 10.254.0.0/24
set snmp trap-group MONITORING targets 10.254.0.50
set snmp trap-group MONITORING categories link
set snmp trap-group MONITORING categories chassis

# LLDP
set protocols lldp interface all

# Management interface
set interfaces em0 unit 0 family inet address 10.255.0.11/24

# Static route for management
set routing-options static route 0.0.0.0/0 next-hop 10.255.0.1 no-readvertise
```
