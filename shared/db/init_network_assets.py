import os
import json
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "network_assets.db")
DEVICES_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "devices.json")

def link_interfaces(cur, dev1, port1, dev2, port2):
    """Helper to link two interfaces bidsirectionally via connected_interface_id."""
    cur.execute("""
        SELECT i.id FROM netbox_interfaces i 
        JOIN netbox_devices d ON i.device_id = d.id 
        WHERE d.name = ? AND i.name = ?
    """, (dev1, port1))
    row1 = cur.fetchone()
    
    cur.execute("""
        SELECT i.id FROM netbox_interfaces i 
        JOIN netbox_devices d ON i.device_id = d.id 
        WHERE d.name = ? AND i.name = ?
    """, (dev2, port2))
    row2 = cur.fetchone()
    
    if row1 and row2:
        id1 = row1[0]
        id2 = row2[0]
        cur.execute("UPDATE netbox_interfaces SET connected_interface_id = ? WHERE id = ?", (id2, id1))
        cur.execute("UPDATE netbox_interfaces SET connected_interface_id = ? WHERE id = ?", (id1, id2))
    else:
        print(f"Warning: Could not link {dev1} {port1} <---> {dev2} {port2} (Interface not found)")

def main():
    print(f"Loading device profiles from {DEVICES_JSON_PATH}...")
    if not os.path.exists(DEVICES_JSON_PATH):
        print(f"Error: {DEVICES_JSON_PATH} not found!")
        return

    with open(DEVICES_JSON_PATH, "r") as f:
        data = json.load(f)
    
    devices_data = data.get("devices", data)
    print(f"Found {len(devices_data)} devices in inventory.")

    print(f"Initializing database at {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Drop existing tables if they exist
    cur.execute("DROP TABLE IF EXISTS netbox_tenants")
    cur.execute("DROP TABLE IF EXISTS netbox_devices")
    cur.execute("DROP TABLE IF EXISTS netbox_vlans")
    cur.execute("DROP TABLE IF EXISTS netbox_interfaces")
    cur.execute("DROP TABLE IF EXISTS netbox_ip_addresses")
    cur.execute("DROP TABLE IF EXISTS licenses")
    cur.execute("DROP TABLE IF EXISTS device_warranty")

    # Create Tables
    cur.execute("""
    CREATE TABLE netbox_tenants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT NOT NULL,
        description TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE netbox_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        model TEXT NOT NULL,
        role TEXT NOT NULL,
        rack TEXT NOT NULL,
        primary_ip TEXT,
        tenant_id INTEGER,
        FOREIGN KEY (tenant_id) REFERENCES netbox_tenants(id)
    )
    """)

    cur.execute("""
    CREATE TABLE netbox_vlans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vid INTEGER NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        tenant_id INTEGER,
        description TEXT,
        FOREIGN KEY (tenant_id) REFERENCES netbox_tenants(id)
    )
    """)

    cur.execute("""
    CREATE TABLE netbox_interfaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        device_id INTEGER NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        mac_address TEXT,
        mode TEXT,
        untagged_vlan_id INTEGER,
        connected_interface_id INTEGER,
        FOREIGN KEY (device_id) REFERENCES netbox_devices(id),
        FOREIGN KEY (untagged_vlan_id) REFERENCES netbox_vlans(id),
        FOREIGN KEY (connected_interface_id) REFERENCES netbox_interfaces(id)
    )
    """)

    cur.execute("""
    CREATE TABLE netbox_ip_addresses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        address TEXT NOT NULL,
        status TEXT NOT NULL,
        assigned_interface_id INTEGER,
        tenant_id INTEGER,
        description TEXT,
        FOREIGN KEY (assigned_interface_id) REFERENCES netbox_interfaces(id),
        FOREIGN KEY (tenant_id) REFERENCES netbox_tenants(id)
    )
    """)

    cur.execute("""
    CREATE TABLE licenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_name TEXT NOT NULL,
        license_key TEXT NOT NULL,
        features TEXT,
        expiry_date TEXT,
        status TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE device_warranty (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_name TEXT NOT NULL,
        serial_number TEXT NOT NULL,
        warranty_package TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        status TEXT NOT NULL
    )
    """)

    # Insert Sample Data
    # 1. Tenants (Customers)
    tenants = [
        (1, "VNG Cloud Tenants", "vng-cloud-tenants", "Internal cloud platform tenants"),
        (2, "Customer A (Viettel IDC)", "customer-a", "Premium Customer A co-located at Viettel IDC"),
        (3, "Customer B (FPT Telecom)", "customer-b", "Customer B using core routing fabric"),
        (4, "NOC Operations Team", "noc-ops", "Internal operations network management"),
        (5, "Customer-001", "customer-001", "Customer-001 with proxy server"),
    ]
    cur.executemany("INSERT INTO netbox_tenants VALUES (?,?,?,?)", tenants)

    # 2. VLANs (IPAM)
    vlans = [
        (1, 100, "VLAN_100_PROD_A", "active", 2, "Production VLAN for Customer A"),
        (2, 101, "VLAN_101_DB_A", "active", 2, "Database private network for Customer A"),
        (3, 200, "VLAN_200_WEB_B", "active", 3, "Web App VLAN for Customer B"),
        (4, 999, "VLAN_999_MGMT", "active", 4, "NOC Infrastructure Management Network"),
        (5, 300, "VLAN_300_PROXY_001", "active", 5, "Proxy Server VLAN for Customer-001"),
    ]
    cur.executemany("INSERT INTO netbox_vlans VALUES (?,?,?,?,?,?)", vlans)

    device_records = []
    interface_records = []
    ip_records = []
    license_records = []
    warranty_records = []
    
    device_id = 1
    interface_id = 1
    ip_id = 1
    license_id = 1
    warranty_id = 1

    # Add active lab devices from devices.json
    for dev_name, info in devices_data.items():
        role = info.get("role", "Switch")
        model = info.get("model", "Unknown")
        primary_ip = info.get("ip")
        vendor = info.get("vendor", "juniper").lower()
        
        # Determine tenant assignment based on name and role
        if dev_name in ["noc-portal-app", "net-monitor"]:
            tenant_id = 4  # NOC Operations Team
        elif "VNPT" in dev_name:
            tenant_id = 3  # Customer B
        else:
            tenant_id = 4  # NOC Operations Team
            
        # Determine rack assignment
        if role == "Server":
            rack = "Rack-C01"
        elif "Spine" in role:
            rack = "Rack-A01"
        elif "Leaf" in role or "ToR" in role:
            rack = "Rack-B01"
        else:
            rack = "Rack-D01"
            
        device_records.append((device_id, dev_name, model, role, rack, primary_ip, tenant_id))
        
        # Create management interface
        if role == "Server":
            mgmt_if_name = "eth0"
        elif vendor == "juniper":
            mgmt_if_name = "me0"
        else:
            mgmt_if_name = "em0"
            
        mac_addr = f"00:50:56:{device_id:02x}:11:aa"
        interface_records.append((interface_id, mgmt_if_name, device_id, 1, mac_addr, "access", 4, None)) # mgmt vlan 4 (vid 999)
        
        # IP Address for management interface
        if primary_ip:
            ip_address = primary_ip if "/" in primary_ip else f"{primary_ip}/24"
            ip_records.append((ip_id, ip_address, "active", interface_id, tenant_id, f"{dev_name} Management IP"))
            ip_id += 1
            
        interface_id += 1
        
        # Add traffic interfaces per device type
        if "Spine" in role:
            # CLOS-3 Gateways: Spines host the L3 IRB Gateways for Customer VLANs (VLAN 100, 101, 200)
            irb_interfaces = [
                ("irb.100", 1, 2, f"10.100.0.{1 if '01' in dev_name else 2}/24", "Customer A VLAN 100 Gateway"),
                ("irb.101", 2, 2, f"10.101.0.{1 if '01' in dev_name else 2}/24", "Customer A VLAN 101 Gateway"),
                ("irb.200", 3, 3, f"10.200.0.{1 if '01' in dev_name else 2}/24", "Customer B VLAN 200 Gateway")
            ]
            for irb_name, vlan_idx, vlan_tenant, irb_ip, irb_desc in irb_interfaces:
                interface_records.append((interface_id, irb_name, device_id, 1, None, None, vlan_idx, None))
                ip_records.append((ip_id, irb_ip, "active", interface_id, vlan_tenant, irb_desc))
                interface_id += 1
                ip_id += 1
            
            # Physical uplinks to Leafs
            for port_idx in range(1, 10):
                traffic_if_name = f"et-0/0/{port_idx}"
                traffic_mac = f"00:50:56:{device_id:02x}:22:{port_idx:02x}"
                interface_records.append((interface_id, traffic_if_name, device_id, 1, traffic_mac, "trunk", None, None))
                interface_id += 1
                
        elif "Leaf" in role or "Switch" in role or "ToR" in role:
            # Physical uplinks to Spines (et-0/0/1 to et-0/0/4 for dual-homed LACP bonding to 2 Spines)
            for port_idx in range(1, 5):
                uplink_name = f"et-0/0/{port_idx}"
                uplink_mac = f"00:50:56:{device_id:02x}:22:{port_idx:02x}"
                interface_records.append((interface_id, uplink_name, device_id, 1, uplink_mac, "trunk", None, None))
                interface_id += 1
                
            # Access ports to Servers (ge-0/0/1 to ge-0/0/9)
            for port_idx in range(1, 10):
                traffic_if_name = f"ge-0/0/{port_idx}"
                traffic_mac = f"00:50:56:{device_id:02x}:33:{port_idx:02x}"
                # Distribute interfaces across tenant VLANs
                if port_idx <= 3:
                    untagged_vlan = 1  # VLAN 100 (Customer A)
                elif port_idx <= 6:
                    untagged_vlan = 2  # VLAN 101 (Customer A)
                else:
                    untagged_vlan = 3  # VLAN 200 (Customer B)
                
                interface_records.append((interface_id, traffic_if_name, device_id, 1, traffic_mac, "access", untagged_vlan, None))
                interface_id += 1
                
        elif "Gateway Router" in role:
            # ge-0/0/47 for Proxy connection
            traffic_if_name = "ge-0/0/47"
            traffic_mac = f"00:50:56:{device_id:02x}:33:47"
            interface_records.append((interface_id, traffic_if_name, device_id, 1, traffic_mac, "access", 5, None)) # VLAN 300 (Customer-001)
            interface_id += 1
            
        # Generate licenses
        if vendor == "juniper":
            lic_key = f"JUNOS-{model.upper()}-ADV-{device_id:04d}"
            features = "BGP-EVPN, MPLS, VXLAN Features, Advanced Telemetry"
            expiry = "2030-12-31" if device_id % 5 != 0 else "2024-05-15"
            status = "ACTIVE" if device_id % 5 != 0 else "EXPIRED"
            license_records.append((license_id, dev_name, lic_key, features, expiry, status))
            license_id += 1
        elif vendor == "ubuntu":
            lic_key = f"UBUNTU-SUPPORT-{device_id:04d}"
            features = "Landscape, ESM Security Patches 24/7 Support"
            expiry = "2029-06-30"
            status = "ACTIVE"
            license_records.append((license_id, dev_name, lic_key, features, expiry, status))
            license_id += 1
            
        # Generate warranty
        serial = f"JN{device_id:03d}X{device_id*7:03d}" if vendor == "juniper" else f"UB{device_id:03d}X{device_id*13:03d}"
        package = "VNG Premium Care 24/7/4" if device_id % 2 == 0 else "Standard NBD Hardware Replacement"
        w_status = "ACTIVE" if device_id % 10 != 0 else "EXPIRED"
        expiry_date = "2028-06-01" if device_id % 10 != 0 else "2025-06-01"
        warranty_records.append((warranty_id, dev_name, serial, package, "2021-06-01", expiry_date, w_status))
        warranty_id += 1
        
        device_id += 1

    # Add custom Customer Servers (Dual-homed eth0 & eth1 for LACP bonding)
    custom_servers = [
        # Customer A Web servers (VLAN 100)
        {"name": "customer-a-web-01", "ip": "10.100.0.50", "tenant_id": 2, "rack": "Rack-C02", "vlan": 1, "desc": "Customer A Production Web Server 01"},
        {"name": "customer-a-web-02", "ip": "10.100.0.51", "tenant_id": 2, "rack": "Rack-C02", "vlan": 1, "desc": "Customer A Production Web Server 02"},
        # Customer A DB servers (VLAN 101)
        {"name": "customer-a-db-01", "ip": "10.101.0.60", "tenant_id": 2, "rack": "Rack-C02", "vlan": 2, "desc": "Customer A Database Server 01"},
        # Customer B Web servers (VLAN 200)
        {"name": "customer-b-web-01", "ip": "10.200.0.70", "tenant_id": 3, "rack": "Rack-C03", "vlan": 3, "desc": "Customer B Frontend Web Server 01"},
        {"name": "customer-b-app-01", "ip": "10.200.0.80", "tenant_id": 3, "rack": "Rack-C03", "vlan": 3, "desc": "Customer B Application Server 01"},
        # Customer-001 Proxy Server (VLAN 300)
        {"name": "customer-001-proxy-01", "ip": "14.238.122.111", "tenant_id": 5, "rack": "Rack-C04", "vlan": 5, "desc": "Customer-001 Proxy Server 01"},
    ]

    for srv in custom_servers:
        device_records.append((device_id, srv["name"], "Standard PC", "Server", srv["rack"], srv["ip"], srv["tenant_id"]))
        
        # Dual-homed: Create eth0 & eth1
        mac_addr_0 = f"00:50:56:{device_id:02x}:11:bb"
        mac_addr_1 = f"00:50:56:{device_id:02x}:22:bb"
        interface_records.append((interface_id, "eth0", device_id, 1, mac_addr_0, "access", srv["vlan"], None))
        
        # Assign IP address to eth0 (LACP bond primary)
        ip_addr_with_mask = f"{srv['ip']}/24"
        ip_records.append((ip_id, ip_addr_with_mask, "active", interface_id, srv["tenant_id"], srv["desc"]))
        interface_id += 1
        ip_id += 1
        
        # Assign eth1
        interface_records.append((interface_id, "eth1", device_id, 1, mac_addr_1, "access", srv["vlan"], None))
        interface_id += 1
        
        # Generate Ubuntu license
        lic_key = f"UBUNTU-SUPPORT-{device_id:04d}"
        features = "ESM Security Patches 24/7 Support"
        license_records.append((license_id, srv["name"], lic_key, features, "2029-06-30", "ACTIVE"))
        
        # Generate Warranty
        serial = f"UB{device_id:03d}X{device_id*13:03d}"
        warranty_records.append((warranty_id, srv["name"], serial, "Standard NBD Hardware Replacement", "2022-01-01", "2027-01-01", "ACTIVE"))

        device_id += 1
        license_id += 1
        warranty_id += 1

    # Bulk insert generated records
    cur.executemany("INSERT INTO netbox_devices VALUES (?,?,?,?,?,?,?)", device_records)
    cur.executemany("INSERT INTO netbox_interfaces VALUES (?,?,?,?,?,?,?,?)", interface_records)
    cur.executemany("INSERT INTO netbox_ip_addresses VALUES (?,?,?,?,?,?)", ip_records)
    cur.executemany("INSERT INTO licenses VALUES (?,?,?,?,?,?)", license_records)
    cur.executemany("INSERT INTO device_warranty VALUES (?,?,?,?,?,?,?)", warranty_records)
    
    # Save base records
    conn.commit()

    # 3. Create Physical Cables / Topology Links (link_interfaces)
    print("Wiring spine-to-leaf trunk connections (CLOS architecture)...")
    # Leaf 01 links to Spine 01 (2 links LACP) and Spine 02 (2 links LACP)
    link_interfaces(cur, "LAB_LEAF.01", "et-0/0/1", "LAB_SPINE.01", "et-0/0/1")
    link_interfaces(cur, "LAB_LEAF.01", "et-0/0/2", "LAB_SPINE.01", "et-0/0/2")
    link_interfaces(cur, "LAB_LEAF.01", "et-0/0/3", "LAB_SPINE.02", "et-0/0/1")
    link_interfaces(cur, "LAB_LEAF.01", "et-0/0/4", "LAB_SPINE.02", "et-0/0/2")

    # Leaf 02 links to Spine 01 (2 links LACP) and Spine 02 (2 links LACP)
    link_interfaces(cur, "LAB_LEAF.02", "et-0/0/1", "LAB_SPINE.01", "et-0/0/3")
    link_interfaces(cur, "LAB_LEAF.02", "et-0/0/2", "LAB_SPINE.01", "et-0/0/4")
    link_interfaces(cur, "LAB_LEAF.02", "et-0/0/3", "LAB_SPINE.02", "et-0/0/3")
    link_interfaces(cur, "LAB_LEAF.02", "et-0/0/4", "LAB_SPINE.02", "et-0/0/4")

    # ToR Switch links to Spines
    link_interfaces(cur, "LAB-EX4400-TOR", "et-0/0/1", "LAB_SPINE.01", "et-0/0/5")
    link_interfaces(cur, "LAB-EX4400-TOR", "et-0/0/2", "LAB_SPINE.02", "et-0/0/5")
    link_interfaces(cur, "LAB-VCEX4600-TOR-2", "et-0/0/1", "LAB_SPINE.01", "et-0/0/6")
    link_interfaces(cur, "LAB-VCEX4600-TOR-2", "et-0/0/2", "LAB_SPINE.02", "et-0/0/6")

    print("Wiring server-to-leaf LACP/bonding dual-homed connections...")
    # Customer A Server 1 connects to Leaf 1 (ge-0/0/1) and Leaf 2 (ge-0/0/1)
    link_interfaces(cur, "customer-a-web-01", "eth0", "LAB_LEAF.01", "ge-0/0/1")
    link_interfaces(cur, "customer-a-web-01", "eth1", "LAB_LEAF.02", "ge-0/0/1")

    # Customer A Server 2 connects to Leaf 1 (ge-0/0/2) and Leaf 2 (ge-0/0/2)
    link_interfaces(cur, "customer-a-web-02", "eth0", "LAB_LEAF.01", "ge-0/0/2")
    link_interfaces(cur, "customer-a-web-02", "eth1", "LAB_LEAF.02", "ge-0/0/2")

    # Customer A DB Server connects to Leaf 1 (ge-0/0/3) and Leaf 2 (ge-0/0/3)
    link_interfaces(cur, "customer-a-db-01", "eth0", "LAB_LEAF.01", "ge-0/0/3")
    link_interfaces(cur, "customer-a-db-01", "eth1", "LAB_LEAF.02", "ge-0/0/3")

    # Customer B Web Server connects to Leaf 1 (ge-0/0/4) and Leaf 2 (ge-0/0/4)
    link_interfaces(cur, "customer-b-web-01", "eth0", "LAB_LEAF.01", "ge-0/0/4")
    link_interfaces(cur, "customer-b-web-01", "eth1", "LAB_LEAF.02", "ge-0/0/4")

    # Customer B App Server connects to Leaf 1 (ge-0/0/5) and Leaf 2 (ge-0/0/5)
    link_interfaces(cur, "customer-b-app-01", "eth0", "LAB_LEAF.01", "ge-0/0/5")
    link_interfaces(cur, "customer-b-app-01", "eth1", "LAB_LEAF.02", "ge-0/0/5")

    # NOC internal servers (noc-portal-app & net-monitor) connect to Leaf 1 ge-0/0/8 and ge-0/0/9
    link_interfaces(cur, "noc-portal-app", "eth0", "LAB_LEAF.01", "ge-0/0/8")
    link_interfaces(cur, "net-monitor", "eth0", "LAB_LEAF.01", "ge-0/0/9")

    # Customer-001 Proxy Server connects to LAB-INTERNET-GATEWAY-01 ge-0/0/47
    link_interfaces(cur, "customer-001-proxy-01", "eth0", "LAB-INTERNET-GATEWAY-01", "ge-0/0/47")

    # Save cabling
    conn.commit()
    conn.close()
    print("Database successfully initialized with CLOS topology, Spine L3 gateways, and dual-homed servers!")

if __name__ == "__main__":
    main()
