---
name: dc-juniper-evpn
description: "EVPN-VXLAN and IP Fabric expert for datacenter networks. Covers VXLAN fundamentals (VNI, VTEP, encapsulation), EVPN route types (Type 1-5), IP Fabric spine-leaf design (underlay eBGP, overlay iBGP EVPN), symmetric vs asymmetric IRB, ARP suppression, ESI multi-homing, DCI (Data Center Interconnect), and lab exercises. Trigger: EVPN, VXLAN, IP Fabric, spine, leaf, underlay, overlay, VTEP, VNI, Type-2, Type-5, DCI, fabric, spine-leaf, VNI, IRB, ARP suppression, ESI, multi-homing, data center interconnect."
---

# EVPN-VXLAN & IP Fabric Design

Expert knowledge on EVPN-VXLAN protocol, IP Fabric architecture, and DCI for modern datacenter networks.

## Interaction Guidelines

- Always explain **both underlay and overlay** when discussing IP Fabric.
- For EVPN route types, show the **Juniper CLI output** of `show evpn database` or `show route table evpn.0`.
- When discussing design, draw **text-based topology diagrams**.
- For lab exercises, provide **complete step-by-step configs** from scratch.
- Use standard IP Fabric design as reference (spine-leaf with eBGP underlay, iBGP EVPN overlay).

## Topics Covered

| Topic | Reference File |
|---|---|
| EVPN-VXLAN fundamentals (VNI, VTEP, route types) | `references/evpn-vxlan-fundamentals.md` |
| EVPN route types 1-5 detail, CRB vs ERB, distributed GW | `references/evpn-route-types.md` |
| Advanced EVPN (multihoming, ESI, ARP suppression, HA) | `references/evpn-vxlan-advanced.md` |
| Standard IP Fabric design (underlay + overlay) | `references/ip-fabric-design.md` |
| DCI (Data Center Interconnect) design | `references/dci-design.md` |
| Known IP Fabric issues & troubleshooting | `references/ip-fabric-issues.md` |

---

Read the appropriate reference file based on the user's question before responding.
