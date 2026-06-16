import os
import json
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "network_assets.db")
DEVICES_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "devices.json")

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
        FOREIGN KEY (device_id) REFERENCES netbox_devices(id),
        FOREIGN KEY (untagged_vlan_id) REFERENCES netbox_vlans(id)
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
    ]
    cur.executemany("INSERT INTO netbox_tenants VALUES (?,?,?,?)", tenants)

    # 2. VLANs
    vlans = [
        (1, 100, "VLAN_100_PROD_A", "active", 2, "Production VLAN for Customer A"),
        (2, 101, "VLAN_101_DB_A", "active", 2, "Database private network for Customer A"),
        (3, 200, "VLAN_200_WEB_B", "active", 3, "Web App VLAN for Customer B"),
        (4, 999, "VLAN_999_MGMT", "active", 4, "NOC Infrastructure Management Network"),
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
    
    for dev_name, info in devices_data.items():
        role = info.get("role", "Switch")
        model = info.get("model", "Unknown")
        primary_ip = info.get("ip")
        vendor = info.get("vendor", "juniper").lower()
        
        # Assign tenant
        if role == "Server":
            tenant_id = 2  # Customer A
        elif "VNPT" in dev_name:
            tenant_id = 3  # Customer B
        else:
            tenant_id = 4  # NOC Ops
            
        # Assign rack
        if role == "Server":
            rack = "Rack-C01"
        elif "Spine" in role:
            rack = "Rack-A01"
        elif "Leaf" in role or "ToR" in role:
            rack = "Rack-B01"
        else:
            rack = "Rack-D01"
            
        device_records.append((device_id, dev_name, model, role, rack, primary_ip, tenant_id))
        
        # Create interfaces
        # 1. Management interface
        if role == "Server":
            mgmt_if_name = "eth0"
        elif vendor == "juniper":
            mgmt_if_name = "me0"
        else:
            mgmt_if_name = "em0"
            
        mac_addr = f"00:50:56:{device_id:02x}:11:aa"
        interface_records.append((interface_id, mgmt_if_name, device_id, 1, mac_addr, "access", 4)) # mgmt is untagged vlan 4 (MGMT)
        
        # 2. IP Address for management interface
        if primary_ip:
            ip_address = primary_ip if "/" in primary_ip else f"{primary_ip}/24"
            ip_records.append((ip_id, ip_address, "active", interface_id, tenant_id, f"{dev_name} Management IP"))
            ip_id += 1
            
        interface_id += 1
        
        # Let's add some more traffic interfaces per device type
        if "Spine" in role:
            for port_idx in range(1, 5):
                traffic_if_name = f"et-0/0/{port_idx}"
                traffic_mac = f"00:50:56:{device_id:02x}:22:{port_idx:02x}"
                interface_records.append((interface_id, traffic_if_name, device_id, 1, traffic_mac, "trunk", None))
                interface_id += 1
        elif "Leaf" in role or "Switch" in role or "ToR" in role:
            for port_idx in range(1, 10):
                traffic_if_name = f"ge-0/0/{port_idx}"
                traffic_mac = f"00:50:56:{device_id:02x}:33:{port_idx:02x}"
                # Let's tag some interfaces with customer VLANs
                untagged_vlan = 1 if port_idx <= 4 else (2 if port_idx <= 7 else 3)
                interface_records.append((interface_id, traffic_if_name, device_id, 1, traffic_mac, "access", untagged_vlan))
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

    # Bulk insert generated records
    cur.executemany("INSERT INTO netbox_devices VALUES (?,?,?,?,?,?,?)", device_records)
    cur.executemany("INSERT INTO netbox_interfaces VALUES (?,?,?,?,?,?,?)", interface_records)
    cur.executemany("INSERT INTO netbox_ip_addresses VALUES (?,?,?,?,?,?)", ip_records)
    cur.executemany("INSERT INTO licenses VALUES (?,?,?,?,?,?)", license_records)
    cur.executemany("INSERT INTO device_warranty VALUES (?,?,?,?,?,?,?)", warranty_records)

    conn.commit()
    conn.close()
    print("Database successfully initialized with dynamic device data!")

if __name__ == "__main__":
    main()
