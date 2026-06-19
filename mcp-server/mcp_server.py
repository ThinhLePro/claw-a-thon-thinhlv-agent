import os
import json
import logging
import hashlib
import hmac
import sqlite3
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
COMMAND_TIMEOUT = int(os.environ.get("COMMAND_TIMEOUT", "60"))

# Monitoring configurations (Prometheus & Loki)
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100")

# Jira configuration (for propose_network_change and webhook)
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
JIRA_USER_EMAIL = os.environ.get("JIRA_USER_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "KAN")
JIRA_WEBHOOK_SECRET = os.environ.get("JIRA_WEBHOOK_SECRET", "")

# Redis configuration (for session log inspector)
# NOTE: Connect via internal LAN IP '10.116.0.181' for local/on-premise hosts (e.g. MCP Server).
# Connect via public NAT IP '49.213.77.222' for cloud-deployed Greennode agents.
REDIS_HOST = os.environ.get("REDIS_HOST", "10.116.0.181")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

import redis
redis_client = redis.Redis(
    host="10.116.0.181",
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True
)

# Command database paths
OPERATION_COMMANDS_DB = os.environ.get("OPERATION_COMMANDS_DB", "/app/db/operation_commands.db")
CONFIG_STATEMENTS_DB = os.environ.get("CONFIG_STATEMENTS_DB", "/app/db/configuration_statements.db")
NETWORK_ASSETS_DB = os.environ.get("NETWORK_ASSETS_DB", "/app/db/network_assets.db")

# Knowledge base (future RAG server)
KNOWLEDGE_BASE_URL = os.environ.get("KNOWLEDGE_BASE_URL", "http://internal-knowledge-base.noc.local")

if not NETCONF_PASSWORD:
    raise ValueError(
        "NETCONF_PASSWORD environment variable is required. "
        "Set it in your .env file or pass via docker-compose."
    )

# --- Import Command ACL ---
from command_acl import CommandACL, validate_command

acl = CommandACL()

# --- Load device inventory from shared JSON file ---
def load_device_map(filepath: str) -> dict:
    """Load device inventory from a JSON file.

    Returns a dict of {device_name: {ip, port, model, vendor, connection_method}} suitable for connections.
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
            "vendor": info.get("vendor", "juniper").lower(),
            "connection_method": info.get("connection_method", "netconf").lower(),
        }
    logger.info(f"Loaded {len(device_map)} devices from {filepath}")
    return device_map


import threading
import time
import subprocess
import shlex
import requests as req_lib

DEVICE_MAP = load_device_map(DEVICES_FILE)


# ---------------------------------------------------------------------------
# Multi-vendor connection support: NETCONF (default) → SSH → API fallback
# ---------------------------------------------------------------------------
def connect_device(device_name: str) -> Device:
    """Resolve and open a connection to the specified device.

    Supports multi-vendor, multi-method connections:
    - NETCONF (default for Juniper devices)
    - SSH fallback (for devices that don't support NETCONF)
    - API fallback (future support)

    Currently returns a Junos Device for NETCONF connections.
    For SSH/API, raises NotImplementedError with guidance.
    """
    # Resolve device_name (by hostname or IP)
    device_info = None
    resolved_name = device_name
    if device_name in DEVICE_MAP:
        device_info = DEVICE_MAP[device_name]
    else:
        # Check by IP
        for hostname, info in DEVICE_MAP.items():
            if info["ip"] == device_name:
                device_info = info
                resolved_name = hostname
                break

    if not device_info:
        raise ValueError(f"Device '{device_name}' is not registered in the database.")

    ip = device_info["ip"]
    port = device_info["port"]
    vendor = device_info.get("vendor", "juniper")
    connection_method = device_info.get("connection_method", "netconf")

    logger.info(f"Connecting to device {resolved_name} ({ip}:{port}) via {connection_method} [vendor: {vendor}]...")

    if connection_method == "netconf":
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
    elif connection_method == "ssh":
        # SSH fallback — uses Netmiko for multi-vendor CLI access
        try:
            from netmiko import ConnectHandler
        except ImportError:
            raise RuntimeError("Netmiko is required for SSH connections. Install with: pip install netmiko")

        # Map vendor names to Netmiko device_type
        vendor_netmiko_map = {
            "juniper": "juniper_junos",
            "cisco": "cisco_ios",
            "arista": "arista_eos",
            "huawei": "huawei",
            "ubuntu": "linux",
        }
        device_type = vendor_netmiko_map.get(vendor, f"{vendor}_ssh")

        # Fallback credentials list
        creds_to_try = []
        if NETCONF_USER and NETCONF_PASSWORD:
            creds_to_try.append((NETCONF_USER, NETCONF_PASSWORD))
        if vendor == "ubuntu" or device_type == "linux":
            for fallback_user, fallback_pass in [("root", "vnd@123#"), ("thinhle", "thinhle@123#")]:
                if (fallback_user, fallback_pass) not in creds_to_try:
                    creds_to_try.append((fallback_user, fallback_pass))

        # Fallback ports list
        ports_to_try = [port]
        if vendor == "ubuntu" or device_type == "linux":
            for fallback_port in [22, 8822, 9922]:
                if fallback_port not in ports_to_try:
                    ports_to_try.append(fallback_port)

        last_err = None
        for current_port in ports_to_try:
            for username, password in creds_to_try:
                logger.info(f"Attempting SSH connection to {resolved_name} ({ip}:{current_port}) with user '{username}'...")
                try:
                    net_connect = ConnectHandler(
                        device_type=device_type,
                        host=ip,
                        username=username,
                        password=password,
                        port=current_port,
                        timeout=15,
                    )
                    logger.info(f"Successfully connected to SSH device {resolved_name} ({ip}:{current_port}) using user '{username}'!")
                    return net_connect
                except Exception as e:
                    logger.warning(f"Failed SSH connection to {resolved_name} ({ip}:{current_port}) using user '{username}': {e}")
                    last_err = e

        raise ConnectionError(f"All SSH connection attempts failed for {resolved_name}. Last error: {last_err}")
    elif connection_method == "api":
        raise NotImplementedError(
            f"API connection method is not yet implemented for {resolved_name}. "
            f"Please configure the device to use 'netconf' or 'ssh' connection method."
        )
    else:
        raise ValueError(f"Unknown connection method '{connection_method}' for device '{resolved_name}'.")


def execute_command_on_device(device_name: str, command: str, timeout: int = None) -> str:
    """Execute a read-only command on a device using the appropriate method.

    Handles multi-vendor connections:
    - NETCONF (Juniper): Uses PyEZ RPC cli()
    - SSH (multi-vendor): Uses Netmiko send_command()
    - API: Future implementation

    Args:
        device_name: Device hostname or IP.
        command: CLI command to execute.
        timeout: Command execution timeout in seconds.

    Returns:
        Command output as string.
    """

    device_info = _resolve_device_info(device_name)
    connection_method = device_info.get("connection_method", "netconf")

    if connection_method == "netconf":
        dev = pool.get(device_name)
        res = dev.rpc.cli(command, format='text')
        if isinstance(res, bool):
            return f"Command '{command}' executed on {device_name} (success: {res})."
            
        content = None
        if hasattr(res, "text") and res.text:
            content = res.text
        elif hasattr(res, "findtext"):
            content = res.findtext('cli-out') or res.findtext('output')
            
        if not content and isinstance(res, etree._Element):
            content = etree.tostring(res, pretty_print=True, encoding='utf-8').decode('utf-8')
        return content or f"No output returned by command '{command}' on {device_name}."

    elif connection_method == "ssh":
        from netmiko import ConnectHandler

        device_info_full = _resolve_device_info(device_name)
        vendor = device_info_full.get("vendor", "juniper")
        vendor_netmiko_map = {
            "juniper": "juniper_junos",
            "cisco": "cisco_ios",
            "arista": "arista_eos",
            "huawei": "huawei",
            "ubuntu": "linux",
        }
        device_type = vendor_netmiko_map.get(vendor, f"{vendor}_ssh")

        # Fallback credentials list
        creds_to_try = []
        if NETCONF_USER and NETCONF_PASSWORD:
            creds_to_try.append((NETCONF_USER, NETCONF_PASSWORD))
        if vendor == "ubuntu" or device_type == "linux":
            for fallback_user, fallback_pass in [("root", "vnd@123#"), ("thinhle", "thinhle@123#")]:
                if (fallback_user, fallback_pass) not in creds_to_try:
                    creds_to_try.append((fallback_user, fallback_pass))

        # Fallback ports list
        ports_to_try = [device_info_full["port"]]
        if vendor == "ubuntu" or device_type == "linux":
            for fallback_port in [22, 8822, 9922]:
                if fallback_port not in ports_to_try:
                    ports_to_try.append(fallback_port)

        last_err = None
        for current_port in ports_to_try:
            for username, password in creds_to_try:
                logger.info(f"Attempting SSH connection (command exec) to {device_name} ({device_info_full['ip']}:{current_port}) with user '{username}'...")
                try:
                    net_connect = ConnectHandler(
                        device_type=device_type,
                        host=device_info_full["ip"],
                        username=username,
                        password=password,
                        port=current_port,
                        timeout=timeout or 15,
                    )
                    logger.info(f"Successfully connected to SSH device {device_name} ({device_info_full['ip']}:{current_port}) using user '{username}' (command exec)!")
                    output = net_connect.send_command(command, read_timeout=timeout)
                    net_connect.disconnect()
                    return output or f"No output returned by command '{command}' on {device_name}."
                except Exception as e:
                    logger.warning(f"Failed SSH connection attempt (command exec) to {device_name} ({device_info_full['ip']}:{current_port}) with user '{username}': {e}")
                    last_err = e

        return f"Error executing SSH command '{command}' on '{device_name}': All connection attempts failed. Last error: {last_err}"

    elif connection_method == "api":
        return f"API connection method is not yet implemented for device '{device_name}'."
    else:
        return f"Unknown connection method '{connection_method}' for device '{device_name}'."


def _resolve_device_info(device_name: str) -> dict:
    """Resolve device info from DEVICE_MAP by hostname or IP."""
    if device_name in DEVICE_MAP:
        return DEVICE_MAP[device_name]
    for hostname, info in DEVICE_MAP.items():
        if info["ip"] == device_name:
            return info
    raise ValueError(f"Device '{device_name}' is not registered in the database.")


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
                    is_connected = False
                    if hasattr(dev, "connected"):
                        is_connected = dev.connected
                    elif hasattr(dev, "is_alive"):
                        is_connected = dev.is_alive()
                    
                    if is_connected:
                        logger.info(f"Reusing existing connection to {resolved_name} from pool.")
                        self._pool[resolved_name] = (dev, time.time())
                        return dev
                except Exception:
                    pass
                logger.info(f"Connection for {resolved_name} is stale/disconnected. Reconnecting...")
                try:
                    if hasattr(dev, "close"):
                        dev.close()
                    elif hasattr(dev, "disconnect"):
                        dev.disconnect()
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
                        if hasattr(dev, "close"):
                            dev.close()
                        elif hasattr(dev, "disconnect"):
                            dev.disconnect()
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
                        if hasattr(dev, "close"):
                            dev.close()
                        elif hasattr(dev, "disconnect"):
                            dev.disconnect()
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

# ===================================================================
# INITIALIZE TOOL ACL IN REDIS
# ===================================================================
def initialize_tool_acls():
    """Register allowed tools for each agent in Redis on startup."""
    try:
        # Define the ACL map
        acl_map = {
            "analytics-network-engineer-agent": [
                "create_jira_task", 
                "query_previous_incidents",
                "get_devices_list",
                "get_device_detail",
                "add_task_comment",
                "query_netbox_inventory",
                "check_flapping_history",
                "check_device_updown",
                "execute_device_command",
                "check_device_alarms",
                "get_device_logs",
                "slack_react_message",
                "slack_check_user_profile",
                "slack_send_file",
                "slack_read_file",
                "slack_send_url",
                "read_url",
                "slack_reply_in_thread",
                "slack_update_message",
                "slack_mention_user_or_group",
                "slack_create_channel",
                "slack_invite_to_channel",
                "slack_send_block_kit",
                "slack_get_channel_history",
                "slack_view_status",
            ],
            "senior-network-engineer-agent": [
                "update_task_status", 
                "add_task_comment", 
                "check_task_status",
                "execute_device_command", 
                "lookup_junos_syntax",
                "get_devices_list",
                "get_device_detail",
                "get_commit_history",
                "get_device_config",
                "propose_network_change",
                "get_network_topology",
                "get_device_hardware",
                "check_device_alarms",
                "get_interface_diagnostics",
                "ping_from_device",
                "query_knowledge_base",
                "query_netbox_inventory",
                "check_device_updown",
                "get_interface_traffic",
                "get_device_logs",
                "query_previous_incidents",
                "check_flapping_history",
                "query_licenses",
                "query_device_warranty",
                "send_notification",
                "slack_react_message",
                "slack_check_user_profile",
                "slack_send_file",
                "slack_read_file",
                "slack_send_url",
                "read_url",
                "slack_reply_in_thread",
                "slack_update_message",
                "slack_mention_user_or_group",
                "slack_create_channel",
                "slack_invite_to_channel",
                "slack_send_block_kit",
                "slack_get_channel_history",
                "slack_view_status",
            ],
            "customer-advisory-agent": [
                "update_task_status", 
                "add_task_comment", 
                "remove_jira_task",
                "check_task_status",
                "send_notification",
                "slack_react_message",
                "slack_check_user_profile",
                "slack_send_file",
                "slack_read_file",
                "slack_send_url",
                "read_url",
                "slack_reply_in_thread",
                "slack_update_message",
                "slack_mention_user_or_group",
                "slack_create_channel",
                "slack_invite_to_channel",
                "slack_send_block_kit",
                "slack_get_channel_history",
                "slack_view_status",
            ]
        }
        for agent, tools_list in acl_map.items():
            key = f"acl:tools:{agent}"
            redis_client.delete(key)  # Clear old
            if tools_list:
                redis_client.sadd(key, *tools_list)
        logger.info("Successfully initialized Tool ACLs in Redis.")
    except Exception as e:
        logger.error(f"Failed to initialize Tool ACLs in Redis: {e}")

# Run ACL initialization
initialize_tool_acls()


# ===================================================================
# DEVICE INVENTORY TOOLS
# ===================================================================

@mcp.tool()
def get_devices_list() -> str:
    """Get the list of all registered datacenter devices and their static profile.

    Returns:
        A formatted list of device names, IP addresses, models, vendors, connection methods, and Netconf ports.
    """
    logger.info("Executing tool: get_devices_list")
    result = ["Registered Datacenter Devices:"]
    for d_name, d_info in DEVICE_MAP.items():
        result.append(
            f"- Hostname: {d_name} | IP: {d_info.get('ip')} | Model: {d_info.get('model')} "
            f"| Vendor: {d_info.get('vendor', 'juniper')} | Method: {d_info.get('connection_method', 'netconf')} "
            f"| Port: {d_info.get('port')}"
        )
    return "\n".join(result)




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
def get_commit_history(device_name: str) -> str:
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
def get_device_config(device_name: str, config_type: str = "active") -> str:
    """Get the running configuration of a specific device (optionally filter to a specific hierarchy).

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


# ===================================================================
# TOOL 1: view_network_status (Fast-Track — Read-only with Command ACL)
# Replaces get_device_operation_detail with ACL enforcement
# ===================================================================

@mcp.tool()
def execute_device_command(device_ip: str, command: str) -> str:
    """Execute a read-only operational CLI command on a network device (Fast-Track).

    This tool is for gathering information and checking device status ONLY.
    All commands pass through a Command ACL that only allows safe operational
    commands (show, ping, traceroute, monitor). Configuration commands are
    blocked and must go through propose_network_change.

    Supports multi-vendor devices:
    - NETCONF (default for Juniper)
    - SSH fallback (for devices not supporting NETCONF)
    - API (future support)

    Args:
        device_ip: IP address or hostname of the device.
        command: The operational CLI command to execute (e.g., 'show interfaces terse', 'show bgp summary').
    """
    logger.info(f"Executing tool: view_network_status for {device_ip} (command: {command})")

    # Step 1: Command ACL validation
    allowed, acl_message = acl.validate(command)
    if not allowed:
        return f"❌ {acl_message}"

    # Step 2: Execute command on device
    try:
        content = execute_command_on_device(device_ip, command, timeout=COMMAND_TIMEOUT)

        # Truncate if too large
        MAX_LEN = 100000
        if len(content) > MAX_LEN:
            truncated = content[:MAX_LEN]
            return (
                f"--- Operational State: {device_ip} [{command}] (Truncated) ---\n"
                f"{truncated}\n\n"
                f"... [TRUNCATED due to length ({len(content)} chars)]"
            )

        return f"--- Operational State: {device_ip} [{command}] ---\n{content}"
    except Exception as e:
        logger.error(f"Failed to execute operational query: {e}")
        return f"Error executing command '{command}' on '{device_ip}': {e}"




# ===================================================================
# TOOL 2: lookup_command_dictionary (Query internal command/config DB)
# ===================================================================

@mcp.tool()
def lookup_junos_syntax(
    intent_keyword: str,
    device_model: str = "",
    device_vendor: str = "juniper",
    os_version: str = "",
) -> str:
    """MANDATORY: Look up command syntax, parameters, and risk level from the internal
    command database BEFORE generating any CLI command or configuration.

    This tool queries two databases:
    - operation_commands: For show/operational commands (3000+ Juniper, Cisco commands)
    - configuration_statements: For config set/delete statements (8400+ Juniper statements)

    Multi-vendor support: Juniper (primary), Cisco, Arista, Huawei.

    Args:
        intent_keyword: The purpose or keyword to search (e.g., "bgp status", "disable interface", "evpn vxlan vni").
        device_model: Device model (e.g., "QFX10008", "MX480"). Optional, for context.
        device_vendor: Device vendor (e.g., "juniper", "cisco", "arista"). Defaults to "juniper".
        os_version: OS version of the device. Optional, for context.
    """
    logger.info(f"Executing tool: lookup_command_dictionary for '{intent_keyword}' (vendor: {device_vendor}, model: {device_model})")

    results = []
    vendor_filter = device_vendor.lower().strip() if device_vendor else ""

    # --- Search operation_commands DB ---
    try:
        conn_ops = sqlite3.connect(OPERATION_COMMANDS_DB)
        cur_ops = conn_ops.cursor()

        # FTS5 search for operational commands
        fts_query = intent_keyword.replace('"', '""')
        query_sql = """
            SELECT oc.command_name, oc.short_desc, oc.syntax, oc.risk_level,
                   oc.options, oc.output_fields, oc.url, oc.vendor
            FROM operation_commands_fts fts
            JOIN operation_commands oc ON fts.rowid = oc.id
            WHERE operation_commands_fts MATCH ?
        """
        params = [fts_query]

        if vendor_filter:
            query_sql += " AND oc.vendor = ?"
            params.append(vendor_filter)

        query_sql += " LIMIT 10"

        cur_ops.execute(query_sql, params)
        rows = cur_ops.fetchall()

        if rows:
            results.append("=== Operational Commands ===")
            for row in rows:
                cmd_name, short_desc, syntax, risk_level, options, output_fields, url, vendor = row
                entry = [f"\n📋 Command: {cmd_name} [Vendor: {vendor}] [Risk: {risk_level or 'INFO'}]"]
                if short_desc:
                    entry.append(f"   Description: {short_desc[:300]}")
                if syntax:
                    entry.append(f"   Syntax: {syntax[:500]}")
                if options:
                    entry.append(f"   Options: {options[:400]}")
                if url:
                    entry.append(f"   Reference: {url}")
                results.append("\n".join(entry))

        conn_ops.close()
    except Exception as e:
        logger.error(f"Error querying operation_commands DB: {e}")
        results.append(f"⚠️ Error querying operational commands DB: {e}")

    # --- Search configuration_statements DB ---
    try:
        conn_cfg = sqlite3.connect(CONFIG_STATEMENTS_DB)
        cur_cfg = conn_cfg.cursor()

        # FTS5 search for configuration statements
        fts_query = intent_keyword.replace('"', '""')
        query_sql = """
            SELECT cs.statement_name, cs.short_desc, cs.syntax, cs.description,
                   cs.default_value, cs.options, cs.hierarchy_level,
                   cs.required_privilege_level, cs.release_information, cs.url, cs.vendor
            FROM config_statements_fts fts
            JOIN config_statements cs ON fts.rowid = cs.id
            WHERE config_statements_fts MATCH ?
        """
        params = [fts_query]

        if vendor_filter:
            query_sql += " AND cs.vendor = ?"
            params.append(vendor_filter)

        query_sql += " LIMIT 10"

        cur_cfg.execute(query_sql, params)
        rows = cur_cfg.fetchall()

        if rows:
            results.append("\n=== Configuration Statements ===")
            for row in rows:
                stmt_name, short_desc, syntax, description, default_val, options, hierarchy, privilege, release, url, vendor = row
                entry = [f"\n🔧 Statement: {stmt_name} [Vendor: {vendor}]"]
                if short_desc:
                    entry.append(f"   Description: {short_desc[:300]}")
                if syntax:
                    entry.append(f"   Syntax: {syntax[:500]}")
                if hierarchy:
                    entry.append(f"   Hierarchy Level: {hierarchy[:300]}")
                if default_val:
                    entry.append(f"   Default: {default_val[:200]}")
                if options:
                    entry.append(f"   Options: {options[:400]}")
                if privilege:
                    entry.append(f"   Required Privilege: {privilege[:200]}")
                if url:
                    entry.append(f"   Reference: {url}")
                results.append("\n".join(entry))

        conn_cfg.close()
    except Exception as e:
        logger.error(f"Error querying config_statements DB: {e}")
        results.append(f"⚠️ Error querying configuration statements DB: {e}")

    if not results:
        return (
            f"No commands or configuration statements found matching '{intent_keyword}' "
            f"for vendor '{device_vendor}'. Try broader keywords or check the vendor name."
        )

    header = f"--- Command Dictionary Results for '{intent_keyword}' ---"
    if device_model:
        header += f" (Model: {device_model})"
    if device_vendor:
        header += f" (Vendor: {device_vendor})"

    return header + "\n" + "\n".join(results)


# ===================================================================
# TOOL 3: propose_network_change (Slow-Track — Creates Jira ticket)
# ===================================================================

def _text_to_adf(text: str) -> dict:
    """Convert plain text to Atlassian Document Format (ADF) for Jira API v3."""
    paragraphs = text.split("\n\n") if "\n\n" in text else [text]
    doc_content = []
    for para in paragraphs:
        lines = para.split("\n")
        inline_nodes = []
        for i, line in enumerate(lines):
            if line:
                inline_nodes.append({"type": "text", "text": line})
            if i < len(lines) - 1:
                inline_nodes.append({"type": "hardBreak"})
        if inline_nodes:
            doc_content.append({"type": "paragraph", "content": inline_nodes})
    return {
        "version": 1,
        "type": "doc",
        "content": doc_content or [
            {"type": "paragraph", "content": [{"type": "text", "text": "(empty)"}]}
        ],
    }


def _send_slack_cab_approval(issue_key: str, device_display: str, reason: str, config_payload: str):
    """Post an approval request with Block Kit buttons to the CAB channel."""
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    channel_id = os.environ.get("SLACK_CHANNEL_APPROVALS", "#noc-cab-approvals")
    
    if not slack_token:
        logger.warning("SLACK_BOT_TOKEN is not configured. Skipping Slack CAB notification.")
        return
        
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔔 CAB Approval Required: {issue_key}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Device:* {device_display}\n*Reason:* {reason}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Configuration Diff:*\n```\n{config_payload}\n```"
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approve"
                    },
                    "style": "primary",
                    "value": issue_key,
                    "action_id": "approve_change"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Reject"
                    },
                    "style": "danger",
                    "value": issue_key,
                    "action_id": "reject_change"
                }
            ]
        }
    ]
    
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel_id,
        "text": f"CAB Approval Required for Change Request: {issue_key}",
        "blocks": blocks
    }
    
    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200 and resp.json().get("ok"):
            logger.info(f"Successfully posted CAB approval request to Slack for {issue_key}")
        else:
            logger.error(f"Failed to post CAB approval request: {resp.text}")
    except Exception as e:
        logger.error(f"Exception posting CAB approval request: {e}")


def _send_teams_cab_approval(issue_key: str, device_display: str, reason: str, config_payload: str):
    """Post an approval request with Adaptive Card to the Teams channel/conversation of the active session."""
    import json
    service_url = None
    conversation_id = None
    
    try:
        # Check if there is a global or latest Teams context stored
        teams_ctx_data = redis_client.get("teams_ctx:latest")
        if teams_ctx_data:
            ctx = json.loads(teams_ctx_data)
            service_url = ctx.get("service_url")
            conversation_id = ctx.get("conversation_id")
            
        # If not found, scan active sessions
        if not service_url or not conversation_id:
            for key in redis_client.scan_iter("state:*"):
                data = redis_client.get(key)
                if data:
                    state = json.loads(data)
                    if state.get("teams_service_url") and state.get("teams_conversation_id"):
                        service_url = state["teams_service_url"]
                        conversation_id = state["teams_conversation_id"]
                        break
    except Exception as e:
        logger.error(f"Error scanning Redis for Teams context: {e}")

    if not service_url or not conversation_id:
        logger.warning("No Teams context found in Redis. Skipping Teams CAB notification.")
        return

    # Fetch token
    app_id = os.environ.get("TEAMS_BOT_APP_ID")
    app_password = os.environ.get("TEAMS_BOT_APP_PASSWORD")
    tenant_id = os.environ.get("TEAMS_BOT_TENANT_ID", "botframework.com")
    if not app_id or not app_password:
        logger.warning("TEAMS_BOT_APP_ID or TEAMS_BOT_APP_PASSWORD not set. Skipping Teams CAB.")
        return

    try:
        # Get access token
        tenant = tenant_id or "botframework.com"
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        token_payload = {
            "grant_type": "client_credentials",
            "client_id": app_id,
            "client_secret": app_password,
            "scope": "https://api.botframework.com/.default"
        }
        token_resp = req_lib.post(token_url, data=token_payload, timeout=10)
        if token_resp.status_code != 200:
            logger.error(f"Failed to get Teams token for CAB: {token_resp.text}")
            return
        token = token_resp.json().get("access_token")

        # Post Adaptive Card
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        card_content = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"🔔 CAB Approval Required: {issue_key}",
                    "weight": "Bolder",
                    "size": "Medium",
                    "color": "Warning"
                },
                {
                    "type": "TextBlock",
                    "text": f"**Device:** {device_display}\n**Reason:** {reason}",
                    "wrap": True
                },
                {
                    "type": "TextBlock",
                    "text": "**Proposed Configuration Diff (Junos XML / CLI):**",
                    "weight": "Bolder"
                },
                {
                    "type": "TextBlock",
                    "text": f"```\n{config_payload}\n```",
                    "wrap": True,
                    "fontType": "Monospace"
                },
                {
                    "type": "Input.Text",
                    "id": "l3_comment",
                    "placeholder": "Nhập comment/feedback (nêu lý do nếu Rework/Reject)...",
                    "isMultiline": True
                }
            ],
            "actions": [
                {
                    "type": "Action.Submit",
                    "title": "✅ Approve",
                    "data": {
                        "action": "approve_change",
                        "value": issue_key
                    }
                },
                {
                    "type": "Action.Submit",
                    "title": "❌ Reject",
                    "data": {
                        "action": "reject_change",
                        "value": issue_key
                    }
                },
                {
                    "type": "Action.Submit",
                    "title": "🔄 Request Changes (Rework)",
                    "data": {
                        "action": "request_changes",
                        "value": issue_key
                    }
                }
            ]
        }

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card_content
                }
            ]
        }

        resp = req_lib.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in [200, 201, 202]:
            logger.info(f"Successfully posted CAB approval request to Teams for {issue_key}")
        else:
            logger.error(f"Failed to post CAB approval request to Teams: {resp.text}")
    except Exception as e:
        logger.error(f"Exception posting Teams CAB approval request: {e}")


@mcp.tool()
def propose_network_change(
    device_ip: str,
    config_payload: str,
    reason: str,
    change_type: str = "CONFIGURATION CHANGE",
) -> str:
    """Propose a configuration change by creating a Jira Change Request ticket (Slow-Track).

    This tool does NOT directly modify the device. Instead, it:
    1. Creates a Jira ticket (Type: Change Request) with the proposed config.
    2. Returns the Jira Issue Key (e.g., NOC-1024) to the agent.
    3. Engineers review and approve the change on Jira.
    4. Upon approval, the Jira webhook triggers the MCP Gateway to push the config.

    For multi-device changes, create ONE ticket per device.

    Args:
        device_ip: IP address or hostname of the target device.
        config_payload: The configuration commands to apply (set/delete commands or structured config block).
        reason: AI-generated analysis explaining why this change is needed.
        change_type: The category of the change. Must be one of: 'CONFIGURATION CHANGE', 'HARDWARE CHANGE', 'SOFTWARE CHANGE', 'OTHER CHANGE'.
    """
    logger.info(f"Executing tool: propose_network_change for {device_ip}")

    if not JIRA_BASE_URL or not JIRA_USER_EMAIL or not JIRA_API_TOKEN:
        return "Error: Jira is not configured. Missing JIRA_BASE_URL, JIRA_USER_EMAIL, or JIRA_API_TOKEN."

    # Resolve device name for context
    device_display = device_ip
    for hostname, info in DEVICE_MAP.items():
        if info["ip"] == device_ip or hostname == device_ip:
            device_display = f"{hostname} ({info['ip']})"
            break

    # Build prefix based on change_type
    valid_changes = {
        "CONFIGURATION CHANGE": "[CONFIGURATION CHANGE]",
        "HARDWARE CHANGE": "[HARDWARE CHANGE]",
        "SOFTWARE CHANGE": "[SOFTWARE CHANGE]",
        "OTHER CHANGE": "[OTHER CHANGE]"
    }
    prefix = valid_changes.get(change_type.strip().upper(), "[CONFIGURATION CHANGE]")

    # Build Jira ticket and sanitize it
    raw_summary = f"{prefix} {device_display}: {reason[:80]}"
    summary = _sanitize_jira_summary(raw_summary, "Change Request")
    description = (
        f"🔧 Network Configuration Change Request\n\n"
        f"📍 Device: {device_display}\n"
        f"📋 Proposed by: AI Network Agent\n\n"
        f"--- REASON ---\n"
        f"{reason}\n\n"
        f"--- CONFIGURATION PAYLOAD ---\n"
        f"{config_payload}\n\n"
        f"--- INSTRUCTIONS ---\n"
        f"Review the proposed change above.\n"
        f"Click 'Approve' to trigger automatic deployment via MCP Gateway.\n"
        f"The MCP Gateway will: Backup → Lock → Load → Commit Check → Commit Confirmed 3 → Commit.\n"
        f"If any step fails, changes will be automatically rolled back."
    )

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": summary,
            "description": _text_to_adf(description),
            "issuetype": {"name": "Task"},
        }
    }

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue"
        resp = req_lib.post(
            url,
            json=payload,
            auth=(JIRA_USER_EMAIL, JIRA_API_TOKEN),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            issue_key = data.get("key", "UNKNOWN")
            logger.info(f"Jira ticket created via propose_network_change: {issue_key}")
            
            # Send Slack CAB approval request
            _send_slack_cab_approval(issue_key, device_display, reason, config_payload)
            
            return (
                f"✅ Change Request created successfully!\n"
                f"📋 Jira Issue: **{issue_key}**\n"
                f"🔗 Link: {JIRA_BASE_URL}/browse/{issue_key}\n"
                f"📍 Device: {device_display}\n"
                f"📝 Status: Pending Approval\n\n"
                f"The engineering team will review and approve the change on Slack. "
                f"Once approved, the MCP Gateway will automatically push the configuration."
            )
        else:
            error_detail = resp.text[:800]
            logger.error(f"Jira create failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error creating Jira ticket: HTTP {resp.status_code} — {error_detail}"
    except req_lib.exceptions.Timeout:
        return "Error: Jira API request timed out."
    except Exception as e:
        logger.error(f"propose_network_change exception: {e}")
        return f"Error creating change request: {e}"


# ===================================================================
# TOOL 4: query_knowledge_base (Stub — future RAG integration)
# ===================================================================

@mcp.tool()
def query_knowledge_base(
    query: str,
    source_type: str = "",
) -> str:
    """Search the internal knowledge base for vendor documentation, best practices,
    and troubleshooting guides BEFORE diagnosing issues or designing configurations.

    The database contains 16,520 document chunks categorized into two main source types:

    1. Juniper Knowledge Base (KB) Articles (source: "kb")
       - Over 10,000+ indexed chunks of sanitized Juniper technical support articles.
       - Troubleshooting Guides: Step-by-step procedures for handling hardware failures, traffic drops, and protocol flaps (e.g., BGP, OSPF, EVPN).
       - Suggested Software Releases: Official guidance on stable Junos releases for evaluation (e.g., the recommended releases list in KB21476).
       - Platform Coverage: Troubleshooting and configurations for SRX Series Firewalls, QFX Series Switches, MX Series Routers, and EX Series Switches.
       - Symptom & Cause Analyses: Explanations of software bugs, physical transceiver issues, and hardware constraints.

    2. Reference Books & Technical Guides (source: "book")
       - Over 6,100+ indexed pages of detailed books and design manuals.
       - Data Center & Switching Guides:
         * Juniper QFX10000 Series: A Comprehensive Guide to Building Next-Generation Data Centers
         * Juniper QFX5100 Series: A Comprehensive Guide to Building Next-Generation Networks
       - Protocol & Design & Operation (DO) Manuals:
         * Junos Design & Operation: Configuring Junos Policies & Filters
         * Junos Design & Operation: EVPNs for Data Center Interconnect (DCI)
         * Junos Design & Operation: Contrail DPDK
         * EVPN-VXLAN Integration Guide
         * Class of Service (CoS) on Security Devices
       - Security & Virtualization:
         * Junos Security
         * Contrail Architecture Guide
         * APS 6.4 User Guide

    This tool performs Vector Similarity Search over the database to find the most relevant chunks.

    Args:
        query: The core question, keyword, or error code to look up (e.g., "RPD_BGP_NEIGHBOR_STATE_CHANGED", "optimize OSPF timers").
        source_type: Optional filter to narrow search scope. Use "kb" for Juniper KB articles only, "book" for reference books only, or leave empty for both.
    """
    logger.info(f"Executing tool: query_knowledge_base for '{query}' (source_type: {source_type})")

    source = source_type.strip().lower() if source_type else None

    try:
        payload = {
            "query": query,
            "top_k": 5
        }
        if source in ["kb", "book"]:
            payload["source"] = source

        url = f"{KNOWLEDGE_BASE_URL}/search"
        resp = req_lib.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if resp.status_code == 200:
            results = resp.json()
            if not results:
                return f"No relevant information found in the knowledge base for query: '{query}'."

            response_lines = [f"Found {len(results)} relevant knowledge base documents for query '{query}':\n"]
            for idx, item in enumerate(results, 1):
                score = item.get("score", 0.0)
                source_type = item.get("source_type", "unknown").upper()
                title = item.get("title", "No Title")
                url_val = item.get("url")
                page_num = item.get("page_num")
                text = item.get("text", "")

                meta = f"Type: {source_type}"
                if page_num:
                    meta += f" | Page: {page_num}"
                if url_val:
                    meta += f" | URL: {url_val}"

                response_lines.append(f"[{idx}] {title} (Similarity Score: {score:.4f})")
                response_lines.append(f"Metadata: {meta}")
                response_lines.append(f"Content:\n{text}")
                response_lines.append("-" * 40 + "\n")
            return "\n".join(response_lines)
        else:
            return f"Error querying knowledge base: HTTP {resp.status_code} — {resp.text[:500]}"
    except req_lib.exceptions.Timeout:
        return "Error: Knowledge Base API request timed out."
    except Exception as e:
        logger.error(f"query_knowledge_base exception: {e}")
        return f"Error querying knowledge base: {e}"


# ===================================================================
# HARDWARE & TOPOLOGY TOOLS (unchanged)
# ===================================================================

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
    """Discover the network topology by querying LLDP neighbors, logical AE bundles, and BGP summaries on all active devices.

    Returns:
        A formatted topology Markdown report including a Mermaid graph and detailed connection summaries.
    """
    logger.info("Executing tool: get_network_topology")
    import re
    import concurrent.futures
    import json
    
    def parse_juniper_lldp(raw_lldp):
        connections = []
        if not raw_lldp:
            return connections
        lines = raw_lldp.splitlines()
        for line in lines:
            if "Local Interface" in line or "---" in line or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 3:
                connections.append({
                    "local_interface": parts[0],
                    "parent_bundle": parts[1] if (len(parts) >= 4 and parts[1] != "-") else None,
                    "remote_port": parts[3] if len(parts) >= 5 else parts[-1],
                    "remote_hostname": parts[-1]
                })
        return connections

    def parse_juniper_bgp(raw_bgp):
        peers = []
        if not raw_bgp:
            return peers
        blocks = re.split(r"Peer: ", raw_bgp)
        for block in blocks[1:]:
            lines = block.splitlines()
            if not lines:
                continue
            first_line = lines[0]
            peer_match = re.search(r"^([a-f\d\.\:\+]+)\s+AS\s+([\d\.]+)\s+Local:\s+([a-f\d\.\:\+a-z]+)\s+AS\s+([\d\.]+)", first_line)
            if peer_match:
                peer_ip = peer_match.group(1).split("+")[0]
                peer_as = peer_match.group(2)
                
                desc = "N/A"
                state = "Unknown"
                for line in lines:
                    if "Description:" in line:
                        desc = line.split("Description:")[1].strip()
                    if "State:" in line:
                        state = line.split("State:")[1].split()[0].strip()
                
                peers.append({
                    "remote_ip": peer_ip,
                    "remote_as": peer_as,
                    "description": desc,
                    "state": state
                })
        return peers

    def parse_juniper_bundles(raw_terse):
        bundles = {}
        if not raw_terse:
            return bundles
        for line in raw_terse.splitlines():
            if "aenet    -->" in line:
                parts = line.split()
                if len(parts) >= 3:
                    phys = parts[0].split(".")[0]
                    bundle = parts[-1].split(".")[0]
                    if bundle not in bundles:
                        bundles[bundle] = []
                    if phys not in bundles[bundle]:
                        bundles[bundle].append(phys)
        return bundles

    def parse_ubuntu_lldp(raw_lldp_dict):
        connections = []
        for iface, output in raw_lldp_dict.items():
            if "sysName" in output:
                match = re.search(r"sysName\s+(.*)", output)
                if match:
                    remote_sys = match.group(1).strip()
                    connections.append({"local_int": iface, "remote_sys": remote_sys})
        return connections

    def collect_device_data(name, info):
        ip = info["ip"]
        port = info["port"]
        vendor = info.get("vendor", "juniper")
        connection_method = info.get("connection_method", "netconf")
        
        node_data = {
            "hostname": name,
            "management_ip": ip,
            "device_type": "Juniper" if connection_method == "netconf" else "Ubuntu",
            "model": info.get("model", "Unknown"),
            "os_version": "Unknown",
            "physical_links": [],
            "logical_bundles": [],
            "bgp_sessions": []
        }
        
        try:
            if connection_method == "netconf":
                dev = pool.get(name)
                
                # OS Version
                try:
                    node_data["os_version"] = dev.facts.get("version", "Unknown")
                except Exception:
                    pass
                
                # LLDP
                try:
                    res_lldp = dev.rpc.cli("show lldp neighbors", format="text")
                    raw_lldp = ""
                    if hasattr(res_lldp, "text") and res_lldp.text:
                        raw_lldp = res_lldp.text
                    elif hasattr(res_lldp, "findtext"):
                        raw_lldp = res_lldp.findtext('cli-out') or res_lldp.findtext('output') or ""
                    
                    node_data["physical_links"] = parse_juniper_lldp(raw_lldp)
                except Exception as e:
                    logger.warning(f"Failed to get LLDP for Juniper {name}: {e}")
                    
                # BGP Sessions
                try:
                    res_bgp = dev.rpc.cli("show bgp neighbor", format="text")
                    raw_bgp = ""
                    if hasattr(res_bgp, "text") and res_bgp.text:
                        raw_bgp = res_bgp.text
                    elif hasattr(res_bgp, "findtext"):
                        raw_bgp = res_bgp.findtext('cli-out') or res_bgp.findtext('output') or ""
                    
                    node_data["bgp_sessions"] = parse_juniper_bgp(raw_bgp)
                except Exception as e:
                    logger.warning(f"Failed to get BGP for Juniper {name}: {e}")
                    
                # Bundles
                try:
                    res_terse = dev.rpc.cli("show interfaces terse", format="text")
                    raw_terse = ""
                    if hasattr(res_terse, "text") and res_terse.text:
                        raw_terse = res_terse.text
                    elif hasattr(res_terse, "findtext"):
                        raw_terse = res_terse.findtext('cli-out') or res_terse.findtext('output') or ""
                    
                    bundles_map = parse_juniper_bundles(raw_terse)
                    for ae, members in bundles_map.items():
                        node_data["logical_bundles"].append({"name": ae, "members": members})
                except Exception as e:
                    logger.warning(f"Failed to get logical bundles for Juniper {name}: {e}")
                    
            elif connection_method == "ssh":
                # Ubuntu/Linux
                dev = pool.get(name) # returns Netmiko handler
                
                # OS Version
                try:
                    os_out = dev.send_command("grep PRETTY_NAME /etc/os-release").strip()
                    node_data["os_version"] = os_out.split("=")[1].strip('"') if "=" in os_out else "Linux"
                except Exception:
                    pass
                
                # LLDP Neighbors
                try:
                    if_list = dev.send_command("ls /sys/class/net | grep -v lo").splitlines()
                    lldp_dict = {}
                    for iface in if_list:
                        iface = iface.strip()
                        if iface:
                            lldp_out = dev.send_command(f"lldptool -t -i {iface} -V sysName -n")
                            lldp_dict[iface] = lldp_out
                    
                    connections = parse_ubuntu_lldp(lldp_dict)
                    for c in connections:
                        node_data["physical_links"].append({
                            "local_interface": c["local_int"],
                            "parent_bundle": None,
                            "remote_port": "Unknown",
                            "remote_hostname": c["remote_sys"]
                        })
                except Exception as e:
                    logger.warning(f"Failed to get LLDP for Linux {name}: {e}")
                    
            return {"status": "Success", "data": node_data}
        except Exception as e:
            logger.error(f"Failed to collect topology data for {name}: {e}")
            return {"status": "Failed", "error": f"{name}: {str(e)}"}

    # Execute collection concurrently for all registered devices
    final_nodes = []
    errors = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_device = {
            executor.submit(collect_device_data, name, info): name
            for name, info in DEVICE_MAP.items()
        }
        for future in concurrent.futures.as_completed(future_to_device):
            res = future.result()
            if res["status"] == "Success":
                final_nodes.append(res["data"])
            else:
                errors.append(res["error"])

    # Deduplicate and build Mermaid
    mermaid = ["graph TD"]
    seen_links = set()
    
    groups = {
        "Gateway": [],
        "SuperSpine": [],
        "Spine": [],
        "Leaf": [],
        "Service": [],
        "Internet": [],
        "Server": []
    }

    for node in final_nodes:
        hostname = node["hostname"]
        dtype = node["device_type"]
        name_upper = hostname.upper()
        
        if "GW" in name_upper or "SRX" in name_upper:
            groups["Gateway"].append(hostname)
        elif "SUPER" in name_upper:
            groups["SuperSpine"].append(hostname)
        elif "SPINE" in name_upper or "SPN" in name_upper:
            groups["Spine"].append(hostname)
        elif "LEAF" in name_upper:
            groups["Leaf"].append(hostname)
        elif "SERVICE" in name_upper:
            groups["Service"].append(hostname)
        elif "INTERNET" in name_upper or "INTER" in name_upper:
            groups["Internet"].append(hostname)
        elif dtype == "Ubuntu":
            groups["Server"].append(hostname)
            
        for conn in node["physical_links"]:
            remote = conn["remote_hostname"]
            remote = remote.split(".")[0]
            
            actual_remote = None
            for n in final_nodes:
                h = n["hostname"]
                if h.lower() == remote.lower() or h.lower().startswith(remote.lower()):
                    actual_remote = h
                    break
            
            if actual_remote:
                link = tuple(sorted([hostname, actual_remote]))
                if link not in seen_links:
                    seen_links.add(link)
                    mermaid.append(f"    {hostname} -- {conn['local_interface']} --- {actual_remote}")

    # Build markdown output
    md = [
        "# Discovered Network Topology Final Report",
        "",
        "## 1. Network Topology Graph (Mermaid)",
        "```mermaid",
        "\n".join(mermaid),
        "```",
        "",
        "## 2. Device Summary",
        "| Hostname | IP | Type | Model | OS Version |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]
    
    # Sort nodes by hostname for stable display
    final_nodes = sorted(final_nodes, key=lambda x: x["hostname"])
    for n in final_nodes:
        md.append(f"| {n['hostname']} | {n['management_ip']} | {n['device_type']} | {n['model']} | {n['os_version']} |")

    md.append("\n## 3. Detailed Connections & Sessions")
    for n in final_nodes:
        md.append(f"\n### {n['hostname']} ({n['management_ip']})")
        
        if n['physical_links']:
            md.append("#### Physical Links (LLDP)")
            for l in n['physical_links']:
                bundle = f" (Bundle: {l['parent_bundle']})" if l['parent_bundle'] else ""
                md.append(f"- `{l['local_interface']}`{bundle} <---> **{l['remote_hostname']}** (on port `{l['remote_port']}`)")
        else:
            md.append("- No physical LLDP links found.")
        
        if n['logical_bundles']:
            md.append("#### Logical Bundles (Aggregated Ethernet)")
            for b in n['logical_bundles']:
                md.append(f"- `{b['name']}`: Members: `[{', '.join(b['members'])}]`")
        
        if n['bgp_sessions']:
            md.append("#### BGP Peering Sessions")
            md.append("| Remote Peer | AS | State | Description |")
            md.append("| :--- | :--- | :--- | :--- |")
            for s in n['bgp_sessions']:
                md.append(f"| {s['remote_ip']} | {s['remote_as']} | {s['state']} | {s['description']} |")

    if errors:
        md.append("\n## 4. Warnings / Discovery Errors")
        for err in errors:
            md.append(f"- {err}")

    return "\n".join(md)


# ===================================================================
# DIAGNOSTIC TOOLS
# ===================================================================

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


# ===================================================================
# GIT OPERATIONS (kept — version control is read/write safe)
# ===================================================================




# ===================================================================
# MONITORING TOOLS (Prometheus & Loki)
# ===================================================================

@mcp.tool()
async def check_device_updown(device_ip: str) -> str:
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


@mcp.tool()
async def check_flapping_history(device_ip: str, time_range: str = "1h") -> str:
    """Check for interface link flapping AND BGP peer flapping on a device.

    Queries Prometheus for ifOperStatus state changes (interface flaps) and
    BGP peer state changes (BGP flaps) within the specified time range.
    Also queries Loki syslogs for flap-related log entries.

    A flapping threshold of >= 3 state changes in the time range indicates active flapping.

    Args:
        device_ip: The IP address of the device to check.
        time_range: Prometheus time range to look back (e.g., '1h', '30m', '2h'). Default '1h'.
    """
    logger.info(f"Executing tool: check_flapping_history for {device_ip} (range: {time_range})")

    results = []
    flap_detected = False

    async with httpx.AsyncClient(timeout=20) as client:
        # --- 1. Interface Flapping: Check ifOperStatus changes ---
        try:
            # Count ifOperStatus transitions (1->2 or 2->1) over the time range
            intf_query = f'changes(ifOperStatus{{instance="{device_ip}:9273"}}[{time_range}])'
            resp = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": intf_query})
            data = resp.json()

            if data.get("status") == "success" and data["data"]["result"]:
                intf_flaps = []
                for metric in data["data"]["result"]:
                    iface = metric["metric"].get("ifName", metric["metric"].get("ifDescr", "unknown"))
                    changes = int(float(metric["value"][1]))
                    if changes >= 1:
                        intf_flaps.append({"interface": iface, "changes": changes})
                        if changes >= 3:
                            flap_detected = True

                if intf_flaps:
                    intf_flaps.sort(key=lambda x: x["changes"], reverse=True)
                    results.append(f"=== INTERFACE FLAPPING ({device_ip}, last {time_range}) ===")
                    for f_item in intf_flaps[:20]:
                        flag = "🔴 FLAPPING" if f_item["changes"] >= 3 else "🟡 Unstable" if f_item["changes"] >= 2 else "🟢 Minor"
                        results.append(f"  {f_item['interface']}: {f_item['changes']} state changes [{flag}]")
                else:
                    results.append(f"=== INTERFACE FLAPPING ({device_ip}, last {time_range}) ===")
                    results.append("  ✅ No interface flapping detected.")
            else:
                results.append(f"=== INTERFACE FLAPPING ({device_ip}, last {time_range}) ===")
                results.append("  ⚠️ No ifOperStatus metrics available for this device in Prometheus.")
        except Exception as e:
            results.append(f"=== INTERFACE FLAPPING ===")
            results.append(f"  ❌ Error querying Prometheus for interface flaps: {e}")

        # --- 2. BGP Flapping: Check BGP peer state changes ---
        try:
            # Check BGP peer state changes (jnxBgpM2PeerState or bgpPeerState)
            bgp_query = f'changes(jnxBgpM2PeerState{{instance="{device_ip}:9273"}}[{time_range}])'
            resp = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": bgp_query})
            data = resp.json()

            bgp_flaps = []
            if data.get("status") == "success" and data["data"]["result"]:
                for metric in data["data"]["result"]:
                    peer = metric["metric"].get("jnxBgpM2PeerRemoteAddr",
                           metric["metric"].get("bgpPeerRemoteAddr", "unknown"))
                    changes = int(float(metric["value"][1]))
                    if changes >= 1:
                        bgp_flaps.append({"peer": peer, "changes": changes})
                        if changes >= 3:
                            flap_detected = True

            # Fallback: try standard bgpPeerState if jnxBgp returned nothing
            if not bgp_flaps:
                bgp_query_std = f'changes(bgpPeerState{{instance="{device_ip}:9273"}}[{time_range}])'
                resp = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": bgp_query_std})
                data = resp.json()
                if data.get("status") == "success" and data["data"]["result"]:
                    for metric in data["data"]["result"]:
                        peer = metric["metric"].get("bgpPeerRemoteAddr", "unknown")
                        changes = int(float(metric["value"][1]))
                        if changes >= 1:
                            bgp_flaps.append({"peer": peer, "changes": changes})
                            if changes >= 3:
                                flap_detected = True

            results.append(f"\n=== BGP FLAPPING ({device_ip}, last {time_range}) ===")
            if bgp_flaps:
                bgp_flaps.sort(key=lambda x: x["changes"], reverse=True)
                for b_item in bgp_flaps[:20]:
                    flag = "🔴 FLAPPING" if b_item["changes"] >= 3 else "🟡 Unstable" if b_item["changes"] >= 2 else "🟢 Minor"
                    results.append(f"  BGP Peer {b_item['peer']}: {b_item['changes']} state changes [{flag}]")
            else:
                results.append("  ✅ No BGP peer flapping detected.")
        except Exception as e:
            results.append(f"\n=== BGP FLAPPING ===")
            results.append(f"  ❌ Error querying Prometheus for BGP flaps: {e}")

        # --- 3. Syslog-based flap detection (Loki) ---
        try:
            # Search for flap-related syslog messages
            loki_query = f'{{job="syslog", host="{device_ip}"}} |~ "(?i)(flap|SNMP_TRAP_LINK|RPD_BGP_NEIGHBOR_STATE_CHANGED|LINK_DOWN|LINK_UP|carrier|link state)"'
            resp = await client.get(f"{LOKI_URL}/loki/api/v1/query_range", params={
                "query": loki_query,
                "limit": 20,
                "start": f"{int(__import__('time').time()) - _parse_time_range(time_range)}000000000",
            })
            data = resp.json()

            results.append(f"\n=== SYSLOG FLAP EVENTS ({device_ip}, last {time_range}) ===")
            if data.get("status") == "success" and data["data"]["result"]:
                log_entries = []
                for stream in data["data"]["result"]:
                    for val in stream.get("values", []):
                        log_entries.append(val[1])
                if log_entries:
                    for entry in log_entries[:15]:
                        results.append(f"  {entry[:200]}")
                    flap_detected = True
                else:
                    results.append("  ✅ No flap-related syslog entries found.")
            else:
                results.append("  ✅ No flap-related syslog entries found.")
        except Exception as e:
            results.append(f"\n=== SYSLOG FLAP EVENTS ===")
            results.append(f"  ⚠️ Error querying Loki for flap logs: {e}")

    # --- Summary ---
    results.insert(0, f"--- Flapping History Report for {device_ip} (last {time_range}) ---")
    results.append(f"\n--- SUMMARY ---")
    if flap_detected:
        results.append(f"⚠️ FLAPPING DETECTED on {device_ip}. Threshold (>=3 state changes) exceeded.")
        results.append(f"ACTION: Log exact metrics to Jira via add_task_comment and escalate immediately.")
    else:
        results.append(f"✅ No significant flapping detected on {device_ip} in the last {time_range}.")

    return "\n".join(results)


def _parse_time_range(time_range: str) -> int:
    """Parse Prometheus time range string to seconds (e.g., '1h' -> 3600)."""
    try:
        unit = time_range[-1].lower()
        val = int(time_range[:-1])
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return val * multipliers.get(unit, 3600)
    except (ValueError, IndexError):
        return 3600  # Default 1 hour


@mcp.tool()
def send_notification(audience_type: str, message: str, session_id: str = "") -> str:
    """Send a notification to a specific audience channel via Slack.

    Use this tool to notify L3 Human Engineers or Customers about incidents,
    status updates, RCA reports, or escalations.

    When audience_type is 'Customer' and a session_id is provided, this tool
    automatically marks the session as 'closure_notified' in Redis to prevent
    duplicate notifications from the Supervisor fallback mechanism.

    Args:
        audience_type: Target audience. Must be one of:
            - "L3_Engineer": Internal L3 NOC Human Engineers (Slack: #noc-l3-alerts)
            - "Customer": Customer-facing channel (Slack: #all-customer-001)
        message: The notification message content to send.
        session_id: Optional session ID. If provided and audience_type is 'Customer',
                    the session state in Redis will be updated with closure_notified=True
                    to prevent duplicate closure notifications.
    """
    logger.info(f"Executing tool: send_notification to {audience_type} (session: {session_id or 'N/A'})")

    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        logger.warning(f"SLACK_BOT_TOKEN not set. Message logged: [{audience_type}] {message}")
        return f"Warning: SLACK_BOT_TOKEN not configured. Message printed to logs:\n[{audience_type}] {message}"

    aud = audience_type.strip().lower()
    
    if session_id and (session_id.startswith("tg-chat-") or session_id.startswith("tg-")):
        logger.info(f"Skipping Slack notification for Telegram session {session_id}")
        return f"Notification skipped for Slack because the session '{session_id}' originates from Telegram."
    
    # Load session state if session_id is provided
    origin_channel = ""
    origin_thread = ""
    if session_id:
        try:
            state_key = f"state:{session_id}"
            state_data = redis_client.get(state_key)
            if state_data:
                state = json.loads(state_data)
                origin_channel = state.get("slack_channel_id", "")
                origin_thread = state.get("slack_thread_ts", "")
        except Exception as ex:
            logger.warning(f"Failed to load session state for routing: {ex}")


    # Determine target channel
    if aud == "customer":
        # Best-effort resolution of originating channel if session_id is not passed
        if not session_id:
            try:
                for key in redis_client.scan_iter("state:*"):
                    data_str = redis_client.get(key)
                    if data_str:
                        state = json.loads(data_str)
                        if state.get("current_assignee") in ("customer-advisory-agent", "FINISH") and not state.get("closure_notified"):
                            session_id = key.replace("state:", "") if isinstance(key, str) else key.decode().replace("state:", "")
                            origin_channel = state.get("slack_channel_id", "")
                            origin_thread = state.get("slack_thread_ts", "")
                            break
            except Exception as scan_ex:
                logger.warning(f"Best-effort session scan failed: {scan_ex}")

        if origin_channel:
            channel = origin_channel
        else:
            channel = os.environ.get("SLACK_CHANNEL_CUSTOMER", "#all-customer-001")
        prefix = "📢 *Customer Update:*\n"
    elif aud == "l3_engineer":
        channel = os.environ.get("SLACK_CHANNEL_L3_ESCALATION") or "C0BCJJVL86L"
        prefix = "🚨 *L3 Engineer Escalation:*\n"
    else:
        return f"Error: Unknown audience_type '{audience_type}'. Must be 'L3_Engineer' or 'Customer'."

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # Replace markdown bold ** with * for Slack format compatibility
    if message:
        message = message.replace("**", "*")
        
    payload = {
        "channel": channel,
        "text": f"{prefix}{message}"
    }
    if origin_thread:
        payload["thread_ts"] = origin_thread

    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        resp_json = resp.json()
        if resp.status_code == 200 and resp_json.get("ok"):
            logger.info(f"Notification sent to {channel} ({audience_type})")
            
            # Auto-set closure_notified flag in Redis when notifying Customer
            if aud == "customer" and session_id:
                try:
                    state_key = f"state:{session_id}"
                    state_data = redis_client.get(state_key)
                    if state_data:
                        state = json.loads(state_data)
                        state["closure_notified"] = True
                        redis_client.set(state_key, json.dumps(state))
                        logger.info(f"Set closure_notified=True for session {session_id}")
                except Exception as redis_ex:
                    logger.warning(f"Failed to set closure_notified flag in Redis: {redis_ex}")
            
            # Also try to find and flag session even without explicit session_id
            # by scanning recent active sessions (best-effort for backward compatibility)
            if aud == "customer" and not session_id:
                try:
                    for key in redis_client.scan_iter("state:*"):
                        data_str = redis_client.get(key)
                        if data_str:
                            state = json.loads(data_str)
                            if state.get("current_assignee") in ("customer-advisory-agent", "FINISH") and not state.get("closure_notified"):
                                state["closure_notified"] = True
                                redis_client.set(key, json.dumps(state))
                                sid = key.replace("state:", "") if isinstance(key, str) else key.decode().replace("state:", "")
                                logger.info(f"Auto-flagged closure_notified=True for active session {sid}")
                                break  # Only flag the most relevant session
                except Exception as scan_ex:
                    logger.warning(f"Best-effort session scan failed: {scan_ex}")
            
            return f"✅ Notification sent successfully to Slack channel {channel} ({audience_type})."
        else:
            error = resp_json.get("error", resp.text[:200])
            return f"Failed to send Slack notification: {error}"
    except Exception as e:
        logger.error(f"send_notification exception: {e}")
        return f"Error sending Slack notification: {e}"


@mcp.tool()
def slack_react_message(channel_id: str, message_ts: str, emoji_name: str) -> str:
    """Add a reaction emoji (e.g. thumbsup, white_check_mark) to a Slack message.
    
    Args:
        channel_id: The Slack Channel ID where the message resides.
        message_ts: The timestamp (ts) of the message to react to.
        emoji_name: The name of the emoji (without colons, e.g. 'thumbsup').
    """
    logger.info(f"slack_react_message tool called: channel={channel_id}, ts={message_ts}, emoji={emoji_name}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    url = "https://slack.com/api/reactions.add"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel_id,
        "timestamp": message_ts,
        "name": emoji_name
    }
    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"Success: Reacted with :{emoji_name}: to message {message_ts}."
        else:
            return f"Failed to react: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_check_user_profile(user_id: str) -> str:
    """Get detailed Slack user profile information including full name, email, and title.
    
    Args:
        user_id: The Slack User ID (e.g. U0123456789).
    """
    logger.info(f"slack_check_user_profile tool called: user_id={user_id}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    url = "https://slack.com/api/users.info"
    headers = {"Authorization": f"Bearer {slack_token}"}
    try:
        resp = req_lib.get(url, headers=headers, params={"user": user_id}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            user = data["user"]
            profile = user.get("profile", {})
            info = {
                "id": user["id"],
                "name": user["name"],
                "real_name": user.get("real_name") or profile.get("real_name") or profile.get("real_name_normalized"),
                "display_name": profile.get("display_name") or profile.get("display_name_normalized"),
                "email": profile.get("email"),
                "title": profile.get("title"),
                "status_text": profile.get("status_text"),
                "status_emoji": profile.get("status_emoji"),
                "is_bot": user.get("is_bot"),
                "is_admin": user.get("is_admin")
            }
            return json.dumps(info, indent=2, ensure_ascii=False)
        else:
            return f"Error retrieving user info: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_view_status(user_id: str) -> str:
    """Get the presence status (active/away) of a user in Slack.
    
    Args:
        user_id: The Slack User ID (e.g. U0123456789).
    """
    logger.info(f"slack_view_status tool called: user_id={user_id}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    url = "https://slack.com/api/users.getPresence"
    headers = {"Authorization": f"Bearer {slack_token}"}
    try:
        resp = req_lib.get(url, headers=headers, params={"user": user_id}, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"User {user_id} presence status: {data.get('presence')}"
        else:
            return f"Failed to get presence: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_send_file(channel_id: str, file_path: str, title: str = "", initial_comment: str = "") -> str:
    """Upload and share a file from the server disk to a Slack channel.
    
    Args:
        channel_id: The Slack Channel ID to send the file to.
        file_path: Absolute or relative path of the file to send.
        title: Title of the file.
        initial_comment: Optional comment to post with the file.
    """
    logger.info(f"slack_send_file tool called: channel={channel_id}, file={file_path}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
        
    resolved = os.path.abspath(file_path)
    if not os.path.exists(resolved):
        return f"Error: File not found: {file_path}"
        
    filename = os.path.basename(resolved)
    try:
        file_size = os.path.getsize(resolved)
        
        # Step 1: Call files.getUploadURLExternal
        url_get_upload = "https://slack.com/api/files.getUploadURLExternal"
        headers = {"Authorization": f"Bearer {slack_token}"}
        params = {"filename": filename, "length": file_size}
        
        resp_get = req_lib.get(url_get_upload, headers=headers, params=params, timeout=10)
        data_get = resp_get.json()
        if not data_get.get("ok"):
            return f"Failed to get upload URL: {data_get.get('error')}"
            
        upload_url = data_get["upload_url"]
        file_id = data_get["file_id"]
        
        # Step 2: Upload the binary data to the upload URL
        with open(resolved, 'rb') as f:
            file_data = f.read()
        resp_upload = req_lib.post(upload_url, files={"file": (filename, file_data)}, timeout=30)
        if resp_upload.status_code != 200:
            return f"Failed uploading file content: HTTP {resp_upload.status_code}"
            
        # Step 3: Call files.completeUploadExternal
        url_complete = "https://slack.com/api/files.completeUploadExternal"
        complete_payload = {
            "files": [{"id": file_id, "title": title or filename}],
            "channel_id": channel_id
        }
        if initial_comment:
            complete_payload["initial_comment"] = initial_comment
            
        resp_complete = req_lib.post(url_complete, json=complete_payload, headers=headers, timeout=15)
        data_complete = resp_complete.json()
        if data_complete.get("ok"):
            return f"Success: File '{filename}' uploaded and shared to channel {channel_id}."
        else:
            return f"Failed to complete upload: {data_complete.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_read_file(file_id: str) -> str:
    """Retrieve details and textual content of a shared Slack file.
    
    Args:
        file_id: The Slack File ID (e.g. F0123456789).
    """
    logger.info(f"slack_read_file tool called: file_id={file_id}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
        
    headers = {"Authorization": f"Bearer {slack_token}"}
    try:
        url_info = "https://slack.com/api/files.info"
        resp_info = req_lib.get(url_info, headers=headers, params={"file": file_id}, timeout=10)
        data_info = resp_info.json()
        if not data_info.get("ok"):
            return f"Failed to get file info: {data_info.get('error')}"
            
        file_meta = data_info["file"]
        download_url = file_meta.get("url_private_download")
        if not download_url:
            return f"File metadata retrieved, but no private download URL found: {json.dumps(file_meta, indent=2)}"
            
        resp_dl = req_lib.get(download_url, headers=headers, timeout=20)
        if resp_dl.status_code == 200:
            content_type = resp_dl.headers.get("Content-Type", "")
            if "text" in content_type or "json" in content_type or "javascript" in content_type:
                text_content = resp_dl.text[:20000]
                truncated = " [TRUNCATED]" if len(resp_dl.text) > 20000 else ""
                return f"File: {file_meta.get('name')} | Type: {file_meta.get('mimetype')}\nContent{truncated}:\n{text_content}"
            else:
                return f"File: {file_meta.get('name')} | Type: {file_meta.get('mimetype')} | Size: {file_meta.get('size')} bytes (Binary content, not printed)."
        else:
            return f"Failed to download file content: HTTP {resp_dl.status_code}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_send_url(channel_id: str, url: str, message: str = "") -> str:
    """Send a URL link with an optional message to a Slack channel.
    
    Args:
        channel_id: The Slack Channel ID to send the link to.
        url: The URL link to share.
        message: Optional text message to send along with the link.
    """
    logger.info(f"slack_send_url tool called: channel={channel_id}, url={url}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
        
    text_content = f"{message}\n{url}" if message else url
    url_post = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel_id,
        "text": text_content
    }
    try:
        resp = req_lib.post(url_post, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"Success: Shared URL '{url}' to channel {channel_id}."
        else:
            return f"Failed to send URL: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def read_url(url: str) -> str:
    """Fetch content of a URL and parse it into human-readable text.
    
    Args:
        url: The web URL to download and read.
    """
    logger.info(f"read_url tool called: url={url}")
    try:
        import re
        import html
        resp = req_lib.get(url, timeout=15)
        if resp.status_code != 200:
            return f"Error: HTTP {resp.status_code}"
            
        html_content = resp.text
        # Remove script and style blocks
        html_content = re.sub(r'<(script|style).*?>.*?</\1>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        # Strip HTML tags
        text = re.sub(r'<[^>]*>', ' ', html_content)
        # Unescape HTML entities
        text = html.unescape(text)
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        truncated = text[:20000]
        if len(text) > 20000:
            truncated += "\n... [Content Truncated]"
        return truncated
    except Exception as e:
        return f"Error: {e}"


# ===================================================================
# ADVANCED SLACK INTERACTION TOOLS (Natural Communication)
# ===================================================================

@mcp.tool()
def slack_reply_in_thread(channel_id: str, thread_ts: str, message: str) -> str:
    """Reply directly into a Slack thread (threaded reply) instead of posting to main channel.
    
    Use this to keep conversations organized and avoid flooding the main channel.
    Before replying, this tool automatically fetches the last 10 messages in the thread
    to provide conversation context.
    
    Args:
        channel_id: The Slack Channel ID where the thread exists.
        thread_ts: The timestamp (ts) of the parent/root message of the thread.
        message: The reply message content.
    """
    logger.info(f"slack_reply_in_thread tool called: channel={channel_id}, thread_ts={thread_ts}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    # Step 1: Fetch conversation context (last 10 messages in thread)
    context_messages = []
    try:
        history_url = "https://slack.com/api/conversations.replies"
        history_params = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 10
        }
        hist_resp = req_lib.get(history_url, headers={"Authorization": f"Bearer {slack_token}"}, params=history_params, timeout=10)
        hist_data = hist_resp.json()
        if hist_data.get("ok"):
            for msg in hist_data.get("messages", []):
                user = msg.get("user", "bot")
                text = msg.get("text", "")
                context_messages.append(f"[{user}]: {text}")
            logger.info(f"Thread context: fetched {len(context_messages)} messages for thread {thread_ts}")
    except Exception as e:
        logger.warning(f"Failed to fetch thread context: {e}")
    
    # Step 2: Post reply in thread
    url = "https://slack.com/api/chat.postMessage"
    payload = {
        "channel": channel_id,
        "thread_ts": thread_ts,
        "text": message
    }
    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            ts = data.get("ts", "")
            context_summary = f"\n\n--- Thread Context ({len(context_messages)} messages) ---\n" + "\n".join(context_messages[-10:]) if context_messages else ""
            return f"Success: Replied in thread {thread_ts} (new message ts: {ts}).{context_summary}"
        else:
            return f"Failed to reply in thread: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_update_message(channel_id: str, message_ts: str, new_text: str) -> str:
    """Edit/update an existing Slack message that the bot previously sent.
    
    Use this to update status messages instead of sending new ones (e.g., 
    changing "🔴 Đang kiểm tra..." to "🟢 [Đã xử lý]...").
    
    Args:
        channel_id: The Slack Channel ID where the message exists.
        message_ts: The timestamp (ts) of the message to update.
        new_text: The new text content to replace the old message.
    """
    logger.info(f"slack_update_message tool called: channel={channel_id}, ts={message_ts}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    url = "https://slack.com/api/chat.update"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel_id,
        "ts": message_ts,
        "text": new_text
    }
    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"Success: Message {message_ts} updated in channel {channel_id}."
        else:
            return f"Failed to update message: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_mention_user_or_group(channel_id: str, mention_target: str, message: str, thread_ts: str = "") -> str:
    """Send a message that @mentions a specific user or user group in Slack.
    
    Use this to tag someone directly (e.g., @NOC L3 Engineer) for urgent attention.
    
    Args:
        channel_id: The Slack Channel ID to send the message to.
        mention_target: The Slack User ID (e.g. U0123456789) or User Group ID (e.g. S0123456789) to mention. Use <!channel> for @channel, <!here> for @here.
        message: The message content (the mention will be prepended automatically).
        thread_ts: Optional thread timestamp to reply in a specific thread.
    """
    logger.info(f"slack_mention_user_or_group tool called: channel={channel_id}, target={mention_target}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    # Build mention syntax
    if mention_target.startswith("<!"):
        # Already formatted: <!channel>, <!here>
        mention_str = mention_target
    elif mention_target.startswith("S"):
        # User group
        mention_str = f"<!subteam^{mention_target}>"
    else:
        # Individual user
        mention_str = f"<@{mention_target}>"
    
    full_text = f"{mention_str} {message}"
    
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel_id,
        "text": full_text
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    
    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"Success: Mentioned {mention_target} in channel {channel_id}."
        else:
            return f"Failed to send mention: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_create_channel(channel_name: str, is_private: bool = False) -> str:
    """Create a new Slack channel (e.g., for incident-specific channels like #inc-kan-105-core-down).
    
    Args:
        channel_name: Name for the new channel (lowercase, no spaces, max 80 chars). 
                      Example: 'inc-kan-105-core-down'
        is_private: If True, creates a private channel. Default is public.
    """
    logger.info(f"slack_create_channel tool called: name={channel_name}, private={is_private}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    # Sanitize channel name
    import re
    clean_name = re.sub(r'[^a-z0-9\-_]', '-', channel_name.lower().strip())[:80]
    
    url = "https://slack.com/api/conversations.create"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "name": clean_name,
        "is_private": is_private
    }
    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            ch = data["channel"]
            return f"Success: Channel #{clean_name} created. Channel ID: {ch['id']}"
        else:
            error = data.get("error", "")
            if error == "name_taken":
                return f"Channel #{clean_name} already exists. Use the existing channel."
            return f"Failed to create channel: {error}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_invite_to_channel(channel_id: str, user_ids: str) -> str:
    """Invite one or more users to a Slack channel.
    
    Args:
        channel_id: The Slack Channel ID to invite users to.
        user_ids: Comma-separated list of Slack User IDs to invite (e.g. 'U0123,U0456,U0789').
    """
    logger.info(f"slack_invite_to_channel tool called: channel={channel_id}, users={user_ids}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    url = "https://slack.com/api/conversations.invite"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel_id,
        "users": user_ids.strip()
    }
    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return f"Success: Users {user_ids} invited to channel {channel_id}."
        else:
            error = data.get("error", "")
            if error == "already_in_channel":
                return f"Users are already in channel {channel_id}."
            return f"Failed to invite users: {error}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_send_block_kit(channel_id: str, blocks_json: str, fallback_text: str = "", thread_ts: str = "") -> str:
    """Send a rich Block Kit message to a Slack channel.
    
    Use this for structured, visually rich messages (status dashboards, incident reports, 
    interactive cards, etc.).
    
    Args:
        channel_id: The Slack Channel ID to send the message to.
        blocks_json: A JSON string representing the Slack Block Kit blocks array.
                     Example: '[{"type":"section","text":{"type":"mrkdwn","text":"*Hello*"}}]'
        fallback_text: Plain text fallback for notifications (required by Slack API).
        thread_ts: Optional thread timestamp to send as a threaded reply.
    """
    logger.info(f"slack_send_block_kit tool called: channel={channel_id}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    try:
        blocks = json.loads(blocks_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid blocks_json — {e}"
    
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "channel": channel_id,
        "text": fallback_text or "Block Kit Message",
        "blocks": blocks
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts
    
    try:
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        data = resp.json()
        if data.get("ok"):
            ts = data.get("ts", "")
            return f"Success: Block Kit message sent to {channel_id} (ts: {ts})."
        else:
            return f"Failed to send Block Kit message: {data.get('error')}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def slack_get_channel_history(channel_id: str, limit: int = 10, thread_ts: str = "") -> str:
    """Fetch recent message history from a Slack channel or thread.
    
    MANDATORY: AI Agents MUST call this tool before replying in any channel or thread 
    to retrieve at least 5-10 previous messages for conversation context.
    
    Args:
        channel_id: The Slack Channel ID to fetch messages from.
        limit: Number of recent messages to fetch (default: 10, max: 50).
        thread_ts: Optional thread timestamp. If provided, fetches replies in that thread 
                   instead of channel-level messages.
    """
    logger.info(f"slack_get_channel_history tool called: channel={channel_id}, limit={limit}, thread_ts={thread_ts}")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        return "Error: SLACK_BOT_TOKEN is not set."
    
    limit = min(max(limit, 1), 50)
    headers = {"Authorization": f"Bearer {slack_token}"}
    
    try:
        if thread_ts:
            # Fetch thread replies
            url = "https://slack.com/api/conversations.replies"
            params = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": limit
            }
        else:
            # Fetch channel history
            url = "https://slack.com/api/conversations.history"
            params = {
                "channel": channel_id,
                "limit": limit
            }
        
        resp = req_lib.get(url, headers=headers, params=params, timeout=10)
        data = resp.json()
        
        if not data.get("ok"):
            return f"Failed to fetch history: {data.get('error')}"
        
        messages = data.get("messages", [])
        if not messages:
            return "No messages found in the channel/thread."
        
        # Format messages with user info enrichment
        formatted = []
        user_cache = {}
        
        for msg in messages:
            user_id = msg.get("user", "")
            text = msg.get("text", "")
            ts = msg.get("ts", "")
            msg_type = msg.get("subtype", "message")
            
            # Try to resolve username
            display_name = user_id
            if user_id and user_id not in user_cache:
                try:
                    user_url = "https://slack.com/api/users.info"
                    user_resp = req_lib.get(user_url, headers=headers, params={"user": user_id}, timeout=5)
                    user_data = user_resp.json()
                    if user_data.get("ok"):
                        profile = user_data["user"].get("profile", {})
                        display_name = (
                            profile.get("display_name") or 
                            profile.get("real_name") or 
                            user_data["user"].get("real_name") or 
                            user_data["user"].get("name") or 
                            user_id
                        )
                        user_cache[user_id] = display_name
                except Exception:
                    user_cache[user_id] = user_id
            elif user_id in user_cache:
                display_name = user_cache[user_id]
            
            # Parse timestamp to human-readable
            try:
                from datetime import datetime as dt
                msg_time = dt.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                msg_time = ts
            
            formatted.append(f"[{msg_time}] {display_name}: {text}")
        
        source = f"thread {thread_ts}" if thread_ts else f"channel {channel_id}"
        header = f"--- Conversation History ({len(formatted)} messages from {source}) ---"
        return header + "\n" + "\n".join(formatted)
        
    except Exception as e:
        return f"Error: {e}"


# ===================================================================
# IPAM & NETWORK ASSET TOOLS (NetBox-like API response format)
# ===================================================================

@mcp.tool()
def query_netbox_inventory(
    resource_type: str, 
    calling_tenant: str,
    query: Optional[str] = None
) -> str:
    """Query NetBox inventory tables (tenants, devices, vlans, interfaces, ip-addresses).
    Returns a NetBox API-like JSON response structure.
    
    Args:
        resource_type: Type of resource to query. Allowed values: 'tenants', 'devices', 'vlans', 'interfaces', 'ip-addresses'.
        calling_tenant: Slug of the tenant querying the resources (e.g. 'customer-a', 'customer-b', 'noc-ops'). Use 'noc-ops' if the query is for internal operations.
        query: Optional string to filter results (e.g. device name, IP address, VLAN ID, tenant name).
    """
    logger.info(f"Executing tool: query_netbox_inventory for resource '{resource_type}' with query '{query}', calling_tenant '{calling_tenant}'")
    
    res_type = resource_type.lower().strip()
    if res_type in ["ip-address", "ip-addresses", "ip_addresses", "ip_address", "ips", "ip"]:
        res_type = "ip-addresses"
    elif res_type in ["tenant", "tenants"]:
        res_type = "tenants"
    elif res_type in ["device", "devices"]:
        res_type = "devices"
    elif res_type in ["vlan", "vlans"]:
        res_type = "vlans"
    elif res_type in ["interface", "interfaces"]:
        res_type = "interfaces"
    else:
        allowed = ["tenants", "devices", "vlans", "interfaces", "ip-addresses"]
        return json.dumps({
            "error": f"Invalid resource_type '{resource_type}'. Allowed: {', '.join(allowed)}"
        }, indent=2)

    try:
        conn = sqlite3.connect(NETWORK_ASSETS_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        results = []
        calling_tenant_clean = calling_tenant.lower().strip() if calling_tenant else "noc-ops"
        if calling_tenant_clean in ["none", "null", "undefined", ""]:
            calling_tenant_clean = "noc-ops"
        
        if res_type == "tenants":
            sql = "SELECT id, name, slug, description FROM netbox_tenants WHERE 1=1"
            params = []
            if calling_tenant_clean and calling_tenant_clean != "noc-ops":
                sql += " AND slug = ?"
                params.append(calling_tenant_clean)
            if query:
                sql += " AND (name LIKE ? OR slug LIKE ? OR description LIKE ?)"
                like_q = f"%{query}%"
                params.extend([like_q, like_q, like_q])
            cur.execute(sql, params)
            for row in cur.fetchall():
                results.append({
                    "id": row["id"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "description": row["description"]
                })
                
        elif res_type == "devices":
            sql = """
                SELECT d.id, d.name, d.model, d.role, d.rack, d.primary_ip, d.tenant_id,
                       t.name as tenant_name, t.slug as tenant_slug
                FROM netbox_devices d
                LEFT JOIN netbox_tenants t ON d.tenant_id = t.id
                WHERE 1=1
            """
            params = []
            if calling_tenant_clean and calling_tenant_clean != "noc-ops":
                sql += " AND t.slug = ?"
                params.append(calling_tenant_clean)
            if query:
                sql += """ AND (d.name LIKE ? OR d.model LIKE ? OR d.role LIKE ? 
                           OR d.rack LIKE ? OR d.primary_ip LIKE ? OR t.name LIKE ?)"""
                like_q = f"%{query}%"
                params.extend([like_q, like_q, like_q, like_q, like_q, like_q])
            cur.execute(sql, params)
            for row in cur.fetchall():
                tenant_info = None
                if row["tenant_id"]:
                    tenant_info = {
                        "id": row["tenant_id"],
                        "name": row["tenant_name"],
                        "slug": row["tenant_slug"]
                    }
                results.append({
                    "id": row["id"],
                    "name": row["name"],
                    "model": {"name": row["model"]},
                    "role": {"name": row["role"]},
                    "rack": {"name": row["rack"]},
                    "primary_ip": {"address": row["primary_ip"]} if row["primary_ip"] else None,
                    "tenant": tenant_info
                })
                
        elif res_type == "vlans":
            sql = """
                SELECT v.id, v.vid, v.name, v.status, v.tenant_id, v.description,
                       t.name as tenant_name, t.slug as tenant_slug
                FROM netbox_vlans v
                LEFT JOIN netbox_tenants t ON v.tenant_id = t.id
                WHERE 1=1
            """
            params = []
            if calling_tenant_clean and calling_tenant_clean != "noc-ops":
                sql += " AND t.slug = ?"
                params.append(calling_tenant_clean)
            if query:
                is_num = False
                try:
                    int_val = int(query)
                    is_num = True
                except ValueError:
                    pass
                
                if is_num:
                    sql += " AND (v.vid = ? OR v.name LIKE ? OR t.name LIKE ?)"
                    params.extend([int_val, f"%{query}%", f"%{query}%"])
                else:
                    sql += " AND (v.name LIKE ? OR t.name LIKE ? OR v.description LIKE ?)"
                    like_q = f"%{query}%"
                    params.extend([like_q, like_q, like_q])
            cur.execute(sql, params)
            for row in cur.fetchall():
                tenant_info = None
                if row["tenant_id"]:
                    tenant_info = {
                        "id": row["tenant_id"],
                        "name": row["tenant_name"],
                        "slug": row["tenant_slug"]
                    }
                results.append({
                    "id": row["id"],
                    "vid": row["vid"],
                    "name": row["name"],
                    "status": {"value": row["status"], "label": row["status"].capitalize()},
                    "tenant": tenant_info,
                    "description": row["description"]
                })
                
        elif res_type == "interfaces":
            sql = """
                SELECT i.id, i.name, i.device_id, i.enabled, i.mac_address, i.mode, i.untagged_vlan_id,
                       d.name as device_name,
                       v.vid as vlan_vid, v.name as vlan_name,
                       i.connected_interface_id,
                       conn_i.name as conn_interface_name,
                       conn_d.id as conn_device_id,
                       conn_d.name as conn_device_name
                FROM netbox_interfaces i
                LEFT JOIN netbox_devices d ON i.device_id = d.id
                LEFT JOIN netbox_vlans v ON i.untagged_vlan_id = v.id
                LEFT JOIN netbox_interfaces conn_i ON i.connected_interface_id = conn_i.id
                LEFT JOIN netbox_devices conn_d ON conn_i.device_id = conn_d.id
                WHERE 1=1
            """
            params = []
            if calling_tenant_clean and calling_tenant_clean != "noc-ops":
                sql += " AND d.tenant_id = (SELECT id FROM netbox_tenants WHERE slug = ?)"
                params.append(calling_tenant_clean)
            if query:
                sql += " AND (i.name LIKE ? OR d.name LIKE ? OR i.mac_address LIKE ? OR i.mode LIKE ?)"
                like_q = f"%{query}%"
                params.extend([like_q, like_q, like_q, like_q])
            cur.execute(sql, params)
            for row in cur.fetchall():
                vlan_info = None
                if row["untagged_vlan_id"]:
                    vlan_info = {
                        "id": row["untagged_vlan_id"],
                        "vid": row["vlan_vid"],
                        "name": row["vlan_name"]
                    }
                connected_endpoint = None
                if row["connected_interface_id"]:
                    connected_endpoint = {
                        "id": row["connected_interface_id"],
                        "name": row["conn_interface_name"],
                        "device": {
                            "id": row["conn_device_id"],
                            "name": row["conn_device_name"]
                        }
                    }
                results.append({
                    "id": row["id"],
                    "name": row["name"],
                    "device": {"id": row["device_id"], "name": row["device_name"]},
                    "enabled": bool(row["enabled"]),
                    "mac_address": row["mac_address"],
                    "mode": {"value": row["mode"], "label": row["mode"].capitalize()} if row["mode"] else None,
                    "untagged_vlan": vlan_info,
                    "connected_endpoint": connected_endpoint
                })
                
        elif res_type == "ip-addresses":
            sql = """
                SELECT ip.id, ip.address, ip.status, ip.assigned_interface_id, ip.tenant_id, ip.description,
                       t.name as tenant_name, t.slug as tenant_slug,
                       i.name as interface_name, i.device_id,
                       d.name as device_name
                FROM netbox_ip_addresses ip
                LEFT JOIN netbox_tenants t ON ip.tenant_id = t.id
                LEFT JOIN netbox_interfaces i ON ip.assigned_interface_id = i.id
                LEFT JOIN netbox_devices d ON i.device_id = d.id
                WHERE 1=1
            """
            params = []
            if calling_tenant_clean and calling_tenant_clean != "noc-ops":
                sql += " AND ip.tenant_id = (SELECT id FROM netbox_tenants WHERE slug = ?)"
                params.append(calling_tenant_clean)
            if query:
                sql += " AND (ip.address LIKE ? OR ip.description LIKE ? OR t.name LIKE ? OR d.name LIKE ?)"
                like_q = f"%{query}%"
                params.extend([like_q, like_q, like_q, like_q])
            cur.execute(sql, params)
            for row in cur.fetchall():
                tenant_info = None
                if row["tenant_id"]:
                    tenant_info = {
                        "id": row["tenant_id"],
                        "name": row["tenant_name"],
                        "slug": row["tenant_slug"]
                    }
                assigned_obj = None
                if row["assigned_interface_id"]:
                    assigned_obj = {
                        "id": row["assigned_interface_id"],
                        "name": row["interface_name"],
                        "device": {
                            "id": row["device_id"],
                            "name": row["device_name"]
                        }
                    }
                results.append({
                    "id": row["id"],
                    "address": row["address"],
                    "status": {"value": row["status"], "label": row["status"].capitalize()},
                    "assigned_object": assigned_obj,
                    "tenant": tenant_info,
                    "description": row["description"]
                })
                
        conn.close()
        return json.dumps({
            "count": len(results),
            "results": results
        }, indent=2, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"Error executing query_netbox_inventory: {e}")
        return json.dumps({"error": str(e)}, indent=2)



def _query_impl_licenses(device_name: Optional[str] = None) -> str:
    try:
        conn = sqlite3.connect(NETWORK_ASSETS_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        sql = "SELECT id, device_name, license_key, features, expiry_date, status FROM licenses WHERE 1=1"
        params = []
        if device_name:
            sql += " AND device_name LIKE ?"
            params.append(f"%{device_name}%")
            
        cur.execute(sql, params)
        results = []
        for row in cur.fetchall():
            results.append({
                "id": row["id"],
                "device_name": row["device_name"],
                "license_key": row["license_key"],
                "features": row["features"],
                "expiry_date": row["expiry_date"],
                "status": row["status"]
            })
            
        conn.close()
        return json.dumps({
            "count": len(results),
            "results": results
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error querying licenses: {e}")
        return json.dumps({"error": str(e)}, indent=2)

@mcp.tool()
def query_licenses(device_name: Optional[str] = None) -> str:
    """Query device license details from the database.
    
    Args:
        device_name: Optional device name to filter by.
    """
    logger.info(f"Executing tool: query_licenses device_name={device_name}")
    return _query_impl_licenses(device_name)


@mcp.tool()
def query_device_warranty(device_name: Optional[str] = None) -> str:
    """Query device hardware warranty details from the database.
    
    Args:
        device_name: Optional device name to filter by.
    """
    logger.info(f"Executing tool: query_device_warranty device_name={device_name}")
    try:
        conn = sqlite3.connect(NETWORK_ASSETS_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        sql = "SELECT id, device_name, serial_number, warranty_package, start_date, end_date, status FROM device_warranty WHERE 1=1"
        params = []
        if device_name:
            sql += " AND device_name LIKE ?"
            params.append(f"%{device_name}%")
            
        cur.execute(sql, params)
        results = []
        for row in cur.fetchall():
            results.append({
                "id": row["id"],
                "device_name": row["device_name"],
                "serial_number": row["serial_number"],
                "warranty_package": row["warranty_package"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "status": row["status"]
            })
            
        conn.close()
        return json.dumps({
            "count": len(results),
            "results": results
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error executing query_device_warranty: {e}")
        return json.dumps({"error": str(e)}, indent=2)


# ===================================================================
# WEBHOOK HANDLER: Jira Approval → Config Push (Slow-Track completion)
# ===================================================================

def _verify_jira_webhook_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify HMAC-SHA256 signature from Jira webhook."""
    if not JIRA_WEBHOOK_SECRET:
        logger.warning("JIRA_WEBHOOK_SECRET not configured — skipping signature verification")
        return True

    # Extract the hex digest if prefixed with sha256=
    if signature_header.startswith("sha256="):
        signature_header = signature_header.split("=", 1)[1]

    expected_sig = hmac.new(
        JIRA_WEBHOOK_SECRET.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_sig, signature_header or "")


def _execute_config_change(device_name: str, config_payload: str, description: str = "") -> tuple[bool, str]:
    """Execute configuration change with careful multi-step process.

    Steps (per user spec):
    1. Backup current config (show config | display set)
    2. Lock configuration database
    3. Load proposed configuration
    4. Commit check (validate syntax and logic)
    5. Commit confirmed 3 (auto-rollback after 3 minutes if not confirmed)
    6. Final commit (confirm the change)

    If any step fails → stop immediately, rollback, unlock, return error.

    For multi-device changes: caller must invoke this one device at a time.
    """
    logger.info(f"Executing careful config change on {device_name}")
    steps_log = []

    try:
        dev = pool.get(device_name)
        cu = Config(dev)

        # Step 1: Backup current config
        try:
            backup_res = dev.rpc.get_config(options={'format': 'set'})
            backup_text = etree.tostring(backup_res, pretty_print=True, encoding='unicode')
            steps_log.append(f"✅ Step 1: Config backup captured ({len(backup_text)} chars)")
        except Exception as e:
            steps_log.append(f"⚠️ Step 1: Backup warning (non-fatal): {e}")

        # Step 2: Lock configuration database
        try:
            cu.lock()
            steps_log.append("✅ Step 2: Configuration database locked")
        except Exception as e:
            steps_log.append(f"❌ Step 2: Failed to lock configuration: {e}")
            return False, "\n".join(steps_log)

        try:
            # Step 3: Load proposed configuration
            is_set = any(line.strip().startswith(("set", "delete")) for line in config_payload.split("\n"))
            fmt = "set" if is_set else "text"

            cu.load(config_payload, format=fmt)
            steps_log.append(f"✅ Step 3: Configuration loaded (format: {fmt})")

            # Step 4: Commit check
            cu.commit(check=True)
            steps_log.append("✅ Step 4: Commit check passed")

            # Step 5: Commit confirmed 3 (auto-rollback after 3 minutes)
            cu.commit(confirm=3, comment=description or "MCP Gateway — Jira approved change (confirmed 3min)")
            steps_log.append("✅ Step 5: Commit confirmed 3 — change active (auto-rollback in 3 min if not confirmed)")

            # Step 6: Final commit (confirm the change permanently)
            cu.commit(comment=description or "MCP Gateway — Confirmed permanent commit")
            steps_log.append("✅ Step 6: Final commit — change confirmed permanently")

        except Exception as load_err:
            steps_log.append(f"❌ Failed at loading/committing: {load_err}")
            logger.warning(f"Config change failed on {device_name}. Rolling back...")
            try:
                cu.rollback()
                steps_log.append("↩️ Rollback executed successfully")
            except Exception as rb_err:
                steps_log.append(f"⚠️ Rollback error: {rb_err}")
            try:
                cu.unlock()
            except Exception:
                pass
            return False, "\n".join(steps_log)

        # Unlock after success
        try:
            cu.unlock()
            steps_log.append("🔓 Configuration database unlocked")
        except Exception as unlock_err:
            steps_log.append(f"⚠️ Unlock warning: {unlock_err}")

        return True, "\n".join(steps_log)

    except Exception as e:
        steps_log.append(f"❌ Connection/execution error: {e}")
        return False, "\n".join(steps_log)


def _update_jira_issue_status(issue_key: str, success: bool, log_text: str):
    """Update Jira ticket with deployment result."""
    if not JIRA_BASE_URL or not JIRA_USER_EMAIL or not JIRA_API_TOKEN:
        logger.warning("Jira not configured — cannot update issue status")
        return

    # Add comment with deployment log
    comment_body = _text_to_adf(
        f"{'✅ DEPLOYMENT SUCCESSFUL' if success else '❌ DEPLOYMENT FAILED'}\n\n"
        f"--- Deployment Log ---\n{log_text}"
    )

    try:
        # Add comment
        comment_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
        req_lib.post(
            comment_url,
            json={"body": comment_body},
            auth=(JIRA_USER_EMAIL, JIRA_API_TOKEN),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=15,
        )

        # Transition to Done/Failed
        transitions_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
        resp = req_lib.get(
            transitions_url,
            auth=(JIRA_USER_EMAIL, JIRA_API_TOKEN),
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            transitions = resp.json().get("transitions", [])
            target_names = ["done", "resolved"] if success else ["error", "failed"]
            for t in transitions:
                t_name_lower = t["name"].lower()
                if any(name in t_name_lower for name in target_names):
                    req_lib.post(
                        transitions_url,
                        json={"transition": {"id": t["id"]}},
                        auth=(JIRA_USER_EMAIL, JIRA_API_TOKEN),
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                        timeout=15,
                    )
                    logger.info(f"Jira {issue_key} transitioned to '{t['name']}'")
                    break

    except Exception as e:
        logger.error(f"Failed to update Jira issue {issue_key}: {e}")


# ===================================================================
# JIRA TOOLS (Centralized from Agents)
# ===================================================================

_JIRA_TIMEOUT = 15

def _jira_auth() -> tuple[str, str]:
    return (JIRA_USER_EMAIL, JIRA_API_TOKEN)

def _jira_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def _is_jira_configured() -> bool:
    return bool(JIRA_BASE_URL and JIRA_USER_EMAIL and JIRA_API_TOKEN)

_STATUS_ALIASES: dict[str, list[str]] = {
    "IN_PROGRESS": ["in progress", "start progress", "in-progress"],
    "WAITING":     ["waiting", "wait", "blocked", "on hold"],
    "ERROR":       ["error", "fail", "failed"],
    "DONE":        ["done", "complete", "resolve", "closed", "close"],
}

def _find_transition_id(issue_key: str, target_status: str) -> tuple[str | None, str]:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    resp = req_lib.get(url, auth=_jira_auth(), headers=_jira_headers(), timeout=_JIRA_TIMEOUT)
    if resp.status_code != 200:
        return None, f"Failed to fetch transitions for {issue_key}: HTTP {resp.status_code} — {resp.text[:500]}"

    transitions = resp.json().get("transitions", [])
    if not transitions:
        return None, f"No transitions available for {issue_key}. The ticket may already be in a terminal state."

    target_norm = target_status.strip().upper().replace(" ", "_")
    aliases = _STATUS_ALIASES.get(target_norm, [target_status.lower()])

    for t in transitions:
        t_name_lower = t["name"].lower()
        for alias in aliases:
            if alias in t_name_lower:
                return t["id"], t["name"]

    available = ", ".join(f'"{t["name"]}"' for t in transitions)
    return None, f"No transition matching '{target_status}' found for {issue_key}. Available transitions: {available}"

def _sanitize_jira_summary(summary: str, issue_type: str = "Task") -> str:
    """Helper function to format and prepend correct prefixes and enforce title length limits."""
    # Truncate/sanitize to prevent exceeding Jira's limit.
    # Jira's limit is 255 characters, let's keep it safe at 200 characters.
    MAX_SUMMARY_LEN = 200
    
    summary = summary.strip()
    
    # Valid prefixes from user requirements (case-insensitive checks)
    valid_prefixes = [
        "[CONFIGURATION CHANGE]",
        "[HARDWARE CHANGE]",
        "[SOFTWARE CHANGE]",
        "[OTHER CHANGE]",
        "[OTHER CHANGE]",
        "[SOFTWARE ISSUES]",
        "[HARDWARE ISSUES]",
        "[OTHER ISSUES]"
    ]
    
    has_valid_prefix = False
    matched_prefix = ""
    for p in valid_prefixes:
        if summary.upper().startswith(p.upper()):
            has_valid_prefix = True
            matched_prefix = p
            break
            
    if not has_valid_prefix:
        # Determine prefix based on issue_type or keywords in summary
        is_change = issue_type.lower() in ["change request", "change", "changerequest"]
        if is_change:
            # For changes, default to CONFIGURATION CHANGE
            prefix = "[CONFIGURATION CHANGE]"
        else:
            # Standardize issue prefix by content keywords
            summary_lower = summary.lower()
            if any(kw in summary_lower for kw in ["hardware", "cable", "port", "physical", "flapping", "interface"]):
                prefix = "[HARDWARE ISSUES]"
            elif any(kw in summary_lower for kw in ["software", "bgp", "ospf", "routing", "config", "ping", "packet loss", "loss"]):
                prefix = "[SOFTWARE ISSUES]"
            else:
                prefix = "[OTHER ISSUES]"
        
        summary = f"{prefix} {summary}"
    else:
        # Normalize legacy [OTHER CHANGGE] typo to [OTHER CHANGE]
        if matched_prefix.upper() == "[OTHER CHANGGE]":
            summary = "[OTHER CHANGE]" + summary[len("[OTHER CHANGGE]"):]
            
    # Truncate summary if it exceeds the limit
    if len(summary) > MAX_SUMMARY_LEN:
        summary = summary[:MAX_SUMMARY_LEN - 3] + "..."
        
    return summary

@mcp.tool()
def create_jira_task(summary: str, description: str, issue_type: str = "Task") -> str:
    """Create a new ticket on the Jira KAN board. issue_type can be 'Task', 'Incident', 'Service Request', or 'Change Request'."""
    if not _is_jira_configured():
        return "Error: Jira is not configured. Missing JIRA_BASE_URL, JIRA_USER_EMAIL, or JIRA_API_TOKEN."

    sanitized_summary = _sanitize_jira_summary(summary, issue_type)

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": sanitized_summary,
            "description": _text_to_adf(description),
            "issuetype": {"name": issue_type},
        }
    }

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue"
        resp = req_lib.post(url, json=payload, auth=_jira_auth(), headers=_jira_headers(), timeout=_JIRA_TIMEOUT)
        if resp.status_code in (200, 201):
            data = resp.json()
            issue_key = data.get("key", "UNKNOWN")
            logger.info(f"Jira ticket created: {issue_key}")
            return (
                f"✅ Đã tạo ticket Jira: **{issue_key}**\n"
                f"Link: {JIRA_BASE_URL}/browse/{issue_key}\n"
                f"Summary: {sanitized_summary}"
            )
        else:
            error_detail = resp.text[:800]
            logger.error(f"Jira create failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error creating Jira ticket: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira create exception: {e}")
        return f"Error creating Jira ticket: {e}"

@mcp.tool()
def update_task_status(issue_key: str, target_status: str) -> str:
    """Change the status of a Jira ticket. target_status can be 'IN_PROGRESS', 'WAITING', 'ERROR', or 'DONE'."""
    if not _is_jira_configured():
        return "Error: Jira is not configured."

    transition_id, match_info = _find_transition_id(issue_key, target_status)
    if transition_id is None:
        return f"Error: {match_info}"

    payload = {"transition": {"id": transition_id}}

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
        resp = req_lib.post(url, json=payload, auth=_jira_auth(), headers=_jira_headers(), timeout=_JIRA_TIMEOUT)
        if resp.status_code == 204:
            logger.info(f"Jira {issue_key} transitioned to '{match_info}'")
            return f"✅ Ticket {issue_key} đã chuyển sang trạng thái: **{match_info}**"
        else:
            error_detail = resp.text[:500]
            logger.error(f"Jira transition failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error transitioning {issue_key}: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira transition exception: {e}")
        return f"Error transitioning {issue_key}: {e}"

@mcp.tool()
def add_task_comment(issue_key: str, comment_body: str) -> str:
    """Add a comment (log entry / report) to a Jira ticket."""
    if not _is_jira_configured():
        return "Error: Jira is not configured."

    payload = {"body": _text_to_adf(comment_body)}

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
        resp = req_lib.post(url, json=payload, auth=_jira_auth(), headers=_jira_headers(), timeout=_JIRA_TIMEOUT)
        if resp.status_code in (200, 201):
            comment_id = resp.json().get("id", "?")
            logger.info(f"Comment added to {issue_key}")
            return f"✅ Đã ghi comment vào ticket {issue_key} (comment #{comment_id})"
        else:
            error_detail = resp.text[:500]
            logger.error(f"Jira comment failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error adding comment to {issue_key}: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira comment exception: {e}")
        return f"Error adding comment to {issue_key}: {e}"

@mcp.tool()
def query_previous_incidents(device_ip: str) -> str:
    """Search Jira for previous incident tasks related to a specific device IP or hostname."""
    if not _is_jira_configured():
        return "Error: Jira is not configured."

    jql = f'project = "{JIRA_PROJECT_KEY}" AND (summary ~ "{device_ip}" OR description ~ "{device_ip}")'

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/search"
        resp = req_lib.get(url, params={"jql": jql, "maxResults": 10}, auth=_jira_auth(), headers=_jira_headers(), timeout=_JIRA_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            issues = data.get("issues", [])
            if not issues:
                return f"No previous incidents found on Jira for device {device_ip}."

            lines = [f"Found {len(issues)} previous incident(s) for device {device_ip}:"]
            for issue in issues:
                key = issue.get("key")
                fields = issue.get("fields", {})
                summary = fields.get("summary", "No Summary")
                status = fields.get("status", {}).get("name", "Unknown")
                created = fields.get("created", "Unknown")[:10]
                lines.append(f"- **{key}** ({status}) | Created: {created} | Summary: {summary}")
            return "\n".join(lines)
        else:
            error_detail = resp.text[:500]
            logger.error(f"Jira search failed: HTTP {resp.status_code} — {error_detail}")
            return f"Error searching Jira: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira search exception: {e}")
        return f"Error searching Jira: {e}"

@mcp.tool()
def check_task_status(issue_key: str) -> str:
    """Check the current status and assignee of a Jira ticket."""
    if not _is_jira_configured():
        return "Error: Jira is not configured."

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
        resp = req_lib.get(url, auth=_jira_auth(), headers=_jira_headers(), timeout=_JIRA_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            fields = data.get("fields", {})
            status = fields.get("status", {}).get("name", "Unknown")
            assignee = fields.get("assignee")
            assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"
            summary = fields.get("summary", "No Summary")
            return f"Ticket {issue_key}:\n- Status: {status}\n- Assignee: {assignee_name}\n- Summary: {summary}"
        else:
            error_detail = resp.text[:500]
            return f"Error checking ticket {issue_key}: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira check status exception: {e}")
        return f"Error checking ticket {issue_key}: {e}"

@mcp.tool()
def remove_jira_task(issue_key: str) -> str:
    """Delete a Jira ticket completely."""
    if not _is_jira_configured():
        return "Error: Jira is not configured."

    try:
        url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
        resp = req_lib.delete(url, auth=_jira_auth(), headers=_jira_headers(), timeout=_JIRA_TIMEOUT)
        if resp.status_code == 204:
            logger.info(f"Jira {issue_key} has been deleted.")
            return f"✅ Ticket {issue_key} đã được xóa thành công."
        else:
            error_detail = resp.text[:500]
            return f"Error deleting ticket {issue_key}: HTTP {resp.status_code} — {error_detail}"
    except Exception as e:
        logger.error(f"Jira delete exception: {e}")
        return f"Error deleting ticket {issue_key}: {e}"


# ===================================================================
# STARTUP — Main entry point
# ===================================================================

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

    # --- Mount Jira webhook endpoint alongside FastMCP SSE ---
    # FastMCP uses Starlette under the hood; we add a custom route for the webhook
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def jira_webhook_handler(request: Request) -> JSONResponse:
        """Handle Jira webhook for approved configuration changes."""
        logger.info("Received Jira webhook request")

        # Read raw body for signature verification
        body = await request.body()

        # Verify HMAC-SHA256 signature
        signature = request.headers.get("X-Hub-Signature", "") or request.headers.get("x-hub-signature", "")
        if JIRA_WEBHOOK_SECRET and not _verify_jira_webhook_signature(body, signature):
            logger.warning("Jira webhook signature verification failed!")
            return JSONResponse({"error": "Invalid signature"}, status_code=401)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        # Parse webhook payload
        webhook_event = data.get("webhookEvent", "")
        issue = data.get("issue", {})
        issue_key = issue.get("key", "UNKNOWN")
        fields = issue.get("fields", {})

        # Check if this is a comment mention event
        if webhook_event == "comment_created":
            comment_obj = data.get("comment", {})
            comment_body = comment_obj.get("body", "")
            author = comment_obj.get("author", {})
            author_name = author.get("displayName", "Jira User")
            author_id = author.get("accountId", "jira-user")
            
            # Extract text from comment body (Jira Cloud uses ADF)
            comment_text = ""
            if isinstance(comment_body, dict):
                for block in comment_body.get("content", []):
                    for node in block.get("content", []):
                        if node.get("type") == "text":
                            comment_text += node.get("text", "")
                        elif node.get("type") == "hardBreak":
                            comment_text += "\n"
                    comment_text += "\n"
            else:
                comment_text = str(comment_body)
                
            comment_text = comment_text.strip()
            
            # Check if mentioned
            bot_names = ["GreenNode Network AI Agent", "NOC-AI-Agent"]
            is_mentioned = any(name.lower() in comment_text.lower() for name in bot_names)
            is_self = any(name.lower() in author_name.lower() for name in bot_names)
            
            if is_mentioned and not is_self:
                logger.info(f"Jira Mention Webhook: Bot mentioned in comment on {issue_key} by {author_name}")
                
                # Strip bot name and @ sign
                clean_comment = comment_text
                for name in bot_names:
                    import re
                    clean_comment = re.sub(re.escape(name), "", clean_comment, flags=re.IGNORECASE).strip()
                clean_comment = re.sub(r"^@\s*", "", clean_comment).strip()
                
                # Find session in Redis or initialize new one
                session_id = f"jira-{issue_key}"
                for key in redis_client.scan_iter("state:*"):
                    data_str = redis_client.get(key)
                    if data_str:
                        try:
                            state_data = json.loads(data_str)
                            if state_data.get("jira_issue_key") == issue_key:
                                session_id = state_data.get("session_id", key.split("state:", 1)[1])
                                break
                        except Exception:
                            continue
                
                # We launch a background thread to call Supervisor Agent asynchronously
                import threading
                
                def _call_supervisor_and_comment_async(sess_id, clean_msg, auth_id, key):
                    supervisor_url = redis_client.get("agent:url:supervisor-network-engineer-agent")
                    if not supervisor_url:
                        logger.error("Supervisor URL not found in Redis for comment mention")
                        add_task_comment(key, "⚠️ Không tìm thấy URL của Supervisor Agent trong hệ thống.")
                        return
                    
                    if supervisor_url.startswith('"') and supervisor_url.endswith('"'):
                        supervisor_url = supervisor_url[1:-1]
                        
                    try:
                        invocations_url = supervisor_url.rstrip("/") + "/invocations"
                        logger.info(f"Background thread invoking Supervisor for session {sess_id}...")
                        
                        resp = req_lib.post(invocations_url, json={
                            "message": clean_msg,
                            "user_id": f"jira-{auth_id}",
                            "session_id": sess_id
                        }, timeout=120)  # comfortable 120s timeout
                        
                        if resp.status_code == 200:
                            agent_resp_json = resp.json()
                            agent_reply = agent_resp_json.get("response", "")
                            
                            # Add session to state and update redis with jira_issue_key
                            state_data = redis_client.get(f"state:{sess_id}")
                            if state_data:
                                try:
                                    parsed_state = json.loads(state_data)
                                    if not parsed_state.get("jira_issue_key"):
                                        parsed_state["jira_issue_key"] = key
                                        redis_client.set(f"state:{sess_id}", json.dumps(parsed_state))
                                except Exception:
                                    pass
                            else:
                                new_state = {
                                    "session_id": sess_id,
                                    "jira_issue_key": key,
                                    "diagnostic_logs": [],
                                    "messages": [{"role": "user", "content": clean_msg}]
                                }
                                redis_client.set(f"state:{sess_id}", json.dumps(new_state))
                            
                            if agent_reply:
                                add_task_comment(key, agent_reply)
                        else:
                            logger.error(f"Failed to invoke Supervisor: HTTP {resp.status_code} — {resp.text}")
                            add_task_comment(key, "⚠️ Xin lỗi, có lỗi hệ thống xảy ra khi chuyển tiếp yêu cầu đến Supervisor Agent.")
                    except Exception as ex:
                        logger.error(f"Exception in background Supervisor thread: {ex}")
                        add_task_comment(key, f"⚠️ Có lỗi xảy ra trong quá trình xử lý yêu cầu: {ex}")
                
                # Start background thread
                threading.Thread(
                    target=_call_supervisor_and_comment_async, 
                    args=(session_id, clean_comment, author_id, issue_key), 
                    daemon=True
                ).start()
                
                return JSONResponse({
                    "status": "processed_async",
                    "issue_key": issue_key,
                    "message": "Mention detected, processing in background thread"
                })
            
            return JSONResponse({"status": "ignored", "reason": "No mention or self comment"})

        # Check if this is an approval or rework event
        status_name = fields.get("status", {}).get("name", "").lower()
        
        # Handle rework/changes-requested events from L3 Human
        if any(kw in status_name for kw in ["rework", "changes requested", "rejected"]):
            logger.info(f"Webhook for {issue_key}: L3 Human requested rework (status: '{status_name}')")
            
            # Fetch latest comments from Jira to get L3 feedback
            l3_feedback = f"L3 Human changed ticket {issue_key} status to '{status_name}'."
            try:
                comments_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
                resp = req_lib.get(
                    comments_url,
                    auth=(JIRA_USER_EMAIL, JIRA_API_TOKEN),
                    headers={"Accept": "application/json"},
                    timeout=15,
                    params={"orderBy": "-created", "maxResults": 1}
                )
                if resp.status_code == 200:
                    comments = resp.json().get("comments", [])
                    if comments:
                        latest = comments[0]
                        # Extract text from ADF comment body
                        comment_text = ""
                        body_doc = latest.get("body", {})
                        if isinstance(body_doc, dict):
                            for block in body_doc.get("content", []):
                                for node in block.get("content", []):
                                    if node.get("type") == "text":
                                        comment_text += node.get("text", "")
                                comment_text += "\n"
                        if comment_text.strip():
                            l3_feedback = f"L3 Human feedback on {issue_key}: {comment_text.strip()}"
            except Exception as e:
                logger.error(f"Failed to fetch Jira comments for rework: {e}")
            
            # Find session in Redis and re-trigger Supervisor
            try:
                for key in redis_client.scan_iter("state:*"):
                    data_str = redis_client.get(key)
                    if data_str:
                        try:
                            state_data = json.loads(data_str)
                            if state_data.get("jira_issue_key") == issue_key:
                                session_id = state_data.get("session_id", key.split("state:", 1)[1])
                                
                                # Get supervisor URL
                                supervisor_url = redis_client.get("agent:url:supervisor-network-engineer-agent")
                                if supervisor_url:
                                    if supervisor_url.startswith('"') and supervisor_url.endswith('"'):
                                        supervisor_url = supervisor_url[1:-1]
                                    
                                    rework_url = supervisor_url.rstrip("/") + "/invocations"
                                    rework_resp = req_lib.post(rework_url, json={
                                        "action": "l3_rework",
                                        "session_id": session_id,
                                        "l3_feedback": l3_feedback,
                                        "sender": "l3-human-jira"
                                    }, timeout=15)
                                    logger.info(f"L3 rework triggered via Jira webhook for {issue_key}: HTTP {rework_resp.status_code}")
                                    return JSONResponse({
                                        "status": "rework_triggered",
                                        "issue_key": issue_key,
                                        "session_id": session_id
                                    })
                                else:
                                    logger.error("Supervisor URL not found in Redis for rework trigger")
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.error(f"Failed to find session for rework: {e}")
            
            return JSONResponse({"status": "rework_attempted", "issue_key": issue_key})
        
        if "approved" not in status_name and "approve" not in status_name:
            logger.info(f"Webhook for {issue_key}: status '{status_name}' is not an approval or rework. Ignoring.")
            return JSONResponse({"status": "ignored", "reason": "Not an approval or rework event"})

        # Extract device and config from description text (since custom fields are not configured)
        description_doc = fields.get("description", {})
        device_name = ""
        config_payload = ""

        # Parse from ADF description
        if isinstance(description_doc, dict):
            # Extract text content from ADF
            full_text = ""
            for block in description_doc.get("content", []):
                for node in block.get("content", []):
                    if node.get("type") == "text":
                        full_text += node.get("text", "")
                    elif node.get("type") == "hardBreak":
                        full_text += "\n"
                full_text += "\n"

            # Parse device and config from structured description
            import re
            device_match = re.search(r"📍 Device:\s*(.+?)(?:\n|$)", full_text)
            if device_match:
                device_name = device_match.group(1).strip()
                # Extract hostname from "hostname (ip)" format
                if "(" in device_name:
                    device_name = device_name.split("(")[0].strip()

            config_match = re.search(r"--- CONFIGURATION PAYLOAD ---\n(.*?)(?:\n--- |$)", full_text, re.DOTALL)
            if config_match:
                config_payload = config_match.group(1).strip()

        # Robust fallback: Fetch ticket details directly from Jira API if payload lacks details
        if not device_name or not config_payload:
            logger.info(f"Missing device or config in webhook payload for {issue_key}. Fetching details directly from Jira...")
            try:
                jira_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
                resp = req_lib.get(
                    jira_url,
                    auth=(JIRA_USER_EMAIL, JIRA_API_TOKEN),
                    headers={"Accept": "application/json"},
                    timeout=15
                )
                if resp.status_code == 200:
                    jira_data = resp.json()
                    jira_desc = jira_data.get("fields", {}).get("description", {})
                    if isinstance(jira_desc, dict):
                        full_text = ""
                        for block in jira_desc.get("content", []):
                            for node in block.get("content", []):
                                if node.get("type") == "text":
                                    full_text += node.get("text", "")
                                elif node.get("type") == "hardBreak":
                                    full_text += "\n"
                            full_text += "\n"
                        
                        import re
                        device_match = re.search(r"📍 Device:\s*(.+?)(?:\n|$)", full_text)
                        if device_match:
                            device_name = device_match.group(1).strip()
                            if "(" in device_name:
                                device_name = device_name.split("(")[0].strip()

                        config_match = re.search(r"--- CONFIGURATION PAYLOAD ---\n(.*?)(?:\n--- |$)", full_text, re.DOTALL)
                        if config_match:
                            config_payload = config_match.group(1).strip()
                            logger.info(f"Successfully fetched and parsed description from Jira for {issue_key}.")
            except Exception as e:
                logger.error(f"Failed to query Jira for fallback description of {issue_key}: {e}")

        if not device_name or not config_payload:
            logger.error(f"Webhook for {issue_key}: could not parse device or config from description")
            _update_jira_issue_status(issue_key, False, "Failed to parse device or configuration from ticket description.")
            return JSONResponse({"error": "Missing device or config in ticket"}, status_code=400)

        logger.info(f"Webhook: Executing approved change on {device_name}: {config_payload[:100]}...")

        # Execute the config change with careful multi-step process
        success, log_text = _execute_config_change(
            device_name, config_payload,
            description=f"Jira approved: {issue_key}"
        )

        # Update Jira with result
        _update_jira_issue_status(issue_key, success, log_text)

        # --- Trigger callback back to NOC Supervisor Agent & Update Redis State ---
        session_id = None
        try:
            for key in redis_client.scan_iter("state:*"):
                data_str = redis_client.get(key)
                if data_str:
                    try:
                        state_data = json.loads(data_str)
                        if state_data.get("jira_issue_key") == issue_key:
                            session_id = state_data.get("session_id", key.split("state:", 1)[1])
                            break
                    except Exception:
                        continue
        except Exception as scan_err:
            logger.error(f"Failed to scan Redis for issue_key {issue_key}: {scan_err}")

        if session_id:
            state_key = f"state:{session_id}"
            try:
                state_data = redis_client.get(state_key)
                if state_data:
                    state = json.loads(state_data)
                    status_str = "SUCCESS" if success else "FAILED"
                    state["diagnostic_logs"].append(
                        f"L3 Human CAB Approved. Configuration applied to device {device_name} via MCP: {status_str}.\n"
                        f"Log:\n{log_text}"
                    )
                    
                    # If failed, escalate to NOC L3 Engineer
                    if not success:
                        escalation_text = (
                            f"🚨 <b>[CONFIG APPLICATION FAILED]</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"⚠️ <b>Junos Configuration Application Error on Core Device</b>\n"
                            f"▪ <b>Device</b>: <code>{device_name}</code>\n"
                            f"▪ <b>Ticket</b>: <code>{issue_key}</code>\n"
                            f"▪ <b>Session ID</b>: <code>{session_id}</code>\n"
                            f"▪ <b>Error Log</b>:\n<pre>{log_text[:500]}</pre>\n"
                            f"📢 <b>Escalating to NOC L3 Engineers and Manager for manual rollback/intervention. AI agents will continue troubleshooting alternative paths.</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━"
                        )
                        # Send telegram notification (manager / L3 room)
                        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                        tg_chat_id = os.environ.get("TELEGRAM_SLA_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "6405110990")
                        if tg_token and tg_chat_id:
                            try:
                                req_lib.post(
                                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                                    json={"chat_id": tg_chat_id, "text": escalation_text, "parse_mode": "HTML"},
                                    timeout=10
                                )
                            except Exception as tg_err:
                                logger.error(f"Failed to send escalation telegram message: {tg_err}")
                        
                        # Send slack notification to #noc-l3-escalation
                        slack_token = os.environ.get("SLACK_BOT_TOKEN")
                        slack_channel = os.environ.get("SLACK_CHANNEL_L3_ESCALATION", "C0BCJJVL86L")
                        if slack_token and slack_channel:
                            try:
                                req_lib.post(
                                    "https://slack.com/api/chat.postMessage",
                                    json={
                                        "channel": slack_channel,
                                        "text": f"🚨 *[CONFIG APPLICATION FAILED]*\nFailed to apply config to *{device_name}* for ticket *{issue_key}*.\nError:\n```{log_text[:500]}```\nEscalating to NOC L3 Engineers."
                                    },
                                    headers={"Authorization": f"Bearer {slack_token}", "Content-Type": "application/json"},
                                    timeout=10
                                )
                            except Exception as slack_err:
                                logger.error(f"Failed to send escalation slack message: {slack_err}")
                    
                    state["current_assignee"] = "supervisor-network-engineer-agent"
                    redis_client.set(state_key, json.dumps(state))

                    # Trigger supervisor callback in a background thread to prevent Jira webhook timeout
                    supervisor_url = redis_client.get("agent:url:supervisor-network-engineer-agent")
                    if supervisor_url:
                        if supervisor_url.startswith('"') and supervisor_url.endswith('"'):
                            supervisor_url = supervisor_url[1:-1]
                        
                        callback_url = supervisor_url.rstrip("/") + "/invocations"
                        logger.info(f"Triggering supervisor callback at {callback_url}...")
                        
                        def _trigger_callback_async(url, sess_id):
                            try:
                                cb_resp = req_lib.post(url, json={
                                    "action": "callback",
                                    "session_id": sess_id,
                                    "sender": "mcp-server-webhook"
                                }, timeout=30)
                                logger.info(f"Callback to supervisor returned status {cb_resp.status_code}")
                            except Exception as cb_err:
                                logger.error(f"Failed to send callback to supervisor: {cb_err}")
                        
                        import threading
                        threading.Thread(target=_trigger_callback_async, args=(callback_url, session_id), daemon=True).start()
                    else:
                        logger.warning("Supervisor URL not in Redis, cannot trigger callback.")
            except Exception as redis_err:
                logger.error(f"Failed to update state and trigger callback for {session_id}: {redis_err}")

        return JSONResponse({
            "status": "success" if success else "failed",
            "issue_key": issue_key,
            "device": device_name,
            "log": log_text,
        })

    # Add webhook route to the FastMCP app
    webhook_route = Route("/webhook/jira", jira_webhook_handler, methods=["POST"])

    # --- Admin API endpoints for the web UI ---
    async def admin_get_operations(request: Request) -> JSONResponse:
        """List/search operation commands from SQLite DB."""
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 20))
        vendor = request.query_params.get("vendor", "")
        risk_level = request.query_params.get("risk_level", "")
        search = request.query_params.get("search", "")

        try:
            conn = sqlite3.connect(OPERATION_COMMANDS_DB)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            if search:
                fts_query = search.replace('"', '""')
                count_sql = "SELECT count(*) FROM operation_commands_fts fts JOIN operation_commands oc ON fts.rowid = oc.id WHERE operation_commands_fts MATCH ?"
                data_sql = """SELECT oc.* FROM operation_commands_fts fts
                    JOIN operation_commands oc ON fts.rowid = oc.id
                    WHERE operation_commands_fts MATCH ?"""
                params = [fts_query]
            else:
                count_sql = "SELECT count(*) FROM operation_commands WHERE 1=1"
                data_sql = "SELECT * FROM operation_commands WHERE 1=1"
                params = []

            if vendor:
                count_sql += " AND vendor = ?"
                data_sql += " AND oc.vendor = ?" if search else " AND vendor = ?"
                params.append(vendor)
            if risk_level:
                count_sql += " AND risk_level = ?"
                data_sql += " AND oc.risk_level = ?" if search else " AND risk_level = ?"
                params.append(risk_level)

            cur.execute(count_sql, params)
            total = cur.fetchone()[0]

            data_sql += f" LIMIT {limit} OFFSET {(page - 1) * limit}"
            cur.execute(data_sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()

            return JSONResponse({"items": rows, "total": total, "page": page})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_update_operation(request: Request) -> JSONResponse:
        """Update an operation command."""
        op_id = request.path_params["id"]
        data = await request.json()
        try:
            conn = sqlite3.connect(OPERATION_COMMANDS_DB)
            cur = conn.cursor()
            cur.execute(
                "UPDATE operation_commands SET command_name=?, vendor=?, risk_level=?, short_desc=?, syntax=? WHERE id=?",
                (data.get("command_name"), data.get("vendor"), data.get("risk_level"),
                 data.get("short_desc"), data.get("syntax"), op_id)
            )
            conn.commit()
            conn.close()
            return JSONResponse({"status": "ok"})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_add_operation(request: Request) -> JSONResponse:
        """Add a new operation command."""
        data = await request.json()
        try:
            conn = sqlite3.connect(OPERATION_COMMANDS_DB)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO operation_commands (vendor, command_name, short_desc, risk_level, syntax) VALUES (?, ?, ?, ?, ?)",
                (data.get("vendor", "juniper"), data.get("command_name"), data.get("short_desc"),
                 data.get("risk_level", "INFO"), data.get("syntax"))
            )
            conn.commit()
            new_id = cur.lastrowid
            conn.close()
            return JSONResponse({"status": "ok", "id": new_id})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_get_configurations(request: Request) -> JSONResponse:
        """List/search configuration statements from SQLite DB."""
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 20))
        vendor = request.query_params.get("vendor", "")
        search = request.query_params.get("search", "")

        try:
            conn = sqlite3.connect(CONFIG_STATEMENTS_DB)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            if search:
                fts_query = search.replace('"', '""')
                count_sql = "SELECT count(*) FROM config_statements_fts fts JOIN config_statements cs ON fts.rowid = cs.id WHERE config_statements_fts MATCH ?"
                data_sql = """SELECT cs.* FROM config_statements_fts fts
                    JOIN config_statements cs ON fts.rowid = cs.id
                    WHERE config_statements_fts MATCH ?"""
                params = [fts_query]
            else:
                count_sql = "SELECT count(*) FROM config_statements WHERE 1=1"
                data_sql = "SELECT * FROM config_statements WHERE 1=1"
                params = []

            if vendor:
                count_sql += " AND vendor = ?"
                data_sql += " AND cs.vendor = ?" if search else " AND vendor = ?"
                params.append(vendor)

            cur.execute(count_sql, params)
            total = cur.fetchone()[0]

            data_sql += f" LIMIT {limit} OFFSET {(page - 1) * limit}"
            cur.execute(data_sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()

            return JSONResponse({"items": rows, "total": total, "page": page})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_update_configuration(request: Request) -> JSONResponse:
        """Update a configuration statement."""
        cfg_id = request.path_params["id"]
        data = await request.json()
        try:
            conn = sqlite3.connect(CONFIG_STATEMENTS_DB)
            cur = conn.cursor()
            cur.execute(
                "UPDATE config_statements SET statement_name=?, vendor=?, short_desc=?, syntax=?, hierarchy_level=? WHERE id=?",
                (data.get("statement_name"), data.get("vendor"), data.get("short_desc"),
                 data.get("syntax"), data.get("hierarchy_level"), cfg_id)
            )
            conn.commit()
            conn.close()
            return JSONResponse({"status": "ok"})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_add_configuration(request: Request) -> JSONResponse:
        """Add a new configuration statement."""
        data = await request.json()
        try:
            conn = sqlite3.connect(CONFIG_STATEMENTS_DB)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO config_statements (vendor, statement_name, short_desc, syntax, hierarchy_level) VALUES (?, ?, ?, ?, ?)",
                (data.get("vendor", "juniper"), data.get("statement_name"), data.get("short_desc"),
                 data.get("syntax"), data.get("hierarchy_level"))
            )
            conn.commit()
            new_id = cur.lastrowid
            conn.close()
            return JSONResponse({"status": "ok", "id": new_id})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_get_devices(request: Request) -> JSONResponse:
        """List all devices from DEVICE_MAP."""
        devices = []
        for name, info in DEVICE_MAP.items():
            devices.append({
                "name": name,
                "hostname": name,
                **info,
            })
        return JSONResponse(devices)

    async def admin_add_device(request: Request) -> JSONResponse:
        """Add a new device to the inventory."""
        data = await request.json()
        name = data.get("name", "")
        if not name or not data.get("ip"):
            return JSONResponse({"error": "Name and IP are required"}, status_code=400)

        # Add to DEVICE_MAP
        DEVICE_MAP[name] = {
            "ip": data["ip"],
            "port": data.get("port", 830),
            "model": data.get("model", "Unknown"),
            "vendor": data.get("vendor", "juniper"),
            "connection_method": data.get("connection_method", "netconf"),
            "role": data.get("role", ""),
            "status": "Online",
        }

        # Save to devices.json
        try:
            devices_data = {"devices": {}}
            for dname, dinfo in DEVICE_MAP.items():
                devices_data["devices"][dname] = {"name": dname, **dinfo}
            with open(DEVICES_FILE, "w") as f:
                json.dump(devices_data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save devices.json: {e}")

    async def admin_get_sessions(request: Request) -> JSONResponse:
        """List all AI agent session states from Redis."""
        try:
            keys = redis_client.keys("state:*")
            sessions = []
            for key in keys:
                session_id = key.split("state:", 1)[1]
                data = redis_client.get(key)
                if data:
                    try:
                        session_data = json.loads(data)
                        sessions.append(session_data)
                    except json.JSONDecodeError:
                        sessions.append({
                            "session_id": session_id,
                            "error": "Failed to decode state JSON"
                        })
            sessions.sort(key=lambda s: s.get("session_id", ""), reverse=True)
            return JSONResponse(sessions)
        except Exception as e:
            logger.error(f"Failed to get Redis sessions: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_get_session(request: Request) -> JSONResponse:
        """Get details of a specific session."""
        session_id = request.path_params["session_id"]
        try:
            data = redis_client.get(f"state:{session_id}")
            if not data:
                return JSONResponse({"error": f"Session {session_id} not found"}, status_code=404)
            return JSONResponse(json.loads(data))
        except Exception as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_clear_session(request: Request) -> JSONResponse:
        """Delete/clear a session in Redis."""
        session_id = request.path_params["session_id"]
        try:
            res = redis_client.delete(f"state:{session_id}")
            return JSONResponse({"status": "ok", "deleted": bool(res)})
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_trigger_parser(request: Request) -> JSONResponse:
        """Trigger NOC Supervisor Agent with a parsed customer request."""
        try:
            data = await request.json()
            message = data.get("message", "")
            if not message:
                return JSONResponse({"error": "Message is required"}, status_code=400)

            # Get supervisor endpoint URL from Redis
            supervisor_url = redis_client.get("agent:url:supervisor-network-engineer-agent")
            if not supervisor_url:
                return JSONResponse({"error": "Supervisor agent URL not found in Redis"}, status_code=404)

            # Remove potential JSON string wrapping quotes
            if supervisor_url.startswith('"') and supervisor_url.endswith('"'):
                supervisor_url = supervisor_url[1:-1]

            import time
            session_id = f"REQ-{int(time.time())}"
            url = f"{supervisor_url.rstrip('/')}/invocations"

            logger.info(f"Triggering NOC Supervisor at {url} with session {session_id}...")
            
            # Make HTTP post request
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "message": message,
                        "session_id": session_id,
                        "user_id": "noc-admin-portal"
                    }
                )
            
            if resp.status_code == 200:
                result = resp.json()
                return JSONResponse({
                    "status": "success",
                    "session_id": session_id,
                    "response": result.get("response", "Workflow triggered successfully.")
                })
            else:
                return JSONResponse({
                    "error": f"Failed to trigger supervisor. Agent returned {resp.status_code}: {resp.text}"
                }, status_code=502)

        except Exception as e:
            logger.error(f"Error triggering NOC Supervisor: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    async def admin_get_tools(request: Request) -> JSONResponse:
        """List all tools registered in the FastMCP server."""
        try:
            tools = await mcp.list_tools()
            tool_list = []
            for t in tools:
                tool_list.append({
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.inputSchema
                })
            tool_list.sort(key=lambda x: x["name"])
            return JSONResponse(tool_list)
        except Exception as e:
            logger.error(f"Failed to list FastMCP tools: {e}", exc_info=True)
            return JSONResponse({"error": str(e)}, status_code=500)

    # Admin static files
    from starlette.staticfiles import StaticFiles

    admin_routes = [
        Route("/admin/api/operations", admin_get_operations, methods=["GET"]),
        Route("/admin/api/operations", admin_add_operation, methods=["POST"]),
        Route("/admin/api/operations/{id:int}", admin_update_operation, methods=["PUT"]),
        Route("/admin/api/configurations", admin_get_configurations, methods=["GET"]),
        Route("/admin/api/configurations", admin_add_configuration, methods=["POST"]),
        Route("/admin/api/configurations/{id:int}", admin_update_configuration, methods=["PUT"]),
        Route("/admin/api/devices", admin_get_devices, methods=["GET"]),
        Route("/admin/api/devices", admin_add_device, methods=["POST"]),
        Route("/admin/api/sessions", admin_get_sessions, methods=["GET"]),
        Route("/admin/api/sessions/{session_id}", admin_get_session, methods=["GET"]),
        Route("/admin/api/sessions/{session_id}/clear", admin_clear_session, methods=["POST"]),
        Route("/admin/api/parser/trigger", admin_trigger_parser, methods=["POST"]),
        Route("/admin/api/tools", admin_get_tools, methods=["GET"]),
    ]



    logger.info(f"Starting FastMCP server with SSE transport on port {MCP_PORT}...")
    logger.info(f"Jira webhook endpoint: POST /webhook/jira")
    logger.info(f"Admin UI: http://0.0.0.0:{MCP_PORT}/admin/")
    logger.info(f"Command timeout: {COMMAND_TIMEOUT}s")

    # Start the MCP server with webhook + admin routes added
    import uvicorn
    from starlette.applications import Starlette
    from starlette.middleware import Middleware

    # Get the MCP app and add our routes
    mcp_app = mcp.sse_app()
    mcp_app.routes.append(webhook_route)
    for route in admin_routes:
        mcp_app.routes.append(route)

    # Mount admin static files
    admin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin")
    if os.path.isdir(admin_dir):
        mcp_app.mount("/admin", StaticFiles(directory=admin_dir, html=True), name="admin")
        logger.info(f"Admin UI mounted from {admin_dir}")

    uvicorn.run(mcp_app, host="0.0.0.0", port=MCP_PORT)
