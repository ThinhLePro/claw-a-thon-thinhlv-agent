import json
import re

def parse_juniper_lldp(raw_lldp):
    connections = []
    lines = raw_lldp.splitlines()
    for line in lines:
        if "Local Interface" in line or "---" in line or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 3:
            local_int = parts[0]
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
    try:
        with open("re_topology_raw_data.json", "r") as f:
            all_data = json.load(f)
    except FileNotFoundError:
        print("Error: re_topology_raw_data.json not found.")
        return

    print("# DEVICE INSPECTION REPORT\n")
    
    for device in all_data:
        hostname = device["hostname"]
        host = device["host"]
        dtype = device["type"]
        results = device["results"]
        
        print(f"## {hostname} ({host})")
        print(f"- **Type:** {dtype}")
        
        if dtype == "Juniper":
            # Extract basic info from results if needed, but we already have it in discovery
            # For now, let's show connections and BGP status
            print("- **LLDP Neighbors:**")
            connections = parse_juniper_lldp(results.get("lldp_neighbors", ""))
            if connections:
                for c in connections:
                    print(f"  - {c['local_int']} -> {c['remote_sys']}")
            else:
                print("  - None")
            
            print("- **BGP Summary Snippet:**")
            bgp_sum = results.get("bgp_summary", "")
            # Just show first few lines or relevant lines
            lines = bgp_sum.splitlines()
            for line in lines[:10]:
                print(f"    {line}")
            if len(lines) > 10:
                print("    ...")

        else:
            print("- **LLDP Neighbors:**")
            connections = parse_ubuntu_lldp(results.get("lldp_neighbors", {}))
            if connections:
                for c in connections:
                    print(f"  - {c['local_int']} -> {c['remote_sys']}")
            else:
                print("  - None")
            
            print("- **IP Route Snippet:**")
            ip_route = results.get("ip_route", "")
            lines = ip_route.splitlines()
            for line in lines[:5]:
                print(f"    {line}")

        print("\n" + "-"*40 + "\n")

if __name__ == "__main__":
    main()
