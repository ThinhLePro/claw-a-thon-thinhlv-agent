---
name: bgp-policy-framework
description: "Modern BGP Policy Framework for Multi-Transit ISP on Juniper Junos. Covers BGP communities as control plane, structured policy chains (import/export), Gao-Rexford valley-free routing, RPKI Route Origin Validation (ROV), customer prefix-list management, customer self-service traffic engineering, RTBH and Flowspec for DDoS mitigation, naming conventions, and complete Junos configuration templates. Trigger: BGP policy, transit, peering, IXP, RPKI, ROV, communities, local-pref, prepend, RTBH, blackhole, Flowspec, DDoS, traffic engineering, multi-homing, Gao-Rexford, valley-free, import policy, export policy, BGP framework, ISP."
---

# Modern BGP Policy Framework for Multi-Transit ISP

Production-ready BGP policy framework for Juniper Junos — designed for multi-transit ISP operations.

## Interaction Guidelines

- Khi tư vấn BGP policy, luôn tham chiếu **Gao-Rexford valley-free model** (Customer > Peer > Transit)
- Sử dụng **BGP Communities as Control Plane** — traffic engineering = "set a community"
- Mọi policy đều tuân theo **Default-Deny** — không route nào leak trừ khi explicitly match
- RPKI ROV: reject invalid, accept valid/unknown, tag state bằng community
- Customer prefix-list: luôn yêu cầu LOA, maintain per-customer
- Cung cấp **complete Junos config** khi được hỏi

## Topics Covered

| Topic | Nội dung |
|---|---|
| Architecture | Policy chain design, route classification (4 buckets), default-deny |
| RPKI ROV | Validator deployment (Routinator, rpki-client), RTR protocol, fail-safe |
| Customer Prefix-Lists | Per-customer LOA, prefix-list management, change control |
| Traffic Engineering | Customer self-service communities (no-export, prepend, selective) |
| DDoS Mitigation | RTBH (/32 blackhole), Flowspec (protocol-level filtering) |
| Naming Conventions | Policy names, prefix-lists, AS-path filters, community plan |
| Junos Configuration | Complete policy-options config, per-peer import/export chains |
| Community Schema | Internal communities (source, RPKI, geo, LP), customer-facing communities |

---

Read `references/modern-bgp-policy-framework.md` for the complete framework with all Junos configurations.
