# JunOS Logical Systems & Routing Instances

## 1. Routing Instances Overview

| Instance Type | Purpose | L2/L3 | Use in DC |
|---|---|---|---|
| **default** | Main routing table (inet.0) | L3 | All traffic by default |
| **Virtual Router (VR)** | Separate routing table, no RT/RD | L3 | Multi-tenant L3, management VRF |
| **VRF (vrf)** | Separate routing table with RT/RD for BGP | L3 | EVPN Type-5, L3VPN |
| **Virtual Switch (VS)** | Separate L2 bridge domain | L2 | Multi-tenant L2 |
| **VPLS** | Virtual Private LAN Service | L2 | Legacy L2VPN |
| **EVPN** | Ethernet VPN | L2+L3 | Modern DC overlay |

## 2. Virtual Router (VR)

A simple L3 routing table separation. No route-target import/export — just isolated routing.

```junos
# Create a Virtual Router instance
set routing-instances MGMT instance-type virtual-router

# Assign interfaces
set routing-instances MGMT interface em0.0

# Add routing within the VR
set routing-instances MGMT routing-options static route 0.0.0.0/0 next-hop 10.255.0.1

# Operational commands
show route table MGMT.inet.0            # Routes in this VR
ping 10.255.0.1 routing-instance MGMT   # Ping from this VR
```

**Use case**: Isolate management traffic from production routing table.

## 3. VRF (Virtual Routing and Forwarding)

VRF adds Route Distinguisher (RD) and Route Target (RT) for BGP route import/export:

```junos
# Create VRF for a tenant
set routing-instances TENANT-A instance-type vrf
set routing-instances TENANT-A route-distinguisher 65001:100
set routing-instances TENANT-A vrf-target target:65001:100

# Assign IRB interfaces (L3 gateway for VLANs)
set routing-instances TENANT-A interface irb.100
set routing-instances TENANT-A interface irb.200

# VRF routing
set routing-instances TENANT-A routing-options static route 0.0.0.0/0 next-hop 10.0.0.1

# EVPN Type-5 (IP prefix routes) for inter-VXLAN L3 routing
set routing-instances TENANT-A protocols evpn ip-prefix-routes advertise direct-nexthop
set routing-instances TENANT-A protocols evpn ip-prefix-routes encapsulation vxlan
set routing-instances TENANT-A protocols evpn ip-prefix-routes vni 5100

# Operational commands
show route table TENANT-A.inet.0
show route table TENANT-A.evpn.0
```

**Use case**: EVPN Type-5 inter-VNI routing, multi-tenant isolation with L3.

## 4. Virtual Switch (VS)

Separate L2 switching domain with its own VLAN namespace:

```junos
# Create Virtual Switch
set routing-instances VS-CUSTOMER-B instance-type virtual-switch

# Assign VLANs
set routing-instances VS-CUSTOMER-B vlans CUST-B-DATA vlan-id 100
set routing-instances VS-CUSTOMER-B vlans CUST-B-MGMT vlan-id 200

# Assign interfaces
set routing-instances VS-CUSTOMER-B interface xe-0/0/10.0

# Bridge domain
set routing-instances VS-CUSTOMER-B bridge-domains CUST-B-DATA vlan-id 100
```

**Use case**: Multi-tenant L2 isolation where VLAN IDs might overlap between tenants.

## 5. Logical Systems (LSYS)

A Logical System is a **virtual partition** of the physical device, each with its own:
- Configuration
- Routing tables
- Interfaces
- Admin accounts

```junos
# Create Logical System
set logical-systems LS-CUSTOMER-A interfaces xe-0/0/10 unit 0
set logical-systems LS-CUSTOMER-A routing-options static route 0.0.0.0/0 next-hop 10.0.1.1
set logical-systems LS-CUSTOMER-A protocols ospf area 0 interface xe-0/0/10.0

# Enter LSYS context
set cli logical-system LS-CUSTOMER-A

# Operational commands within LSYS
show route logical-system LS-CUSTOMER-A
show interfaces terse logical-system LS-CUSTOMER-A
```

**Use case**: True device virtualization for managed services. Less common in modern DC (EVPN/VRF preferred).

## 6. When to Use What

| Scenario | Instance Type | Why |
|---|---|---|
| Isolate management traffic | **Virtual Router** | Simple, no BGP integration needed |
| Multi-tenant L3 with EVPN | **VRF** | RT/RD for BGP advertisement, Type-5 routes |
| Multi-tenant L2 (overlapping VLANs) | **Virtual Switch** | Separate VLAN namespaces |
| EVPN-VXLAN tenant routing | **VRF** (with EVPN Type-5) | Standard IP Fabric design |
| Full device partition (managed service) | **Logical System** | Independent admin, routing, interfaces |
| Legacy L2 VPN | **VPLS** | Being replaced by EVPN |

## 7. Verification Commands

```junos
# List all routing instances
show route instance

# Show routes in specific instance
show route table <instance-name>.inet.0

# Ping from specific instance
ping 10.0.1.1 routing-instance <instance-name>

# Traceroute from specific instance
traceroute 10.0.1.1 routing-instance <instance-name>
```
