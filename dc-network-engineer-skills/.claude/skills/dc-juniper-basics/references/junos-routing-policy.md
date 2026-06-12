# JunOS Routing Policy & Firewall Filters

## 1. Routing Policy Framework

### Policy Structure
```junos
policy-options {
    policy-statement <NAME> {
        term <TERM-NAME> {
            from {
                # Match conditions
            }
            then {
                # Actions
            }
        }
        term <TERM-2> { ... }
        # If no term matches → default action (depends on where policy is applied)
    }
}
```

### Match Conditions (`from`)
| Condition | Example | Matches |
|---|---|---|
| `protocol` | `from protocol bgp` | Routes learned via BGP |
| `prefix-list` | `from prefix-list MY-PREFIXES` | Routes matching prefix list |
| `route-filter` | `from route-filter 10.0.0.0/8 orlonger` | Routes within range |
| `community` | `from community MY-COMM` | Routes with specific community |
| `as-path` | `from as-path MY-AS-PATH` | Routes matching AS-path regex |
| `interface` | `from interface xe-0/0/0.0` | Routes from specific interface |
| `neighbor` | `from neighbor 10.0.0.1` | Routes from specific BGP peer |
| `local-preference` | `from local-preference 200` | Routes with specific LP |
| `tag` | `from tag 100` | Routes with specific tag |

### Actions (`then`)
| Action | Example | Effect |
|---|---|---|
| `accept` | `then accept` | Accept the route (terminate) |
| `reject` | `then reject` | Reject the route (terminate) |
| `next policy` | `then next policy` | Evaluate next policy in chain |
| `next term` | `then next term` | Evaluate next term (implicit) |
| `local-preference` | `then local-preference 200` | Set LP value |
| `metric` | `then metric 100` | Set MED |
| `community add` | `then community add MY-COMM` | Add community |
| `community set` | `then community set MY-COMM` | Replace community |
| `community delete` | `then community delete MY-COMM` | Remove community |
| `as-path-prepend` | `then as-path-prepend "65001 65001"` | Prepend AS |
| `next-hop` | `then next-hop self` | Change next-hop |

### Route Filters
```junos
# Exact match
from route-filter 10.0.0.0/24 exact

# Prefix and all more-specifics
from route-filter 10.0.0.0/8 orlonger

# Prefix length range
from route-filter 0.0.0.0/0 prefix-length-range /24-/32

# Upto (from /8 to /24)
from route-filter 10.0.0.0/8 upto /24
```

### Prefix Lists
```junos
set policy-options prefix-list LOOPBACKS 10.0.0.0/24

# In policy:
set policy-options policy-statement EXPORT-LO term LO from prefix-list LOOPBACKS
set policy-options policy-statement EXPORT-LO term LO from protocol direct
set policy-options policy-statement EXPORT-LO term LO then accept
```

### Communities
```junos
# Standard community
set policy-options community DOMESTIC members 65001:1000

# Extended community (for EVPN)
set policy-options community RT-100 members target:65001:100

# In policy:
set policy-options policy-statement TAG-DOMESTIC term 1 then community add DOMESTIC
```

### AS-Path Regular Expressions
```junos
set policy-options as-path CUSTOMER-ONLY "^65002$"          # Only origin AS 65002
set policy-options as-path TRANSIT-FREE "^65002 .+"          # 65002 + any path
set policy-options as-path ANY-PATH ".*"                      # Match any path
set policy-options as-path DIRECT-PEER "^65002$|^65003$"     # Either 65002 or 65003
```

### Complete Policy Example
```junos
# Import policy for ISP with community tagging and local-preference
set policy-options policy-statement IMPORT-ISP-A {
    term REJECT-BOGONS {
        from prefix-list BOGONS;
        then reject;
    }
    term TAG-AND-ACCEPT {
        then {
            local-preference 200;
            community add FROM-ISP-A;
            accept;
        }
    }
}

# Apply to BGP group
set protocols bgp group ISP-A import IMPORT-ISP-A
set protocols bgp group ISP-A export EXPORT-OUR-PREFIXES
```

---

## 2. Firewall Filters (ACLs)

### Purpose
Firewall filters in JunOS are **stateless packet filters** (ACLs). They match packets by header fields and take actions (accept, discard, count, policer, etc.).

> **Note**: These are NOT the same as SRX security policies. Firewall filters are applied on interfaces; SRX security policies are zone-based and stateful. See `/dc-juniper-firewall` for SRX.

### Filter Structure
```junos
firewall {
    family inet {
        filter <NAME> {
            term <TERM> {
                from {
                    # Match conditions
                }
                then {
                    # Actions
                }
            }
        }
    }
}
```

### Match Conditions
| Condition | Example |
|---|---|
| `source-address` | `from source-address 10.0.1.0/24` |
| `destination-address` | `from destination-address 10.0.2.0/24` |
| `source-prefix-list` | `from source-prefix-list MGMT-NETS` |
| `protocol` | `from protocol tcp` |
| `source-port` | `from source-port ssh` |
| `destination-port` | `from destination-port [http https]` |
| `tcp-flags` | `from tcp-flags syn` |
| `icmp-type` | `from icmp-type echo-request` |
| `packet-length` | `from packet-length 1500-9000` |
| `forwarding-class` | `from forwarding-class best-effort` |

### Actions
| Action | Effect |
|---|---|
| `accept` | Allow packet |
| `discard` | Silently drop |
| `reject` | Drop with ICMP unreachable |
| `count <counter>` | Increment counter (for monitoring) |
| `log` | Log to syslog |
| `policer <name>` | Apply rate limiting |
| `loss-priority` | Set drop priority |
| `next term` | Continue to next term |

### Example: Server VLAN Access Control
```junos
# Allow only specific traffic to server VLAN
set firewall family inet filter SERVER-VLAN-ACL term ALLOW-SSH from source-prefix-list MGMT-NETS
set firewall family inet filter SERVER-VLAN-ACL term ALLOW-SSH from protocol tcp
set firewall family inet filter SERVER-VLAN-ACL term ALLOW-SSH from destination-port ssh
set firewall family inet filter SERVER-VLAN-ACL term ALLOW-SSH then accept
set firewall family inet filter SERVER-VLAN-ACL term ALLOW-SSH then count ALLOW-SSH

set firewall family inet filter SERVER-VLAN-ACL term ALLOW-ICMP from protocol icmp
set firewall family inet filter SERVER-VLAN-ACL term ALLOW-ICMP from icmp-type echo-request
set firewall family inet filter SERVER-VLAN-ACL term ALLOW-ICMP then accept

set firewall family inet filter SERVER-VLAN-ACL term ALLOW-ESTABLISHED from tcp-established
set firewall family inet filter SERVER-VLAN-ACL term ALLOW-ESTABLISHED then accept

set firewall family inet filter SERVER-VLAN-ACL term DENY-ALL then count DENIED
set firewall family inet filter SERVER-VLAN-ACL term DENY-ALL then log
set firewall family inet filter SERVER-VLAN-ACL term DENY-ALL then discard

# Apply to interface (input = ingress)
set interfaces irb unit 100 family inet filter input SERVER-VLAN-ACL
```

### Verification
```junos
show firewall                               # All filter counters
show firewall filter SERVER-VLAN-ACL        # Specific filter counters
show firewall log                           # Logged packets (if 'log' action used)

# Clear counters
clear firewall filter SERVER-VLAN-ACL
```
