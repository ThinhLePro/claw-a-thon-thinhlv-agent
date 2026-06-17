import json
from netmiko import ConnectHandler
import concurrent.futures

def configure_lldp_ubuntu(device_info):
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
        "device_type": "linux",
        "host": host,
        "username": username,
        "password": password,
        "port": port,
        "timeout": 30,
    }

    print(f"Connecting to {host} ({device_info.get('hostname', 'Unknown')})...")
    try:
        with ConnectHandler(**device_params) as net_connect:
            print(f"[{host}] Installing lldpad...")
            # Use -y to avoid interactive prompts, and DEBIAN_FRONTEND=noninteractive
            install_cmd = "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y lldpad"
            net_connect.send_command(install_cmd, expect_string=r"[:#\$]")
            
            print(f"[{host}] Starting lldpad service...")
            net_connect.send_command("systemctl start lldpad && systemctl enable lldpad", expect_string=r"[:#\$]")
            
            print(f"[{host}] Enabling LLDP on interfaces...")
            # Get list of interfaces excluding loopback and virtual ones if possible
            interfaces_raw = net_connect.send_command("ls /sys/class/net | grep -v lo", expect_string=r"[:#\$]")
            interfaces = [i.strip() for i in interfaces_raw.splitlines() if i.strip()]
            
            for iface in interfaces:
                print(f"[{host}]  - Configuring {iface}")
                net_connect.send_command(f"lldptool set-lldp -i {iface} adminStatus=rxtx", expect_string=r"[:#\$]")
                # Enable basic TLVs
                net_connect.send_command(f"lldptool -T -i {iface} -V sysName enableTx=yes", expect_string=r"[:#\$]")
                net_connect.send_command(f"lldptool -T -i {iface} -V portDesc enableTx=yes", expect_string=r"[:#\$]")
                net_connect.send_command(f"lldptool -T -i {iface} -V sysDesc enableTx=yes", expect_string=r"[:#\$]")

            return {
                "host": host, 
                "hostname": device_info.get('hostname', 'Unknown'),
                "status": "Success", 
                "details": f"Configured {len(interfaces)} interfaces"
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

    # Filter only successful Ubuntu devices
    ubuntu_devices = [d for d in devices if d.get("status") == "Success" and d.get("type") == "Ubuntu/Linux"]
    
    if not ubuntu_devices:
        print("No Ubuntu devices found to configure.")
        return

    print(f"Starting LLDP configuration on {len(ubuntu_devices)} Ubuntu servers...")
    
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_device = {executor.submit(configure_lldp_ubuntu, d): d for d in ubuntu_devices}
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
