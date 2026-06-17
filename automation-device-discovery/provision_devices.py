import os
import json
from netmiko import ConnectHandler
from dotenv import load_dotenv

load_dotenv()

DEVICES = {
    "LAB-QFX10K8-GW-01": {"host": "10.116.0.64", "device_type": "juniper_junos"},
    "LAB_2BW11.18_SRX1500.STF.GW-N0": {"host": "10.116.0.96", "device_type": "juniper_junos"},
    "LAB-EX4400-01-VNPT": {"host": "10.116.0.54", "device_type": "juniper_junos"},
    "LAB-EX4400-TOR": {"host": "10.116.0.158", "device_type": "juniper_junos"},
    "LAB_2BW11.12_QFX5120-32C_STL.GW.02": {"host": "10.116.1.99", "device_type": "juniper_junos"},
    "LAB_2BW11.11_QFX5120-32C_STL.GW.01": {"host": "10.116.1.98", "device_type": "juniper_junos"},
    "LAB_2BW11.9_QFX5120-48Y_STL.GW.01": {"host": "10.116.1.150", "device_type": "juniper_junos"},
    "LAB_STL.GW.01": {"host": "10.116.0.37", "device_type": "juniper_junos"},
    "LAB_STL.GW.02": {"host": "10.116.0.38", "device_type": "juniper_junos"},
    "LAB_INTER.01": {"host": "10.116.0.22", "device_type": "juniper_junos"},
    "LAB_INTER.02": {"host": "10.116.0.23", "device_type": "juniper_junos"},
    "LAB_SERVICE.01": {"host": "10.116.0.24", "device_type": "juniper_junos"},
    "LAB_SERVICE.02": {"host": "10.116.0.25", "device_type": "juniper_junos"},
    "LAB_LEAF.01": {"host": "10.116.0.26", "device_type": "juniper_junos"},
    "LAB_LEAF.02": {"host": "10.116.0.27", "device_type": "juniper_junos"},
    "LAB_SPINE.01": {"host": "10.116.0.28", "device_type": "juniper_junos"},
    "LAB_SPINE.02": {"host": "10.116.0.29", "device_type": "juniper_junos"},
    "LAB_SUPER.01": {"host": "10.116.0.30", "device_type": "juniper_junos"},
    "LAB_SUPER.02": {"host": "10.116.0.31", "device_type": "juniper_junos"},
    "LAB_INTERNET.01": {"host": "10.116.0.32", "device_type": "juniper_junos"},
    "LAB_INTERNET.02": {"host": "10.116.0.33", "device_type": "juniper_junos"},
    "LAB.STF.GW.N0": {"host": "10.116.0.34", "device_type": "juniper_junos"},
}

USERNAME = os.getenv("NETWORK_USERNAME")
PASSWORD = os.getenv("NETWORK_PASSWORD")
MONITOR_IP = os.getenv("MONITOR_SERVER_IP", "10.116.0.1")

# Juniper Configuration Commands
CONFIG_COMMANDS = [
    "set snmp community public authorization read-only",
    f"set system syslog host {MONITOR_IP} any any",
    f"set protocols sflow collector {MONITOR_IP} udp-port 6343",
    "set protocols sflow polling-interval 20",
    "set protocols sflow sample-rate ingress 1000",
    "set protocols sflow sample-rate egress 1000",
    "set protocols sflow interfaces all",
]

def provision_device(name, details):
    device = {
        "device_type": details["device_type"],
        "host": details["host"],
        "username": USERNAME,
        "password": PASSWORD,
    }
    
    print(f"Connecting to {name} ({details['host']})...")
    try:
        with ConnectHandler(**device) as net_connect:
            net_connect.send_config_set(CONFIG_COMMANDS)
            net_connect.commit()
            print(f"Successfully configured {name}.")
    except Exception as e:
        print(f"Failed to configure {name}: {str(e)}")

if __name__ == "__main__":
    for name, details in DEVICES.items():
        provision_device(name, details)
