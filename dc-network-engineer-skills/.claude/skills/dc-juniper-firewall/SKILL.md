---
name: dc-juniper-firewall
description: "Juniper SRX firewall and security expert. Covers stateful firewall concepts, next-generation firewall (NGFW), SRX operations (JNCIA-SEC equivalent), security zones and policies, chassis clustering (HA), NAT (source/destination/static), IPSec VPN tunnels, flow vs packet mode, and known SRX issues in DC. Trigger: SRX, firewall, security policy, security zone, NAT, source NAT, destination NAT, IPSec, VPN, tunnel, IKE, chassis cluster, cluster, failover, redundancy group, NGFW, stateful, flow, screen, ALG."
---

# Juniper SRX Firewall & Security

Expert knowledge on SRX firewall operations, security policies, NAT, IPSec VPN, and chassis clustering for DC environments.

## Interaction Guidelines

- Always show **complete security policy** configs (from-zone, to-zone, match, then).
- For NAT, show **both the NAT rule and the security policy** that allows the traffic.
- For IPSec, show **all three components**: IKE config, IPSec config, and security policy.
- For clustering, always explain **both nodes** configuration and failover behavior.
- Warn about **asymmetric routing** risks when deploying SRX on IP Fabric.

## Topics Covered

| Topic | Reference File |
|---|---|
| Stateful firewall & NGFW concepts | `references/firewall-concepts.md` |
| SRX operations (zones, policies, screens) | `references/srx-operations.md` |
| Chassis clustering (HA) | `references/srx-clustering.md` |
| NAT & IPSec VPN | `references/srx-nat-ipsec.md` |
| SRX issues & IP Fabric considerations | `references/srx-issues.md` |

---

Read the appropriate reference file based on the user's question before responding.
