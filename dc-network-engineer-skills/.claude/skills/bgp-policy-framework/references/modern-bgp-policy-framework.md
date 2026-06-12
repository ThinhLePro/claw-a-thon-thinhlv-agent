# Modern BGP Policy Framework for Multi-Transit ISP

---


# Executive Summary

This document presents a complete, production-ready BGP policy framework for a multi-transit Tier-3 ISP. It is designed for Juniper Networks platforms (Junos OS) and follows the conventions used by major Tier-1/Tier-2 carriers and large content networks.

The framework is built around three core principles:


1. **BGP Communities as the Control Plane.** Once the framework is built, traffic engineering becomes "set a community" rather than "edit a policy." This is how Hurricane Electric (AS6939), NTT (AS2914), Cogent (AS174), Telia/Arelion (AS1299) and most CDNs operate.
2. **Default-Deny with Structured Policy Chains.** Every EBGP session has a deterministic ingress and egress chain. Nothing leaks unless it explicitly matches an accept term. The Gao-Rexford valley-free routing model is enforced at all times.
3. **Validation at Every Edge.** RPKI Route Origin Validation rejects invalids on ingress. Customer prefix-lists enforce per-customer authorization. Both work together; neither replaces the other.

Note on scope: ASPA (Autonomous System Provider Authorization) is intentionally excluded from this design. ASPA is not yet broadly supported across Junos releases or the global validator/publisher ecosystem. This framework can be extended to include ASPA when the dataset and platform support mature, without requiring restructuring.

# Part 1: Architecture

## 1.1 Architectural Concepts

### 1.1.1 The "BGP Communities as Control Plane" Philosophy

The single most important modern principle: never manipulate traffic by editing prefix-lists or per-peer policies directly. Instead:

* Tag every route at ingress with informational communities (where it came from, what type, what region).
* Tag every route at ingress or via internal tools with action communities (what to do with it).
* Write generic, peer-agnostic export/import policies that read communities and act accordingly.

This means once your framework is built, 99% of traffic engineering becomes "set a community" — done by NOC engineers, automation, or even peering tools — without touching policy code.

### 1.1.2 Policy Chain Architecture

Every EBGP session has a structured chain rather than one monolithic policy:

```
IMPORT chain (from peer → into RIB):
  [martians-reject] → [bogon-asn-reject] → [RPKI-reject-invalid]
  → [reject-own-prefixes-back] → [peer-specific-filter]
  → [scrub-inbound-communities] → [tag-RPKI-state]
  → [tag-source/region] → [set-base-localpref]
  → [RPKI-localpref-bonus] → [accept]

EXPORT chain (from RIB → to peer):
  [reject-NO_EXPORT] → [honor-action-communities]
  → [scrub-action-communities]
  → [advertise-own] → [advertise-customers]
  → [advertise-peers/transits-conditional] → [default-reject]
```

The key principle: default deny on both directions. Nothing leaks unless it matches an explicit accept term.

### 1.1.3 Route Classification (Four Buckets)

Every route in your RIB belongs to exactly one class, identified by community:

| Class | Meaning | Default LP | To Transit | To Peer | To Customer |
|-------|---------|------------|------------|---------|-------------|
| Customer | Paying you | 200        | Yes        | Yes     | Yes         |
| Peer  | Settlement-free | 100        | No         | No      | Yes         |
| Transit | You pay them | 80         | No         | No      | Yes         |
| Internal/Own | Your aggregates | 250        | Yes        | Yes     | Yes         |

This is the Gao-Rexford valley-free routing model. Violating it (e.g., re-advertising transit routes to other transit) is what causes major BGP leak incidents.

## 1.2 System Architecture Diagram

```
┌──────────────────────────────────────────────────────────┐
│                         CONTROL PLANE                    │
│                                                          │
│  ┌──────────────┐   ┌──────────────┐                     │
│  │  Routinator  │   │ rpki-client  │                     │
│  │  Site A      │   │  Site B      │                     │
│  │  (RPKI ROV)  │   │  (RPKI ROV)  │                     │
│  └──────┬───────┘   └──────┬───────┘                     │
│         │ RTR              │ RTR                         │
│         └──────────┬───────┘                             │
│                    │                                     │
│  ┌─────────────────▼──────────────────────────────────┐  │
│  │           Edge Routers (Junos)                     │  │
│  │  - validation-database (RPKI ROV)                  │  │
│  │  - per-customer prefix-lists (manually maintained) │  │
│  │  - Flowspec rules from controller                  │  │
│  └─────┬──────────┬──────────┬──────────┬─────────────┘  │
└────────┼──────────┼──────────┼──────────┼────────────────┘
         │ EBGP     │ EBGP     │ EBGP     │ EBGP
    ┌────▼────┐ ┌───▼───┐ ┌────▼───┐ ┌────▼─────┐
    │ Transit │ │ Peer  │ │ IXP    │ │ Customer │
    │ NTT     │ │ HE    │ │ DE-CIX │ │ ACME     │
    └─────────┘ └───────┘ └────────┘ └──────────┘
```

# Part 2: RPKI Route Origin Validation

## 2.1 Concept

RPKI ROV answers one question for every received route: "Is this AS authorized to originate this prefix?"

The router compares the route's (prefix, prefix-length, origin-AS) against ROAs (Route Origin Authorizations) cryptographically signed by IP resource holders. The result is one of three states:

| State | Meaning | Action |
|-------|---------|--------|
| valid | Matches a ROA — origin AS is authorized | Accept, prefer |
| unknown | No ROA exists for this prefix | Accept |
| invalid | A ROA exists, but origin AS or prefix-length differs | **Reject** |

Rejecting invalids is the entire point. This stops route hijacks like AS7007, the YouTube/Pakistan Telecom hijack, and the dozens that happen monthly today.

## 2.2 RPKI Architecture — Separation of Concerns

The router does NOT validate RSA signatures itself. The architecture has three components:

```
┌────────────────────┐     ┌──────────────────┐     ┌───────────────┐
│  RIRs / TAs        │     │  RPKI Validator  │     │  Junos Router │
│  (ARIN/RIPE/APNIC/ │ →   │  (Routinator /   │ →   │  (RTR client) │
│   LACNIC/AFRINIC)  │     │   rpki-client /  │     │               │
│  Publish ROAs      │     │   FORT / OctoRPKI│     │  validation-  │
│  via rsync/RRDP    │     │  Builds VRP set  │     │  database     │
└────────────────────┘     └──────────────────┘     └───────────────┘
       Signed ROAs            Validated Cache         RTR Protocol
                                                      (RFC 6810/8210)
```

* RIRs/TAs publish signed ROAs.
* RPKI Validator (Routinator, rpki-client, FORT, OctoRPKI — pick at least two different implementations for diversity) periodically pulls and validates them, producing a flat list called VRPs (Validated ROA Payloads).
* Routers speak RTR (RPKI-to-Router) protocol to the validator and import VRPs into their `validation-database`.
* The router only does fast lookups: prefix + origin → state.

## 2.3 Design Principles for ROV


1. Run at least two validators in different locations.
2. Validate at every EBGP ingress point — transits, peers, IXPs, customers.
3. Reject invalid only on EBGP import. Never apply ROV on IBGP or customer-facing exports.
4. Tag valid/unknown with communities so you preserve state across IBGP and can audit/troubleshoot.
5. Use LocalPref tiebreak (small additive bonus) so two routes identical except validation state — valid wins over unknown — without breaking Gao-Rexford ordering.
6. Fail-safe behavior: if all validators are down, Junos treats everything as unknown (not invalid), so traffic continues to flow. Don't change this default.
7. Customers get extra scrutiny. Reject invalid AND require the prefix to be in their per-customer authorized prefix-list.
8. Publish your own ROAs for every prefix you originate, with `maxLength` set tightly. Over-permissive `maxLength` is the most common ROA misconfiguration that allows attackers to hijack more-specifics and still appear valid.

## 2.4 Validator Deployment

**Architecture:** two implementations, two locations.

```
                      ┌──────────────┐
                      │  RIR Repos   │
                      │ (rsync/RRDP) │
                      └──────┬───────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
     ┌────────▼────────┐         ┌──────────▼────────┐
     │  Site A         │         │   Site B          │
     │  Routinator     │         │   rpki-client +   │
     │  (Rust, NLnet)  │         │   StayRTR         │
     └────────┬────────┘         └──────────┬────────┘
              │                             │
              │  RTR (TCP 3323)             │
              │                             │
     ┌────────▼─────────────────────────────▼────────┐
     │              Edge Routers (Junos)             │
     └───────────────────────────────────────────────┘
```

**Design principles:**


1. Two implementations, two locations. Routinator (Rust) at Site A; rpki-client + StayRTR at Site B. If a bug lands in one, the other catches it.
2. Validators on dedicated VMs/containers, not on routers.
3. Outbound Internet access (HTTPS/443 for RRDP, rsync/873 fallback). Don't block this.
4. RTR sessions inbound from routers only. Firewall TCP/3323 to known router IPs.
5. Monitor: VRP count, last-update timestamp, RTR session state, repository fetch failures.

**Routinator setup (Debian/Ubuntu):**

```bash
# Install
curl -O https://packages.nlnetlabs.nl/linux/debian/dists/bookworm/main/binary-amd64/routinator_*_amd64.deb
sudo apt install ./routinator_*_amd64.deb

# Initialize trust anchors (accept ARIN TAL terms)
sudo routinator-init --accept-arin-rpa

# Configure /etc/routinator/routinator.conf
[server]
rtr-listen = ["0.0.0.0:3323"]
http-listen = ["0.0.0.0:8323"]

[rrdp]
fallback = "rsync"

[validation]
strict = false
stale = "reject"

# Start
sudo systemctl enable --now routinator

# Verify
routinator vrps -f csv | wc -l
curl http://localhost:8323/metrics
```

**rpki-client + StayRTR setup:**

```bash
sudo apt install rpki-client stayrtr

# Cron rpki-client to refresh every 20 min
echo '*/20 * * * * rpki-client -j /var/lib/rpki-client/' | sudo crontab -

# StayRTR reads rpki-client output and serves RTR
stayrtr -bind :3323 -cache /var/lib/rpki-client/json -refresh 600
```

**Monitoring (Prometheus key metrics on Routinator):**

* `routinator_rrdp_status` — should be 200 for all repos.
* `routinator_vrps_final` — total VRPs (alert if drops >20%).
* `routinator_rtr_current_connections` — number of routers connected.
* `routinator_last_update_done_ago` — alert if >1 hour.

High availability: validators are stateless. Losing one is fine; Junos `preference` on RTR sessions handles primary/backup. If both fail, Junos treats all routes as unknown — fail-safe.

## 2.5 Originating Your Own ROAs

For every prefix you announce, create a ROA via your RIR portal:

* ARIN: [account.arin.net](http://account.arin.net)
* RIPE: [my.ripe.net](http://my.ripe.net)
* APNIC: [myapnic.net](http://myapnic.net)
* LACNIC: [mi.lacnic.net](http://mi.lacnic.net)
* AFRINIC: [my.afrinic.net](http://my.afrinic.net)

Set `maxLength` to match what you actually announce. If you announce only `203.0.113.0/24`, set `maxLength = 24`. Do NOT set it to 32 "just in case." Validate publicly via:

* <https://rpki-validator.ripe.net/ui/>
* <https://bgp.tools/>
* <https://rpki.cloudflare.com/>

# Part 3: Customer Prefix-List Management

## 3.1 Why Per-Customer Prefix-Lists Are Required

RPKI ROV validates origin AS. It does not tell you which prefixes a customer is allowed to announce to your network. A customer could have valid ROAs for 1000 prefixes, but you only have a contract for 10. You still need explicit per-customer prefix filters as part of your service agreement.

For each customer:

* Obtain a Letter of Authorization (LOA) listing every prefix they are authorized to announce.
* Translate that list into a Junos `prefix-list` named `PL-CUSTOMER-<NAME>-V4` and `PL-CUSTOMER-<NAME>-V6`.
* Translate their authorized origin AS into an `as-path` named `ASP-CUSTOMER-<NAME>`.
* Reference both in the customer-import policy (Part 7.8).

Example:

```
policy-options {
    prefix-list PL-CUSTOMER-ACME-V4 {
        198.51.100.0/24;
        198.51.101.0/24;
    }
    prefix-list PL-CUSTOMER-ACME-V6 {
        2001:db8:acme::/48;
    }
    as-path ASP-CUSTOMER-ACME "^65001(_65001)*$";
}
```

## 3.2 Change Control

When a customer needs to add or remove a prefix:


1. Customer submits change request with updated LOA.
2. NOC verifies the customer is authorized for the prefix (RIR WHOIS or registrar confirmation).
3. NOC updates the relevant `prefix-list` via the standard config change process.
4. Validate with `commit confirmed` and verify the route is being received and accepted.

## 3.3 Best Practices

* Always include both IPv4 and IPv6 prefix-lists, even if the customer only currently announces one family.
* Maintain a master spreadsheet or database of customer → authorized prefixes → LOA reference → date approved.
* Periodically (quarterly) re-verify that each customer's prefix-list still matches their LOA.
* Cross-check against RPKI: if a customer announces a prefix that is RPKI-invalid for their AS, alert and require them to either fix their ROA or update their announcement.

# Part 4: Customer Self-Service Traffic Engineering

## 4.1 Concept

Document a set of communities customers can set on routes they announce to you. Your export policy honors them automatically. Customers self-serve traffic engineering 24/7 without opening tickets.

This is what NTT, Hurricane Electric, Cogent, and most major carriers do. It's the gold standard.

## 4.2 Customer-Facing Community Schema (your ASN = 65000)

Action communities (CUSTOMER sets these on routes they send YOU):

```
Block selective announcement:
  65000:0:peer_asn  → Don't announce to peer_asn
  65000:0:0         → Don't announce to anyone (suppress globally)

  Examples (customer-set):
    65000:0:2914   Don't announce to NTT
    65000:0:1299   Don't announce to Telia
    65000:0:174    Don't announce to Cogent
    65000:0:6939   Don't announce to HE

Selective announcement (whitelist):
  65000:1:peer_asn  → ONLY announce to peer_asn

Prepending:
  65000:101:peer_asn  → Prepend 1x when announcing to peer_asn
  65000:102:peer_asn  → Prepend 2x to peer_asn
  65000:103:peer_asn  → Prepend 3x to peer_asn

  Wildcards:
    65000:101:0    Prepend 1x to all transits
    65000:102:0    Prepend 2x to all transits
    65000:103:0    Prepend 3x to all transits

Special:
  65000:666     RTBH (blackhole this prefix)
  65000:999     Set NO_EXPORT (your AS only, no further propagation)
```

Why this naming pattern (`asn:0:peer`, `asn:1:peer`, etc.):

* `X:0:Y` — "Don't go to Y." The `0` reads as "block."
* `X:1:Y` — "Only to Y." The `1` reads as "exclusively."
* `X:10N:Y` — "Prepend N times to Y." Reads naturally.
* This is the Hurricane Electric / NTT-style scheme.

Large community equivalent (publish both):

```
65000:0:peer_asn   →  Don't announce
65000:1:peer_asn   →  Only announce to
65000:101:peer_asn →  Prepend 1x
65000:102:peer_asn →  Prepend 2x
65000:103:peer_asn →  Prepend 3x
```

# Part 5: RTBH and Flowspec for DDoS Mitigation

## 5.1 Remote-Triggered Blackhole (RTBH)

Concept: when under attack on prefix X, you want all your transits to drop traffic to X at *their* edge (not yours), saving your transit capacity. You signal this by announcing X with a special community + special next-hop.

### 5.1.1 Customer-Triggered RTBH

A customer wants you to blackhole their own prefix:

```
Customer announces:    198.51.100.55/32 community 65000:666
You verify:           - Prefix is within customer's authorized space
                      - Community matches your RTBH community
You re-announce:      To transits with the transit's RTBH community
                      Set next-hop to discard locally
                      Set NO_EXPORT to peers (avoid leaking)
```

### 5.1.2 Operator-Triggered RTBH

You inject a static into your network:

```
set routing-options static route 198.51.100.55/32 discard
                                            community [ 65000:9999 no-export ]
```

### 5.1.3 RTBH Safety Rules

* Only accept RTBH on /32 IPv4 or /128 IPv6.
* Verify the prefix is within the customer's authorized space (covered by their prefix-list).
* Always set NO_EXPORT so it doesn't leak.
* Forward to transits' RTBH communities only if the transit supports it.

## 5.2 BGP Flowspec (RFC 8955)

Concept: instead of nullrouting an entire prefix (which kills the victim too), Flowspec lets you signal packet filters — drop only traffic matching `(src=A, dst=B, port=C, proto=UDP, length=X)`. Routers install these as ACLs in hardware.

Use cases:

* Drop reflection-amplification attacks at edge (e.g., drop UDP src-port 11211 toward customer for memcached attack).
* Rate-limit specific traffic patterns.
* Redirect to scrubbing centers.

Junos Flowspec config:

```
protocols {
    bgp {
        group IBGP-FLOWSPEC {
            type internal;
            family inet {
                flow;
            }
            family inet6 {
                flow;
            }
            neighbor 10.0.0.10;
        }
    }
}

routing-options {
    flow {
        route DROP-MEMCACHED-REFLECTION {
            match {
                destination 198.51.100.0/24;
                protocol udp;
                source-port 11211;
            }
            then discard;
        }
        route RATE-LIMIT-NTP-AMPLIFICATION {
            match {
                destination 198.51.100.0/24;
                protocol udp;
                source-port 123;
                packet-length 468;
            }
            then {
                rate-limit 1m;
            }
        }
    }
}
```

Most large operators run a Flowspec controller (FastNetMon, ExaBGP-based custom systems, vendor solutions) that detects DDoS via NetFlow/sFlow and auto-injects Flowspec rules.

EBGP Flowspec with transits: many transits accept Flowspec from customers with strict validation. Each publishes its rules — typically: match destinations only within your assigned space, limited number of rules, rate-limits. Consult each transit's documentation.

Customer-facing DDoS communities:

```
65000:666           RTBH /32 IPv4 or /128 IPv6
65000:667           RTBH + announce to transits (if transit-RTBH supported)
65000:668           RTBH but only within our AS (no-export)
```

# Part 6: Naming Conventions

## 6.1 Policy Names

```
PL-<purpose>                    Reusable building-block policies
IMPORT-<TYPE>-<NAME>-<ASN>      Per-peer import
EXPORT-<TYPE>-<NAME>-<ASN>      Per-peer export

Examples:
PL-REJECT-MARTIANS-V4
PL-RPKI-REJECT-INVALID
PL-RPKI-TAG-STATE
PL-EXPORT-ACTION-COMMUNITIES
PL-SCRUB-INBOUND
PL-SCRUB-OUTBOUND
IMPORT-TRANSIT-NTT-2914
EXPORT-PEER-HE-6939
IMPORT-CUSTOMER-ACME-65001
```

## 6.2 Prefix-Lists, AS-Path, Communities

```
PL-MARTIANS-V4 / PL-MARTIANS-V6
PL-OWN-AGGREGATES-V4 / V6
PL-CUSTOMER-<NAME>-V4 / V6              (per LOA, manually maintained)

ASP-OWN-ORIGIN
ASP-CUSTOMER-<NAME>                     (per LOA, manually maintained)
ASP-SANITY                              (group: too-long, private, reserved)

CM-FROM-<source>                        Informational
CM-RPKI-VALID / CM-RPKI-UNKNOWN
CM-LP-<value>
CM-PREPEND-<count>X-<target>
CM-NOEXPORT-<target>
CM-CUST-NOEXP-<peer-name>               (customer-facing)
CM-CUST-PREPEND-<n>X-<peer-name>
CM-RTBH-CUSTOMER / CM-RTBH-LOCAL
```

## 6.3 Final Community Plan (your ASN = 65000)

### 6.3.1 Internal-Only (you set, you read)

```
Source / type:
  65000:1000  From transit (any)
  65000:1100  From peer (any)
  65000:1200  From customer (any)
  65000:1300  Originated by us
  65000:1101  From NTT (2914)
  65000:1102  From Telia (1299)
  65000:1103  From Cogent (174)
  65000:1201  From HE (6939)
  65000:1202  From DE-CIX route servers
  65000:1203  From Equinix-IX

Validation state:
  65000:1301  RPKI valid
  65000:1302  RPKI unknown
  /* invalid never tagged — invalid is rejected */

Geography:
  65000:2001  Ingress HKG
  65000:2002  Ingress SIN
  65000:2003  Ingress TYO
  65000:2004  Ingress LAX
  65000:2005  Ingress FRA

LocalPref scheme (set internally):
  65000:5050  Force LP 50
  65000:5080  Force LP 80
  65000:5150  Force LP 150
  65000:5250  Force LP 250
```

### 6.3.2 Customer-Facing (customers set, you honor)

```
Don't announce:
  65000:0:0       Don't announce anywhere
  65000:0:2914    Don't announce to NTT
  65000:0:1299    Don't announce to Telia
  65000:0:174     Don't announce to Cogent
  65000:0:6939    Don't announce to HE

Only announce to:
  65000:1:2914    Only announce to NTT
  65000:1:1299    Only announce to Telia

Prepend 1x:
  65000:101:0     Prepend 1x to all transits
  65000:101:2914  Prepend 1x to NTT
  65000:101:1299  Prepend 1x to Telia

Prepend 2x:
  65000:102:0     Prepend 2x to all transits
  65000:102:2914  Prepend 2x to NTT

Prepend 3x:
  65000:103:0     Prepend 3x to all transits
  65000:103:2914  Prepend 3x to NTT

DDoS / RTBH:
  65000:666       RTBH (host route only, /32 v4 or /128 v6)
  65000:667       RTBH + signal upstream transits' RTBH
  65000:668       RTBH within our AS only

Standard:
  no-export       Standard NO_EXPORT
```

### 6.3.3 Large-Community Equivalents (publish both)

Same scheme, but using large communities for 4-byte ASN cleanliness:

```
65000:0:peer_asn      Don't announce
65000:1:peer_asn      Only announce
65000:101:peer_asn    Prepend 1x
65000:102:peer_asn    Prepend 2x
65000:103:peer_asn    Prepend 3x
```

# Part 7: Final Junos Configuration

This is the consolidated, deployable configuration. Replace ASN `65000`, prefixes `203.0.113.0/24`, etc. with your actuals.

## 7.1 Foundation: Prefix-Lists & AS-Path Filters

```
policy-options {
    prefix-list PL-MARTIANS-V4 {
        0.0.0.0/8;
        10.0.0.0/8;
        100.64.0.0/10;
        127.0.0.0/8;
        169.254.0.0/16;
        172.16.0.0/12;
        192.0.0.0/24;
        192.0.2.0/24;
        192.168.0.0/16;
        198.18.0.0/15;
        198.51.100.0/24;
        203.0.113.0/24;
        224.0.0.0/4;
        240.0.0.0/4;
    }
    prefix-list PL-MARTIANS-V6 {
        ::/8;
        100::/64;
        2001:db8::/32;
        fc00::/7;
        fe80::/10;
        ff00::/8;
    }
    prefix-list PL-OWN-AGGREGATES-V4 {
        203.0.113.0/24;
    }
    prefix-list PL-OWN-AGGREGATES-V6 {
        2001:db8::/32;
    }
    prefix-list PL-RTBH-DISCARD-NH {
        192.0.2.1/32;
    }

    as-path-group ASP-SANITY {
        as-path NO-PRIVATE ".* [64512-65534] .*";
        as-path NO-RESERVED ".* 23456 .*";
        as-path TOO-LONG ".{50,}";
    }
    as-path ASP-OWN-ORIGIN "^65000$";
    as-path ASP-CUSTOMER-ACME "^65001(_65001)*$";
}
```

## 7.2 Communities — Complete

```
policy-options {
    /* === SOURCE / TYPE === */
    community CM-FROM-TRANSIT      members 65000:1000;
    community CM-FROM-PEER         members 65000:1100;
    community CM-FROM-CUSTOMER     members 65000:1200;
    community CM-FROM-OWN          members 65000:1300;
    community CM-FROM-NTT          members 65000:1101;
    community CM-FROM-TELIA        members 65000:1102;
    community CM-FROM-COGENT       members 65000:1103;
    community CM-FROM-HE           members 65000:1201;

    /* === VALIDATION === */
    community CM-RPKI-VALID    members 65000:1301;
    community CM-RPKI-UNKNOWN  members 65000:1302;

    /* === GEOGRAPHY === */
    community CM-INGRESS-HKG   members 65000:2001;
    community CM-INGRESS-SIN   members 65000:2002;
    community CM-INGRESS-TYO   members 65000:2003;

    /* === INTERNAL LP === */
    community CM-LP-50    members 65000:5050;
    community CM-LP-80    members 65000:5080;
    community CM-LP-150   members 65000:5150;
    community CM-LP-250   members 65000:5250;

    /* === CUSTOMER-FACING: NO-EXPORT TO PEER === */
    community CM-CUST-NOEXP-ALL members [
        65000:0:0
        large:65000:0:0
    ];
    community CM-CUST-NOEXP-NTT members [
        65000:0:2914
        large:65000:0:2914
    ];
    community CM-CUST-NOEXP-TELIA members [
        65000:0:1299
        large:65000:0:1299
    ];
    community CM-CUST-NOEXP-COGENT members [
        65000:0:174
        large:65000:0:174
    ];
    community CM-CUST-NOEXP-HE members [
        65000:0:6939
        large:65000:0:6939
    ];

    /* === CUSTOMER-FACING: ONLY-EXPORT-TO === */
    community CM-CUST-ONLY-NTT members [
        65000:1:2914
        large:65000:1:2914
    ];
    community CM-CUST-ONLY-TELIA members [
        65000:1:1299
        large:65000:1:1299
    ];
    community CM-CUST-ONLY-COGENT members [
        65000:1:174
        large:65000:1:174
    ];
    community CM-CUST-ONLY-HE members [
        65000:1:6939
        large:65000:1:6939
    ];

    /* === CUSTOMER-FACING: PREPEND === */
    community CM-CUST-PREPEND-1X-ALL-TRANSIT members [
        65000:101:0
        large:65000:101:0
    ];
    community CM-CUST-PREPEND-2X-ALL-TRANSIT members [
        65000:102:0
        large:65000:102:0
    ];
    community CM-CUST-PREPEND-3X-ALL-TRANSIT members [
        65000:103:0
        large:65000:103:0
    ];
    community CM-CUST-PREPEND-1X-NTT members [
        65000:101:2914
        large:65000:101:2914
    ];
    community CM-CUST-PREPEND-2X-NTT members [
        65000:102:2914
        large:65000:102:2914
    ];
    community CM-CUST-PREPEND-3X-NTT members [
        65000:103:2914
        large:65000:103:2914
    ];
    community CM-CUST-PREPEND-1X-TELIA members [
        65000:101:1299
        large:65000:101:1299
    ];
    community CM-CUST-PREPEND-2X-TELIA members [
        65000:102:1299
        large:65000:102:1299
    ];
    community CM-CUST-PREPEND-3X-TELIA members [
        65000:103:1299
        large:65000:103:1299
    ];

    /* === RTBH === */
    community CM-RTBH-CUSTOMER          members 65000:666;
    community CM-RTBH-CUSTOMER-UPSTREAM members 65000:667;
    community CM-RTBH-CUSTOMER-LOCAL    members 65000:668;
    community CM-RTBH-LOCAL             members 65000:9999;

    /* === STANDARD === */
    community CM-NO-EXPORT     members no-export;
    community CM-NO-ADVERTISE  members no-advertise;

    /* === SCRUBBING === */
    community CM-ALL-OURS members "^65000:.*$";
    community CM-ALL-OURS-LC members "^large:65000:.*:.*$";
}
```

## 7.3 Reusable Building-Block Policies

```
policy-options {

    /* ─── BLOCK 1: REJECT MARTIANS ─── */
    policy-statement PL-REJECT-MARTIANS-V4 {
        term martians {
            from {
                family inet;
                prefix-list-filter PL-MARTIANS-V4 orlonger;
            }
            then reject;
        }
        term too-specific {
            from {
                family inet;
                route-filter 0.0.0.0/0 prefix-length-range /25-/32;
            }
            then reject;
        }
        term too-broad {
            from {
                family inet;
                route-filter 0.0.0.0/0 upto /7;
            }
            then reject;
        }
    }

    policy-statement PL-REJECT-MARTIANS-V6 {
        term martians {
            from {
                family inet6;
                prefix-list-filter PL-MARTIANS-V6 orlonger;
            }
            then reject;
        }
        term too-specific {
            from {
                family inet6;
                route-filter ::/0 prefix-length-range /49-/128;
            }
            then reject;
        }
        term too-broad {
            from {
                family inet6;
                route-filter ::/0 upto /15;
            }
            then reject;
        }
    }

    /* ─── BLOCK 2: REJECT BAD AS-PATH ─── */
    policy-statement PL-REJECT-BAD-ASPATH {
        term bad {
            from as-path-group ASP-SANITY;
            then reject;
        }
    }

    /* ─── BLOCK 3: RPKI ─── */
    policy-statement PL-RPKI-REJECT-INVALID {
        term reject-invalid {
            from validation-database invalid;
            then {
                validation-state invalid;
                reject;
            }
        }
    }
    policy-statement PL-RPKI-TAG-STATE {
        term tag-valid {
            from validation-database valid;
            then {
                validation-state valid;
                community add CM-RPKI-VALID;
                next term;
            }
        }
        term tag-unknown {
            from validation-database unknown;
            then {
                validation-state unknown;
                community add CM-RPKI-UNKNOWN;
                next term;
            }
        }
    }
    policy-statement PL-RPKI-LP-BONUS {
        term valid-bonus {
            from community CM-RPKI-VALID;
            then {
                local-preference add 5;
                next term;
            }
        }
    }

    /* ─── BLOCK 4: SCRUBBING ─── */
    policy-statement PL-SCRUB-INBOUND {
        term strip-our-communities {
            then {
                community delete CM-ALL-OURS;
                community delete CM-ALL-OURS-LC;
            }
        }
    }

    /* ─── BLOCK 5: REJECT OWN PREFIXES BACK ─── */
    policy-statement PL-REJECT-OWN-PREFIXES {
        term v4 {
            from {
                family inet;
                prefix-list-filter PL-OWN-AGGREGATES-V4 orlonger;
            }
            then reject;
        }
        term v6 {
            from {
                family inet6;
                prefix-list-filter PL-OWN-AGGREGATES-V6 orlonger;
            }
            then reject;
        }
    }

    /* ─── BLOCK 6: RTBH FROM CUSTOMER ─── */
    policy-statement PL-RTBH-FROM-CUSTOMER {
        term rtbh-host-only-v4 {
            from {
                family inet;
                community CM-RTBH-CUSTOMER;
                route-filter 0.0.0.0/0 prefix-length-range /32-/32;
            }
            then {
                local-preference 250;
                next-hop 192.0.2.1;
                community add CM-NO-EXPORT;
                accept;
            }
        }
        term rtbh-host-only-v6 {
            from {
                family inet6;
                community CM-RTBH-CUSTOMER;
                route-filter ::/0 prefix-length-range /128-/128;
            }
            then {
                local-preference 250;
                next-hop 192.0.2.1;
                community add CM-NO-EXPORT;
                accept;
            }
        }
        term reject-bad-rtbh {
            from community CM-RTBH-CUSTOMER;
            then reject;
        }
    }
}
```

## 7.4 Per-Peer Templates: Honor Customer Actions

For each transit/peer, define a policy that honors customer-set communities. Below is the template for the NTT export — replicate per peer.

```
policy-options {
    policy-statement PL-EXPORT-ACTIONS-NTT {
        /* === CUSTOMER ASKED NO-ANNOUNCE === */
        term cust-noexp-all {
            from community CM-CUST-NOEXP-ALL;
            then reject;
        }
        term cust-noexp-ntt {
            from community CM-CUST-NOEXP-NTT;
            then reject;
        }

        /* === CUSTOMER ASKED ONLY-TO-OTHER === */
        term cust-only-telia-not-us {
            from community CM-CUST-ONLY-TELIA;
            then reject;
        }
        term cust-only-cogent-not-us {
            from community CM-CUST-ONLY-COGENT;
            then reject;
        }
        term cust-only-he-not-us {
            from community CM-CUST-ONLY-HE;
            then reject;
        }

        /* === PREPEND === */
        term prepend-3x {
            from community [
                CM-CUST-PREPEND-3X-NTT
                CM-CUST-PREPEND-3X-ALL-TRANSIT
            ];
            then {
                as-path-prepend "65000 65000 65000";
            }
        }
        term prepend-2x {
            from community [
                CM-CUST-PREPEND-2X-NTT
                CM-CUST-PREPEND-2X-ALL-TRANSIT
            ];
            then {
                as-path-prepend "65000 65000";
            }
        }
        term prepend-1x {
            from community [
                CM-CUST-PREPEND-1X-NTT
                CM-CUST-PREPEND-1X-ALL-TRANSIT
            ];
            then {
                as-path-prepend "65000";
            }
        }
    }
}
```

Mirror this for each transit/peer with names like `PL-EXPORT-ACTIONS-TELIA`, `PL-EXPORT-ACTIONS-COGENT`, `PL-EXPORT-ACTIONS-HE`.

## 7.5 Outbound Scrub

```
policy-options {
    policy-statement PL-SCRUB-OUTBOUND {
        term strip-action-communities {
            then {
                community delete CM-CUST-NOEXP-ALL;
                community delete CM-CUST-NOEXP-NTT;
                community delete CM-CUST-NOEXP-TELIA;
                community delete CM-CUST-NOEXP-COGENT;
                community delete CM-CUST-NOEXP-HE;
                community delete CM-CUST-ONLY-NTT;
                community delete CM-CUST-ONLY-TELIA;
                community delete CM-CUST-ONLY-COGENT;
                community delete CM-CUST-ONLY-HE;
                community delete CM-CUST-PREPEND-1X-NTT;
                community delete CM-CUST-PREPEND-2X-NTT;
                community delete CM-CUST-PREPEND-3X-NTT;
                community delete CM-CUST-PREPEND-1X-TELIA;
                community delete CM-CUST-PREPEND-2X-TELIA;
                community delete CM-CUST-PREPEND-3X-TELIA;
                community delete CM-CUST-PREPEND-1X-ALL-TRANSIT;
                community delete CM-CUST-PREPEND-2X-ALL-TRANSIT;
                community delete CM-CUST-PREPEND-3X-ALL-TRANSIT;
                community delete CM-RTBH-CUSTOMER;
                community delete CM-RTBH-CUSTOMER-LOCAL;
                community delete CM-RTBH-LOCAL;
            }
        }
    }
}
```

## 7.6 Per-Peer Import: Transit (NTT)

```
policy-options {
    policy-statement IMPORT-TRANSIT-NTT-2914 {
        term reject-martians {
            from policy PL-REJECT-MARTIANS-V4;
        }
        term reject-bad-aspath {
            from policy PL-REJECT-BAD-ASPATH;
        }
        term reject-rpki-invalid {
            from policy PL-RPKI-REJECT-INVALID;
        }
        term reject-own-prefixes {
            from policy PL-REJECT-OWN-PREFIXES;
        }
        term scrub-communities {
            from policy PL-SCRUB-INBOUND;
        }
        term tag-rpki {
            from policy PL-RPKI-TAG-STATE;
        }
        term tag-source {
            then {
                community add CM-FROM-TRANSIT;
                community add CM-FROM-NTT;
                community add CM-INGRESS-HKG;
                local-preference 80;
            }
        }
        term lp-bonus {
            from policy PL-RPKI-LP-BONUS;
        }
        term accept {
            then accept;
        }
    }
}
```

## 7.7 Per-Peer Export: Transit (NTT)

```
policy-options {
    policy-statement EXPORT-TRANSIT-NTT-2914 {
        /* === Honor explicit no-export attributes === */
        term respect-no-export {
            from community CM-NO-EXPORT;
            then reject;
        }
        term respect-no-advertise {
            from community CM-NO-ADVERTISE;
            then reject;
        }

        /* === Honor customer/operator action communities === */
        term action-block {
            from policy PL-EXPORT-ACTIONS-NTT;
        }

        /* === Scrub before announcing === */
        term scrub {
            from policy PL-SCRUB-OUTBOUND;
        }

        /* === Allow our own aggregates === */
        term advertise-own {
            from {
                protocol [ aggregate static ];
                prefix-list PL-OWN-AGGREGATES-V4;
            }
            then {
                community add CM-FROM-OWN;
                accept;
            }
        }
        term advertise-own-v6 {
            from {
                protocol [ aggregate static ];
                prefix-list PL-OWN-AGGREGATES-V6;
            }
            then {
                community add CM-FROM-OWN;
                accept;
            }
        }

        /* === Allow customer routes === */
        term advertise-customers {
            from community CM-FROM-CUSTOMER;
            then accept;
        }

        /* === Default reject (Gao-Rexford) === */
        term default-reject {
            then reject;
        }
    }
}
```

## 7.8 Per-Peer Import: Customer (ACME)

```
policy-options {
    policy-statement IMPORT-CUSTOMER-ACME-65001 {
        term reject-martians {
            from policy PL-REJECT-MARTIANS-V4;
        }
        term reject-bad-aspath {
            from policy PL-REJECT-BAD-ASPATH;
        }
        term reject-rpki-invalid {
            from policy PL-RPKI-REJECT-INVALID;
        }
        term reject-own-prefixes {
            from policy PL-REJECT-OWN-PREFIXES;
        }

        /* === RTBH special handling — must come before scrubbing! === */
        term rtbh-handling {
            from policy PL-RTBH-FROM-CUSTOMER;
        }

        /* === Verify origin AS === */
        term enforce-aspath {
            from as-path ASP-CUSTOMER-ACME;
        }
        term reject-bad-origin {
            then reject;
        }

        /* === Verify prefix is in authorized list (per customer LOA) === */
        term enforce-prefixlist {
            from {
                prefix-list-filter PL-CUSTOMER-ACME-V4 orlonger;
            }
        }
        term reject-not-authorized {
            then reject;
        }

        /* === Scrub, tag, accept === */
        term scrub {
            from policy PL-SCRUB-INBOUND;
        }
        term tag-rpki {
            from policy PL-RPKI-TAG-STATE;
        }
        term tag-source {
            then {
                community add CM-FROM-CUSTOMER;
                community add CM-INGRESS-HKG;
                local-preference 200;
            }
        }
        term lp-bonus {
            from policy PL-RPKI-LP-BONUS;
        }
        term accept {
            then accept;
        }
    }
}
```

## 7.9 Per-Peer Export: Customer (ACME)

```
policy-options {
    policy-statement EXPORT-CUSTOMER-ACME-65001 {
        term respect-no-export {
            from community CM-NO-EXPORT;
            then reject;
        }
        term scrub {
            from policy PL-SCRUB-OUTBOUND;
        }
        /* Customers get the full table */
        term advertise-own {
            from {
                protocol [ aggregate static ];
                prefix-list PL-OWN-AGGREGATES-V4;
            }
            then accept;
        }
        term advertise-customers {
            from community CM-FROM-CUSTOMER;
            then accept;
        }
        term advertise-peers {
            from community CM-FROM-PEER;
            then accept;
        }
        term advertise-transits {
            from community CM-FROM-TRANSIT;
            then accept;
        }
        term default-reject {
            then reject;
        }
    }
}
```

## 7.10 RPKI Validator Configuration

```
routing-options {
    validation {
        group RPKI-VALIDATORS {
            session 192.0.2.10 {
                refresh-time 120;
                hold-time 180;
                port 3323;
                local-address 192.0.2.254;
                preference 100;
            }
            session 192.0.2.11 {
                refresh-time 120;
                hold-time 180;
                port 3323;
                local-address 192.0.2.254;
                preference 200;
            }
        }
    }
    static {
        route 192.0.2.1/32 discard;   /* RTBH discard next-hop */
    }
}
```

## 7.11 BGP Group / Neighbor Application

```
groups {
    EBGP-COMMON-V4 {
        protocols {
            bgp {
                group <*> {
                    neighbor <*> {
                        family inet {
                            unicast {
                                prefix-limit {
                                    maximum 1000000;
                                    teardown 90 idle-timeout 30;
                                }
                            }
                        }
                        bfd-liveness-detection {
                            minimum-interval 300;
                            multiplier 3;
                        }
                    }
                }
            }
        }
    }
}

protocols {
    bgp {
        /* === IBGP === */
        group IBGP {
            type internal;
            local-address 10.0.0.1;
            family inet {
                unicast;
            }
            family inet6 {
                unicast;
            }
            family route-validation;     /* carry RPKI state across IBGP */
            family inet {
                flow;                    /* Flowspec */
            }
            neighbor 10.0.0.2;
            neighbor 10.0.0.3;
        }

        /* === TRANSIT NTT === */
        group EBGP-TRANSIT-NTT {
            apply-groups EBGP-COMMON-V4;
            type external;
            peer-as 2914;
            import IMPORT-TRANSIT-NTT-2914;
            export EXPORT-TRANSIT-NTT-2914;
            neighbor 192.0.2.1;
        }

        /* === TRANSIT TELIA === */
        group EBGP-TRANSIT-TELIA {
            apply-groups EBGP-COMMON-V4;
            type external;
            peer-as 1299;
            import IMPORT-TRANSIT-TELIA-1299;
            export EXPORT-TRANSIT-TELIA-1299;
            neighbor 192.0.2.5;
        }

        /* === PEER HE === */
        group EBGP-PEER-HE {
            apply-groups EBGP-COMMON-V4;
            type external;
            peer-as 6939;
            import IMPORT-PEER-HE-6939;
            export EXPORT-PEER-HE-6939;
            neighbor 192.0.2.9;
        }

        /* === CUSTOMER ACME === */
        group EBGP-CUSTOMER-ACME {
            apply-groups EBGP-COMMON-V4;
            type external;
            peer-as 65001;
            import IMPORT-CUSTOMER-ACME-65001;
            export EXPORT-CUSTOMER-ACME-65001;
            neighbor 192.0.2.13;
        }
    }
}
```

# Part 8: Operations Reference

## 8.1 Common Use Cases — Traffic Engineering by Community

Once the framework is in place, NOC tasks become trivial. Each is a single static-route or aggregate community tag — no policy edit:

| Task | Action |
|------|--------|
| Move outbound traffic for `1.2.3.0/24` away from NTT | Tag inbound NTT route with `CM-LP-50` or block at ingress |
| Stop announcing `5.6.7.0/24` to Cogent only | Aggregate, add `65000:0:174` |
| Make inbound traffic from APAC arrive via Telia, not NTT | Prepend 2x to NTT for that prefix: `65000:102:2914` |
| Withdraw a prefix from the Internet entirely (RTBH) | Tag with `65000:9999`; RTBH policy nullroutes it and applies NO_EXPORT |
| Announce only to peers, not transit (regional traffic) | Tag with peer-only community |
| Customer requests "don't send my routes to ASN X" | Customer sets `65000:0:X` themselves; you honor it |

## 8.2 Key Show Commands

```
# RPKI
show validation session
show validation database
show validation database prefix 8.8.8.0/24
show validation statistics
show route validation-state invalid
show route validation-state valid

# BGP general
show bgp summary
show bgp neighbor 192.0.2.1 detail
show route receive-protocol bgp 192.0.2.1
show route advertising-protocol bgp 192.0.2.1
show route community 65000:1101
show route community-name CM-FROM-NTT

# Verify policy logic
show route protocol bgp 1.1.1.0/24 detail
test policy IMPORT-TRANSIT-NTT-2914 1.1.1.0/24
```

## 8.3 Verifying Customer Self-Service Communities

After a customer sets `65000:0:2914` on a route:

```
show route receive-protocol bgp <customer> | match community
show route advertising-protocol bgp <NTT-neighbor> 1.1.1.0/24
   → should be empty (suppressed)
show route advertising-protocol bgp <Telia-neighbor> 1.1.1.0/24
   → should still be present
```

## 8.4 Phased Rollout Schedule

| Week | Action |
|------|--------|
| 1    | Deploy validators (Routinator + rpki-client). Verify VRP counts. |
| 2    | Configure RTR sessions on routers. Verify `show validation session`. |
| 3    | Add `PL-RPKI-TAG-STATE` to imports. Tag only, no rejection. Observe. |
| 4    | Audit your own ROAs. Fix any maxLength issues. Publish missing ROAs. |
| 5    | Add `PL-RPKI-REJECT-INVALID` to one transit. Monitor. |
| 6    | Roll RPKI rejection to all transits. |
| 7    | Roll RPKI rejection to peers and IXPs. |
| 8    | Build per-customer prefix-lists from LOAs. Apply to customer imports. |
| 9    | Migrate customers to new IMPORT/EXPORT framework one at a time. |
| 10   | Publish customer community documentation. Notify customers. |
| 11   | Deploy Flowspec controller. Test with a single attack scenario. |

## 8.5 Maintenance Routines

Daily (automated):

* RPKI validator health check.
* VRP count diff alert.
* BGP session state monitoring.

Weekly:

* Review RPKI invalid rejections per peer (large spike = investigate).
* Audit your own prefixes for ROA correctness via external validator ([rpki.cloudflare.com](http://rpki.cloudflare.com), bgp.tools).

Monthly:

* Audit customer communities — are customers actually using them? What changes have been made?
* Review prefix-limit thresholds.
* Update peer/transit list — any new ASNs to add to community plan?

Quarterly:

* Re-verify each customer's prefix-list still matches their LOA.
* Disaster recovery test: shut down primary validator, verify failover.
* Review of MANRS compliance.
* Communities documentation review.

## 8.6 Public Documentation Page

Maintain a public page (e.g., `https://as65000.net/communities`) documenting your full community scheme. Customers and peers will reference it. Register it in PeeringDB. Examples to model after:

* AS2914 (NTT): <https://www.us.ntt.net/support/policy/routing.cfm>
* AS6939 (HE): <http://routerguide.he.net/>
* AS3257 (GTT), AS1299 (Telia/Arelion), AS174 (Cogent) all publish similar docs.

# Part 9: Standards Reference

| RFC / Standard | Topic |
|----------------|-------|
| RFC 7454 / BCP 194 | BGP Operations and Security |
| RFC 6480, 6482, 6811 | RPKI architecture, ROAs, ROV |
| RFC 6810, 8210 | RPKI-to-Router (RTR) protocol |
| RFC 8092, 8195 | Large BGP Communities + operational use |
| RFC 8097       | RPKI validation state extended community |
| RFC 8955, 8956 | BGP Flowspec v4 / v6 |
| RFC 9234       | BGP Role / Only-to-Customer attribute |
| MANRS          | Mutually Agreed Norms for Routing Security |
| RIPE-705       | BGP filtering recommendations |

# Part 10: Summary

This framework provides:


1. **Architecture** — multi-validator RPKI ROV + per-customer prefix-list filtering + Flowspec controller, all feeding edge routers running a deterministic policy chain.
2. **Conventions** — structured community plan that's both internal-control and customer-facing, with regular and large communities, fully documented for public consumption.
3. **Detailed policies** — modular reusable building blocks, per-peer import/export, RTBH, action-honoring blocks, scrubbing, validation tagging.
4. **Configuration** — production-ready Junos config skeleton for transits, peers, and customers, drop-in ready (replace ASN/IPs/aggregates).
5. **Operations** — monitoring, phased rollout, maintenance routines.

This framework matches what large carriers run today, scales to thousands of EBGP sessions, and turns traffic engineering into a community-tagging exercise rather than policy editing.


---

## title: "Modern BGP Policy Framework for Multi-Transit ISP" subtitle: "Juniper-Focused Design with RPKI ROV, RTBH and Flowspec" author: "Network Engineering"

# Executive Summary

This document presents a complete, production-ready BGP policy framework for a multi-transit Tier-3 ISP. It is designed for Juniper Networks platforms (Junos OS) and follows the conventions used by major Tier-1/Tier-2 carriers and large content networks.

The framework is built around three core principles:


1. **BGP Communities as the Control Plane.** Once the framework is built, traffic engineering becomes "set a community" rather than "edit a policy." This is how Hurricane Electric (AS6939), NTT (AS2914), Cogent (AS174), Telia/Arelion (AS1299) and most CDNs operate.
2. **Default-Deny with Structured Policy Chains.** Every EBGP session has a deterministic ingress and egress chain. Nothing leaks unless it explicitly matches an accept term. The Gao-Rexford valley-free routing model is enforced at all times.
3. **Validation at Every Edge.** RPKI Route Origin Validation rejects invalids on ingress. Customer prefix-lists enforce per-customer authorization. Both work together; neither replaces the other.

Note on scope: ASPA (Autonomous System Provider Authorization) is intentionally excluded from this design. ASPA is not yet broadly supported across Junos releases or the global validator/publisher ecosystem. This framework can be extended to include ASPA when the dataset and platform support mature, without requiring restructuring.

# Part 1: Architecture

## 1.1 Architectural Concepts

### 1.1.1 The "BGP Communities as Control Plane" Philosophy

The single most important modern principle: never manipulate traffic by editing prefix-lists or per-peer policies directly. Instead:

* Tag every route at ingress with informational communities (where it came from, what type, what region).
* Tag every route at ingress or via internal tools with action communities (what to do with it).
* Write generic, peer-agnostic export/import policies that read communities and act accordingly.

This means once your framework is built, 99% of traffic engineering becomes "set a community" — done by NOC engineers, automation, or even peering tools — without touching policy code.

### 1.1.2 Policy Chain Architecture

Every EBGP session has a structured chain rather than one monolithic policy:

```
IMPORT chain (from peer → into RIB):
  [martians-reject] → [bogon-asn-reject] → [RPKI-reject-invalid]
  → [reject-own-prefixes-back] → [peer-specific-filter]
  → [scrub-inbound-communities] → [tag-RPKI-state]
  → [tag-source/region] → [set-base-localpref]
  → [RPKI-localpref-bonus] → [accept]

EXPORT chain (from RIB → to peer):
  [reject-NO_EXPORT] → [honor-action-communities]
  → [scrub-action-communities]
  → [advertise-own] → [advertise-customers]
  → [advertise-peers/transits-conditional] → [default-reject]
```

The key principle: default deny on both directions. Nothing leaks unless it matches an explicit accept term.

### 1.1.3 Route Classification (Four Buckets)

Every route in your RIB belongs to exactly one class, identified by community:

| Class | Meaning | Default LP | To Transit | To Peer | To Customer |
|-------|---------|------------|------------|---------|-------------|
| Customer | Paying you | 200        | Yes        | Yes     | Yes         |
| Peer  | Settlement-free | 100        | No         | No      | Yes         |
| Transit | You pay them | 80         | No         | No      | Yes         |
| Internal/Own | Your aggregates | 250        | Yes        | Yes     | Yes         |

This is the Gao-Rexford valley-free routing model. Violating it (e.g., re-advertising transit routes to other transit) is what causes major BGP leak incidents.

## 1.2 System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CONTROL PLANE                                │
│                                                                       │
│  ┌──────────────┐   ┌──────────────┐                                │
│  │  Routinator  │   │ rpki-client  │                                │
│  │  Site A      │   │  Site B      │                                │
│  │  (RPKI ROV)  │   │  (RPKI ROV)  │                                │
│  └──────┬───────┘   └──────┬───────┘                                │
│         │ RTR              │ RTR                                     │
│         └──────────┬───────┘                                         │
│                    │                                                 │
│  ┌─────────────────▼─────────────────────────────────────┐          │
│  │           Edge Routers (Junos)                         │          │
│  │  - validation-database (RPKI ROV)                      │          │
│  │  - per-customer prefix-lists (manually maintained)     │          │
│  │  - Flowspec rules from controller                      │          │
│  └─────┬──────────┬──────────┬──────────┬─────────────────┘          │
└────────┼──────────┼──────────┼──────────┼─────────────────────────────┘
         │ EBGP     │ EBGP     │ EBGP     │ EBGP
    ┌────▼────┐ ┌──▼────┐ ┌──▼─────┐ ┌──▼────────┐
    │ Transit │ │ Peer  │ │ IXP    │ │ Customer  │
    │ NTT     │ │ HE    │ │ DE-CIX │ │ ACME      │
    └─────────┘ └───────┘ └────────┘ └───────────┘
```

# Part 2: RPKI Route Origin Validation

## 2.1 Concept

RPKI ROV answers one question for every received route: "Is this AS authorized to originate this prefix?"

The router compares the route's (prefix, prefix-length, origin-AS) against ROAs (Route Origin Authorizations) cryptographically signed by IP resource holders. The result is one of three states:

| State | Meaning | Action |
|-------|---------|--------|
| valid | Matches a ROA — origin AS is authorized | Accept, prefer |
| unknown | No ROA exists for this prefix | Accept |
| invalid | A ROA exists, but origin AS or prefix-length differs | **Reject** |

Rejecting invalids is the entire point. This stops route hijacks like AS7007, the YouTube/Pakistan Telecom hijack, and the dozens that happen monthly today.

## 2.2 RPKI Architecture — Separation of Concerns

The router does NOT validate RSA signatures itself. The architecture has three components:

```
┌────────────────────┐     ┌──────────────────┐     ┌───────────────┐
│  RIRs / TAs        │     │  RPKI Validator  │     │  Junos Router │
│  (ARIN/RIPE/APNIC/ │ →   │  (Routinator /   │ →   │  (RTR client) │
│   LACNIC/AFRINIC)  │     │   rpki-client /  │     │               │
│  Publish ROAs      │     │   FORT / OctoRPKI│     │  validation-  │
│  via rsync/RRDP    │     │  Builds VRP set  │     │  database     │
└────────────────────┘     └──────────────────┘     └───────────────┘
       Signed ROAs            Validated Cache         RTR Protocol
                                                      (RFC 6810/8210)
```

* RIRs/TAs publish signed ROAs.
* RPKI Validator (Routinator, rpki-client, FORT, OctoRPKI — pick at least two different implementations for diversity) periodically pulls and validates them, producing a flat list called VRPs (Validated ROA Payloads).
* Routers speak RTR (RPKI-to-Router) protocol to the validator and import VRPs into their `validation-database`.
* The router only does fast lookups: prefix + origin → state.

## 2.3 Design Principles for ROV


1. Run at least two validators in different locations.
2. Validate at every EBGP ingress point — transits, peers, IXPs, customers.
3. Reject invalid only on EBGP import. Never apply ROV on IBGP or customer-facing exports.
4. Tag valid/unknown with communities so you preserve state across IBGP and can audit/troubleshoot.
5. Use LocalPref tiebreak (small additive bonus) so two routes identical except validation state — valid wins over unknown — without breaking Gao-Rexford ordering.
6. Fail-safe behavior: if all validators are down, Junos treats everything as unknown (not invalid), so traffic continues to flow. Don't change this default.
7. Customers get extra scrutiny. Reject invalid AND require the prefix to be in their per-customer authorized prefix-list.
8. Publish your own ROAs for every prefix you originate, with `maxLength` set tightly. Over-permissive `maxLength` is the most common ROA misconfiguration that allows attackers to hijack more-specifics and still appear valid.

## 2.4 Validator Deployment

Architecture: two implementations, two locations.

```
                      ┌──────────────┐
                      │  RIR Repos   │
                      │ (rsync/RRDP) │
                      └──────┬───────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
     ┌────────▼────────┐         ┌──────────▼────────┐
     │  Site A         │         │   Site B          │
     │  Routinator     │         │   rpki-client +   │
     │  (Rust, NLnet)  │         │   StayRTR         │
     └────────┬────────┘         └──────────┬────────┘
              │                             │
              │  RTR (TCP 3323)             │
              │                             │
     ┌────────▼─────────────────────────────▼────────┐
     │              Edge Routers (Junos)              │
     └────────────────────────────────────────────────┘
```

Design principles:


1. Two implementations, two locations. Routinator (Rust) at Site A; rpki-client + StayRTR at Site B. If a bug lands in one, the other catches it.
2. Validators on dedicated VMs/containers, not on routers.
3. Outbound Internet access (HTTPS/443 for RRDP, rsync/873 fallback). Don't block this.
4. RTR sessions inbound from routers only. Firewall TCP/3323 to known router IPs.
5. Monitor: VRP count, last-update timestamp, RTR session state, repository fetch failures.

Routinator setup (Debian/Ubuntu):

```bash
# Install
curl -O https://packages.nlnetlabs.nl/linux/debian/dists/bookworm/main/binary-amd64/routinator_*_amd64.deb
sudo apt install ./routinator_*_amd64.deb

# Initialize trust anchors (accept ARIN TAL terms)
sudo routinator-init --accept-arin-rpa

# Configure /etc/routinator/routinator.conf
[server]
rtr-listen = ["0.0.0.0:3323"]
http-listen = ["0.0.0.0:8323"]

[rrdp]
fallback = "rsync"

[validation]
strict = false
stale = "reject"

# Start
sudo systemctl enable --now routinator

# Verify
routinator vrps -f csv | wc -l
curl http://localhost:8323/metrics
```

rpki-client + StayRTR setup:

```bash
sudo apt install rpki-client stayrtr

# Cron rpki-client to refresh every 20 min
echo '*/20 * * * * rpki-client -j /var/lib/rpki-client/' | sudo crontab -

# StayRTR reads rpki-client output and serves RTR
stayrtr -bind :3323 -cache /var/lib/rpki-client/json -refresh 600
```

Monitoring (Prometheus key metrics on Routinator):

* `routinator_rrdp_status` — should be 200 for all repos.
* `routinator_vrps_final` — total VRPs (alert if drops >20%).
* `routinator_rtr_current_connections` — number of routers connected.
* `routinator_last_update_done_ago` — alert if >1 hour.

High availability: validators are stateless. Losing one is fine; Junos `preference` on RTR sessions handles primary/backup. If both fail, Junos treats all routes as unknown — fail-safe.

## 2.5 Originating Your Own ROAs

For every prefix you announce, create a ROA via your RIR portal:

* ARIN: [account.arin.net](http://account.arin.net)
* RIPE: [my.ripe.net](http://my.ripe.net)
* APNIC: [myapnic.net](http://myapnic.net)
* LACNIC: [mi.lacnic.net](http://mi.lacnic.net)
* AFRINIC: [my.afrinic.net](http://my.afrinic.net)

Set `maxLength` to match what you actually announce. If you announce only `203.0.113.0/24`, set `maxLength = 24`. Do NOT set it to 32 "just in case." Validate publicly via:

* <https://rpki-validator.ripe.net/ui/>
* <https://bgp.tools/>
* <https://rpki.cloudflare.com/>

# Part 3: Customer Prefix-List Management

## 3.1 Why Per-Customer Prefix-Lists Are Required

RPKI ROV validates origin AS. It does not tell you which prefixes a customer is allowed to announce to your network. A customer could have valid ROAs for 1000 prefixes, but you only have a contract for 10. You still need explicit per-customer prefix filters as part of your service agreement.

For each customer:

* Obtain a Letter of Authorization (LOA) listing every prefix they are authorized to announce.
* Translate that list into a Junos `prefix-list` named `PL-CUSTOMER-<NAME>-V4` and `PL-CUSTOMER-<NAME>-V6`.
* Translate their authorized origin AS into an `as-path` named `ASP-CUSTOMER-<NAME>`.
* Reference both in the customer-import policy (Part 7.8).

Example:

```
policy-options {
    prefix-list PL-CUSTOMER-ACME-V4 {
        198.51.100.0/24;
        198.51.101.0/24;
    }
    prefix-list PL-CUSTOMER-ACME-V6 {
        2001:db8:acme::/48;
    }
    as-path ASP-CUSTOMER-ACME "^65001(_65001)*$";
}
```

## 3.2 Change Control

When a customer needs to add or remove a prefix:


1. Customer submits change request with updated LOA.
2. NOC verifies the customer is authorized for the prefix (RIR WHOIS or registrar confirmation).
3. NOC updates the relevant `prefix-list` via the standard config change process.
4. Validate with `commit confirmed` and verify the route is being received and accepted.

## 3.3 Best Practices

* Always include both IPv4 and IPv6 prefix-lists, even if the customer only currently announces one family.
* Maintain a master spreadsheet or database of customer → authorized prefixes → LOA reference → date approved.
* Periodically (quarterly) re-verify that each customer's prefix-list still matches their LOA.
* Cross-check against RPKI: if a customer announces a prefix that is RPKI-invalid for their AS, alert and require them to either fix their ROA or update their announcement.

# Part 4: Customer Self-Service Traffic Engineering

## 4.1 Concept

Document a set of communities customers can set on routes they announce to you. Your export policy honors them automatically. Customers self-serve traffic engineering 24/7 without opening tickets.

This is what NTT, Hurricane Electric, Cogent, and most major carriers do. It's the gold standard.

## 4.2 Customer-Facing Community Schema (your ASN = 65000)

Action communities (CUSTOMER sets these on routes they send YOU):

```
Block selective announcement:
  65000:0:peer_asn  → Don't announce to peer_asn
  65000:0:0         → Don't announce to anyone (suppress globally)

  Examples (customer-set):
    65000:0:2914   Don't announce to NTT
    65000:0:1299   Don't announce to Telia
    65000:0:174    Don't announce to Cogent
    65000:0:6939   Don't announce to HE

Selective announcement (whitelist):
  65000:1:peer_asn  → ONLY announce to peer_asn

Prepending:
  65000:101:peer_asn  → Prepend 1x when announcing to peer_asn
  65000:102:peer_asn  → Prepend 2x to peer_asn
  65000:103:peer_asn  → Prepend 3x to peer_asn

  Wildcards:
    65000:101:0    Prepend 1x to all transits
    65000:102:0    Prepend 2x to all transits
    65000:103:0    Prepend 3x to all transits

Special:
  65000:666     RTBH (blackhole this prefix)
  65000:999     Set NO_EXPORT (your AS only, no further propagation)
```

Why this naming pattern (`asn:0:peer`, `asn:1:peer`, etc.):

* `X:0:Y` — "Don't go to Y." The `0` reads as "block."
* `X:1:Y` — "Only to Y." The `1` reads as "exclusively."
* `X:10N:Y` — "Prepend N times to Y." Reads naturally.
* This is the Hurricane Electric / NTT-style scheme.

Large community equivalent (publish both):

```
65000:0:peer_asn   →  Don't announce
65000:1:peer_asn   →  Only announce to
65000:101:peer_asn →  Prepend 1x
65000:102:peer_asn →  Prepend 2x
65000:103:peer_asn →  Prepend 3x
```

# Part 5: RTBH and Flowspec for DDoS Mitigation

## 5.1 Remote-Triggered Blackhole (RTBH)

Concept: when under attack on prefix X, you want all your transits to drop traffic to X at *their* edge (not yours), saving your transit capacity. You signal this by announcing X with a special community + special next-hop.

### 5.1.1 Customer-Triggered RTBH

A customer wants you to blackhole their own prefix:

```
Customer announces:    198.51.100.55/32 community 65000:666
You verify:           - Prefix is within customer's authorized space
                      - Community matches your RTBH community
You re-announce:      To transits with the transit's RTBH community
                      Set next-hop to discard locally
                      Set NO_EXPORT to peers (avoid leaking)
```

### 5.1.2 Operator-Triggered RTBH

You inject a static into your network:

```
set routing-options static route 198.51.100.55/32 discard
                                            community [ 65000:9999 no-export ]
```

### 5.1.3 RTBH Safety Rules

* Only accept RTBH on /32 IPv4 or /128 IPv6.
* Verify the prefix is within the customer's authorized space (covered by their prefix-list).
* Always set NO_EXPORT so it doesn't leak.
* Forward to transits' RTBH communities only if the transit supports it.

## 5.2 BGP Flowspec (RFC 8955)

Concept: instead of nullrouting an entire prefix (which kills the victim too), Flowspec lets you signal packet filters — drop only traffic matching `(src=A, dst=B, port=C, proto=UDP, length=X)`. Routers install these as ACLs in hardware.

Use cases:

* Drop reflection-amplification attacks at edge (e.g., drop UDP src-port 11211 toward customer for memcached attack).
* Rate-limit specific traffic patterns.
* Redirect to scrubbing centers.

Junos Flowspec config:

```
protocols {
    bgp {
        group IBGP-FLOWSPEC {
            type internal;
            family inet {
                flow;
            }
            family inet6 {
                flow;
            }
            neighbor 10.0.0.10;
        }
    }
}

routing-options {
    flow {
        route DROP-MEMCACHED-REFLECTION {
            match {
                destination 198.51.100.0/24;
                protocol udp;
                source-port 11211;
            }
            then discard;
        }
        route RATE-LIMIT-NTP-AMPLIFICATION {
            match {
                destination 198.51.100.0/24;
                protocol udp;
                source-port 123;
                packet-length 468;
            }
            then {
                rate-limit 1m;
            }
        }
    }
}
```

Most large operators run a Flowspec controller (FastNetMon, ExaBGP-based custom systems, vendor solutions) that detects DDoS via NetFlow/sFlow and auto-injects Flowspec rules.

EBGP Flowspec with transits: many transits accept Flowspec from customers with strict validation. Each publishes its rules — typically: match destinations only within your assigned space, limited number of rules, rate-limits. Consult each transit's documentation.

Customer-facing DDoS communities:

```
65000:666           RTBH /32 IPv4 or /128 IPv6
65000:667           RTBH + announce to transits (if transit-RTBH supported)
65000:668           RTBH but only within our AS (no-export)
```

# Part 6: Naming Conventions

## 6.1 Policy Names

```
PL-<purpose>                    Reusable building-block policies
IMPORT-<TYPE>-<NAME>-<ASN>      Per-peer import
EXPORT-<TYPE>-<NAME>-<ASN>      Per-peer export

Examples:
PL-REJECT-MARTIANS-V4
PL-RPKI-REJECT-INVALID
PL-RPKI-TAG-STATE
PL-EXPORT-ACTION-COMMUNITIES
PL-SCRUB-INBOUND
PL-SCRUB-OUTBOUND
IMPORT-TRANSIT-NTT-2914
EXPORT-PEER-HE-6939
IMPORT-CUSTOMER-ACME-65001
```

## 6.2 Prefix-Lists, AS-Path, Communities

```
PL-MARTIANS-V4 / PL-MARTIANS-V6
PL-OWN-AGGREGATES-V4 / V6
PL-CUSTOMER-<NAME>-V4 / V6              (per LOA, manually maintained)

ASP-OWN-ORIGIN
ASP-CUSTOMER-<NAME>                     (per LOA, manually maintained)
ASP-SANITY                              (group: too-long, private, reserved)

CM-FROM-<source>                        Informational
CM-RPKI-VALID / CM-RPKI-UNKNOWN
CM-LP-<value>
CM-PREPEND-<count>X-<target>
CM-NOEXPORT-<target>
CM-CUST-NOEXP-<peer-name>               (customer-facing)
CM-CUST-PREPEND-<n>X-<peer-name>
CM-RTBH-CUSTOMER / CM-RTBH-LOCAL
```

## 6.3 Final Community Plan (your ASN = 65000)

### 6.3.1 Internal-Only (you set, you read)

```
Source / type:
  65000:1000  From transit (any)
  65000:1100  From peer (any)
  65000:1200  From customer (any)
  65000:1300  Originated by us
  65000:1101  From NTT (2914)
  65000:1102  From Telia (1299)
  65000:1103  From Cogent (174)
  65000:1201  From HE (6939)
  65000:1202  From DE-CIX route servers
  65000:1203  From Equinix-IX

Validation state:
  65000:1301  RPKI valid
  65000:1302  RPKI unknown
  /* invalid never tagged — invalid is rejected */

Geography:
  65000:2001  Ingress HKG
  65000:2002  Ingress SIN
  65000:2003  Ingress TYO
  65000:2004  Ingress LAX
  65000:2005  Ingress FRA

LocalPref scheme (set internally):
  65000:5050  Force LP 50
  65000:5080  Force LP 80
  65000:5150  Force LP 150
  65000:5250  Force LP 250
```

### 6.3.2 Customer-Facing (customers set, you honor)

```
Don't announce:
  65000:0:0       Don't announce anywhere
  65000:0:2914    Don't announce to NTT
  65000:0:1299    Don't announce to Telia
  65000:0:174     Don't announce to Cogent
  65000:0:6939    Don't announce to HE

Only announce to:
  65000:1:2914    Only announce to NTT
  65000:1:1299    Only announce to Telia

Prepend 1x:
  65000:101:0     Prepend 1x to all transits
  65000:101:2914  Prepend 1x to NTT
  65000:101:1299  Prepend 1x to Telia

Prepend 2x:
  65000:102:0     Prepend 2x to all transits
  65000:102:2914  Prepend 2x to NTT

Prepend 3x:
  65000:103:0     Prepend 3x to all transits
  65000:103:2914  Prepend 3x to NTT

DDoS / RTBH:
  65000:666       RTBH (host route only, /32 v4 or /128 v6)
  65000:667       RTBH + signal upstream transits' RTBH
  65000:668       RTBH within our AS only

Standard:
  no-export       Standard NO_EXPORT
```

### 6.3.3 Large-Community Equivalents (publish both)

Same scheme, but using large communities for 4-byte ASN cleanliness:

```
65000:0:peer_asn      Don't announce
65000:1:peer_asn      Only announce
65000:101:peer_asn    Prepend 1x
65000:102:peer_asn    Prepend 2x
65000:103:peer_asn    Prepend 3x
```

# Part 7: Final Junos Configuration

This is the consolidated, deployable configuration. Replace ASN `65000`, prefixes `203.0.113.0/24`, etc. with your actuals.

## 7.1 Foundation: Prefix-Lists & AS-Path Filters

```
policy-options {
    prefix-list PL-MARTIANS-V4 {
        0.0.0.0/8;
        10.0.0.0/8;
        100.64.0.0/10;
        127.0.0.0/8;
        169.254.0.0/16;
        172.16.0.0/12;
        192.0.0.0/24;
        192.0.2.0/24;
        192.168.0.0/16;
        198.18.0.0/15;
        198.51.100.0/24;
        203.0.113.0/24;
        224.0.0.0/4;
        240.0.0.0/4;
    }
    prefix-list PL-MARTIANS-V6 {
        ::/8;
        100::/64;
        2001:db8::/32;
        fc00::/7;
        fe80::/10;
        ff00::/8;
    }
    prefix-list PL-OWN-AGGREGATES-V4 {
        203.0.113.0/24;
    }
    prefix-list PL-OWN-AGGREGATES-V6 {
        2001:db8::/32;
    }
    prefix-list PL-RTBH-DISCARD-NH {
        192.0.2.1/32;
    }

    as-path-group ASP-SANITY {
        as-path NO-PRIVATE ".* [64512-65534] .*";
        as-path NO-RESERVED ".* 23456 .*";
        as-path TOO-LONG ".{50,}";
    }
    as-path ASP-OWN-ORIGIN "^65000$";
    as-path ASP-CUSTOMER-ACME "^65001(_65001)*$";
}
```

## 7.2 Communities — Complete

```
policy-options {
    /* === SOURCE / TYPE === */
    community CM-FROM-TRANSIT      members 65000:1000;
    community CM-FROM-PEER         members 65000:1100;
    community CM-FROM-CUSTOMER     members 65000:1200;
    community CM-FROM-OWN          members 65000:1300;
    community CM-FROM-NTT          members 65000:1101;
    community CM-FROM-TELIA        members 65000:1102;
    community CM-FROM-COGENT       members 65000:1103;
    community CM-FROM-HE           members 65000:1201;

    /* === VALIDATION === */
    community CM-RPKI-VALID    members 65000:1301;
    community CM-RPKI-UNKNOWN  members 65000:1302;

    /* === GEOGRAPHY === */
    community CM-INGRESS-HKG   members 65000:2001;
    community CM-INGRESS-SIN   members 65000:2002;
    community CM-INGRESS-TYO   members 65000:2003;

    /* === INTERNAL LP === */
    community CM-LP-50    members 65000:5050;
    community CM-LP-80    members 65000:5080;
    community CM-LP-150   members 65000:5150;
    community CM-LP-250   members 65000:5250;

    /* === CUSTOMER-FACING: NO-EXPORT TO PEER === */
    community CM-CUST-NOEXP-ALL members [
        65000:0:0
        large:65000:0:0
    ];
    community CM-CUST-NOEXP-NTT members [
        65000:0:2914
        large:65000:0:2914
    ];
    community CM-CUST-NOEXP-TELIA members [
        65000:0:1299
        large:65000:0:1299
    ];
    community CM-CUST-NOEXP-COGENT members [
        65000:0:174
        large:65000:0:174
    ];
    community CM-CUST-NOEXP-HE members [
        65000:0:6939
        large:65000:0:6939
    ];

    /* === CUSTOMER-FACING: ONLY-EXPORT-TO === */
    community CM-CUST-ONLY-NTT members [
        65000:1:2914
        large:65000:1:2914
    ];
    community CM-CUST-ONLY-TELIA members [
        65000:1:1299
        large:65000:1:1299
    ];
    community CM-CUST-ONLY-COGENT members [
        65000:1:174
        large:65000:1:174
    ];
    community CM-CUST-ONLY-HE members [
        65000:1:6939
        large:65000:1:6939
    ];

    /* === CUSTOMER-FACING: PREPEND === */
    community CM-CUST-PREPEND-1X-ALL-TRANSIT members [
        65000:101:0
        large:65000:101:0
    ];
    community CM-CUST-PREPEND-2X-ALL-TRANSIT members [
        65000:102:0
        large:65000:102:0
    ];
    community CM-CUST-PREPEND-3X-ALL-TRANSIT members [
        65000:103:0
        large:65000:103:0
    ];
    community CM-CUST-PREPEND-1X-NTT members [
        65000:101:2914
        large:65000:101:2914
    ];
    community CM-CUST-PREPEND-2X-NTT members [
        65000:102:2914
        large:65000:102:2914
    ];
    community CM-CUST-PREPEND-3X-NTT members [
        65000:103:2914
        large:65000:103:2914
    ];
    community CM-CUST-PREPEND-1X-TELIA members [
        65000:101:1299
        large:65000:101:1299
    ];
    community CM-CUST-PREPEND-2X-TELIA members [
        65000:102:1299
        large:65000:102:1299
    ];
    community CM-CUST-PREPEND-3X-TELIA members [
        65000:103:1299
        large:65000:103:1299
    ];

    /* === RTBH === */
    community CM-RTBH-CUSTOMER          members 65000:666;
    community CM-RTBH-CUSTOMER-UPSTREAM members 65000:667;
    community CM-RTBH-CUSTOMER-LOCAL    members 65000:668;
    community CM-RTBH-LOCAL             members 65000:9999;

    /* === STANDARD === */
    community CM-NO-EXPORT     members no-export;
    community CM-NO-ADVERTISE  members no-advertise;

    /* === SCRUBBING === */
    community CM-ALL-OURS members "^65000:.*$";
    community CM-ALL-OURS-LC members "^large:65000:.*:.*$";
}
```

## 7.3 Reusable Building-Block Policies

```
policy-options {

    /* ─── BLOCK 1: REJECT MARTIANS ─── */
    policy-statement PL-REJECT-MARTIANS-V4 {
        term martians {
            from {
                family inet;
                prefix-list-filter PL-MARTIANS-V4 orlonger;
            }
            then reject;
        }
        term too-specific {
            from {
                family inet;
                route-filter 0.0.0.0/0 prefix-length-range /25-/32;
            }
            then reject;
        }
        term too-broad {
            from {
                family inet;
                route-filter 0.0.0.0/0 upto /7;
            }
            then reject;
        }
    }

    policy-statement PL-REJECT-MARTIANS-V6 {
        term martians {
            from {
                family inet6;
                prefix-list-filter PL-MARTIANS-V6 orlonger;
            }
            then reject;
        }
        term too-specific {
            from {
                family inet6;
                route-filter ::/0 prefix-length-range /49-/128;
            }
            then reject;
        }
        term too-broad {
            from {
                family inet6;
                route-filter ::/0 upto /15;
            }
            then reject;
        }
    }

    /* ─── BLOCK 2: REJECT BAD AS-PATH ─── */
    policy-statement PL-REJECT-BAD-ASPATH {
        term bad {
            from as-path-group ASP-SANITY;
            then reject;
        }
    }

    /* ─── BLOCK 3: RPKI ─── */
    policy-statement PL-RPKI-REJECT-INVALID {
        term reject-invalid {
            from validation-database invalid;
            then {
                validation-state invalid;
                reject;
            }
        }
    }
    policy-statement PL-RPKI-TAG-STATE {
        term tag-valid {
            from validation-database valid;
            then {
                validation-state valid;
                community add CM-RPKI-VALID;
                next term;
            }
        }
        term tag-unknown {
            from validation-database unknown;
            then {
                validation-state unknown;
                community add CM-RPKI-UNKNOWN;
                next term;
            }
        }
    }
    policy-statement PL-RPKI-LP-BONUS {
        term valid-bonus {
            from community CM-RPKI-VALID;
            then {
                local-preference add 5;
                next term;
            }
        }
    }

    /* ─── BLOCK 4: SCRUBBING ─── */
    policy-statement PL-SCRUB-INBOUND {
        term strip-our-communities {
            then {
                community delete CM-ALL-OURS;
                community delete CM-ALL-OURS-LC;
            }
        }
    }

    /* ─── BLOCK 5: REJECT OWN PREFIXES BACK ─── */
    policy-statement PL-REJECT-OWN-PREFIXES {
        term v4 {
            from {
                family inet;
                prefix-list-filter PL-OWN-AGGREGATES-V4 orlonger;
            }
            then reject;
        }
        term v6 {
            from {
                family inet6;
                prefix-list-filter PL-OWN-AGGREGATES-V6 orlonger;
            }
            then reject;
        }
    }

    /* ─── BLOCK 6: RTBH FROM CUSTOMER ─── */
    policy-statement PL-RTBH-FROM-CUSTOMER {
        term rtbh-host-only-v4 {
            from {
                family inet;
                community CM-RTBH-CUSTOMER;
                route-filter 0.0.0.0/0 prefix-length-range /32-/32;
            }
            then {
                local-preference 250;
                next-hop 192.0.2.1;
                community add CM-NO-EXPORT;
                accept;
            }
        }
        term rtbh-host-only-v6 {
            from {
                family inet6;
                community CM-RTBH-CUSTOMER;
                route-filter ::/0 prefix-length-range /128-/128;
            }
            then {
                local-preference 250;
                next-hop 192.0.2.1;
                community add CM-NO-EXPORT;
                accept;
            }
        }
        term reject-bad-rtbh {
            from community CM-RTBH-CUSTOMER;
            then reject;
        }
    }
}
```

## 7.4 Per-Peer Templates: Honor Customer Actions

For each transit/peer, define a policy that honors customer-set communities. Below is the template for the NTT export — replicate per peer.

```
policy-options {
    policy-statement PL-EXPORT-ACTIONS-NTT {
        /* === CUSTOMER ASKED NO-ANNOUNCE === */
        term cust-noexp-all {
            from community CM-CUST-NOEXP-ALL;
            then reject;
        }
        term cust-noexp-ntt {
            from community CM-CUST-NOEXP-NTT;
            then reject;
        }

        /* === CUSTOMER ASKED ONLY-TO-OTHER === */
        term cust-only-telia-not-us {
            from community CM-CUST-ONLY-TELIA;
            then reject;
        }
        term cust-only-cogent-not-us {
            from community CM-CUST-ONLY-COGENT;
            then reject;
        }
        term cust-only-he-not-us {
            from community CM-CUST-ONLY-HE;
            then reject;
        }

        /* === PREPEND === */
        term prepend-3x {
            from community [
                CM-CUST-PREPEND-3X-NTT
                CM-CUST-PREPEND-3X-ALL-TRANSIT
            ];
            then {
                as-path-prepend "65000 65000 65000";
            }
        }
        term prepend-2x {
            from community [
                CM-CUST-PREPEND-2X-NTT
                CM-CUST-PREPEND-2X-ALL-TRANSIT
            ];
            then {
                as-path-prepend "65000 65000";
            }
        }
        term prepend-1x {
            from community [
                CM-CUST-PREPEND-1X-NTT
                CM-CUST-PREPEND-1X-ALL-TRANSIT
            ];
            then {
                as-path-prepend "65000";
            }
        }
    }
}
```

Mirror this for each transit/peer with names like `PL-EXPORT-ACTIONS-TELIA`, `PL-EXPORT-ACTIONS-COGENT`, `PL-EXPORT-ACTIONS-HE`.

## 7.5 Outbound Scrub

```
policy-options {
    policy-statement PL-SCRUB-OUTBOUND {
        term strip-action-communities {
            then {
                community delete CM-CUST-NOEXP-ALL;
                community delete CM-CUST-NOEXP-NTT;
                community delete CM-CUST-NOEXP-TELIA;
                community delete CM-CUST-NOEXP-COGENT;
                community delete CM-CUST-NOEXP-HE;
                community delete CM-CUST-ONLY-NTT;
                community delete CM-CUST-ONLY-TELIA;
                community delete CM-CUST-ONLY-COGENT;
                community delete CM-CUST-ONLY-HE;
                community delete CM-CUST-PREPEND-1X-NTT;
                community delete CM-CUST-PREPEND-2X-NTT;
                community delete CM-CUST-PREPEND-3X-NTT;
                community delete CM-CUST-PREPEND-1X-TELIA;
                community delete CM-CUST-PREPEND-2X-TELIA;
                community delete CM-CUST-PREPEND-3X-TELIA;
                community delete CM-CUST-PREPEND-1X-ALL-TRANSIT;
                community delete CM-CUST-PREPEND-2X-ALL-TRANSIT;
                community delete CM-CUST-PREPEND-3X-ALL-TRANSIT;
                community delete CM-RTBH-CUSTOMER;
                community delete CM-RTBH-CUSTOMER-LOCAL;
                community delete CM-RTBH-LOCAL;
            }
        }
    }
}
```

## 7.6 Per-Peer Import: Transit (NTT)

```
policy-options {
    policy-statement IMPORT-TRANSIT-NTT-2914 {
        term reject-martians {
            from policy PL-REJECT-MARTIANS-V4;
        }
        term reject-bad-aspath {
            from policy PL-REJECT-BAD-ASPATH;
        }
        term reject-rpki-invalid {
            from policy PL-RPKI-REJECT-INVALID;
        }
        term reject-own-prefixes {
            from policy PL-REJECT-OWN-PREFIXES;
        }
        term scrub-communities {
            from policy PL-SCRUB-INBOUND;
        }
        term tag-rpki {
            from policy PL-RPKI-TAG-STATE;
        }
        term tag-source {
            then {
                community add CM-FROM-TRANSIT;
                community add CM-FROM-NTT;
                community add CM-INGRESS-HKG;
                local-preference 80;
            }
        }
        term lp-bonus {
            from policy PL-RPKI-LP-BONUS;
        }
        term accept {
            then accept;
        }
    }
}
```

## 7.7 Per-Peer Export: Transit (NTT)

```
policy-options {
    policy-statement EXPORT-TRANSIT-NTT-2914 {
        /* === Honor explicit no-export attributes === */
        term respect-no-export {
            from community CM-NO-EXPORT;
            then reject;
        }
        term respect-no-advertise {
            from community CM-NO-ADVERTISE;
            then reject;
        }

        /* === Honor customer/operator action communities === */
        term action-block {
            from policy PL-EXPORT-ACTIONS-NTT;
        }

        /* === Scrub before announcing === */
        term scrub {
            from policy PL-SCRUB-OUTBOUND;
        }

        /* === Allow our own aggregates === */
        term advertise-own {
            from {
                protocol [ aggregate static ];
                prefix-list PL-OWN-AGGREGATES-V4;
            }
            then {
                community add CM-FROM-OWN;
                accept;
            }
        }
        term advertise-own-v6 {
            from {
                protocol [ aggregate static ];
                prefix-list PL-OWN-AGGREGATES-V6;
            }
            then {
                community add CM-FROM-OWN;
                accept;
            }
        }

        /* === Allow customer routes === */
        term advertise-customers {
            from community CM-FROM-CUSTOMER;
            then accept;
        }

        /* === Default reject (Gao-Rexford) === */
        term default-reject {
            then reject;
        }
    }
}
```

## 7.8 Per-Peer Import: Customer (ACME)

```
policy-options {
    policy-statement IMPORT-CUSTOMER-ACME-65001 {
        term reject-martians {
            from policy PL-REJECT-MARTIANS-V4;
        }
        term reject-bad-aspath {
            from policy PL-REJECT-BAD-ASPATH;
        }
        term reject-rpki-invalid {
            from policy PL-RPKI-REJECT-INVALID;
        }
        term reject-own-prefixes {
            from policy PL-REJECT-OWN-PREFIXES;
        }

        /* === RTBH special handling — must come before scrubbing! === */
        term rtbh-handling {
            from policy PL-RTBH-FROM-CUSTOMER;
        }

        /* === Verify origin AS === */
        term enforce-aspath {
            from as-path ASP-CUSTOMER-ACME;
        }
        term reject-bad-origin {
            then reject;
        }

        /* === Verify prefix is in authorized list (per customer LOA) === */
        term enforce-prefixlist {
            from {
                prefix-list-filter PL-CUSTOMER-ACME-V4 orlonger;
            }
        }
        term reject-not-authorized {
            then reject;
        }

        /* === Scrub, tag, accept === */
        term scrub {
            from policy PL-SCRUB-INBOUND;
        }
        term tag-rpki {
            from policy PL-RPKI-TAG-STATE;
        }
        term tag-source {
            then {
                community add CM-FROM-CUSTOMER;
                community add CM-INGRESS-HKG;
                local-preference 200;
            }
        }
        term lp-bonus {
            from policy PL-RPKI-LP-BONUS;
        }
        term accept {
            then accept;
        }
    }
}
```

## 7.9 Per-Peer Export: Customer (ACME)

```
policy-options {
    policy-statement EXPORT-CUSTOMER-ACME-65001 {
        term respect-no-export {
            from community CM-NO-EXPORT;
            then reject;
        }
        term scrub {
            from policy PL-SCRUB-OUTBOUND;
        }
        /* Customers get the full table */
        term advertise-own {
            from {
                protocol [ aggregate static ];
                prefix-list PL-OWN-AGGREGATES-V4;
            }
            then accept;
        }
        term advertise-customers {
            from community CM-FROM-CUSTOMER;
            then accept;
        }
        term advertise-peers {
            from community CM-FROM-PEER;
            then accept;
        }
        term advertise-transits {
            from community CM-FROM-TRANSIT;
            then accept;
        }
        term default-reject {
            then reject;
        }
    }
}
```

## 7.10 RPKI Validator Configuration

```
routing-options {
    validation {
        group RPKI-VALIDATORS {
            session 192.0.2.10 {
                refresh-time 120;
                hold-time 180;
                port 3323;
                local-address 192.0.2.254;
                preference 100;
            }
            session 192.0.2.11 {
                refresh-time 120;
                hold-time 180;
                port 3323;
                local-address 192.0.2.254;
                preference 200;
            }
        }
    }
    static {
        route 192.0.2.1/32 discard;   /* RTBH discard next-hop */
    }
}
```

## 7.11 BGP Group / Neighbor Application

```
groups {
    EBGP-COMMON-V4 {
        protocols {
            bgp {
                group <*> {
                    neighbor <*> {
                        family inet {
                            unicast {
                                prefix-limit {
                                    maximum 1000000;
                                    teardown 90 idle-timeout 30;
                                }
                            }
                        }
                        bfd-liveness-detection {
                            minimum-interval 300;
                            multiplier 3;
                        }
                    }
                }
            }
        }
    }
}

protocols {
    bgp {
        /* === IBGP === */
        group IBGP {
            type internal;
            local-address 10.0.0.1;
            family inet {
                unicast;
            }
            family inet6 {
                unicast;
            }
            family route-validation;     /* carry RPKI state across IBGP */
            family inet {
                flow;                    /* Flowspec */
            }
            neighbor 10.0.0.2;
            neighbor 10.0.0.3;
        }

        /* === TRANSIT NTT === */
        group EBGP-TRANSIT-NTT {
            apply-groups EBGP-COMMON-V4;
            type external;
            peer-as 2914;
            import IMPORT-TRANSIT-NTT-2914;
            export EXPORT-TRANSIT-NTT-2914;
            neighbor 192.0.2.1;
        }

        /* === TRANSIT TELIA === */
        group EBGP-TRANSIT-TELIA {
            apply-groups EBGP-COMMON-V4;
            type external;
            peer-as 1299;
            import IMPORT-TRANSIT-TELIA-1299;
            export EXPORT-TRANSIT-TELIA-1299;
            neighbor 192.0.2.5;
        }

        /* === PEER HE === */
        group EBGP-PEER-HE {
            apply-groups EBGP-COMMON-V4;
            type external;
            peer-as 6939;
            import IMPORT-PEER-HE-6939;
            export EXPORT-PEER-HE-6939;
            neighbor 192.0.2.9;
        }

        /* === CUSTOMER ACME === */
        group EBGP-CUSTOMER-ACME {
            apply-groups EBGP-COMMON-V4;
            type external;
            peer-as 65001;
            import IMPORT-CUSTOMER-ACME-65001;
            export EXPORT-CUSTOMER-ACME-65001;
            neighbor 192.0.2.13;
        }
    }
}
```

# Part 8: Operations Reference

## 8.1 Common Use Cases — Traffic Engineering by Community

Once the framework is in place, NOC tasks become trivial. Each is a single static-route or aggregate community tag — no policy edit:

| Task | Action |
|------|--------|
| Move outbound traffic for `1.2.3.0/24` away from NTT | Tag inbound NTT route with `CM-LP-50` or block at ingress |
| Stop announcing `5.6.7.0/24` to Cogent only | Aggregate, add `65000:0:174` |
| Make inbound traffic from APAC arrive via Telia, not NTT | Prepend 2x to NTT for that prefix: `65000:102:2914` |
| Withdraw a prefix from the Internet entirely (RTBH) | Tag with `65000:9999`; RTBH policy nullroutes it and applies NO_EXPORT |
| Announce only to peers, not transit (regional traffic) | Tag with peer-only community |
| Customer requests "don't send my routes to ASN X" | Customer sets `65000:0:X` themselves; you honor it |

## 8.2 Key Show Commands

```
# RPKI
show validation session
show validation database
show validation database prefix 8.8.8.0/24
show validation statistics
show route validation-state invalid
show route validation-state valid

# BGP general
show bgp summary
show bgp neighbor 192.0.2.1 detail
show route receive-protocol bgp 192.0.2.1
show route advertising-protocol bgp 192.0.2.1
show route community 65000:1101
show route community-name CM-FROM-NTT

# Verify policy logic
show route protocol bgp 1.1.1.0/24 detail
test policy IMPORT-TRANSIT-NTT-2914 1.1.1.0/24
```

## 8.3 Verifying Customer Self-Service Communities

After a customer sets `65000:0:2914` on a route:

```
show route receive-protocol bgp <customer> | match community
show route advertising-protocol bgp <NTT-neighbor> 1.1.1.0/24
   → should be empty (suppressed)
show route advertising-protocol bgp <Telia-neighbor> 1.1.1.0/24
   → should still be present
```

## 8.4 Phased Rollout Schedule

| Week | Action |
|------|--------|
| 1    | Deploy validators (Routinator + rpki-client). Verify VRP counts. |
| 2    | Configure RTR sessions on routers. Verify `show validation session`. |
| 3    | Add `PL-RPKI-TAG-STATE` to imports. Tag only, no rejection. Observe. |
| 4    | Audit your own ROAs. Fix any maxLength issues. Publish missing ROAs. |
| 5    | Add `PL-RPKI-REJECT-INVALID` to one transit. Monitor. |
| 6    | Roll RPKI rejection to all transits. |
| 7    | Roll RPKI rejection to peers and IXPs. |
| 8    | Build per-customer prefix-lists from LOAs. Apply to customer imports. |
| 9    | Migrate customers to new IMPORT/EXPORT framework one at a time. |
| 10   | Publish customer community documentation. Notify customers. |
| 11   | Deploy Flowspec controller. Test with a single attack scenario. |

## 8.5 Maintenance Routines

Daily (automated):

* RPKI validator health check.
* VRP count diff alert.
* BGP session state monitoring.

Weekly:

* Review RPKI invalid rejections per peer (large spike = investigate).
* Audit your own prefixes for ROA correctness via external validator ([rpki.cloudflare.com](http://rpki.cloudflare.com), bgp.tools).

Monthly:

* Audit customer communities — are customers actually using them? What changes have been made?
* Review prefix-limit thresholds.
* Update peer/transit list — any new ASNs to add to community plan?

Quarterly:

* Re-verify each customer's prefix-list still matches their LOA.
* Disaster recovery test: shut down primary validator, verify failover.
* Review of MANRS compliance.
* Communities documentation review.

## 8.6 Public Documentation Page

Maintain a public page (e.g., `https://as65000.net/communities`) documenting your full community scheme. Customers and peers will reference it. Register it in PeeringDB. Examples to model after:

* AS2914 (NTT): <https://www.us.ntt.net/support/policy/routing.cfm>
* AS6939 (HE): <http://routerguide.he.net/>
* AS3257 (GTT), AS1299 (Telia/Arelion), AS174 (Cogent) all publish similar docs.

# Part 9: Standards Reference

| RFC / Standard | Topic |
|----------------|-------|
| RFC 7454 / BCP 194 | BGP Operations and Security |
| RFC 6480, 6482, 6811 | RPKI architecture, ROAs, ROV |
| RFC 6810, 8210 | RPKI-to-Router (RTR) protocol |
| RFC 8092, 8195 | Large BGP Communities + operational use |
| RFC 8097       | RPKI validation state extended community |
| RFC 8955, 8956 | BGP Flowspec v4 / v6 |
| RFC 9234       | BGP Role / Only-to-Customer attribute |
| MANRS          | Mutually Agreed Norms for Routing Security |
| RIPE-705       | BGP filtering recommendations |

# Part 10: Summary

This framework provides:


1. **Architecture** — multi-validator RPKI ROV + per-customer prefix-list filtering + Flowspec controller, all feeding edge routers running a deterministic policy chain.
2. **Conventions** — structured community plan that's both internal-control and customer-facing, with regular and large communities, fully documented for public consumption.
3. **Detailed policies** — modular reusable building blocks, per-peer import/export, RTBH, action-honoring blocks, scrubbing, validation tagging.
4. **Configuration** — production-ready Junos config skeleton for transits, peers, and customers, drop-in ready (replace ASN/IPs/aggregates).
5. **Operations** — monitoring, phased rollout, maintenance routines.

This framework matches what large carriers run today, scales to thousands of EBGP sessions, and turns traffic engineering into a community-tagging exercise rather than policy editing.