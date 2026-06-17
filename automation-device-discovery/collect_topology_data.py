import json
from netmiko import ConnectHandler
import concurrent.futures
import re

def collect_juniper_data(device_info):
    host = device_info["host"]
    access = device_info["access"]
    hostname = device_info.get("hostname", "Unknown")
    
    try:
        parts = access.split()
        user_pass = parts[0].split("/")
        username = user_pass[0]
        password = user_pass[1]
        port = int(parts[2])
    except Exception as e:
        return {"host": host, "status": "Failed", "error": f"Access info error: {str(e)}"}

    device_params = {
        "device_type": "juniper_junos",
        "host": host,
        "username": username,
        "password": password,
        "port": port,
        "timeout": 30,
    }

    commands = {
        "lldp_neighbors": "show lldp neighbors",
        "interfaces_desc": "show interfaces descriptions",
        "interfaces_terse": "show interfaces terse",
        "bgp_neighbors": "show bgp neighbor"
    }

    data = {"host": host, "hostname": hostname, "type": "Juniper", "results": {}}
    
    print(f"Collecting data from {hostname} ({host})...")
    try:
        with ConnectHandler(**device_params) as net_connect:
            for key, cmd in commands.items():
                data["results"][key] = net_connect.send_command(cmd)
            return {"host": host, "status": "Success", "data": data}
    except Exception as e:
        return {"host": host, "status": "Failed", "error": str(e)}

def collect_ubuntu_data(device_info):
    host = device_info["host"]
    access = device_info["access"]
    hostname = device_info.get("hostname", "Unknown")
    
    try:
        parts = access.split()
        user_pass = parts[0].split("/")
        username = user_pass[0]
        password = user_pass[1]
        port = int(parts[2])
    except Exception as e:
        return {"host": host, "status": "Failed", "error": f"Access info error: {str(e)}"}

    device_params = {
        "device_type": "linux",
        "host": host,
        "username": username,
        "password": password,
        "port": port,
        "timeout": 30,
    }

    data = {"host": host, "hostname": hostname, "type": "Ubuntu", "results": {}}
    
    print(f"Collecting data from {hostname} ({host})...")
    try:
        with ConnectHandler(**device_params) as net_connect:
            # Get interfaces
            if_list = net_connect.send_command("ls /sys/class/net | grep -v lo").splitlines()
            lldp_results = {}
            for iface in if_list:
                iface = iface.strip()
                if iface:
                    lldp_results[iface] = net_connect.send_command(f"lldptool -t -i {iface} -V sysName -n")
            
            data["results"]["lldp_neighbors"] = lldp_results
            data["results"]["interfaces_terse"] = net_connect.send_command("ip addr")
            return {"host": host, "status": "Success", "data": data}
    except Exception as e:
        return {"host": host, "status": "Failed", "error": str(e)}

def main():
    try:
        with open("discovery_results.json", "r") as f:
            devices = json.load(f)
    except FileNotFoundError:
        print("Error: discovery_results.json not found.")
        return

    # Filter successful devices
    target_devices = [d for d in devices if d.get("status") == "Success"]
    
    all_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for d in target_devices:
            if d.get("type") == "Juniper":
                futures.append(executor.submit(collect_juniper_data, d))
            elif d.get("type") == "Ubuntu/Linux":
                futures.append(executor.submit(collect_ubuntu_data, d))
        
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res["status"] == "Success":
                all_data.append(res["data"])
            else:
                print(f"Failed to collect from {res['host']}: {res.get('error')}")

    with open("topology_raw_data.json", "w") as f:
        json.dump(all_data, f, indent=4)
    print(f"\nCollected data from {len(all_data)} devices. Saved to topology_raw_data.json")

if __name__ == "__main__":
    main()
