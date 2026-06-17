import json
from netmiko import ConnectHandler
import concurrent.futures

def configure_lldp_juniper(device_info):
    host = device_info["host"]
    access = device_info["access"]
    
    # Parse access info: "user/pass port port_num"
    try:
        parts = access.split()
        user_pass = parts[0].split("/")
        username = user_pass[0]
        password = user_pass[1]
        port = int(parts[2])
    except Exception as e:
        return {"host": host, "status": "Failed", "error": f"Could not parse access info: {str(e)}"}

    device_params = {
        "device_type": "juniper_junos",
        "host": host,
        "username": username,
        "password": password,
        "port": port,
        "timeout": 20,
    }

    config_commands = [
        "set protocols lldp interface all",
        "set protocols lldp-med interface all"
    ]

    print(f"Connecting to {host} ({device_info.get('hostname', 'Unknown')})...")
    try:
        with ConnectHandler(**device_params) as net_connect:
            output = net_connect.send_config_set(config_commands)
            commit_output = net_connect.commit()
            return {
                "host": host, 
                "hostname": device_info.get('hostname', 'Unknown'),
                "status": "Success", 
                "details": commit_output
            }
    except Exception as e:
        return {
            "host": host, 
            "hostname": device_info.get('hostname', 'Unknown'),
            "status": "Failed", 
            "error": str(e)
        }

def main():
    try:
        with open("discovery_results.json", "r") as f:
            devices = json.load(f)
    except FileNotFoundError:
        print("Error: discovery_results.json not found. Please run discovery first.")
        return

    # Filter only successful Juniper devices
    juniper_devices = [d for d in devices if d.get("status") == "Success" and d.get("type") == "Juniper"]
    
    if not juniper_devices:
        print("No Juniper devices found to configure.")
        return

    print(f"Starting LLDP configuration on {len(juniper_devices)} Juniper devices...")
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_device = {executor.submit(configure_lldp_juniper, d): d for d in juniper_devices}
        for future in concurrent.futures.as_completed(future_to_device):
            res = future.result()
            results.append(res)
            print(f"Finished {res['host']} ({res.get('hostname', 'N/A')}): {res['status']}")

    print("\n" + "="*80)
    print(f"{'IP Address':<15} | {'Hostname':<30} | {'Status'}")
    print("-" * 80)
    for r in results:
        print(f"{r['host']:<15} | {r.get('hostname', 'N/A'):<30} | {r['status']}")

if __name__ == "__main__":
    main()
