import json
import re

def parse_juniper_lldp(raw_lldp):
    connections = []
    lines = raw_lldp.splitlines()
    for line in lines:
        if "Local Interface" in line or "---" in line or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 5:
            local_int = parts[0]
            parent_ae = parts[1] if parts[1] != "-" else None
            remote_port = parts[3]
            remote_sys = parts[4]
            connections.append({
                "local_int": local_int,
                "parent_bundle": parent_ae,
                "remote_port": remote_port,
                "remote_sys": remote_sys
            })
    return connections

def parse_juniper_bgp(raw_bgp):
    peers = []
    # Split by Peer blocks
    blocks = re.split(r"Peer: ", raw_bgp)
    for block in blocks[1:]:
        lines = block.splitlines()
        first_line = lines[0]
        # Peer: 10.112.0.33 AS 65001.11004 Local: unspecified AS 65001.11004
        peer_match = re.search(r"^([\d\.\+]+)\s+AS\s+([\d\.]+)\s+Local:\s+([\d\.\+a-z]+)\s+AS\s+([\d\.]+)", first_line)
        if peer_match:
            peer_ip = peer_match.group(1).split("+")[0]
            peer_as = peer_match.group(2)
            local_ip = peer_match.group(3).split("+")[0]
            local_as = peer_match.group(4)
            
            desc = "N/A"
            state = "Unknown"
            for line in lines:
                if "Description:" in line:
                    desc = line.split("Description:")[1].strip()
                if "State:" in line:
                    state = line.split("State:")[1].split()[0].strip()
            
            peers.append({
                "remote_ip": peer_ip,
                "remote_as": peer_as,
                "local_ip": local_ip,
                "local_as": local_as,
                "description": desc,
                "state": state
            })
    return peers

def parse_juniper_bundles(raw_terse):
    bundles = {} # aeX -> [ge-..., xe-...]
    for line in raw_terse.splitlines():
        if "aenet    -->" in line:
            parts = line.split()
            phys = parts[0].split(".")[0]
            bundle = parts[-1].split(".")[0]
            if bundle not in bundles:
                bundles[bundle] = []
            if phys not in bundles[bundle]:
                bundles[bundle].append(phys)
    return bundles

def main():
    with open("topology_raw_data.json", "r") as f:
        all_data = json.load(f)

    report = []

    for device in all_data:
        hostname = device["hostname"]
        if device["type"] == "Juniper":
            lldp = parse_juniper_lldp(device["results"].get("lldp_neighbors", ""))
            bgp = parse_juniper_bgp(device["results"].get("bgp_neighbors", ""))
            bundles = parse_juniper_bundles(device["results"].get("interfaces_terse", ""))
            
            report.append({
                "hostname": hostname,
                "ip": device["host"],
                "lldp": lldp,
                "bgp": bgp,
                "bundles": bundles
            })

    # Print Detailed Report
    print("="*100)
    print(f"{'DEVICE':<30} | {'CONNECTION DETAIL'}")
    print("="*100)

    for dev in report:
        print(f"\n>>> {dev['hostname']} ({dev['ip']})")
        
        print(f"  [Physical Connections (LLDP)]")
        if not dev['lldp']:
            print("    None found")
        for conn in dev['lldp']:
            bundle_info = f" (Part of {conn['parent_bundle']})" if conn['parent_bundle'] else ""
            print(f"    - {conn['local_int']}{bundle_info} <---> {conn['remote_sys']} (Port: {conn['remote_port']})")
        
        if dev['bundles']:
            print(f"  [Logical Bundles (Aggregated Ethernet)]")
            for ae, members in dev['bundles'].items():
                print(f"    - {ae}: [{', '.join(members)}]")
        
        if dev['bgp']:
            print(f"  [BGP Sessions]")
            for p in dev['bgp']:
                print(f"    - Peer: {p['remote_ip']} (AS {p['remote_as']}) | State: {p['state']} | Desc: {p['description']}")

if __name__ == "__main__":
    main()
