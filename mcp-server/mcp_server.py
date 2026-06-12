import os
import json
import logging
import httpx
from typing import Optional
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from jnpr.junos import Device
from jnpr.junos.utils.config import Config
from lxml import etree

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-server")

# --- Configuration from environment ---
NETCONF_USER = os.environ.get("NETCONF_USER", "network-agent")
NETCONF_PASSWORD = os.environ.get("NETCONF_PASSWORD", "")
MCP_PORT = int(os.environ.get("MCP_PORT", "8000"))
DEVICES_FILE = os.environ.get("DEVICES_FILE", "/app/shared/devices.json")

# Monitoring configurations (Prometheus & Loki)
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100")

if not NETCONF_PASSWORD:
    raise ValueError(
        "NETCONF_PASSWORD environment variable is required. "
        "Set it in your .env file or pass via docker-compose."
    )

# --- Load device inventory from shared JSON file ---
def load_device_map(filepath: str) -> dict:
    """Load device inventory from a JSON file.

    Returns a dict of {device_name: {ip, port, model}} suitable for NETCONF connections.
    """
    logger.info(f"Loading device inventory from {filepath}...")
    with open(filepath, "r") as f:
        data = json.load(f)

    devices = data.get("devices", data)
    device_map = {}
    for name, info in devices.items():
        device_map[name] = {
            "ip": info["ip"],
            "port": info.get("port", 830),
            "model": info.get("model", "Unknown"),
        }
    logger.info(f"Loaded {len(device_map)} devices from {filepath}")
    return device_map


import threading
import time
import subprocess
import shlex

DEVICE_MAP = load_device_map(DEVICES_FILE)


def connect_device(device_name: str) -> Device:
    """Resolve and open a connection to the specified Junos device."""
    # Resolve device_name (by hostname or IP)
    device_info = None
    if device_name in DEVICE_MAP:
        device_info = DEVICE_MAP[device_name]
    else:
        # Check by IP
        for hostname, info in DEVICE_MAP.items():
            if info["ip"] == device_name:
                device_info = info
                break

    if not device_info:
        raise ValueError(f"Device '{device_name}' is not registered in the database.")

    ip = device_info["ip"]
    port = device_info["port"]

    logger.info(f"Connecting to device {device_name} ({ip}:{port}) via Netconf...")
    dev = Device(
        host=ip,
        user=NETCONF_USER,
        passwd=NETCONF_PASSWORD,
        port=port,
        huge_tree=True,
        conn_open_timeout=15
    )
    dev.open()
    return dev


class DeviceConnectionPool:
    """Thread-safe NETCONF connection pool with TTL-based expiry."""

    def __init__(self, ttl_seconds: int = 300, max_connections: int = 20):
        self._pool: dict[str, tuple[Device, float]] = {}  # {device_name: (device, last_used)}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_connections
        # Background cleanup thread
        self._cleaner = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleaner.start()

    def get(self, device_name: str) -> Device:
        """Get a connected device from pool, or create new connection."""
        resolved_name = self._resolve_hostname(device_name)
        
        with self._lock:
            if resolved_name in self._pool:
                dev, _ = self._pool[resolved_name]
                try:
                    if dev.connected:
                        logger.info(f"Reusing existing connection to {resolved_name} from pool.")
                        self._pool[resolved_name] = (dev, time.time())
                        return dev
                except Exception:
                    pass
                logger.info(f"Connection for {resolved_name} is stale/disconnected. Reconnecting...")
                try:
                    dev.close()
                except Exception:
                    pass
                del self._pool[resolved_name]

            # Connect new device
            dev = connect_device(resolved_name)
            self._pool[resolved_name] = (dev, time.time())
            return dev

    def _resolve_hostname(self, device_name: str) -> str:
        """Normalize device name to the configured hostname in DEVICE_MAP."""
        if device_name in DEVICE_MAP:
            return device_name
        # Check by IP
        for hostname, info in DEVICE_MAP.items():
            if info["ip"] == device_name:
                return hostname
        return device_name

    def close_all_except(self, active_names: set[str]):
        """Close connections for any devices not in active_names (used on reload)."""
        with self._lock:
            to_remove = []
            for name, (dev, _) in self._pool.items():
                if name not in active_names:
                    logger.info(f"Closing pooled connection for removed/unregistered device {name}")
                    try:
                        dev.close()
                    except Exception as e:
                        logger.warning(f"Error closing connection for {name}: {e}")
                    to_remove.append(name)
            for name in to_remove:
                del self._pool[name]

    def _cleanup_loop(self):
        """Periodically close expired connections."""
        while True:
            time.sleep(60)
            now = time.time()
            with self._lock:
                expired = [
                    name for name, (dev, ts) in self._pool.items()
                    if now - ts > self._ttl
                ]
                for name in expired:
                    logger.info(f"TTL expired for connection to {name}. Closing connection.")
                    dev, _ = self._pool.pop(name)
                    try:
                        dev.close()
                    except Exception as e:
                        logger.warning(f"Error closing expired connection for {name}: {e}")


pool = DeviceConnectionPool()

# Create FastMCP Server with SSE enabled
# Bind to all interfaces (0.0.0.0)
# Disable DNS rebinding protection and allow all hosts/origins to permit GreenNode Agent calls
ts = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
    allowed_hosts=["*"],
    allowed_origins=["*"]
)

mcp = FastMCP(
    "network-devices-mcp",
    host="0.0.0.0",
    port=MCP_PORT,
    transport_security=ts
)

@mcp.tool()
def get_devices_list() -> str:
    """Get the list of all registered datacenter devices and their static profile.

    Returns:
        A formatted list of device names, IP addresses, models, and Netconf ports.
    """
    logger.info("Executing tool: get_devices_list")
    result = ["Registered Datacenter Devices:"]
    for d_name, d_info in DEVICE_MAP.items():
        result.append(
            f"- Hostname: {d_name} | IP: {d_info.get('ip')} | Model: {d_info.get('model')} | Port: {d_info.get('port')}"
        )
    return "\n".join(result)


@mcp.tool()
def reload_devices() -> str:
    """Reload device inventory from the shared devices.json file.
    Use this after updating the device inventory file to pick up new or removed devices.

    Returns:
        Summary of loaded devices after reload.
    """
    global DEVICE_MAP
    logger.info("Reloading device inventory...")
    try:
        DEVICE_MAP = load_device_map(DEVICES_FILE)
        # Clear connection pool for removed devices
        pool.close_all_except(set(DEVICE_MAP.keys()))
        names = ", ".join(DEVICE_MAP.keys())
        return f"Reloaded successfully. {len(DEVICE_MAP)} devices: {names}"
    except Exception as e:
        return f"Error reloading devices: {e}"
@mcp.tool()
def get_device_detail(device_name: str) -> str:
    """Get the live detailed facts and system specifications of a specific device.

    Args:
        device_name: The name of the device or its IP address.
    """
    logger.info(f"Executing tool: get_device_detail for {device_name}")
    try:
        dev = pool.get(device_name)
        facts = dev.facts

        details = [
            f"Device Details for {facts.get('hostname', device_name)} (Live Facts):",
            f"  IP Address: {facts.get('fqdn') or dev.hostname}",
            f"  Model:      {facts.get('model')}",
            f"  OS Version: {facts.get('version')}",
            f"  Serial:     {facts.get('serialnumber')}",
            f"  Uptime:     {facts.get('uptime')}",
            f"  Host ID:    {facts.get('host_id')}",
            f"  Virtual:    {facts.get('virtual')}",
            f"  RE0 Uptime: {facts.get('re0_uptime') or 'N/A'}"
        ]
        return "\n".join(details)
    except Exception as e:
        logger.error(f"Failed to get device detail: {e}")
        return f"Error connecting to device '{device_name}': {e}"

@mcp.tool()
def get_device_configuration_list(device_name: str) -> str:
    """Get the configuration commit history of a specific device.

    Args:
        device_name: The name of the device or its IP address.
    """
    logger.info(f"Executing tool: get_device_configuration_list for {device_name}")
    try:
        dev = pool.get(device_name)
        res = dev.rpc.get_commit_information()

        commits = res.findall('commit-history')
        if not commits:
            return f"No configuration commits found for device '{device_name}'."

        result = [f"Commit History for {device_name} (Last 10 commits):"]
        for c in commits[:10]:
            seq = c.findtext('sequence-number')
            user = c.findtext('user')
            date = c.findtext('date-time')
            comment = c.findtext('comment') or c.findtext('log') or "No comment"
            result.append(f"- Commit #{seq} | User: {user} | Date: {date} | Comment: {comment}")

        return "\n".join(result)
    except Exception as e:
        logger.error(f"Failed to get configuration list: {e}")
        return f"Error connecting to device '{device_name}': {e}"

@mcp.tool()
def get_device_configuration_detail(device_name: str, config_type: str = "active") -> str:
    """Get the configuration details of a specific device (optionally filter to a specific hierarchy).

    Args:
        device_name: The name of the device or its IP address.
        config_type: Hierarchy block to filter config (e.g. 'interfaces', 'protocols bgp', 'policy-options'). Defaults to 'active' (entire config).
    """
    logger.info(f"Executing tool: get_device_configuration_detail for {device_name} (filter: {config_type})")
    try:
        dev = pool.get(device_name)

        # Build XML filter if hierarchy block path is specified
        filter_xml = None
        if config_type and config_type.lower() != "active":
            parts = config_type.strip().split()
            xml_str = ""
            for p in reversed(parts):
                if not xml_str:
                    xml_str = f"<{p}/>"
                else:
                    xml_str = f"<{p}>{xml_str}</{p}>"
            xml_filter_str = f"<configuration>{xml_str}</configuration>"
            logger.info(f"Applying XML filter: {xml_filter_str}")
            filter_xml = etree.XML(xml_filter_str)

        # Get configuration
        config_res = dev.rpc.get_config(filter_xml=filter_xml, options={'format': 'text'})
        content = config_res.text if config_res.text else config_res.findtext('configuration-output')

        if not content:
            return f"No configuration found on {device_name} matching filter '{config_type}'."

        # Truncate if too large for LLM safety
        MAX_LEN = 100000
        if len(content) > MAX_LEN:
            truncated = content[:MAX_LEN]
            return (
                f"--- Active Configuration for {device_name} (Truncated - first {MAX_LEN} chars) ---\n"
                f"{truncated}\n\n"
                f"... [TRUNCATED due to length ({len(content)} chars). "
                f"Please pass a specific hierarchy like 'interfaces' or 'protocols bgp' in config_type parameter to view specific parts.]"
            )

        return f"--- Configuration for {device_name} (filter: '{config_type}') ---\n{content}"
    except Exception as e:
        logger.error(f"Failed to get configuration detail: {e}")
        return f"Error retrieving config from device '{device_name}': {e}"

@mcp.tool()
def get_device_operation_list(device_name: str) -> str:
    """Get the suggested list of operational commands/queries supported by the device.

    Args:
        device_name: The name of the device or its IP address.
    """
    logger.info(f"Executing tool: get_device_operation_list for {device_name}")
    # Show standard operational queries Junos supports
    queries = [
        "show interfaces terse",
        "show route",
        "show bgp summary",
        "show ospf neighbor",
        "show lldp neighbors",
        "show chassis hardware"
    ]
    return f"Suggested Operational Commands for {device_name}:\n" + "\n".join(f"- {q}" for q in queries)

@mcp.tool()
def get_device_operation_detail(device_name: str, query_type: str) -> str:
    """Get the live operational command output of a device.

    Args:
        device_name: The name of the device or its IP address.
        query_type: The operational CLI command to execute (e.g., 'show interfaces terse', 'show bgp summary').
    """
    logger.info(f"Executing tool: get_device_operation_detail for {device_name} (command: {query_type})")
    try:
        dev = pool.get(device_name)

        # Run CLI command RPC
        res = dev.rpc.cli(query_type, format='text')
        content = res.text if res.text else res.findtext('cli-out')

        # If it returned XML instead, serialize it
        if not content and isinstance(res, etree._Element):
            content = etree.tostring(res, pretty_print=True, encoding='utf-8').decode('utf-8')

        if not content:
            return f"No output returned by command '{query_type}' on {device_name}."

        # Truncate if too large
        MAX_LEN = 100000
        if len(content) > MAX_LEN:
            truncated = content[:MAX_LEN]
            return (
                f"--- Operational State: {device_name} [{query_type}] (Truncated) ---\n"
                f"{truncated}\n\n"
                f"... [TRUNCATED due to length ({len(content)} chars)]"
            )

        return f"--- Operational State: {device_name} [{query_type}] ---\n{content}"
    except Exception as e:
        logger.error(f"Failed to execute operational query: {e}")
        return f"Error executing command '{query_type}' on '{device_name}': {e}"

@mcp.tool()
def edit_device_configuration(device_name: str, configuration_snippet: str, description: str = "") -> str:
    """Safely apply and commit configuration changes to a device.

    Args:
        device_name: The name of the device or its IP address.
        configuration_snippet: The configuration commands to apply (set commands or curly-braces config format).
        description: A short description for the commit log.
    """
    logger.info(f"Executing tool: edit_device_configuration for {device_name}")
    try:
        dev = pool.get(device_name)
        cu = Config(dev)

        # Determine format (set vs text)
        is_set = any(line.strip().startswith(("set", "delete")) for line in configuration_snippet.split("\n"))
        fmt = "set" if is_set else "text"

        logger.info(f"Loading configuration (format: {fmt})...")

        # Lock, load, check, commit and unlock
        cu.lock()
        try:
            cu.load(configuration_snippet, format=fmt)
            logger.info("Running commit check...")
            cu.commit(check=True)
            logger.info("Commit check succeeded! Committing...")
            cu.commit(comment=description or "Configured via MCP Agent")
            cu.unlock()
            return f"Success: Configuration applied and committed successfully to '{device_name}'."
        except Exception as load_err:
            logger.warning("Configuration commit check failed. Rolling back changes...")
            try:
                cu.rollback()
            except Exception:
                pass
            try:
                cu.unlock()
            except Exception:
                pass
            raise load_err

    except Exception as e:
        logger.error(f"Failed to edit device configuration: {e}")
        return f"Error applying configuration to device '{device_name}': {e}"

@mcp.tool()
def get_device_hardware(device_name: str) -> str:
    """Get the detailed chassis hardware inventory of a specific device.

    Args:
        device_name: The name of the device or its IP address.
    """
    logger.info(f"Executing tool: get_device_hardware for {device_name}")
    try:
        dev = pool.get(device_name)
        res = dev.rpc.get_chassis_inventory()
        chassis = res.find('chassis')
        if chassis is None:
            return f"No chassis inventory found for device '{device_name}'."

        serial = chassis.findtext('serial-number') or "N/A"
        desc = chassis.findtext('description') or "N/A"
        result = [f"Chassis: {desc} | Serial: {serial}"]

        # Simple recursive function to find all sub-modules
        def parse_module(module, depth=1):
            indent = "  " * depth
            name = module.findtext('name') or "Unknown Module"
            part = module.findtext('part-number') or "N/A"
            serial = module.findtext('serial-number') or "N/A"
            desc = module.findtext('description') or "N/A"
            result.append(f"{indent}- {name} | Description: {desc} | Part: {part} | Serial: {serial}")
            for sub in module.findall('chassis-sub-module'):
                parse_module(sub, depth + 1)
            for sub_sub in module.findall('chassis-sub-sub-module'):
                parse_module(sub_sub, depth + 2)

        for mod in res.findall('.//chassis-module'):
            parse_module(mod)

        return f"Hardware Inventory for {device_name}:\n" + "\n".join(result)
    except Exception as e:
        logger.error(f"Failed to get device hardware: {e}")
        return f"Error retrieving hardware for device '{device_name}': {e}"

@mcp.tool()
def get_network_topology() -> str:
    """Discover the network topology by querying LLDP neighbors on all active devices.

    Returns:
        A formatted topology connection list/graph showing connected switch ports.
    """
    logger.info("Executing tool: get_network_topology")
    topology_links = []
    errors = []

    for name, info in DEVICE_MAP.items():
        try:
            logger.info(f"Topology query: connecting to {name}...")
            dev = pool.get(name)
            lldp_xml = dev.rpc.get_lldp_neighbors_information()
            neighbors = lldp_xml.findall('.//lldp-neighbor-information')

            for n in neighbors:
                local_port = n.findtext('lldp-local-port-id') or n.findtext('lldp-local-interface')
                remote_sys = n.findtext('lldp-remote-system-name')
                remote_port = n.findtext('lldp-remote-port-id') or n.findtext('lldp-remote-interface')

                if remote_sys:
                    topology_links.append({
                        "source": name,
                        "source_port": local_port,
                        "target": remote_sys,
                        "target_port": remote_port
                    })
        except Exception as e:
            logger.warning(f"Failed to get LLDP neighbors for {name}: {e}")
            errors.append(f"{name}: {e}")

    if not topology_links:
        return f"Failed to discover topology. Errors: {'; '.join(errors)}"

    # Deduplicate bidirectional links (A-B and B-A are the same edge)
    seen_links = set()
    unique_links = []
    for link in topology_links:
        edge = tuple(sorted([
            (link["source"], link["source_port"]),
            (link["target"], link["target_port"])
        ]))
        if edge not in seen_links:
            seen_links.add(edge)
            unique_links.append(link)

    result = ["Live Datacenter Network Topology (Discovered via LLDP):", ""]
    result.append("Connections:")
    for link in unique_links:
        result.append(f"  {link['source']} [{link['source_port']}] <---> {link['target']} [{link['target_port']}]")

    if errors:
        result.append("")
        result.append("Warning: Could not contact some devices:")
        for err in errors:
            result.append(f"  - {err}")

    return "\n".join(result)

# --- Phase 3: Enhanced Diagnostic Tools ---

@mcp.tool()
def ping_from_device(device_name: str, destination: str, count: int = 5) -> str:
    """Execute ping from a network device to a destination IP/hostname.

    Args:
        device_name: Source device name.
        destination: Target IP or hostname to ping.
        count: Number of ping packets (default 5).
    """
    logger.info(f"Executing tool: ping_from_device from {device_name} to {destination}")
    try:
        dev = pool.get(device_name)
        res = dev.rpc.cli(f"ping {destination} count {count} rapid", format='text')
        content = res.text or res.findtext('cli-out') or "No output"
        return f"--- Ping from {device_name} to {destination} ---\n{content}"
    except Exception as e:
        logger.error(f"Failed to execute ping: {e}")
        return f"Error executing ping from '{device_name}' to '{destination}': {e}"


@mcp.tool()
def compare_device_configs(device_name: str, rollback_index: int = 1) -> str:
    """Compare current config with a previous rollback version.

    Args:
        device_name: Device name.
        rollback_index: Rollback index to compare against (default 1 = previous commit).
    """
    logger.info(f"Executing tool: compare_device_configs for {device_name} (rollback {rollback_index})")
    try:
        dev = pool.get(device_name)
        res = dev.rpc.cli(f"show configuration | compare rollback {rollback_index}", format='text')
        content = res.text or res.findtext('cli-out') or "No differences found"
        return f"--- Config Diff ({device_name}: current vs rollback {rollback_index}) ---\n{content}"
    except Exception as e:
        logger.error(f"Failed to compare configs: {e}")
        return f"Error comparing configs on '{device_name}': {e}"


@mcp.tool()
def check_device_alarms(device_name: str) -> str:
    """Check active system alarms and chassis alarms on a device.

    Args:
        device_name: Device name.
    """
    logger.info(f"Executing tool: check_device_alarms for {device_name}")
    try:
        dev = pool.get(device_name)
        sys_alarms = dev.rpc.cli("show system alarms", format='text')
        chassis_alarms = dev.rpc.cli("show chassis alarms", format='text')
        sys_text = sys_alarms.text or sys_alarms.findtext('cli-out') or "No system alarms"
        chassis_text = chassis_alarms.text or chassis_alarms.findtext('cli-out') or "No chassis alarms"
        return f"--- Alarms on {device_name} ---\nSystem Alarms:\n{sys_text}\n\nChassis Alarms:\n{chassis_text}"
    except Exception as e:
        logger.error(f"Failed to check alarms: {e}")
        return f"Error checking alarms on '{device_name}': {e}"


@mcp.tool()
def get_interface_diagnostics(device_name: str, interface_name: str) -> str:
    """Get optical transceiver diagnostics (Rx/Tx power, temperature) for an interface.

    Args:
        device_name: Device name.
        interface_name: Interface name (e.g. 'et-0/0/0').
    """
    logger.info(f"Executing tool: get_interface_diagnostics for {device_name} {interface_name}")
    try:
        dev = pool.get(device_name)
        res = dev.rpc.cli(f"show interfaces diagnostics optics {interface_name}", format='text')
        content = res.text or res.findtext('cli-out') or "No diagnostics data available"
        return f"--- Interface Diagnostics: {device_name} {interface_name} ---\n{content}"
    except Exception as e:
        logger.error(f"Failed to get interface diagnostics: {e}")
        return f"Error getting diagnostics for '{interface_name}' on '{device_name}': {e}"


@mcp.tool()
def execute_shell(command: str, timeout: int = 30, working_directory: str = "/tmp") -> str:
    """Execute a shell command on the MCP Gateway Linux server.

    This server has direct network access to the lab (10.116.0.0/22).
    Use this for network diagnostics, running scripts, or system operations.

    Common use cases:
    - Network diagnostics: ping, traceroute, dig, nslookup, nmap, curl
    - File processing: grep, awk, sed, wc on log files
    - Python scripts: python3 -c "..." or python3 script.py

    Args:
        command: The shell command to execute.
        timeout: Maximum execution time in seconds (default 30, max 120).
        working_directory: Working directory for the command (default /tmp).
    """
    timeout = min(timeout, 120)  # Cap at 2 minutes
    logger.info(f"Executing shell command: {command[:100]}...")

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=working_directory,
        )

        output = f"--- Shell Command: {command[:100]} ---\n"
        output += f"Return Code: {result.returncode}\n"
        if result.stdout:
            stdout = result.stdout[:50000]
            trunc = " [TRUNCATED]" if len(result.stdout) > 50000 else ""
            output += f"STDOUT{trunc}:\n{stdout}\n"
        if result.stderr:
            stderr = result.stderr[:10000]
            output += f"STDERR:\n{stderr}\n"
        return output

    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds."
    except Exception as e:
        return f"Error executing command: {e}"


@mcp.tool()
def write_and_run_script(
    script_content: str,
    script_name: str = "agent_script.py",
    timeout: int = 60,
) -> str:
    """Write a Python script to disk and execute it on the MCP Gateway server.

    Use this to run complex network automation scripts that need:
    - Direct access to lab devices (10.116.0.0/22)
    - Python libraries available on the server
    - Multi-step logic that can't be done in a single shell command

    Args:
        script_content: The full Python script content to execute.
        script_name: Filename for the script (default: agent_script.py).
        timeout: Maximum execution time in seconds (default 60, max 300).
    """
    timeout = min(timeout, 300)
    script_dir = "/tmp/agent-scripts"
    os.makedirs(script_dir, exist_ok=True)

    script_path = os.path.join(script_dir, script_name)
    try:
        with open(script_path, 'w') as f:
            f.write(script_content)

        result = subprocess.run(
            ["python3", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=script_dir,
        )

        output = f"--- Script: {script_name} ---\n"
        output += f"Return Code: {result.returncode}\n"
        if result.stdout:
            output += f"STDOUT:\n{result.stdout[:50000]}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr[:10000]}\n"
        return output

    except subprocess.TimeoutExpired:
        return f"Error: Script timed out after {timeout} seconds."
    except Exception as e:
        return f"Error running script: {e}"


@mcp.tool()
def git_operation(
    repo_path: str,
    operation: str,
    args: str = "",
) -> str:
    """Execute a Git operation on the MCP Gateway server.

    Use this for version control operations:
    - Clone repos, commit config changes, push documentation
    - Manage network configuration as code

    Args:
        repo_path: Path to the git repository on the server.
        operation: Git operation (clone, status, add, commit, push, pull, log, diff).
        args: Additional arguments for the git command.
    """
    ALLOWED_OPS = {"clone", "status", "add", "commit", "push", "pull", "log", "diff", "show", "branch", "checkout"}
    if operation not in ALLOWED_OPS:
        return f"Error: Operation '{operation}' not allowed. Allowed: {', '.join(sorted(ALLOWED_OPS))}"

    cmd = f"git -C {shlex.quote(repo_path)} {operation} {args}"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60
        )
        output = f"--- Git {operation} ---\n"
        if result.stdout:
            output += result.stdout[:20000]
        if result.stderr:
            output += f"\nSTDERR: {result.stderr[:5000]}"
        output += f"\nReturn Code: {result.returncode}"
        return output
    except Exception as e:
        return f"Error: Git operation failed: {e}"


@mcp.tool()
async def get_device_status(device_ip: str) -> str:
    """Check the status of a network device using SNMP metrics from Prometheus.

    Args:
        device_ip: The IP address of the device.
    """
    async with httpx.AsyncClient() as client:
        # Simple query to check if we are getting any metrics for this device
        query = f'up{{instance="{device_ip}:9273"}}'
        try:
            response = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
            data = response.json()
            if data["status"] == "success" and data["data"]["result"]:
                status = data["data"]["result"][0]["value"][1]
                return f"Device {device_ip} is {'UP' if status == '1' else 'DOWN'}."
            else:
                return f"No status data found for device {device_ip}."
        except Exception as e:
            return f"Error querying Prometheus: {str(e)}"


@mcp.tool()
async def get_interface_traffic(device_ip: str, interface_name: str) -> str:
    """Get current interface traffic for a device.

    Args:
        device_ip: The IP address of the device.
        interface_name: The name of the interface.
    """
    async with httpx.AsyncClient() as client:
        # Example query for interface traffic (bits/sec)
        # Using rate() on ifHCInOctets and ifHCOutOctets
        query_in = f'rate(interface_traffic_ifHCInOctets{{instance="{device_ip}:9273", ifName="{interface_name}"}}[5m]) * 8'
        query_out = f'rate(interface_traffic_ifHCOutOctets{{instance="{device_ip}:9273", ifName="{interface_name}"}}[5m]) * 8'
        
        try:
            res_in = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query_in})
            res_out = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query_out})
            
            data_in = res_in.json()
            data_out = res_out.json()
            
            val_in = data_in["data"]["result"][0]["value"][1] if data_in["data"]["result"] else "0"
            val_out = data_out["data"]["result"][0]["value"][1] if data_out["data"]["result"] else "0"
            
            return f"Traffic on {interface_name} for {device_ip}:\nInbound: {float(val_in)/1000000:.2f} Mbps\nOutbound: {float(val_out)/1000000:.2f} Mbps"
        except Exception as e:
            return f"Error querying Prometheus: {str(e)}"


@mcp.tool()
async def get_device_logs(device_ip: str, limit: int = 10) -> str:
    """Query Syslogs from Loki for a specific device.

    Args:
        device_ip: The IP address of the device.
        limit: Number of syslog lines to retrieve (default 10).
    """
    async with httpx.AsyncClient() as client:
        # LogQL query to fetch logs from Loki
        query = f'{{job="syslog", host="{device_ip}"}}'
        try:
            response = await client.get(f"{LOKI_URL}/loki/api/v1/query_range", params={"query": query, "limit": limit})
            data = response.json()
            logs = []
            if data["status"] == "success" and data["data"]["result"]:
                for result in data["data"]["result"]:
                    for val in result["values"]:
                        logs.append(val[1])
                return "\n".join(logs)
            else:
                return f"No logs found for device {device_ip}."
        except Exception as e:
            return f"Error querying Loki: {str(e)}"


if __name__ == "__main__":
    # Configure Git credentials if provided
    git_username = os.environ.get("GIT_USERNAME")
    git_email = os.environ.get("GIT_EMAIL")
    git_password = os.environ.get("GIT_PASSWORD")
    if git_username and git_email:
        logger.info("Configuring Git user name and email...")
        subprocess.run(["git", "config", "--global", "user.name", git_username], check=False)
        subprocess.run(["git", "config", "--global", "user.email", git_email], check=False)
        
        if git_password:
            logger.info("Configuring Git credential helper...")
            subprocess.run(["git", "config", "--global", "credential.helper", "store"], check=False)
            
            # Write to ~/.git-credentials
            home_dir = os.path.expanduser("~")
            creds_path = os.path.join(home_dir, ".git-credentials")
            
            import urllib.parse
            encoded_username = urllib.parse.quote_plus(git_username)
            encoded_password = urllib.parse.quote_plus(git_password)
            cred_line = f"https://{encoded_username}:{encoded_password}@github.com\n"
            
            try:
                with open(creds_path, "w") as f:
                    f.write(cred_line)
                logger.info("Git credentials stored successfully.")
            except Exception as e:
                logger.error(f"Failed to write git credentials: {e}")

    logger.info(f"Starting FastMCP server with SSE transport on port {MCP_PORT}...")
    mcp.run(transport="sse")
