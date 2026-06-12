# Gateway Routing Policies — Domestic & International

## 1. Concept: Domestic vs International Gateways

In many DC environments (especially in Vietnam / APAC), traffic is classified into:
- **Domestic**: Traffic destined for IP prefixes within the country (e.g., Vietnamese ISPs, local services)
- **International**: Traffic destined for prefixes outside the country (e.g., Google, AWS, global CDNs)

This classification is important because:
- **Domestic transit** is typically cheaper and lower latency
- **International transit** is more expensive and higher latency
- Routing policies can direct domestic traffic through domestic ISP links and international traffic through international links

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        DC Network                            │
│                                                              │
│  ┌──────────────┐                    ┌──────────────────┐   │
│  │ Domestic GW   │                    │ International GW  │   │
│  │ (Edge router) │                    │ (Edge router)     │   │
│  │ AS 65001      │                    │ AS 65001          │   │
│  └───┬───────┬───┘                    └───┬──────────┬───┘   │
│      │       │                            │          │       │
│      │       │                            │          │       │
│  ┌───┴──┐ ┌──┴───┐                  ┌───┴──┐  ┌───┴──┐    │
│  │ISP-VN│ │ISP-VN│                  │ISP-  │  │ISP-  │    │
│  │  #1  │ │  #2  │                  │Intl  │  │Intl  │    │
│  │(VNPT)│ │(VTL) │                  │ #1   │  │ #2   │    │
│  └──────┘ └──────┘                  └──────┘  └──────┘    │
│  Domestic ISPs                       International ISPs     │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Domestic Gateway Routing Policies

### Principles

1. **Accept domestic prefixes with high local-preference** from domestic ISPs
2. **Tag domestic routes** with a community (e.g., `65001:1000`)
3. **Export only our prefixes** (and customer prefixes) to domestic ISPs
4. **Do not send international transit traffic** through domestic links (waste of domestic bandwidth)

### Identifying Domestic Prefixes

Domestic prefixes can be identified by:
- **ASN-based**: Maintain a list of known domestic ASNs (ISPs, major services)
- **GeoIP prefix list**: Maintain a prefix list of all domestic IP blocks
- **Community from ISP**: Some ISPs tag routes with a community indicating domestic vs international
- **IRR / RPKI origin AS**: Check if the origin AS is registered in the country

### Juniper Configuration — Domestic Gateway

```junos
# Community definitions
set policy-options community DOMESTIC members 65001:1000
set policy-options community FROM-DOMESTIC-ISP members 65001:100
set policy-options community INTERNATIONAL members 65001:2000

# Domestic prefix list (simplified — in production, use bgpq4 to generate from IRR)
# This list should contain all Vietnamese IP blocks
set policy-options prefix-list DOMESTIC-PREFIXES 14.0.0.0/8 orlonger
set policy-options prefix-list DOMESTIC-PREFIXES 27.64.0.0/12 orlonger
set policy-options prefix-list DOMESTIC-PREFIXES 42.112.0.0/13 orlonger
set policy-options prefix-list DOMESTIC-PREFIXES 42.96.0.0/14 orlonger
set policy-options prefix-list DOMESTIC-PREFIXES 103.0.0.0/8 orlonger
set policy-options prefix-list DOMESTIC-PREFIXES 113.160.0.0/11 orlonger
set policy-options prefix-list DOMESTIC-PREFIXES 115.64.0.0/11 orlonger
set policy-options prefix-list DOMESTIC-PREFIXES 171.224.0.0/11 orlonger
set policy-options prefix-list DOMESTIC-PREFIXES 183.80.0.0/13 orlonger
# ... (full list maintained separately)

# Import from domestic ISP: tag and prefer
set policy-options policy-statement IMPORT-DOMESTIC-ISP term REJECT-BOGONS from prefix-list BOGONS
set policy-options policy-statement IMPORT-DOMESTIC-ISP term REJECT-BOGONS then reject

set policy-options policy-statement IMPORT-DOMESTIC-ISP term DOMESTIC-ROUTES from prefix-list DOMESTIC-PREFIXES
set policy-options policy-statement IMPORT-DOMESTIC-ISP term DOMESTIC-ROUTES then local-preference 300
set policy-options policy-statement IMPORT-DOMESTIC-ISP term DOMESTIC-ROUTES then community add DOMESTIC
set policy-options policy-statement IMPORT-DOMESTIC-ISP term DOMESTIC-ROUTES then community add FROM-DOMESTIC-ISP
set policy-options policy-statement IMPORT-DOMESTIC-ISP term DOMESTIC-ROUTES then accept

# Accept non-domestic routes with lower preference (as backup)
set policy-options policy-statement IMPORT-DOMESTIC-ISP term OTHER-ROUTES then local-preference 50
set policy-options policy-statement IMPORT-DOMESTIC-ISP term OTHER-ROUTES then accept

# Export to domestic ISP: our prefixes only
set policy-options policy-statement EXPORT-TO-DOMESTIC-ISP term OUR-PREFIXES from prefix-list OUR-PREFIXES
set policy-options policy-statement EXPORT-TO-DOMESTIC-ISP term OUR-PREFIXES then accept
set policy-options policy-statement EXPORT-TO-DOMESTIC-ISP term REJECT then reject
```

---

## 3. International Gateway Routing Policies

### Principles

1. **Accept all prefixes** from international ISPs (full transit table)
2. **Set moderate local-preference** — international routes should be used when domestic path not available
3. **Tag international routes** with community (e.g., `65001:2000`)
4. **Export our prefixes** to international ISPs
5. **Optionally AS-PATH prepend** on backup international ISP

### Juniper Configuration — International Gateway

```junos
# Import from international ISP-A (primary)
set policy-options policy-statement IMPORT-INTL-ISP-A term REJECT-BOGONS from prefix-list BOGONS
set policy-options policy-statement IMPORT-INTL-ISP-A term REJECT-BOGONS then reject

set policy-options policy-statement IMPORT-INTL-ISP-A term ACCEPT then local-preference 200
set policy-options policy-statement IMPORT-INTL-ISP-A term ACCEPT then community add INTERNATIONAL
set policy-options policy-statement IMPORT-INTL-ISP-A term ACCEPT then accept

# Import from international ISP-B (backup)
set policy-options policy-statement IMPORT-INTL-ISP-B term REJECT-BOGONS from prefix-list BOGONS
set policy-options policy-statement IMPORT-INTL-ISP-B term REJECT-BOGONS then reject

set policy-options policy-statement IMPORT-INTL-ISP-B term ACCEPT then local-preference 100
set policy-options policy-statement IMPORT-INTL-ISP-B term ACCEPT then community add INTERNATIONAL
set policy-options policy-statement IMPORT-INTL-ISP-B term ACCEPT then accept

# Export: prepend on backup ISP to influence inbound from internet
set policy-options policy-statement EXPORT-TO-INTL-ISP-B term OUR-PREFIXES from prefix-list OUR-PREFIXES
set policy-options policy-statement EXPORT-TO-INTL-ISP-B term OUR-PREFIXES then as-path-prepend "65001 65001"
set policy-options policy-statement EXPORT-TO-INTL-ISP-B term OUR-PREFIXES then accept
set policy-options policy-statement EXPORT-TO-INTL-ISP-B term REJECT then reject
```

---

## 4. Traffic Flow Summary

| Traffic Type | Path | Local Pref | Why |
|---|---|---|---|
| Domestic → Domestic IP | Via domestic ISP | 300 | Cheapest, lowest latency |
| Outbound → International IP | Via international ISP primary | 200 | Dedicated intl bandwidth |
| Inbound from domestic | Via domestic ISP (our prefix announced there) | — | Direct path to us |
| Inbound from international | Via intl ISP primary (prepend on backup) | — | Primary path preferred |
| Failover (domestic ISP down) | International ISP carries all traffic | 100/50 | Backup path works |

---

## 5. Verification

```junos
# Check route classification
show route 14.0.1.1 detail | match "Local Pref|Communities"
# Should show: Local Pref 300, community 65001:1000 (domestic)

show route 8.8.8.8 detail | match "Local Pref|Communities"
# Should show: Local Pref 200, community 65001:2000 (international)

# Verify domestic traffic exits via domestic ISP
traceroute 14.0.1.1 source <our-prefix>
# First hop should be domestic ISP's IP

# Verify international traffic exits via international ISP
traceroute 8.8.8.8 source <our-prefix>
# First hop should be international ISP's IP
```
