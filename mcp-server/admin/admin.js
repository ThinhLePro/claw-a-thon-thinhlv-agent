/* ═══════════════════════════════════════════════════
   MCP Gateway Admin — JavaScript Logic
   ═══════════════════════════════════════════════════
   
   This admin UI works with local data stored in localStorage.
   It manages:
   - Command ACL rules (whitelist/blacklist)
   - Operation commands database browser/editor
   - Configuration statements database browser/editor
   - Device inventory viewer
   
   Data is loaded from the MCP API endpoints when available,
   or from localStorage as a fallback.
*/

// ═══ Configuration ═══
const API_BASE = window.location.origin;
const ITEMS_PER_PAGE = 20;

// ═══ State ═══
let state = {
    acl: {
        whitelist: ['^(show|ping|traceroute|monitor)\\s+.*$'],
        blacklist: [
            'set ', 'delete ', 'edit ', 'configure',
            'request system', 'clear ', 'restart ',
            'commit', 'rollback', 'load ',
            'activate ', 'deactivate ',
            'request chassis', 'file ',
            'start shell', 'run '
        ]
    },
    operations: { data: [], page: 1, total: 0 },
    configurations: { data: [], page: 1, total: 0 },
    devices: { data: [] }
};

// ═══ Initialize ═══
document.addEventListener('DOMContentLoaded', () => {
    loadState();
    setupNavigation();
    setupSearch();
    renderACL();
    loadOperations();
    loadConfigurations();
    loadDevices();
});

// ═══ State Persistence ═══
function saveState() {
    localStorage.setItem('mcp_admin_state', JSON.stringify(state.acl));
}

function loadState() {
    const saved = localStorage.getItem('mcp_admin_state');
    if (saved) {
        try {
            state.acl = JSON.parse(saved);
        } catch (e) {
            console.warn('Failed to load saved state:', e);
        }
    }
}

// ═══ Navigation ═══
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const titles = {
        'acl': 'Command ACL Rules',
        'operations': 'Operation Commands',
        'configurations': 'Configuration Statements',
        'devices': 'Device Inventory'
    };

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const tab = item.dataset.tab;
            
            // Update nav
            navItems.forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            
            // Update content
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.getElementById(`tab-${tab}`).classList.add('active');
            
            // Update title
            document.getElementById('pageTitle').textContent = titles[tab];
        });
    });

    // Mobile menu toggle
    document.getElementById('menuToggle').addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('open');
    });
}

// ═══ Global Search ═══
function setupSearch() {
    const searchInput = document.getElementById('globalSearch');
    let debounceTimer;
    
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            const query = searchInput.value.trim();
            // Determine active tab and search
            const activeTab = document.querySelector('.nav-item.active').dataset.tab;
            if (activeTab === 'operations') {
                document.getElementById('opsSearch').value = query;
                loadOperations();
            } else if (activeTab === 'configurations') {
                document.getElementById('cfgSearch').value = query;
                loadConfigurations();
            }
        }, 300);
    });
}

// ═══ ACL Management ═══
function renderACL() {
    // Whitelist
    const wlContainer = document.getElementById('whitelistRules');
    wlContainer.innerHTML = state.acl.whitelist.map((rule, i) => `
        <div class="rule-item">
            <code>${escapeHtml(rule)}</code>
            <button class="rule-delete" onclick="removeWhitelistRule(${i})" title="Remove rule">✕</button>
        </div>
    `).join('');

    // Blacklist
    const blContainer = document.getElementById('blacklistRules');
    blContainer.innerHTML = state.acl.blacklist.map((keyword, i) => `
        <div class="rule-item">
            <code>${escapeHtml(keyword)}</code>
            <button class="rule-delete" onclick="removeBlacklistRule(${i})" title="Remove keyword">✕</button>
        </div>
    `).join('');
}

function addWhitelistRule() {
    const input = document.getElementById('newWhitelistRule');
    const rule = input.value.trim();
    if (!rule) return;

    // Validate regex
    try {
        new RegExp(rule, 'i');
    } catch (e) {
        showToast(`Invalid regex: ${e.message}`, 'error');
        return;
    }

    state.acl.whitelist.push(rule);
    input.value = '';
    saveState();
    renderACL();
    showToast('Whitelist rule added', 'success');
}

function removeWhitelistRule(index) {
    state.acl.whitelist.splice(index, 1);
    saveState();
    renderACL();
    showToast('Whitelist rule removed', 'success');
}

function addBlacklistRule() {
    const input = document.getElementById('newBlacklistRule');
    const keyword = input.value.trim();
    if (!keyword) return;

    state.acl.blacklist.push(keyword);
    input.value = '';
    saveState();
    renderACL();
    showToast('Blacklist keyword added', 'success');
}

function removeBlacklistRule(index) {
    state.acl.blacklist.splice(index, 1);
    saveState();
    renderACL();
    showToast('Blacklist keyword removed', 'success');
}

function testACL() {
    const command = document.getElementById('testCommand').value.trim();
    const resultDiv = document.getElementById('testResult');

    if (!command) {
        resultDiv.className = 'test-result';
        resultDiv.textContent = '';
        return;
    }

    // Check blacklist first
    const cmdLower = command.toLowerCase();
    for (const keyword of state.acl.blacklist) {
        if (cmdLower.startsWith(keyword) || (' ' + cmdLower).includes(' ' + keyword)) {
            resultDiv.className = 'test-result blocked';
            resultDiv.textContent = `🚫 BLOCKED — Command matches blacklist keyword: "${keyword.trim()}"`;
            return;
        }
    }

    // Check whitelist
    let whitelistMatch = false;
    for (const pattern of state.acl.whitelist) {
        try {
            const regex = new RegExp(pattern, 'i');
            if (regex.test(command)) {
                whitelistMatch = true;
                break;
            }
        } catch (e) {
            // Skip invalid regex
        }
    }

    if (whitelistMatch) {
        resultDiv.className = 'test-result allowed';
        resultDiv.textContent = `✅ ALLOWED — Command passes whitelist and blacklist checks.`;
    } else {
        resultDiv.className = 'test-result blocked';
        resultDiv.textContent = `🚫 BLOCKED — Command does not match any whitelist pattern.`;
    }
}

// ═══ Operations Database ═══
async function loadOperations() {
    const vendor = document.getElementById('opsVendorFilter').value;
    const risk = document.getElementById('opsRiskFilter').value;
    const search = document.getElementById('opsSearch').value.trim();

    try {
        const params = new URLSearchParams({
            page: state.operations.page,
            limit: ITEMS_PER_PAGE,
            ...(vendor && { vendor }),
            ...(risk && { risk_level: risk }),
            ...(search && { search }),
        });

        const response = await fetch(`${API_BASE}/admin/api/operations?${params}`);
        if (response.ok) {
            const data = await response.json();
            state.operations.data = data.items || [];
            state.operations.total = data.total || 0;
        }
    } catch (e) {
        // Fallback: show empty state
        console.warn('Could not load operations from API:', e);
    }

    renderOperationsTable();
}

function renderOperationsTable() {
    const tbody = document.getElementById('opsTableBody');
    
    if (state.operations.data.length === 0) {
        tbody.innerHTML = `
            <tr><td colspan="5" style="text-align:center; padding:40px; color:var(--text-secondary);">
                No operation commands found. Connect to the MCP API to browse the database.
            </td></tr>
        `;
        return;
    }

    tbody.innerHTML = state.operations.data.map(op => {
        const riskBadge = {
            'INFO': 'badge-info',
            'WARNING': 'badge-warning',
            'CRITICAL': 'badge-danger'
        }[op.risk_level] || 'badge-info';

        return `
            <tr>
                <td class="cmd-name">${escapeHtml(op.command_name || '')}</td>
                <td>${escapeHtml(op.vendor || '')}</td>
                <td><span class="badge ${riskBadge}">${escapeHtml(op.risk_level || 'INFO')}</span></td>
                <td title="${escapeHtml(op.short_desc || '')}">${escapeHtml((op.short_desc || '').substring(0, 80))}</td>
                <td>
                    <button class="btn btn-ghost btn-sm" onclick="viewOperation(${op.id})">View</button>
                    <button class="btn btn-ghost btn-sm" onclick="editOperation(${op.id})">Edit</button>
                </td>
            </tr>
        `;
    }).join('');

    renderPagination('opsPagination', state.operations.total, state.operations.page, (p) => {
        state.operations.page = p;
        loadOperations();
    });
}

function viewOperation(id) {
    const op = state.operations.data.find(o => o.id === id);
    if (!op) return;

    openModal(`Operation: ${op.command_name}`, `
        <div class="form-group">
            <label>Command Name</label>
            <div class="input-field" style="cursor:default">${escapeHtml(op.command_name)}</div>
        </div>
        <div class="form-group">
            <label>Vendor</label>
            <div class="input-field" style="cursor:default">${escapeHtml(op.vendor)}</div>
        </div>
        <div class="form-group">
            <label>Risk Level</label>
            <div><span class="badge ${op.risk_level === 'CRITICAL' ? 'badge-danger' : op.risk_level === 'WARNING' ? 'badge-warning' : 'badge-info'}">${escapeHtml(op.risk_level || 'INFO')}</span></div>
        </div>
        <div class="form-group">
            <label>Description</label>
            <div class="input-field" style="cursor:default; white-space:pre-wrap; max-height:200px; overflow-y:auto">${escapeHtml(op.short_desc || 'N/A')}</div>
        </div>
        <div class="form-group">
            <label>Syntax</label>
            <pre style="background:var(--bg-input); padding:12px; border-radius:6px; font-family:'JetBrains Mono',monospace; font-size:12px; overflow-x:auto">${escapeHtml(op.syntax || 'N/A')}</pre>
        </div>
        ${op.options ? `<div class="form-group">
            <label>Options</label>
            <pre style="background:var(--bg-input); padding:12px; border-radius:6px; font-family:'JetBrains Mono',monospace; font-size:12px; overflow-x:auto; max-height:200px; overflow-y:auto">${escapeHtml(op.options)}</pre>
        </div>` : ''}
        ${op.url ? `<div class="form-group">
            <label>Reference</label>
            <a href="${escapeHtml(op.url)}" target="_blank" style="color:var(--text-accent)">${escapeHtml(op.url)}</a>
        </div>` : ''}
    `);
}

function editOperation(id) {
    const op = state.operations.data.find(o => o.id === id);
    if (!op) return;

    openModal(`Edit: ${op.command_name}`, `
        <div class="form-group">
            <label>Command Name</label>
            <input type="text" class="input-field" id="editOpName" value="${escapeHtml(op.command_name)}" style="width:100%">
        </div>
        <div class="form-group">
            <label>Vendor</label>
            <select class="select-field" id="editOpVendor" style="width:100%">
                <option value="juniper" ${op.vendor === 'juniper' ? 'selected' : ''}>Juniper</option>
                <option value="cisco" ${op.vendor === 'cisco' ? 'selected' : ''}>Cisco</option>
                <option value="arista" ${op.vendor === 'arista' ? 'selected' : ''}>Arista</option>
                <option value="huawei" ${op.vendor === 'huawei' ? 'selected' : ''}>Huawei</option>
            </select>
        </div>
        <div class="form-group">
            <label>Risk Level</label>
            <select class="select-field" id="editOpRisk" style="width:100%">
                <option value="INFO" ${op.risk_level === 'INFO' ? 'selected' : ''}>INFO</option>
                <option value="WARNING" ${op.risk_level === 'WARNING' ? 'selected' : ''}>WARNING</option>
                <option value="CRITICAL" ${op.risk_level === 'CRITICAL' ? 'selected' : ''}>CRITICAL</option>
            </select>
        </div>
        <div class="form-group">
            <label>Description</label>
            <textarea class="textarea-field" id="editOpDesc">${escapeHtml(op.short_desc || '')}</textarea>
        </div>
        <div class="form-group">
            <label>Syntax</label>
            <textarea class="textarea-field" id="editOpSyntax">${escapeHtml(op.syntax || '')}</textarea>
        </div>
    `, `
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="saveOperation(${op.id})">Save Changes</button>
    `);
}

async function saveOperation(id) {
    const data = {
        command_name: document.getElementById('editOpName').value,
        vendor: document.getElementById('editOpVendor').value,
        risk_level: document.getElementById('editOpRisk').value,
        short_desc: document.getElementById('editOpDesc').value,
        syntax: document.getElementById('editOpSyntax').value,
    };

    try {
        const response = await fetch(`${API_BASE}/admin/api/operations/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (response.ok) {
            showToast('Operation command updated', 'success');
            closeModal();
            loadOperations();
        } else {
            showToast('Failed to save changes', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

function showAddOperationModal() {
    openModal('Add Operation Command', `
        <div class="form-group">
            <label>Command Name</label>
            <input type="text" class="input-field" id="addOpName" placeholder="e.g., show bgp summary" style="width:100%">
        </div>
        <div class="form-group">
            <label>Vendor</label>
            <select class="select-field" id="addOpVendor" style="width:100%">
                <option value="juniper">Juniper</option>
                <option value="cisco">Cisco</option>
                <option value="arista">Arista</option>
                <option value="huawei">Huawei</option>
            </select>
        </div>
        <div class="form-group">
            <label>Risk Level</label>
            <select class="select-field" id="addOpRisk" style="width:100%">
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="CRITICAL">CRITICAL</option>
            </select>
        </div>
        <div class="form-group">
            <label>Description</label>
            <textarea class="textarea-field" id="addOpDesc" placeholder="Brief description of this command..."></textarea>
        </div>
        <div class="form-group">
            <label>Syntax</label>
            <textarea class="textarea-field" id="addOpSyntax" placeholder="Command syntax template..."></textarea>
        </div>
    `, `
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="addOperation()">Add Command</button>
    `);
}

async function addOperation() {
    const data = {
        command_name: document.getElementById('addOpName').value,
        vendor: document.getElementById('addOpVendor').value,
        risk_level: document.getElementById('addOpRisk').value,
        short_desc: document.getElementById('addOpDesc').value,
        syntax: document.getElementById('addOpSyntax').value,
    };

    if (!data.command_name) {
        showToast('Command name is required', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/admin/api/operations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (response.ok) {
            showToast('Operation command added', 'success');
            closeModal();
            loadOperations();
        } else {
            showToast('Failed to add command', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

// ═══ Configurations Database ═══
async function loadConfigurations() {
    const vendor = document.getElementById('cfgVendorFilter').value;
    const search = document.getElementById('cfgSearch').value.trim();

    try {
        const params = new URLSearchParams({
            page: state.configurations.page,
            limit: ITEMS_PER_PAGE,
            ...(vendor && { vendor }),
            ...(search && { search }),
        });

        const response = await fetch(`${API_BASE}/admin/api/configurations?${params}`);
        if (response.ok) {
            const data = await response.json();
            state.configurations.data = data.items || [];
            state.configurations.total = data.total || 0;
        }
    } catch (e) {
        console.warn('Could not load configurations from API:', e);
    }

    renderConfigurationsTable();
}

function renderConfigurationsTable() {
    const tbody = document.getElementById('cfgTableBody');

    if (state.configurations.data.length === 0) {
        tbody.innerHTML = `
            <tr><td colspan="5" style="text-align:center; padding:40px; color:var(--text-secondary);">
                No configuration statements found. Connect to the MCP API to browse the database.
            </td></tr>
        `;
        return;
    }

    tbody.innerHTML = state.configurations.data.map(cfg => `
        <tr>
            <td class="cmd-name">${escapeHtml(cfg.statement_name || '')}</td>
            <td>${escapeHtml(cfg.vendor || '')}</td>
            <td title="${escapeHtml(cfg.short_desc || '')}">${escapeHtml((cfg.short_desc || '').substring(0, 80))}</td>
            <td>${escapeHtml((cfg.hierarchy_level || '').substring(0, 60))}</td>
            <td>
                <button class="btn btn-ghost btn-sm" onclick="viewConfiguration(${cfg.id})">View</button>
                <button class="btn btn-ghost btn-sm" onclick="editConfiguration(${cfg.id})">Edit</button>
            </td>
        </tr>
    `).join('');

    renderPagination('cfgPagination', state.configurations.total, state.configurations.page, (p) => {
        state.configurations.page = p;
        loadConfigurations();
    });
}

function viewConfiguration(id) {
    const cfg = state.configurations.data.find(c => c.id === id);
    if (!cfg) return;

    openModal(`Statement: ${cfg.statement_name}`, `
        <div class="form-group">
            <label>Statement Name</label>
            <div class="input-field" style="cursor:default">${escapeHtml(cfg.statement_name)}</div>
        </div>
        <div class="form-group">
            <label>Vendor</label>
            <div class="input-field" style="cursor:default">${escapeHtml(cfg.vendor)}</div>
        </div>
        <div class="form-group">
            <label>Description</label>
            <div class="input-field" style="cursor:default; white-space:pre-wrap; max-height:200px; overflow-y:auto">${escapeHtml(cfg.short_desc || 'N/A')}</div>
        </div>
        <div class="form-group">
            <label>Syntax</label>
            <pre style="background:var(--bg-input); padding:12px; border-radius:6px; font-family:'JetBrains Mono',monospace; font-size:12px; overflow-x:auto">${escapeHtml(cfg.syntax || 'N/A')}</pre>
        </div>
        <div class="form-group">
            <label>Hierarchy Level</label>
            <pre style="background:var(--bg-input); padding:12px; border-radius:6px; font-family:'JetBrains Mono',monospace; font-size:12px">${escapeHtml(cfg.hierarchy_level || 'N/A')}</pre>
        </div>
        ${cfg.default_value ? `<div class="form-group">
            <label>Default Value</label>
            <div class="input-field" style="cursor:default">${escapeHtml(cfg.default_value)}</div>
        </div>` : ''}
        ${cfg.url ? `<div class="form-group">
            <label>Reference</label>
            <a href="${escapeHtml(cfg.url)}" target="_blank" style="color:var(--text-accent)">${escapeHtml(cfg.url)}</a>
        </div>` : ''}
    `);
}

function editConfiguration(id) {
    const cfg = state.configurations.data.find(c => c.id === id);
    if (!cfg) return;

    openModal(`Edit: ${cfg.statement_name}`, `
        <div class="form-group">
            <label>Statement Name</label>
            <input type="text" class="input-field" id="editCfgName" value="${escapeHtml(cfg.statement_name)}" style="width:100%">
        </div>
        <div class="form-group">
            <label>Vendor</label>
            <select class="select-field" id="editCfgVendor" style="width:100%">
                <option value="juniper" ${cfg.vendor === 'juniper' ? 'selected' : ''}>Juniper</option>
            </select>
        </div>
        <div class="form-group">
            <label>Description</label>
            <textarea class="textarea-field" id="editCfgDesc">${escapeHtml(cfg.short_desc || '')}</textarea>
        </div>
        <div class="form-group">
            <label>Syntax</label>
            <textarea class="textarea-field" id="editCfgSyntax">${escapeHtml(cfg.syntax || '')}</textarea>
        </div>
        <div class="form-group">
            <label>Hierarchy Level</label>
            <textarea class="textarea-field" id="editCfgHierarchy">${escapeHtml(cfg.hierarchy_level || '')}</textarea>
        </div>
    `, `
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="saveConfiguration(${cfg.id})">Save Changes</button>
    `);
}

async function saveConfiguration(id) {
    const data = {
        statement_name: document.getElementById('editCfgName').value,
        vendor: document.getElementById('editCfgVendor').value,
        short_desc: document.getElementById('editCfgDesc').value,
        syntax: document.getElementById('editCfgSyntax').value,
        hierarchy_level: document.getElementById('editCfgHierarchy').value,
    };

    try {
        const response = await fetch(`${API_BASE}/admin/api/configurations/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (response.ok) {
            showToast('Configuration statement updated', 'success');
            closeModal();
            loadConfigurations();
        } else {
            showToast('Failed to save changes', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

function showAddConfigModal() {
    openModal('Add Configuration Statement', `
        <div class="form-group">
            <label>Statement Name</label>
            <input type="text" class="input-field" id="addCfgName" placeholder="e.g., protocols bgp group" style="width:100%">
        </div>
        <div class="form-group">
            <label>Vendor</label>
            <select class="select-field" id="addCfgVendor" style="width:100%">
                <option value="juniper">Juniper</option>
            </select>
        </div>
        <div class="form-group">
            <label>Description</label>
            <textarea class="textarea-field" id="addCfgDesc" placeholder="Brief description of this statement..."></textarea>
        </div>
        <div class="form-group">
            <label>Syntax</label>
            <textarea class="textarea-field" id="addCfgSyntax" placeholder="Configuration syntax template..."></textarea>
        </div>
        <div class="form-group">
            <label>Hierarchy Level</label>
            <input type="text" class="input-field" id="addCfgHierarchy" placeholder="e.g., [edit protocols bgp]" style="width:100%">
        </div>
    `, `
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="addConfiguration()">Add Statement</button>
    `);
}

async function addConfiguration() {
    const data = {
        statement_name: document.getElementById('addCfgName').value,
        vendor: document.getElementById('addCfgVendor').value,
        short_desc: document.getElementById('addCfgDesc').value,
        syntax: document.getElementById('addCfgSyntax').value,
        hierarchy_level: document.getElementById('addCfgHierarchy').value,
    };

    if (!data.statement_name) {
        showToast('Statement name is required', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/admin/api/configurations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (response.ok) {
            showToast('Configuration statement added', 'success');
            closeModal();
            loadConfigurations();
        } else {
            showToast('Failed to add statement', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

// ═══ Devices ═══
async function loadDevices() {
    try {
        const response = await fetch(`${API_BASE}/admin/api/devices`);
        if (response.ok) {
            state.devices.data = await response.json();
        }
    } catch (e) {
        console.warn('Could not load devices from API:', e);
    }

    renderDevices();
}

function renderDevices() {
    const grid = document.getElementById('deviceGrid');

    if (state.devices.data.length === 0) {
        grid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 60px; color: var(--text-secondary);">
                No devices loaded. Connect to the MCP API to view device inventory.
            </div>
        `;
        return;
    }

    grid.innerHTML = state.devices.data.map(dev => `
        <div class="device-card">
            <div class="device-card-header">
                <span class="device-name">${escapeHtml(dev.name || dev.hostname)}</span>
                <span class="device-status" title="${dev.status || 'Online'}"></span>
            </div>
            <dl class="device-info">
                <dt>IP Address</dt>
                <dd>${escapeHtml(dev.ip)}</dd>
                <dt>Model</dt>
                <dd>${escapeHtml(dev.model)}</dd>
                <dt>Vendor</dt>
                <dd>${escapeHtml(dev.vendor || 'juniper')}</dd>
                <dt>Method</dt>
                <dd>${escapeHtml(dev.connection_method || 'netconf')}</dd>
                <dt>Port</dt>
                <dd>${dev.port}</dd>
                <dt>Role</dt>
                <dd>${escapeHtml(dev.role || 'N/A')}</dd>
            </dl>
        </div>
    `).join('');
}

function showAddDeviceModal() {
    openModal('Add Device', `
        <div class="form-group">
            <label>Hostname</label>
            <input type="text" class="input-field" id="addDevName" placeholder="e.g., core-leaf-03" style="width:100%">
        </div>
        <div class="form-group">
            <label>IP Address</label>
            <input type="text" class="input-field" id="addDevIP" placeholder="e.g., 10.0.1.3" style="width:100%">
        </div>
        <div class="form-group">
            <label>Model</label>
            <input type="text" class="input-field" id="addDevModel" placeholder="e.g., QFX5120-32C" style="width:100%">
        </div>
        <div class="form-group">
            <label>Vendor</label>
            <select class="select-field" id="addDevVendor" style="width:100%">
                <option value="juniper">Juniper</option>
                <option value="cisco">Cisco</option>
                <option value="arista">Arista</option>
                <option value="huawei">Huawei</option>
            </select>
        </div>
        <div class="form-group">
            <label>Connection Method</label>
            <select class="select-field" id="addDevMethod" style="width:100%">
                <option value="netconf">NETCONF (default)</option>
                <option value="ssh">SSH</option>
                <option value="api">API</option>
            </select>
        </div>
        <div class="form-group">
            <label>Port</label>
            <input type="number" class="input-field" id="addDevPort" value="830" style="width:100%">
        </div>
        <div class="form-group">
            <label>Role</label>
            <input type="text" class="input-field" id="addDevRole" placeholder="e.g., Core Leaf" style="width:100%">
        </div>
    `, `
        <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="addDevice()">Add Device</button>
    `);
}

async function addDevice() {
    const data = {
        name: document.getElementById('addDevName').value,
        ip: document.getElementById('addDevIP').value,
        model: document.getElementById('addDevModel').value,
        vendor: document.getElementById('addDevVendor').value,
        connection_method: document.getElementById('addDevMethod').value,
        port: parseInt(document.getElementById('addDevPort').value) || 830,
        role: document.getElementById('addDevRole').value,
    };

    if (!data.name || !data.ip) {
        showToast('Hostname and IP are required', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/admin/api/devices`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (response.ok) {
            showToast('Device added', 'success');
            closeModal();
            loadDevices();
        } else {
            showToast('Failed to add device', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

// ═══ Pagination ═══
function renderPagination(containerId, total, currentPage, onPageChange) {
    const container = document.getElementById(containerId);
    const totalPages = Math.ceil(total / ITEMS_PER_PAGE);

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '';
    const maxVisible = 7;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);

    if (endPage - startPage < maxVisible - 1) {
        startPage = Math.max(1, endPage - maxVisible + 1);
    }

    if (currentPage > 1) {
        html += `<button class="page-btn" data-page="${currentPage - 1}">← Prev</button>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
    }

    if (currentPage < totalPages) {
        html += `<button class="page-btn" data-page="${currentPage + 1}">Next →</button>`;
    }

    container.innerHTML = html;

    container.querySelectorAll('.page-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            onPageChange(parseInt(btn.dataset.page));
        });
    });
}

// ═══ Modal ═══
function openModal(title, bodyHtml, footerHtml = '') {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').innerHTML = bodyHtml;
    document.getElementById('modalFooter').innerHTML = footerHtml;
    document.getElementById('modalOverlay').classList.add('active');
}

function closeModal() {
    document.getElementById('modalOverlay').classList.remove('active');
}

// Close modal on overlay click
document.getElementById('modalOverlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});

// Close modal on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ═══ Toast ═══
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// ═══ Utility ═══
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
