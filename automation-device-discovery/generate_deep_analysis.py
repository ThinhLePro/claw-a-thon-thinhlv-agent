import json
import os
import re

BASE_DIR = "device_analysis"

def clean_name(name):
    return name.replace("/", "_").replace(" ", "_")

def parse_bgp_details(raw_bgp):
    peers = []
    blocks = re.split(r"Peer: ", raw_bgp)
    for block in blocks[1:]:
        lines = block.splitlines()
        first_line = lines[0]
        peer_match = re.search(r"^([\d\.\+]+)\s+AS\s+([\d\.]+)\s+Local:\s+([\d\.\+a-z]+)\s+AS\s+([\d\.]+)", first_line)
        if peer_match:
            peer_ip = peer_match.group(1).split("+")[0]
            peer_as = peer_match.group(2)
            local_ip = peer_match.group(3).split("+")[0]
            local_as = peer_match.group(4)
            
            desc = "N/A"
            state = "Unknown"
            type_bgp = "External" if peer_as != local_as else "Internal"
            
            for line in lines:
                if "Description:" in line:
                    desc = line.split("Description:")[1].strip()
                if "State:" in line:
                    state = line.split("State:")[1].split()[0].strip()
                if "Table" in line and "inet.0" in line:
                    # Logic to identify if it's part of a specific VRF or Global
                    pass

            peers.append({
                "ip": peer_ip, "as": peer_as, "local_ip": local_ip, "local_as": local_as,
                "desc": desc, "state": state, "type": type_bgp
            })
    return peers

def generate_device_reports(device, meta):
    hostname = device["hostname"]
    ip = device["host"]
    dev_type = device["type"]
    
    dir_name = f"{ip}_{clean_name(hostname)}"
    full_path = os.path.join(BASE_DIR, dir_name)
    os.makedirs(full_path, exist_ok=True)

    # 1. device_metadata.md
    with open(os.path.join(full_path, "device_metadata.md"), "w") as f:
        f.write(f"# Device Metadata: {hostname}\n\n")
        f.write(f"- **Management IP:** {ip}\n")
        f.write(f"- **Model:** {meta.get('model', 'Unknown')}\n")
        f.write(f"- **OS Version:** {meta.get('os', 'Unknown')}\n")
        f.write(f"- **Uptime:** {meta.get('uptime', 'Unknown')}\n")
        f.write(f"- **Device Type:** {dev_type}\n")

    if dev_type == "Juniper":
        # 2. physical_topology.md
        with open(os.path.join(full_path, "physical_topology.md"), "w") as f:
            f.write(f"# Physical Connectivity Analysis: {hostname}\n\n")
            lldp_raw = device["results"].get("lldp_neighbors", "")
            f.write("## LLDP Neighbors\n")
            if lldp_raw:
                f.write("```text\n" + lldp_raw + "\n```\n")
            else:
                f.write("No LLDP neighbors detected.\n")
            
            f.write("\n## Interface Descriptions\n")
            desc_raw = device["results"].get("interfaces_desc", "")
            f.write("```text\n" + desc_raw + "\n```\n")

        # 3. logical_structures.md
        with open(os.path.join(full_path, "logical_interfaces.md"), "w") as f:
            f.write(f"# Logical Interface & Bundle Analysis: {hostname}\n\n")
            terse_raw = device["results"].get("interfaces_terse", "")
            f.write("## Interface Status (Terse)\n")
            f.write("```text\n" + terse_raw + "\n```\n")
            
            f.write("\n## Aggregated Ethernet (Bundles)\n")
            bundles = []
            for line in terse_raw.splitlines():
                if "aenet    -->" in line:
                    bundles.append(line.strip())
            if bundles:
                for b in bundles:
                    f.write(f"- {b}\n")
            else:
                f.write("No Aggregated Ethernet bundles configured or active.\n")

        # 4. routing_engine.md
        with open(os.path.join(full_path, "routing_engine.md"), "w") as f:
            f.write(f"# Routing & BGP Session Deep-Dive: {hostname}\n\n")
            bgp_raw = device["results"].get("bgp_neighbors", "")
            peers = parse_bgp_details(bgp_raw)
            
            if peers:
                f.write("| Peer IP | AS | Type | State | Description |\n")
                f.write("| :--- | :--- | :--- | :--- | :--- |\n")
                for p in peers:
                    f.write(f"| {p['ip']} | {p['as']} | {p['type']} | {p['state']} | {p['desc']} |\n")
                
                f.write("\n## Raw BGP Neighbor Output\n")
                f.write("```text\n" + bgp_raw[:2000] + "... (truncated)\n```\n")
            else:
                f.write("No active BGP sessions identified.\n")

    elif dev_type == "Ubuntu":
        with open(os.path.join(full_path, "system_analysis.md"), "w") as f:
            f.write(f"# System Analysis: {hostname}\n\n")
            f.write("## Network Interfaces\n")
            f.write("```text\n" + device["results"].get("interfaces_terse", "") + "\n```\n")
            f.write("\n## LLDP Tool Output\n")
            lldp_dict = device["results"].get("lldp_neighbors", {})
            for iface, out in lldp_dict.items():
                f.write(f"### Interface {iface}\n")
                f.write("```text\n" + out + "\n```\n")

def main():
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)

    with open("topology_raw_data.json", "r") as f:
        all_data = json.load(f)
    with open("discovery_results.json", "r") as f:
        discovery = json.load(f)
    
    device_meta = {d["host"]: d for d in discovery}

    print(f"Generating deep analysis for {len(all_data)} devices...")
    for device in all_data:
        meta = device_meta.get(device["host"], {})
        generate_device_reports(device, meta)
    
    print(f"Deep analysis completed. All files saved in the '{BASE_DIR}' directory.")

if __name__ == "__main__":
    main()
