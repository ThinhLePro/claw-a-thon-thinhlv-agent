import json
import re

def parse_juniper_bgp(raw_bgp):
    peers = []
    # Simple regex to find peer IP and state
    matches = re.findall(r"Peer:\s+([\d\.]+)\+?\d*\s+AS\s+\d+\s+Local:\s+([\d\.]+)\+?\d*\s+AS\s+\d+", raw_bgp)
    # Also find description if available in 'show bgp neighbor' output
    # This might be tricky with raw text, but let's try to find 'Description: ...'
    for match in matches:
        peer_ip = match[0]
        local_ip = match[1]
        desc = "Unknown"
        desc_match = re.search(f"Peer: {re.escape(peer_ip)}.*?Description: (.*?)\n", raw_bgp, re.DOTALL)
        if desc_match:
            desc = desc_match.group(1).strip()
        peers.append({"peer_ip": peer_ip, "local_ip": local_ip, "description": desc})
    return peers

def parse_juniper_ips(raw_terse):
    ips = {}
    for line in raw_terse.splitlines():
        parts = line.split()
        if len(parts) >= 4 and "." in parts[3]:
            iface = parts[0]
            ip = parts[3].split("/")[0]
            ips[iface] = ip
    return ips

def main():
    with open("topology_raw_data.json", "r") as f:
        all_data = json.load(f)

    print("="*80)
    print(f"{'Hostname':<30} | {'BGP Peer':<15} | {'Description'}")
    print("-" * 80)

    for device in all_data:
        if device["type"] == "Juniper":
            hostname = device["hostname"]
            bgp_data = device["results"].get("bgp_neighbors", "")
            peers = parse_juniper_bgp(bgp_data)
            
            for p in peers:
                print(f"{hostname:<30} | {p['peer_ip']:<15} | {p['description']}")

    print("\n" + "="*80)
    print("LOGICAL TOPOLOGY (BGP PEERING)")
    print("="*80)
    
    mermaid_bgp = ["graph LR"]
    seen_bgp = set()
    
    # Map IPs to Hostnames for better visualization
    ip_to_host = {d["host"]: d["hostname"] for d in all_data}
    
    for device in all_data:
        if device["type"] == "Juniper":
            hostname = device["hostname"]
            bgp_data = device["results"].get("bgp_neighbors", "")
            peers = parse_juniper_bgp(bgp_data)
            for p in peers:
                peer_host = ip_to_host.get(p["peer_ip"], p["peer_ip"])
                link = tuple(sorted([hostname, peer_host]))
                if link not in seen_bgp:
                    seen_bgp.add(link)
                    mermaid_bgp.append(f"    {hostname} -- BGP --- {peer_host}")

    print("\n".join(mermaid_bgp))

if __name__ == "__main__":
    main()
