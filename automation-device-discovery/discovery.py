import subprocess
import concurrent.futures
from netmiko import ConnectHandler
import json
import socket

HOSTS = [
    "10.116.0.11", "10.116.0.13", "10.116.0.158", "10.116.0.175", "10.116.0.176",
    "10.116.0.20", "10.116.0.21", "10.116.0.22", "10.116.0.23", "10.116.0.24",
    "10.116.0.25", "10.116.0.26", "10.116.0.27", "10.116.0.28", "10.116.0.29",
    "10.116.0.30", "10.116.0.31", "10.116.0.32", "10.116.0.33", "10.116.0.34",
    "10.116.0.36", "10.116.0.37", "10.116.0.38", "10.116.0.54", "10.116.0.64",
    "10.116.0.96", "10.116.1.102", "10.116.1.103", "10.116.1.150", "10.116.1.151",
    "10.116.1.98", "10.116.1.99", "10.116.2.11", "10.116.2.13", "10.116.2.144",
    "10.116.2.145"
]

CREDS = [
    ("root", "vnd@123#"),
    ("thinhle", "thinhle@123#")
]
PORTS = [22, 8822, 9922]

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
    
    # Try TextFSM first for version
    try:
        version_out = net_connect.send_command("show version", use_textfsm=True)
        if isinstance(version_out, list) and len(version_out) > 0:
            data = version_out[0]
            hostname = data.get("hostname", "Unknown")
            model = data.get("model", "Unknown")
            os_ver = f"Junos {data.get('version') or data.get('junos_version') or 'Unknown'}"
    except Exception:
        pass
    
    # If still unknown, try manual parsing of the string output
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

    # Uptime parsing
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

def try_ssh(host, port, user, password):
    # Try as Juniper first
    device_params = {
        "device_type": "juniper_junos",
        "host": host,
        "username": user,
        "password": password,
        "port": port,
        "timeout": 10,
    }
    
    try:
        with ConnectHandler(**device_params) as net_connect:
            info = get_juniper_info(net_connect)
            info["access"] = f"{user}/{password} port {port}"
            info["type"] = "Juniper"
            return info
    except Exception:
        # Try as Linux
        device_params["device_type"] = "linux"
        try:
            with ConnectHandler(**device_params) as net_connect:
                info = get_linux_info(net_connect)
                info["access"] = f"{user}/{password} port {port}"
                info["type"] = "Ubuntu/Linux"
                return info
        except Exception:
            return None

def discover_host(host):
    if not ping_host(host):
        return {"host": host, "status": "No ICMP Response"}
    
    for port in PORTS:
        # Fast port check
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            for user, password in CREDS:
                info = try_ssh(host, port, user, password)
                if info:
                    info["host"] = host
                    info["status"] = "Success"
                    return info
    
    return {"host": host, "status": "ICMP OK, SSH Failed"}

def main():
    results = []
    print(f"Starting discovery on {len(HOSTS)} hosts...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_host = {executor.submit(discover_host, host): host for host in HOSTS}
        for future in concurrent.futures.as_completed(future_to_host):
            res = future.result()
            results.append(res)
            print(f"Finished {res['host']}: {res['status']}")

    print("\n" + "="*80)
    print(f"{'IP Address':<15} | {'Hostname':<20} | {'Type':<10} | {'OS':<20} | {'Status'}")
    print("-" * 80)
    for r in results:
        if r["status"] == "Success":
            print(f"{r['host']:<15} | {r.get('hostname', 'N/A'):<20} | {r.get('type', 'N/A'):<10} | {r.get('os', 'N/A'):<20} | {r['status']}")
        else:
            print(f"{r['host']:<15} | {'N/A':<20} | {'N/A':<10} | {'N/A':<20} | {r['status']}")

    with open("discovery_results.json", "w") as f:
        json.dump(results, f, indent=4)
    print("\nResults saved to discovery_results.json")

if __name__ == "__main__":
    main()
