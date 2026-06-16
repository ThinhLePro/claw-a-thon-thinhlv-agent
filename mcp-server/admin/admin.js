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
    devices: { data: [] },
    tools: { data: [] },
    logs: { sessions: [], activeSessionId: null }
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
    loadTools();
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
        'devices': 'Device Inventory',
        'tools': 'Registered MCP Tools',
        'logs': 'AI Incident Session Logs',
        'parser': 'NOC Inbound Request Parser'
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

            // Trigger log loading
            if (tab === 'logs') {
                loadSessions();
            } else if (tab === 'tools') {
                loadTools();
            }
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
            } else if (activeTab === 'tools') {
                document.getElementById('toolsSearch').value = query;
                filterTools();
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

// ═══ AI Session Logs ═══
async function loadSessions() {
    const listContainer = document.getElementById('sessionsList');
    if (!listContainer) return;
    
    listContainer.innerHTML = '<div class="empty-state">Loading active sessions...</div>';
    
    try {
        const response = await fetch(`${API_BASE}/admin/api/sessions`);
        if (response.ok) {
            state.logs.sessions = await response.json();
            renderSessionsList(state.logs.sessions);
            
            // Re-select active session if it still exists
            if (state.logs.activeSessionId) {
                const stillExists = state.logs.sessions.some(s => s.session_id === state.logs.activeSessionId);
                if (stillExists) {
                    selectSession(state.logs.activeSessionId);
                } else {
                    state.logs.activeSessionId = null;
                    resetDetailPane();
                }
            }
        } else {
            listContainer.innerHTML = '<div class="empty-state text-danger">Failed to fetch sessions.</div>';
        }
    } catch (e) {
        console.error('Error fetching sessions:', e);
        listContainer.innerHTML = '<div class="empty-state text-danger">Error connecting to Redis API.</div>';
    }
}

function renderSessionsList(sessions) {
    const listContainer = document.getElementById('sessionsList');
    if (!listContainer) return;
    
    if (!sessions || sessions.length === 0) {
        listContainer.innerHTML = `
            <div class="empty-state" style="padding: 20px 0;">
                <p>No active sessions in Redis.</p>
            </div>
        `;
        return;
    }
    
    listContainer.innerHTML = sessions.map(session => {
        const activeClass = session.session_id === state.logs.activeSessionId ? 'active' : '';
        const summary = escapeHtml(session.symptoms || 'No symptoms summary');
        const assignee = escapeHtml(session.current_assignee || 'Unknown');
        const loopCount = session.loop_count || 0;
        const cleanId = escapeHtml(session.session_id);
        
        return `
            <div class="session-item ${activeClass}" onclick="selectSession('${cleanId}')">
                <div class="session-item-header">
                    <div class="session-id" title="${cleanId}">${cleanId}</div>
                </div>
                <div class="session-summary" title="${summary}">${summary}</div>
                <div class="session-meta">
                    <span class="session-assignee">${assignee}</span>
                    <span class="session-loop">Loops: ${loopCount}</span>
                </div>
            </div>
        `;
    }).join('');
}

function selectSession(sessionId) {
    state.logs.activeSessionId = sessionId;
    
    // Highlight active item
    document.querySelectorAll('.session-item').forEach(item => {
        const idDiv = item.querySelector('.session-id');
        if (idDiv && idDiv.textContent === sessionId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
    
    loadSessionDetails(sessionId);
}

async function loadSessionDetails(sessionId) {
    const detailPane = document.getElementById('sessionDetailPane');
    if (!detailPane) return;
    
    try {
        const response = await fetch(`${API_BASE}/admin/api/sessions/${sessionId}`);
        if (response.ok) {
            const session = await response.json();
            renderSessionDetails(session);
        } else {
            detailPane.innerHTML = `<div class="empty-state text-danger">Failed to load details for ${escapeHtml(sessionId)}.</div>`;
        }
    } catch (e) {
        console.error('Error fetching session details:', e);
        detailPane.innerHTML = `<div class="empty-state text-danger">Error connecting to session details API.</div>`;
    }
}

function resetDetailPane() {
    const detailPane = document.getElementById('sessionDetailPane');
    if (detailPane) {
        detailPane.innerHTML = `
            <div class="empty-state">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 17h6M9 12h6M9 7h6"/></svg>
                <p>Select an AI Session to view details and live diagnostics timeline</p>
            </div>
        `;
    }
}

async function clearSession(sessionId) {
    if (!confirm(`Are you sure you want to clear/delete session "${sessionId}" from Redis? This will stop the workflow and allow fresh alert re-triggers.`)) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/admin/api/sessions/${sessionId}/clear`, {
            method: 'POST'
        });
        if (response.ok) {
            showToast(`Session ${sessionId} cleared successfully`, 'success');
            state.logs.activeSessionId = null;
            loadSessions();
            resetDetailPane();
        } else {
            showToast('Failed to clear session', 'error');
        }
    } catch (e) {
        console.error('Error clearing session:', e);
        showToast(`Error: ${e.message}`, 'error');
    }
}

function filterSessions() {
    const query = document.getElementById('sessionSearch').value.trim().toLowerCase();
    const filtered = state.logs.sessions.filter(session => {
        const id = (session.session_id || '').toLowerCase();
        const symptoms = (session.symptoms || '').toLowerCase();
        const assignee = (session.current_assignee || '').toLowerCase();
        return id.includes(query) || symptoms.includes(query) || assignee.includes(query);
    });
    renderSessionsList(filtered);
}

function parseTimelineLog(logStr, index) {
    let agent = "System";
    let statusClass = "";
    let time = null;
    let text = logStr;
    
    // Extract ISO timestamp if present
    const isoRegex = /(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)/;
    const timeMatch = logStr.match(isoRegex);
    if (timeMatch) {
        time = timeMatch[1];
        text = text.replace(/at \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?/, '').trim();
    }
    
    // Identify agent and level
    if (logStr.startsWith("AlertManager triggered")) {
        agent = "AlertManager";
        statusClass = "warning";
    } else if (logStr.startsWith("Supervisor decision") || logStr.startsWith("Supervisor:")) {
        agent = "Supervisor";
        statusClass = logStr.includes("failed") || logStr.includes("exceeded") ? "danger" : "success";
    } else if (logStr.includes("Analytics Agent")) {
        agent = "Analytics Agent";
        statusClass = logStr.includes("failed") ? "danger" : logStr.includes("started") ? "info" : "success";
    } else if (logStr.includes("Expert Agent")) {
        agent = "Expert Agent";
        statusClass = logStr.includes("failed") ? "danger" : logStr.includes("started") ? "info" : "success";
    } else if (logStr.includes("Customer Advisory Agent")) {
        agent = "Customer Advisory Agent";
        statusClass = logStr.includes("failed") ? "danger" : logStr.includes("started") ? "info" : "success";
    } else {
        if (logStr.includes("failed") || logStr.includes("error")) {
            statusClass = "danger";
        } else if (logStr.includes("started") || logStr.includes("running")) {
            statusClass = "info";
        } else if (logStr.includes("finished") || logStr.includes("completed") || logStr.includes("success")) {
            statusClass = "success";
        }
    }
    
    let htmlContent = escapeHtml(text);
    htmlContent = htmlContent.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    return {
        agent,
        time,
        content: htmlContent,
        statusClass
    };
}

function renderSessionDetails(session) {
    const detailPane = document.getElementById('sessionDetailPane');
    if (!detailPane) return;
    
    const sessionId = escapeHtml(session.session_id);
    const symptoms = escapeHtml(session.symptoms || 'N/A');
    const alertSource = escapeHtml(session.alert_source || 'N/A');
    const currentAssignee = escapeHtml(session.current_assignee || 'N/A');
    const loopCount = session.loop_count || 0;
    const rcaSummary = escapeHtml(session.rca_summary || 'No root cause identified yet.');
    const jiraIssueKey = escapeHtml(session.jira_issue_key || 'N/A');
    const affectedEntities = escapeHtml(Array.isArray(session.affected_entities) ? session.affected_entities.join(', ') : session.affected_entities || 'None');
    
    const logs = session.diagnostic_logs || [];
    let timelineHtml = '<div class="empty-state" style="padding: 20px 0;">No diagnostic logs recorded yet.</div>';
    
    if (logs.length > 0) {
        timelineHtml = `<div class="timeline-container">`;
        logs.forEach((logStr, index) => {
            const parsed = parseTimelineLog(logStr, index);
            timelineHtml += `
                <div class="timeline-item">
                    <div class="timeline-dot ${parsed.statusClass}"></div>
                    <div class="timeline-item-meta">
                        <span class="timeline-agent">${escapeHtml(parsed.agent)}</span>
                        ${parsed.time ? `<span class="timeline-time">${escapeHtml(parsed.time)}</span>` : ''}
                    </div>
                    <div class="timeline-content">
                        <div class="timeline-content-body">${parsed.content}</div>
                    </div>
                </div>
            `;
        });
        timelineHtml += `</div>`;
    }

    detailPane.innerHTML = `
        <div class="detail-header">
            <div class="detail-header-left">
                <h2>Session Logs</h2>
                <p>ID: ${sessionId}</p>
            </div>
            <div class="detail-header-right">
                <button class="btn btn-ghost btn-sm" onclick="loadSessionDetails('${sessionId}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
                    Refresh
                </button>
                <button class="btn btn-danger btn-sm" onclick="clearSession('${sessionId}')">Clear Session</button>
            </div>
        </div>
        <div class="detail-body">
            <div class="info-cards-row">
                <div class="info-card">
                    <div class="info-card-label">Assignee</div>
                    <div class="info-card-value">${currentAssignee}</div>
                </div>
                <div class="info-card">
                    <div class="info-card-label">Loop Count</div>
                    <div class="info-card-value">${loopCount} / 5</div>
                </div>
                <div class="info-card">
                    <div class="info-card-label">Jira Issue</div>
                    <div class="info-card-value">
                        ${jiraIssueKey !== 'N/A' && jiraIssueKey ? `<a href="https://vngcloud-internship.atlassian.net/browse/${jiraIssueKey}" target="_blank" style="color:var(--text-accent); text-decoration:none;">${jiraIssueKey} ↗</a>` : 'N/A'}
                    </div>
                </div>
                <div class="info-card">
                    <div class="info-card-label">Entities</div>
                    <div class="info-card-value" title="${affectedEntities}">${affectedEntities}</div>
                </div>
            </div>

            <div class="info-card" style="margin-bottom: 20px;">
                <div class="info-card-label">Symptoms & Summary</div>
                <div style="font-size: 13px; line-height: 1.5; color: var(--text-primary); margin-bottom: 8px;">${symptoms}</div>
                <div class="info-card-label" style="margin-top: 12px;">RCA Summary</div>
                <div style="font-size: 13px; line-height: 1.5; color: var(--text-accent); font-weight: 500;">${rcaSummary}</div>
            </div>

            <div class="timeline-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                Execution Trace
            </div>
            ${timelineHtml}
        </div>
    `;
}

// ═══ NOC Request Parser Interactive Logic ═══
function applyScenario() {
    const val = document.getElementById('scenarioDropdown').value;
    const txtArea = document.getElementById('requestText');
    const scenarios = {
        '1': 'Hi team, nhờ check giúp link peering giữa srx-core-01 và đối tác bên VNG đang bị loss gói từ 9h sáng nay.',
        '2': 'Nhờ NOC dump cấu hình interface ge-0/0/1 của switch qfx-leaf-02 ra file text gửi qua email giúp mình nhé, cần gấp để audit.',
        '3': 'Bên em mới gửi phiếu yêu cầu hỗ trợ tạo ticket bảo trì định kỳ cho cụm EX-Switch vào đêm nay, mã phiếu #1102.'
    };
    if (val in scenarios) {
        txtArea.value = scenarios[val];
    } else {
        txtArea.value = '';
    }
}

function analyzeRequest() {
    const text = document.getElementById('requestText').value.trim();
    if (!text) {
        showToast('Please enter request text first.', 'error');
        return;
    }

    // Perform Entity Extraction simulation
    let intent = 'GENERAL_INQUIRY';
    let device = 'None';
    let priority = 'Trung bình';
    let priorityClass = 'badge-warning';
    let agent = 'supervisor-network-engineer-agent';
    let jiraTitle = '';
    let jiraDesc = '';
    let confidence = 95;

    const lower = text.toLowerCase();

    // Check for Scenario 1
    if (lower.includes('peering') || lower.includes('loss') || lower.includes('srx-core-01')) {
        intent = 'INCIDENT_RESPONSE';
        device = 'srx-core-01';
        priority = 'Cao';
        priorityClass = 'badge-danger';
        agent = 'analytics-network-engineer-agent';
        jiraTitle = '[Incident] srx-core-01: Packet loss on peering link';
        jiraDesc = `Ticket created automatically from client request.\n\nDescription: ${text}\n\nRecommended worker action: Verify peering status and links on srx-core-01.`;
        confidence = 98;
    }
    // Check for Scenario 2
    else if (lower.includes('dump') || lower.includes('qfx-leaf-02') || lower.includes('ge-0/0/1')) {
        intent = 'RESOURCE_PROVISIONING';
        device = 'qfx-leaf-02';
        priority = 'Khẩn cấp';
        priorityClass = 'badge-danger';
        agent = 'expert-engineer-agent';
        jiraTitle = '[Service Request] qfx-leaf-02: Export interface ge-0/0/1 config';
        jiraDesc = `Ticket created automatically from client request.\n\nDescription: ${text}\n\nRecommended worker action: Execute show configuration command on qfx-leaf-02 ge-0/0/1 and export log.`;
        confidence = 97;
    }
    // Check for Scenario 3
    else if (lower.includes('bảo trì') || lower.includes('ex-switch') || lower.includes('#1102') || lower.includes('maintenance')) {
        intent = 'PROACTIVE_AUDIT';
        device = 'EX-Switch';
        priority = 'Trung bình';
        priorityClass = 'badge-warning';
        agent = 'customer-advisory-agent';
        jiraTitle = '[Change Request] EX-Switch: Scheduled maintenance ticket #1102';
        jiraDesc = `Ticket created automatically from client request.\n\nDescription: ${text}\n\nRecommended worker action: Draft maintenance ticket, contact L3 engineer for coordinates, notify client.`;
        confidence = 96;
    }
    // Custom inputs
    else {
        // Simple logic for custom text
        if (lower.includes('error') || lower.includes('hỏng') || lower.includes('lỗi') || lower.includes('chết') || lower.includes('mất kết nối') || lower.includes('loss') || lower.includes('ping')) {
            intent = 'INCIDENT_RESPONSE';
            agent = 'analytics-network-engineer-agent';
            priority = 'Cao';
            priorityClass = 'badge-danger';
        } else if (lower.includes('cấu hình') || lower.includes('config') || lower.includes('mở port') || lower.includes('vlan') || lower.includes('peering') || lower.includes('provision')) {
            intent = 'RESOURCE_PROVISIONING';
            agent = 'expert-engineer-agent';
            priority = 'Trung bình';
            priorityClass = 'badge-warning';
        } else {
            intent = 'PROACTIVE_AUDIT';
            agent = 'customer-advisory-agent';
            priority = 'Thấp';
            priorityClass = 'badge-success';
        }

        // Device extraction
        const deviceMatch = text.match(/([a-zA-Z0-9]+-[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)?)/);
        if (deviceMatch) {
            device = deviceMatch[1];
        } else {
            device = 'Unknown';
        }

        jiraTitle = `[NOC Task] ${device !== 'Unknown' ? device : 'System'}: Customer request processing`;
        jiraDesc = `Auto-drafted NOC ticket.\n\nDescription: ${text}`;
    }

    // Update UI fields
    document.getElementById('resIntent').textContent = intent;
    document.getElementById('resDevice').textContent = device;
    document.getElementById('resPriority').innerHTML = `<span class="badge ${priorityClass}">${priority}</span>`;
    document.getElementById('resAgent').textContent = agent;
    document.getElementById('resJiraTitle').textContent = jiraTitle;
    document.getElementById('resJiraDesc').textContent = jiraDesc;
    document.getElementById('resultConfidence').textContent = `Confidence: ${confidence}%`;

    // Toggle panels
    document.getElementById('parserEmptyState').style.display = 'none';
    document.getElementById('parserResultContent').style.display = 'flex';

    showToast('Request analyzed successfully', 'success');
}

function resetParser() {
    document.getElementById('scenarioDropdown').value = '';
    document.getElementById('requestText').value = '';
    document.getElementById('parserEmptyState').style.display = 'flex';
    document.getElementById('parserResultContent').style.display = 'none';
}

async function triggerSupervisor() {
    const message = document.getElementById('requestText').value.trim();
    if (!message) {
        showToast('Please enter a request message first.', 'error');
        return;
    }

    const btn = document.getElementById('btnTriggerSupervisor');
    btn.disabled = true;
    btn.textContent = 'Triggering...';

    try {
        const response = await fetch(`${API_BASE}/admin/api/parser/trigger`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message })
        });

        if (response.ok) {
            const data = await response.json();
            showToast(`Workflow ${data.session_id} triggered successfully!`, 'success');
            
            // Wait 1.5 seconds, then redirect to AI Session Logs tab
            setTimeout(() => {
                // Find logs tab menu item and click it
                const logsTabMenuItem = document.querySelector('.nav-item[data-tab="logs"]');
                if (logsTabMenuItem) {
                    logsTabMenuItem.click();
                    // Load sessions and automatically select the new session
                    setTimeout(() => {
                        loadSessions().then(() => {
                            selectSession(data.session_id);
                        });
                    }, 500);
                }
            }, 1500);
        } else {
            const err = await response.json();
            showToast(`Error: ${err.error || 'Failed to trigger supervisor'}`, 'error');
        }
    } catch (e) {
        showToast(`Connection error: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Gửi đến NOC Supervisor / Tạo Ticket';
    }
}

// ═══ MCP Tools ═══
async function loadTools() {
    try {
        const response = await fetch(`${API_BASE}/admin/api/tools`);
        if (response.ok) {
            state.tools = { data: await response.json() };
        }
    } catch (e) {
        console.warn('Could not load tools from API:', e);
    }
    renderToolsTable();
}

function renderToolsTable() {
    const tbody = document.getElementById('toolsTableBody');
    const data = state.tools ? state.tools.data : [];
    
    if (data.length === 0) {
        tbody.innerHTML = `
            <tr><td colspan="3" style="text-align:center; padding:40px; color:var(--text-secondary);">
                No registered MCP tools found. Connect to the MCP API.
            </td></tr>
        `;
        return;
    }

    tbody.innerHTML = data.map(t => {
        // Format properties from inputSchema
        let argsHtml = '';
        if (t.inputSchema && t.inputSchema.properties) {
            const props = t.inputSchema.properties;
            const required = t.inputSchema.required || [];
            argsHtml = Object.keys(props).map(propName => {
                const isRequired = required.includes(propName);
                const info = props[propName];
                return `<div class="tool-arg">
                    <span class="arg-name">${propName}${isRequired ? ' <span style="color:var(--accent-danger);">*</span>' : ''}</span>
                    <span class="arg-type">(${info.type || 'any'})</span>
                    ${info.description ? ` - <span class="arg-desc">${info.description}</span>` : ''}
                </div>`;
            }).join('');
        } else {
            argsHtml = `<span style="color:var(--text-secondary); font-style:italic;">No arguments</span>`;
        }

        return `
            <tr>
                <td class="cmd-name" style="font-family:'JetBrains Mono',monospace; font-size:13px; color:var(--text-accent); vertical-align: top;">${escapeHtml(t.name)}</td>
                <td style="vertical-align: top; line-height: 1.5;">${escapeHtml(t.description || 'No description')}</td>
                <td>
                    <div style="font-size: 12px; display: flex; flex-direction: column; gap: 4px;">
                        ${argsHtml}
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function filterTools() {
    const search = document.getElementById('toolsSearch').value.toLowerCase();
    const rows = document.querySelectorAll('#toolsTableBody tr');
    
    rows.forEach(row => {
        const name = row.querySelector('.cmd-name').textContent.toLowerCase();
        const desc = row.cells[1].textContent.toLowerCase();
        if (name.includes(search) || desc.includes(search)) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}
