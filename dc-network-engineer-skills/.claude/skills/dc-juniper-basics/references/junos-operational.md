# JunOS Operational Monitoring & Maintenance Commands

## Interface Commands

```junos
show interfaces terse                           # Quick status of ALL interfaces (up/down, IP)
show interfaces terse | match "xe-|et-|ae"      # Only show data interfaces
show interfaces terse | except "\.32767|down"    # Hide internal + down interfaces

show interfaces xe-0/0/0                        # Summary for specific interface
show interfaces xe-0/0/0 extensive              # Full details (counters, errors, DOM)
show interfaces xe-0/0/0 extensive | match "error|CRC|drop|discard"  # Error check

show interfaces xe-0/0/0 statistics             # Traffic counters
show interfaces descriptions                    # Show all interface descriptions

show interfaces diagnostics optics xe-0/0/0     # SFP/QSFP DOM values (Rx/Tx power, temp)
show interfaces diagnostics optics xe-0/0/0 | match "power|temp|alarm"
```

## Routing Commands

```junos
show route                                       # Full routing table
show route 10.0.1.0/24                          # Specific prefix
show route 10.0.1.100 exact                     # Exact match
show route 10.0.1.100 best                      # Best path only
show route 10.0.1.100 detail                    # Full details (communities, local-pref, etc.)
show route 10.0.1.100 extensive                 # All details including inactive paths

show route protocol bgp                         # Only BGP routes
show route protocol ospf                        # Only OSPF routes
show route protocol static                      # Only static routes
show route protocol direct                      # Only directly connected

show route summary                              # Route count by protocol
show route table inet.0 summary                 # IPv4 summary
show route table inet6.0 summary                # IPv6 summary
show route forwarding-table destination 10.0.1.0/24  # FIB (actual forwarding)
```

## BGP Commands

```junos
show bgp summary                                # All BGP peers status
show bgp neighbor 10.0.0.1                      # Detailed neighbor info
show bgp neighbor 10.0.0.1 | match "State|Peer|Active|Received|Accepted|Advertised"

show route advertising-protocol bgp 10.0.0.1    # Routes we SEND to this peer
show route receive-protocol bgp 10.0.0.1        # Routes we RECEIVE (pre-policy)

show bgp group                                  # BGP group configuration summary
```

## OSPF Commands

```junos
show ospf neighbor                              # OSPF adjacencies
show ospf interface                             # OSPF-enabled interfaces
show ospf database                              # LSDB
show ospf route                                 # OSPF routes
show ospf statistics                            # OSPF packet counters
```

## ARP / MAC / LLDP

```junos
show arp no-resolve                             # ARP table (fast, no DNS lookup)
show arp interface irb.100                      # ARP for specific VLAN gateway

show ethernet-switching table                   # MAC address table
show ethernet-switching table vlan-name PROD    # MACs in specific VLAN
show ethernet-switching table interface xe-0/0/0

show lldp neighbors                             # Directly connected neighbor devices
show lldp neighbors interface xe-0/0/0          # Specific port neighbor
```

## System Commands

```junos
show version                                    # JunOS version, model, serial
show chassis hardware                           # Hardware inventory (line cards, optics, PSU)
show chassis hardware | match "SFP|QSFP|XFP"   # List installed optics

show chassis environment                        # Temperature, fan speed, PSU status
show chassis alarms                             # Active alarms
show chassis routing-engine                     # RE CPU/memory utilization

show system uptime                              # System boot time, current time
show system processes extensive | head 20       # Top processes by CPU
show system storage                             # Disk usage
show system memory                              # Memory usage

show system connections                         # TCP connections (like netstat)
show system users                               # Currently logged-in users
show system commit                              # Recent commit history
```

## Log Commands

```junos
show log messages                               # Main system log
show log messages | last 50                     # Last 50 entries
show log messages | match "error|LINK"          # Filter
show log interactive-commands                   # Audit trail of user commands
show log chassisd                               # Chassis daemon log

monitor start messages                          # Live log streaming
monitor stop                                    # Stop live log

# File operations
file list /var/log/                             # List log files
file show /var/log/messages | last 100          # Read a log file
```

## Traffic Monitoring

```junos
monitor traffic interface xe-0/0/0              # Live packet capture (like tcpdump)
monitor traffic interface xe-0/0/0 matching "host 10.0.1.100"
monitor traffic interface xe-0/0/0 write-file /var/tmp/capture.pcap size 10m count 500

monitor interface xe-0/0/0                      # Live interface counters (refreshing)
monitor interface traffic                       # All interfaces traffic rate
```

## Maintenance Commands

```junos
# Restart a daemon
restart routing                                  # Restart routing process (rpd)
restart chassis-control                          # Restart chassis process

# Clear commands
clear interfaces statistics xe-0/0/0            # Reset interface counters
clear arp                                        # Clear ARP cache
clear bgp neighbor 10.0.0.1                     # Reset BGP session
clear ospf neighbor                              # Reset OSPF adjacencies
clear ethernet-switching table                   # Clear MAC table

# File operations
request system software add /var/tmp/junos-image.tgz  # Upgrade JunOS
request system reboot                            # Reboot (requires confirmation)
request system snapshot                          # Backup current system

# Copy files
file copy /var/tmp/capture.pcap scp://user@10.254.0.60:/captures/
```
