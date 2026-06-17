import json
import re

def parse_juniper_lldp(raw_lldp):
    connections = []
    lines = raw_lldp.splitlines()
    # Skip headers
    for line in lines:
        if "Local Interface" in line or "---" in line or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 3:
            local_int = parts[0]
            # Handle potential spaces in chassis id or system name
            remote_sys = parts[-1]
            connections.append({"local_int": local_int, "remote_sys": remote_sys})
    return connections

def parse_ubuntu_lldp(raw_lldp_dict):
    connections = []
    for iface, output in raw_lldp_dict.items():
        if "sysName" in output:
            match = re.search(r"sysName\s+(.*)", output)
            if match:
                remote_sys = match.group(1).strip()
                connections.append({"local_int": iface, "remote_sys": remote_sys})
    return connections

def main():
    with open("topology_raw_data.json", "r") as f:
        all_data = json.load(f)

    topology = []
    nodes = {}

    for device in all_data:
        hostname = device["hostname"]
        nodes[hostname] = {
            "type": device["type"],
            "ip": device["host"],
            "connections": []
        }

        if device["type"] == "Juniper":
            lldp_conn = parse_juniper_lldp(device["results"]["lldp_neighbors"])
            nodes[hostname]["connections"] = lldp_conn
        else:
            lldp_conn = parse_ubuntu_lldp(device["results"]["lldp_neighbors"])
            nodes[hostname]["connections"] = lldp_conn

    # Deduplicate and build Mermaid
    mermaid = ["graph TD"]
    seen_links = set()

    # Define groups for styling
    groups = {
        "Gateway": [],
        "SuperSpine": [],
        "Spine": [],
        "Leaf": [],
        "Service": [],
        "Internet": [],
        "Server": []
    }

    for hostname, info in nodes.items():
        # Simple categorization based on hostname
        name_upper = hostname.upper()
        if "GW" in name_upper or "SRX" in name_upper:
            groups["Gateway"].append(hostname)
        elif "SUPER" in name_upper:
            groups["SuperSpine"].append(hostname)
        elif "SPINE" in name_upper or "SPN" in name_upper:
            groups["Spine"].append(hostname)
        elif "LEAF" in name_upper:
            groups["Leaf"].append(hostname)
        elif "SERVICE" in name_upper:
            groups["Service"].append(hostname)
        elif "INTERNET" in name_upper or "INTER" in name_upper:
            groups["Internet"].append(hostname)
        elif info["type"] == "Ubuntu":
            groups["Server"].append(hostname)

        for conn in info["connections"]:
            remote = conn["remote_sys"]
            # Clean remote name (sometimes includes domain)
            remote = remote.split(".")[0]
            
            # Find the actual node if it exists in our list (case insensitive)
            actual_remote = None
            for h in nodes:
                if h.lower() == remote.lower() or h.lower().startswith(remote.lower()):
                    actual_remote = h
                    break
            
            if actual_remote:
                link = tuple(sorted([hostname, actual_remote]))
                if link not in seen_links:
                    seen_links.add(link)
                    mermaid.append(f"    {hostname} -- {conn['local_int']} --- {actual_remote}")

    # Add styling
    for group, members in groups.items():
        if members:
            # Replace characters for Mermaid IDs
            safe_members = [m.replace("-", "_") for m in members]
            # We'll just print them for now
            pass

    print("\n".join(mermaid))

    # Also output a textual summary
    print("\n\n" + "="*80)
    print("TOPOLOGY SUMMARY")
    print("="*80)
    for group, members in groups.items():
        if members:
            print(f"\n[{group}]")
            for m in members:
                print(f"  - {m} ({nodes[m]['ip']})")

if __name__ == "__main__":
    main()
