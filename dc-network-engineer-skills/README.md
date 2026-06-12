# DC Network Engineer Skills

A bundle of [SKILL.md](https://www.mintlify.com/blog/skill-md)-compatible skills that turn your AI coding tool into a **Senior Network Engineer** for datacenter operations — covering physical infrastructure, cabling, TCP/IP, internet routing, Juniper expertise (EVPN-VXLAN, SRX, MC-LAG), and day-to-day operational workflows.

Drop them into **Claude Code**, **Cursor**, **OpenAI Codex**, or any SKILL.md-aware client and you get deep networking expertise plus operational SOPs accessible via natural language.

---

## TL;DR — Install in 30 Seconds

```bash
git clone <this-repo> dc-network-engineer-skills

# Pick the install target for your tool
#   Claude Code  → ~/.claude/skills        or  <project>/.claude/skills
#   Cursor       → ~/.cursor/skills        or  <project>/.cursor/skills

mkdir -p ~/.claude/skills
cp -r dc-network-engineer-skills/.claude/skills/* ~/.claude/skills/
```

Then restart your tool and ask: *"Giải thích EVPN Type-5 route"* or *"Hướng dẫn thêm VLAN 100 vào trunk trên Juniper"*.

---

## Skills Index

| Skill | Domain | What it does |
|---|---|---|
| `/dc-overview` | Reference | **Start here.** Platform reference, skill index, and routing to the correct skill. |
| `/dc-infrastructure` | Physical DC | Chiller, CRAC, UPS, Genset, Racks, containment, power distribution, cabinet coordinates. |
| `/dc-cabling` | Cabling | Copper/fiber cables, transceivers (SFP/QSFP), patch panels, ODF, labeling, pricing, cabling best practices. |
| `/dc-tcpip` | Networking | TCP/IP deep dive — OSI model, L2/L3/L4 protocols, packet analysis with tcpdump/Wireshark. |
| `/dc-routing` | Internet | BGP, ISP peering, routing policies, DDoS protection, domestic/international gateways. |
| `/dc-juniper-basics` | Juniper | JunOS CLI, configuration, OSPF, BGP, static routes, routing policies, firewall filters, instances. |
| `/dc-juniper-evpn` | Juniper | EVPN-VXLAN protocol, IP Fabric design, DCI, spine-leaf architecture, lab exercises. |
| `/dc-juniper-firewall` | Juniper | SRX firewall, security policies, NAT, IPSec VPN, chassis clustering, NGFW. |
| `/dc-juniper-mclag` | Juniper | MC-LAG protocols, ICCP, ICL, comparison with other HA technologies, issues. |
| `/dc-operations` | Operations | Daily SOPs — VLAN/ACL/bonding config, new switch deployment, change management. |
| `/dc-troubleshoot` | Operations | Alert handling, monitoring tools (CheckMK, Cacti, Grafana), troubleshooting playbooks. |
| `/dc-planning` | Operations | Network design, configuration audit, hardware lifecycle, capacity planning. |

### Lifecycle Map

```
┌───────────────────────────────────────────────────────────────┐
│ GETTING STARTED                                               │
│   /dc-overview ──────────── Platform reference & skill index  │
├───────────────────────────────────────────────────────────────┤
│ KNOWLEDGE BASE (Tra cứu kiến thức)                            │
│   /dc-infrastructure ────── DC vật lý: Chiller, UPS, Racks   │
│   /dc-cabling ───────────── Cáp, module, patch panel, ODF    │
│   /dc-tcpip ─────────────── TCP/IP stack, pcap analysis       │
│   /dc-routing ───────────── BGP, ISP peering, DDoS           │
├───────────────────────────────────────────────────────────────┤
│ JUNIPER EXPERTISE                                             │
│   /dc-juniper-basics ────── JunOS CLI, routing, policies     │
│   /dc-juniper-evpn ─────── EVPN-VXLAN, IP Fabric design     │
│   /dc-juniper-firewall ──── SRX, NAT, IPSec, clustering     │
│   /dc-juniper-mclag ─────── MC-LAG protocols & use cases     │
├───────────────────────────────────────────────────────────────┤
│ DAY-TO-DAY OPERATIONS                                         │
│   /dc-operations ────────── SOP: VLAN, ACL, bonding, deploy  │
│   /dc-troubleshoot ──────── Alert → Debug → Fix workflow     │
│   /dc-planning ──────────── Network design, audit, review    │
└───────────────────────────────────────────────────────────────┘
```

---

## Persona

When these skills are loaded, the AI agent adopts the persona of a **Senior Network Engineer** with the following characteristics:

- **Experience**: 8+ years in datacenter network operations
- **Vendor expertise**: Juniper Networks (JunOS, EVPN-VXLAN, SRX, MC-LAG)
- **Communication style**: Practical, clear, with real CLI examples — never abstract theory without actionable context
- **Safety-first**: Always recommends `commit confirmed`, rollback plans, and maintenance windows for production changes
- **Bilingual**: Responds in the user's language (Vietnamese or English), uses standard English networking terminology

---

## Repo Layout

```
dc-network-engineer-skills/
├── .claude/skills/
│   ├── dc-overview/              # Platform reference & skill router
│   ├── dc-infrastructure/        # DC physical infrastructure
│   │   └── references/
│   ├── dc-cabling/               # Cabling expert
│   │   └── references/
│   ├── dc-tcpip/                 # TCP/IP deep dive
│   │   └── references/
│   ├── dc-routing/               # Internet routing & BGP
│   │   └── references/
│   ├── dc-juniper-basics/        # JunOS fundamentals
│   │   └── references/
│   ├── dc-juniper-evpn/          # EVPN-VXLAN & IP Fabric
│   │   └── references/
│   ├── dc-juniper-firewall/      # SRX firewall & security
│   │   └── references/
│   ├── dc-juniper-mclag/         # MC-LAG technologies
│   │   └── references/
│   ├── dc-operations/            # Day-to-day SOPs
│   │   └── references/
│   ├── dc-troubleshoot/          # Incident response
│   │   └── references/
│   └── dc-planning/              # Design & audit
│       └── references/
└── README.md
```

Each skill folder contains a `SKILL.md` (the contract read by the AI tool) and `references/` with detailed knowledge base documents.

---

## Important Notes

1. **This is a knowledge agent** — it provides expert guidance and generates configurations, but does NOT automatically execute commands on production network devices.
2. **Always verify generated configs** — review in a lab or with `commit check` before applying to production.
3. **VNG-specific content** — files marked with `[VNG-SPECIFIC]` contain organization-specific knowledge. Customize for your environment.
4. **First time? Use `/dc-overview`** — it will route you to the right skill.
