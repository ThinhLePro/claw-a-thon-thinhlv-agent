import sys
import json
import logging

logging.basicConfig(level=logging.INFO)

# Add parent dir /app to path so we can import mcp_server
sys.path.append("/app")

import mcp_server

def run_test():
    print("=== Testing Arista Integration in MCP ===")
    
    # 1. Test get_devices_list
    print("\n--- Testing get_devices_list ---")
    print(mcp_server.get_devices_list())
    
    # Target Arista device
    arista_device = "LAB-ARISTA-01"  # Or "10.116.1.104"
    
    # 2. Test get_device_detail
    print(f"\n--- Testing get_device_detail for {arista_device} ---")
    try:
        print(mcp_server.get_device_detail(arista_device))
    except Exception as e:
        print(f"Error: {e}")
        
    # 3. Test execute_device_command
    print(f"\n--- Testing execute_device_command (show version) for {arista_device} ---")
    try:
        print(mcp_server.execute_device_command(arista_device, "show version"))
    except Exception as e:
        print(f"Error: {e}")

    # 4. Test get_device_hardware
    print(f"\n--- Testing get_device_hardware for {arista_device} ---")
    try:
        print(mcp_server.get_device_hardware(arista_device))
    except Exception as e:
        print(f"Error: {e}")

    # 5. Test get_device_config
    print(f"\n--- Testing get_device_config (active) for {arista_device} ---")
    try:
        print(mcp_server.get_device_config(arista_device, "active"))
    except Exception as e:
        print(f"Error: {e}")

    # 6. Test ping_from_device
    print(f"\n--- Testing ping_from_device to 10.116.1.105 for {arista_device} ---")
    try:
        print(mcp_server.ping_from_device(arista_device, "10.116.1.105", count=3))
    except Exception as e:
        print(f"Error: {e}")

    # 7. Test check_device_alarms
    print(f"\n--- Testing check_device_alarms for {arista_device} ---")
    try:
        print(mcp_server.check_device_alarms(arista_device))
    except Exception as e:
        print(f"Error: {e}")

    # 8. Test get_interface_diagnostics
    print(f"\n--- Testing get_interface_diagnostics (Ethernet1) for {arista_device} ---")
    try:
        print(mcp_server.get_interface_diagnostics(arista_device, "Ethernet1"))
    except Exception as e:
        print(f"Error: {e}")

    # 9. Test get_commit_history (shows configuration sessions)
    print(f"\n--- Testing get_commit_history for {arista_device} ---")
    try:
        print(mcp_server.get_commit_history(arista_device))
    except Exception as e:
        print(f"Error: {e}")

    # 10. Test get_network_topology
    print("\n--- Testing get_network_topology ---")
    try:
        print(mcp_server.get_network_topology())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_test()
