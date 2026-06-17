import subprocess
import concurrent.futures
from netmiko import ConnectHandler
import json
import socket

TARGET_DEVICES = [
    {"name": "LAB-LEAF-01", "ip": "10.116.0.158", "port": 830, "type": "Juniper"},
    {"name": "LAB_2BW14.30_QFX5210-64C_SPN.01", "ip": "10.116.1.102", "port": 830, "type": "Juniper"},
    {"name": "LAB_2BW14.27_QFX5210-64C_SPN.02", "ip": "10.116.1.103", "port": 830, "type": "Juniper"},
    {"name": "LAB_2BW11.11_QFX5120-32C_STL.GW.01", "ip": "10.116.1.98", "port": 22, "type": "Juniper"},
    {"name": "LAB_2BW11.12_QFX5120-32C_STL.GW.02", "ip": "10.116.1.99", "port": 830, "type": "Juniper"},
    {"name": "LAB-INTERNET-GATEWAY-01", "ip": "10.116.0.54", "port": 830, "type": "Juniper"},
    {"name": "noc-portal-app", "ip": "10.116.0.176", "port": 8822, "type": "Ubuntu/Linux"},
    {"name": "net-monitor", "ip": "10.116.0.175", "port": 8822, "type": "Ubuntu/Linux"}
]

CREDS = [
    ("root", "vnd@123#"),
    ("thinhle", "thinhle@123#")
]

def ping_host(host):
    try:
        subprocess.check_output(["ping", "-c", "1", "-W", "1", host])
        return True
    except subprocess.CalledProcessError:
        return False

def get_juniper_info(net_connect):
    hostname = "Unknown"
    model = "Unknown"
    os_ver = "Unknown"
    uptime = "Unknown"
    
    try:
        version_out = net_connect.send_command("show version", use_textfsm=True)
        if isinstance(version_out, list) and len(version_out) > 0:
            data = version_out[0]
            hostname = data.get("hostname", "Unknown")
            model = data.get("model", "Unknown")
            os_ver = f"Junos {data.get('version') or data.get('junos_version') or 'Unknown'}"
    except Exception:
        pass
    
    if hostname == "Unknown" or model == "Unknown" or os_ver == "Junos Unknown":
        try:
            raw_version = net_connect.send_command("show version")
            for line in raw_version.splitlines():
                if "Hostname:" in line:
                    hostname = line.split(":", 1)[1].strip()
                elif "Model:" in line:
                    model = line.split(":", 1)[1].strip()
                elif "Junos:" in line:
                    os_ver = "Junos " + line.split("Junos:", 1)[1].strip()
        except Exception:
            pass

    try:
        uptime_out = net_connect.send_command("show system uptime")
        if isinstance(uptime_out, str):
            for line in uptime_out.splitlines():
                 if "System booted" in line:
                     uptime = line.strip()
                     break
                 elif "up " in line:
                     uptime = line.strip()
                     break
    except Exception:
        pass

    return {
        "hostname": hostname,
        "model": model,
        "os": os_ver,
        "uptime": uptime
    }

def get_linux_info(net_connect):
    try:
        hostname = net_connect.send_command("hostname").strip()
        os_out = net_connect.send_command("grep PRETTY_NAME /etc/os-release").strip()
        os_ver = os_out.split("=")[1].strip('"') if "=" in os_out else "Linux"
        uptime = net_connect.send_command("uptime -p").strip()
        model = net_connect.send_command("cat /sys/class/dmi/id/product_name 2>/dev/null || echo 'Virtual Machine'").strip()
        
        return {
            "hostname": hostname,
            "model": model,
            "os": os_ver,
            "uptime": uptime
        }
    except Exception as e:
        return {"error": str(e)}

def discover_device(device):
    host = device["ip"]
    primary_port = device["port"]
    dev_type = device["type"]
    
    ports_to_try = [primary_port]
    if dev_type == "Juniper" and 22 not in ports_to_try:
        ports_to_try.append(22)
    elif dev_type == "Ubuntu/Linux":
        if 8822 not in ports_to_try: ports_to_try.append(8822)
        if 9922 not in ports_to_try: ports_to_try.append(9922)
        if 22 not in ports_to_try: ports_to_try.append(22)

    if not ping_host(host):
        return {"host": host, "status": "No ICMP Response"}
    
    for port in ports_to_try:
        # Fast port check
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result != 0:
            continue

        for user, password in CREDS:
            device_params = {
                "device_type": "juniper_junos" if dev_type == "Juniper" else "linux",
                "host": host,
                "username": user,
                "password": password,
                "port": port,
                "timeout": 15,
            }
            
            try:
                with ConnectHandler(**device_params) as net_connect:
                    if dev_type == "Juniper":
                        info = get_juniper_info(net_connect)
                    else:
                        info = get_linux_info(net_connect)
                    
                    info["access"] = f"{user}/{password} port {port}"
                    info["type"] = "Juniper" if dev_type == "Juniper" else "Ubuntu/Linux"
                    info["host"] = host
                    info["status"] = "Success"
                    return info
            except Exception:
                continue
    
    return {"host": host, "status": "Failed to connect (all ports/creds)"}

def main():
    results = []
    print(f"Starting targeted discovery on {len(TARGET_DEVICES)} devices...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_device = {executor.submit(discover_device, d): d for d in TARGET_DEVICES}
        for future in concurrent.futures.as_completed(future_to_device):
            res = future.result()
            results.append(res)
            print(f"Finished {res['host']}: {res['status']}")

    with open("re_discovery_results.json", "w") as f:
        json.dump(results, f, indent=4)
    print("\nResults saved to re_discovery_results.json")

if __name__ == "__main__":
    main()
