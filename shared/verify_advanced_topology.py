import sys
import asyncio

# Add parent directory to path so we can import from mcp_server
sys.path.append("/app")

try:
    import mcp_server
    print("Successfully imported mcp_server module.")
except Exception as e:
    print(f"Error importing mcp_server: {e}")
    sys.exit(1)

async def test_topology():
    print("\n--- Testing get_network_topology (Parallel Discovery) ---")
    try:
        # Call the tool
        report = mcp_server.get_network_topology()
        print("Topology Report:")
        print("=" * 80)
        print(report)
        print("=" * 80)
    except Exception as e:
        print(f"Error in get_network_topology: {e}")

if __name__ == "__main__":
    asyncio.run(test_topology())
