import sys
import asyncio
import json

# Add parent directory to path so we can import from mcp_server
sys.path.append("/app")

try:
    import mcp_server
    print("Successfully imported mcp_server module.")
except Exception as e:
    print(f"Error importing mcp_server: {e}")
    sys.exit(1)

async def test_tools():
    # 1. Test get_devices_list
    print("\n--- Testing get_devices_list ---")
    try:
        devices_list_str = mcp_server.get_devices_list()
        devices = json.loads(devices_list_str)
        print("Devices list parsed successfully. Devices count:", len(devices))
        for d in devices:
            print(f"- {d['name']} ({d['ip']}) - Role: {d['role']}")
    except Exception as e:
        print(f"Error in get_devices_list: {e}")

    # 2. Test get_device_detail on SPN.02
    target_device = "LAB_2BW14.27_QFX5210-64C_SPN.02"
    print(f"\n--- Testing get_device_detail for {target_device} ---")
    try:
        detail_str = mcp_server.get_device_detail(target_device)
        print("Device details returned:")
        print(detail_str)
    except Exception as e:
        print(f"Error in get_device_detail: {e}")

    # 3. Test ping_from_device from SPN.02 to local gateway (10.116.0.181 or 127.0.0.1)
    print(f"\n--- Testing ping_from_device from {target_device} ---")
    try:
        ping_res = mcp_server.ping_from_device(target_device, destination="10.116.0.181", count=3)
        print("Ping result:")
        print(ping_res)
    except Exception as e:
        print(f"Error in ping_from_device: {e}")

    # 4. Test get_device_config (active) from SPN.02
    print(f"\n--- Testing get_device_config (active) for {target_device} ---")
    try:
        # Limit config return to first 30 lines for check
        config_res = mcp_server.get_device_config(target_device, config_type="active")
        lines = config_res.split("\n")
        print(f"Config retrieved successfully ({len(lines)} lines). First 15 lines:")
        print("\n".join(lines[:15]))
    except Exception as e:
        print(f"Error in get_device_config: {e}")

if __name__ == "__main__":
    asyncio.run(test_tools())
