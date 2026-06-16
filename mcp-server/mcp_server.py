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
        }
        device_type = vendor_netmiko_map.get(vendor, f"{vendor}_ssh")

        net_connect = ConnectHandler(
            device_type=device_type,
            host=ip,
            username=NETCONF_USER,
            password=NETCONF_PASSWORD,
            port=port,
            timeout=15,
        )
        return net_connect
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
    if timeout is None:
        timeout = COMMAND_TIMEOUT

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
        }
        device_type = vendor_netmiko_map.get(vendor, f"{vendor}_ssh")

        try:
            net_connect = ConnectHandler(
                device_type=device_type,
                host=device_info_full["ip"],
                username=NETCONF_USER,
                password=NETCONF_PASSWORD,
                port=device_info_full["port"],
                timeout=timeout,
            )
            output = net_connect.send_command(command, read_timeout=timeout)
            net_connect.disconnect()
            return output or f"No output returned by command '{command}' on {device_name}."
        except Exception as e:
            return f"Error executing SSH command '{command}' on '{device_name}': {e}"

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
                "get_device_detail"
            ],
            "expert-engineer-agent": [
                "update_task_status", 
                "add_task_comment", 
                "check_task_status",
                "view_network_status", 
                "lookup_command_dictionary",
                "get_devices_list",
                "get_device_detail",
                "get_device_configuration_list",
                "get_device_configuration_detail"
            ],
            "customer-advisory-agent": [
                "update_task_status", 
                "add_task_comment", 
                "remove_jira_task",
                "check_task_status"
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


# ===================================================================
# TOOL 1: view_network_status (Fast-Track — Read-only with Command ACL)
# Replaces get_device_operation_detail with ACL enforcement
# ===================================================================

@mcp.tool()
def view_network_status(device_ip: str, command: str) -> str:
    """Execute a read-only operational command on a network device (Fast-Track).

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


# Keep legacy name as an alias for backward compatibility
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


# ===================================================================
# TOOL 2: lookup_command_dictionary (Query internal command/config DB)
# ===================================================================

@mcp.tool()
def lookup_command_dictionary(
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


@mcp.tool()
def propose_network_change(
    device_ip: str,
    config_payload: str,
    reason: str,
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

    # Build Jira ticket
    summary = f"[Network Change] {device_display}: {reason[:80]}"
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
    filters: str = "",
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
        filters: Optional JSON string of metadata filters to narrow scope (e.g., '{"source": "kb"}' or '{"source": "book"}').
    """
    logger.info(f"Executing tool: query_knowledge_base for '{query}' (filters: {filters})")

    source = None
    if filters:
        try:
            import json
            filter_data = json.loads(filters)
            if isinstance(filter_data, dict):
                source = filter_data.get("source") or filter_data.get("source_type")
        except Exception as e:
            logger.warning(f"Failed to parse filters JSON '{filters}': {e}")

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


# ===================================================================
# GIT OPERATIONS (kept — version control is read/write safe)
# ===================================================================

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


# ===================================================================
# MONITORING TOOLS (Prometheus & Loki)
# ===================================================================

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


# ===================================================================
# IPAM & NETWORK ASSET TOOLS (NetBox-like API response format)
# ===================================================================

@mcp.tool()
def query_netbox_inventory(resource_type: str, query: Optional[str] = None) -> str:
    """Query NetBox inventory tables (tenants, devices, vlans, interfaces, ip-addresses).
    Returns a NetBox API-like JSON response structure.
    
    Args:
        resource_type: Type of resource to query. Allowed values: 'tenants', 'devices', 'vlans', 'interfaces', 'ip-addresses'.
        query: Optional string to filter results (e.g. device name, IP address, VLAN ID, tenant name).
    """
    logger.info(f"Executing tool: query_netbox_inventory for resource '{resource_type}' with query '{query}'")
    
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
        
        if res_type == "tenants":
            sql = "SELECT id, name, slug, description FROM netbox_tenants"
            params = []
            if query:
                sql += " WHERE name LIKE ? OR slug LIKE ? OR description LIKE ?"
                like_q = f"%{query}%"
                params = [like_q, like_q, like_q]
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
            """
            params = []
            if query:
                sql += """ WHERE d.name LIKE ? OR d.model LIKE ? OR d.role LIKE ? 
                           OR d.rack LIKE ? OR d.primary_ip LIKE ? OR t.name LIKE ?"""
                like_q = f"%{query}%"
                params = [like_q, like_q, like_q, like_q, like_q, like_q]
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
            """
            params = []
            if query:
                is_num = False
                try:
                    int_val = int(query)
                    is_num = True
                except ValueError:
                    pass
                
                if is_num:
                    sql += " WHERE v.vid = ? OR v.name LIKE ? OR t.name LIKE ?"
                    params = [int_val, f"%{query}%", f"%{query}%"]
                else:
                    sql += " WHERE v.name LIKE ? OR t.name LIKE ? OR v.description LIKE ?"
                    like_q = f"%{query}%"
                    params = [like_q, like_q, like_q]
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
                       v.vid as vlan_vid, v.name as vlan_name
                FROM netbox_interfaces i
                LEFT JOIN netbox_devices d ON i.device_id = d.id
                LEFT JOIN netbox_vlans v ON i.untagged_vlan_id = v.id
            """
            params = []
            if query:
                sql += " WHERE i.name LIKE ? OR d.name LIKE ? OR i.mac_address LIKE ? OR i.mode LIKE ?"
                like_q = f"%{query}%"
                params = [like_q, like_q, like_q, like_q]
            cur.execute(sql, params)
            for row in cur.fetchall():
                vlan_info = None
                if row["untagged_vlan_id"]:
                    vlan_info = {
                        "id": row["untagged_vlan_id"],
                        "vid": row["vlan_vid"],
                        "name": row["vlan_name"]
                    }
                results.append({
                    "id": row["id"],
                    "name": row["name"],
                    "device": {"id": row["device_id"], "name": row["device_name"]},
                    "enabled": bool(row["enabled"]),
                    "mac_address": row["mac_address"],
                    "mode": {"value": row["mode"], "label": row["mode"].capitalize()} if row["mode"] else None,
                    "untagged_vlan": vlan_info
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
            """
            params = []
            if query:
                sql += " WHERE ip.address LIKE ? OR ip.description LIKE ? OR t.name LIKE ? OR d.name LIKE ?"
                like_q = f"%{query}%"
                params = [like_q, like_q, like_q, like_q]
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

@mcp.tool()
def query_vlan_ip(vlan_id: Optional[int] = None, subnet: Optional[str] = None) -> str:
    """Query VLANs and IP addresses from the network assets.
    Returns NetBox API-like JSON structures.
    """
    logger.info(f"Executing tool: query_vlan_ip vlan_id={vlan_id}, subnet={subnet}")
    try:
        conn = sqlite3.connect(NETWORK_ASSETS_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        vlans = []
        ip_addresses = []
        
        vlan_sql = """
            SELECT v.id, v.vid, v.name, v.status, v.tenant_id, v.description,
                   t.name as tenant_name, t.slug as tenant_slug
            FROM netbox_vlans v
            LEFT JOIN netbox_tenants t ON v.tenant_id = t.id
        """
        vlan_params = []
        if vlan_id is not None:
            vlan_sql += " WHERE v.vid = ?"
            vlan_params.append(vlan_id)
        cur.execute(vlan_sql, vlan_params)
        for row in cur.fetchall():
            vlans.append({
                "id": row["id"],
                "vid": row["vid"],
                "name": row["name"],
                "status": {"value": row["status"], "label": row["status"].capitalize()},
                "tenant": {
                    "id": row["tenant_id"],
                    "name": row["tenant_name"],
                    "slug": row["tenant_slug"]
                } if row["tenant_id"] else None,
                "description": row["description"]
            })
            
        ip_sql = """
            SELECT ip.id, ip.address, ip.status, ip.assigned_interface_id, ip.tenant_id, ip.description,
                   t.name as tenant_name, t.slug as tenant_slug,
                   i.name as interface_name, i.device_id,
                   d.name as device_name
            FROM netbox_ip_addresses ip
            LEFT JOIN netbox_tenants t ON ip.tenant_id = t.id
            LEFT JOIN netbox_interfaces i ON ip.assigned_interface_id = i.id
            LEFT JOIN netbox_devices d ON i.device_id = d.id
        """
        ip_params = []
        if subnet is not None:
            ip_sql += " WHERE ip.address LIKE ?"
            ip_params.append(f"{subnet}%")
        cur.execute(ip_sql, ip_params)
        for row in cur.fetchall():
            ip_addresses.append({
                "id": row["id"],
                "address": row["address"],
                "status": {"value": row["status"], "label": row["status"].capitalize()},
                "assigned_object": {
                    "id": row["assigned_interface_id"],
                    "name": row["interface_name"],
                    "device": {
                        "id": row["device_id"],
                        "name": row["device_name"]
                    }
                } if row["assigned_interface_id"] else None,
                "tenant": {
                    "id": row["tenant_id"],
                    "name": row["tenant_name"],
                    "slug": row["tenant_slug"]
                } if row["tenant_id"] else None,
                "description": row["description"]
            })
            
        conn.close()
        return json.dumps({
            "vlans": vlans,
            "ip_addresses": ip_addresses
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error executing query_vlan_ip: {e}")
        return json.dumps({"error": str(e)}, indent=2)

@mcp.tool()
def query_servers(hostname: Optional[str] = None, ip_address: Optional[str] = None) -> str:
    """Query server devices from the network assets database.
    Returns NetBox API-like JSON response structure.
    """
    logger.info(f"Executing tool: query_servers hostname={hostname}, ip_address={ip_address}")
    try:
        conn = sqlite3.connect(NETWORK_ASSETS_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        sql = """
            SELECT d.id, d.name, d.model, d.role, d.rack, d.primary_ip, d.tenant_id,
                   t.name as tenant_name, t.slug as tenant_slug
            FROM netbox_devices d
            LEFT JOIN netbox_tenants t ON d.tenant_id = t.id
            WHERE d.role = 'Server'
        """
        params = []
        if hostname:
            sql += " AND d.name LIKE ?"
            params.append(f"%{hostname}%")
        if ip_address:
            sql += " AND d.primary_ip LIKE ?"
            params.append(f"%{ip_address}%")
            
        cur.execute(sql, params)
        results = []
        for row in cur.fetchall():
            results.append({
                "id": row["id"],
                "name": row["name"],
                "model": {"name": row["model"]},
                "role": {"name": row["role"]},
                "rack": {"name": row["rack"]},
                "primary_ip": {"address": row["primary_ip"]} if row["primary_ip"] else None,
                "tenant": {
                    "id": row["tenant_id"],
                    "name": row["tenant_name"],
                    "slug": row["tenant_slug"]
                } if row["tenant_id"] else None
            })
            
        conn.close()
        return json.dumps({
            "count": len(results),
            "results": results
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error executing query_servers: {e}")
        return json.dumps({"error": str(e)}, indent=2)

@mcp.tool()
def query_customers(customer_id: Optional[int] = None, name_query: Optional[str] = None) -> str:
    """Query customer tenants from the network assets database.
    Returns NetBox API-like JSON response structure.
    """
    logger.info(f"Executing tool: query_customers customer_id={customer_id}, name_query={name_query}")
    try:
        conn = sqlite3.connect(NETWORK_ASSETS_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        sql = "SELECT id, name, slug, description FROM netbox_tenants WHERE 1=1"
        params = []
        if customer_id is not None:
            sql += " AND id = ?"
            params.append(customer_id)
        if name_query:
            sql += " AND (name LIKE ? OR slug LIKE ?)"
            like_q = f"%{name_query}%"
            params.extend([like_q, like_q])
            
        cur.execute(sql, params)
        results = []
        for row in cur.fetchall():
            results.append({
                "id": row["id"],
                "name": row["name"],
                "slug": row["slug"],
                "description": row["description"]
            })
            
        conn.close()
        return json.dumps({
            "count": len(results),
            "results": results
        }, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error executing query_customers: {e}")
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
def query_device_licenses(device_name: Optional[str] = None) -> str:
    """Query device license details from the database.
    
    Args:
        device_name: Optional device name to filter by.
    """
    logger.info(f"Executing tool: query_device_licenses device_name={device_name}")
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

@mcp.tool()
def create_jira_task(summary: str, description: str, issue_type: str = "Task") -> str:
    """Create a new ticket on the Jira KAN board. issue_type can be 'Task', 'Incident', 'Service Request', or 'Change Request'."""
    if not _is_jira_configured():
        return "Error: Jira is not configured. Missing JIRA_BASE_URL, JIRA_USER_EMAIL, or JIRA_API_TOKEN."

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": summary,
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
                f"Summary: {summary}"
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

        # Check if this is an approval event
        status_name = fields.get("status", {}).get("name", "").lower()
        if "approved" not in status_name and "approve" not in status_name:
            logger.info(f"Webhook for {issue_key}: status '{status_name}' is not an approval. Ignoring.")
            return JSONResponse({"status": "ignored", "reason": "Not an approval event"})

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
