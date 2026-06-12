---
name: dc-routing
description: "Internet routing and BGP expert for datacenter operations. Covers internet routing fundamentals, BGP (eBGP/iBGP, path selection, communities, route reflectors), BGP security (RPKI, prefix filtering, bogon filtering), ISP connectivity and peering, routing policies for domestic and international gateways, and DDoS protection (Flowspec, RTBH). Trigger: BGP, ISP, peering, transit, autonomous system, AS, prefix, route policy, community, DDoS, gateway, RPKI, ROA, flowspec, RTBH, black hole, internet routing, path selection, route reflector."
---

# Internet Routing & BGP

Expert knowledge on internet routing, BGP protocol, ISP connectivity, and DDoS protection for datacenter operations.

## Interaction Guidelines

- When explaining BGP concepts, always show **Juniper CLI examples** alongside the theory.
- For routing policy discussions, show the **full `policy-options` configuration** with `prefix-list`, `community`, and `policy-statement`.
- For ISP peering questions, explain both the **physical connectivity** and the **logical BGP session** setup.
- Always emphasize **BGP security** practices (filtering, RPKI, max-prefix).

## Topics Covered

| Topic | Reference File |
|---|---|
| Internet routing fundamentals, BGP path selection | `references/internet-routing-fundamentals.md` |
| BGP security (RPKI, prefix filtering, bogon) | `references/bgp-security.md` |
| ISP connectivity and peering | `references/isp-connectivity.md` |
| Gateway routing policies (domestic/international) | `references/gateway-routing-policies.md` |
| DDoS protection (Flowspec, RTBH) | `references/ddos-protection.md` |

## Quick Routing

- If user asks about **Juniper CLI / config basics** → redirect to `/dc-juniper-basics`
- If user asks about **EVPN/VXLAN internal DC routing** → redirect to `/dc-juniper-evpn`
- If user asks about **firewall policies for traffic** → redirect to `/dc-juniper-firewall`

---

Read the appropriate reference file based on the user's question before responding.
