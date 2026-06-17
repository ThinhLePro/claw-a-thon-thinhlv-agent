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
            connections.append({
                "local_interface": parts[0],
                "parent_bundle": parts[1] if parts[1] != "-" else None,
                "remote_port": parts[3],
                "remote_hostname": parts[4]
            })
    return connections

def parse_juniper_bgp(raw_bgp):
    peers = []
    blocks = re.split(r"Peer: ", raw_bgp)
    for block in blocks[1:]:
        lines = block.splitlines()
        first_line = lines[0]
        peer_match = re.search(r"^([\d\.\+]+)\s+AS\s+([\d\.]+)\s+Local:\s+([\d\.\+a-z]+)\s+AS\s+([\d\.]+)", first_line)
        if peer_match:
            peer_ip = peer_match.group(1).split("+")[0]
            peer_as = peer_match.group(2)
            
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
                "description": desc,
                "state": state
            })
    return peers

def parse_juniper_bundles(raw_terse):
    bundles = {}
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
    try:
        with open("topology_raw_data.json", "r") as f:
            raw_data = json.load(f)
        with open("discovery_results.json", "r") as f:
            discovery = json.load(f)
    except Exception as e:
        print(f"Error loading data: {e}")
        return

    # Map discovery data for easy lookup
    device_meta = {d["host"]: d for d in discovery}

    final_topology = []

    for device in raw_data:
        host = device["host"]
        meta = device_meta.get(host, {})
        
        node = {
            "hostname": device["hostname"],
            "management_ip": host,
            "device_type": device["type"],
            "model": meta.get("model", "Unknown"),
            "os_version": meta.get("os", "Unknown"),
            "physical_links": [],
            "logical_bundles": [],
            "bgp_sessions": []
        }

        if device["type"] == "Juniper":
            node["physical_links"] = parse_juniper_lldp(device["results"].get("lldp_neighbors", ""))
            node["bgp_sessions"] = parse_juniper_bgp(device["results"].get("bgp_neighbors", ""))
            bundles = parse_juniper_bundles(device["results"].get("interfaces_terse", ""))
            for ae, members in bundles.items():
                node["logical_bundles"].append({"name": ae, "members": members})
        
        final_topology.append(node)

    # Save as JSON
    with open("network_topology_final.json", "w") as f:
        json.dump(final_topology, f, indent=4)

    # Generate Markdown Summary
    md = [
        "# Network Topology Final Report",
        f"**Generated:** 2026-06-14",
        f"**Scope:** 10.116.0.0/22 (LAB NETWORK)",
        "",
        "## Device Summary",
        "| Hostname | IP | Type | Model | OS |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]
    for n in final_topology:
        md.append(f"| {n['hostname']} | {n['management_ip']} | {n['device_type']} | {n['model']} | {n['os_version']} |")

    md.append("\n## Detailed Connections and Sessions")
    for n in final_topology:
        md.append(f"\n### {n['hostname']} ({n['management_ip']})")
        
        if n['physical_links']:
            md.append("#### Physical Links (LLDP)")
            for l in n['physical_links']:
                bundle = f" (Bundle: {l['parent_bundle']})" if l['parent_bundle'] else ""
                md.append(f"- `{l['local_interface']}`{bundle} <---> **{l['remote_hostname']}** (on port `{l['remote_port']}`)")
        
        if n['logical_bundles']:
            md.append("#### Logical Bundles (Aggregated Ethernet)")
            for b in n['logical_bundles']:
                md.append(f"- `{b['name']}`: Members: `[{', '.join(b['members'])}]`")
        
        if n['bgp_sessions']:
            md.append("#### BGP Peering Sessions")
            md.append("| Remote Peer | AS | State | Description |")
            md.append("| :--- | :--- | :--- | :--- |")
            for s in n['bgp_sessions']:
                md.append(f"| {s['remote_ip']} | {s['remote_as']} | {s['state']} | {s['description']} |")

    with open("network_topology_final.md", "w") as f:
        f.write("\n".join(md))

    print("Successfully exported topology to:")
    print("- network_topology_final.json (Machine Readable)")
    print("- network_topology_final.md (Human/AI Readable)")

if __name__ == "__main__":
    main()
