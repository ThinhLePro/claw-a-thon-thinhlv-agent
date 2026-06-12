# JunOS CLI — User Interface & Navigation

## 1. Two Modes

| Mode | Prompt | Purpose | Enter with |
|---|---|---|---|
| **Operational** | `user@device>` | Monitoring, troubleshooting, file ops | Default at login |
| **Configuration** | `user@device#` | Modify configuration | `configure` or `edit` |

### Switching Between Modes
```junos
# From operational → configuration
user@device> configure
[edit]
user@device#

# From configuration → operational (temporarily)
user@device# run show interfaces terse    # 'run' prefix executes operational commands

# From configuration → exit to operational
user@device# exit
user@device>
```

---

## 2. Operational Mode Commands

### Navigation
```junos
# Help
?                                    # Show available commands/options at current position
show ?                               # Show available 'show' subcommands

# Command completion
show int<Tab>                        # Auto-completes to 'show interfaces'
show interfaces <Tab>                # Shows available options

# Pipe commands (filter output)
show interfaces terse | match xe-    # Grep for 'xe-' interfaces
show route | count                   # Count lines
show log messages | last 50          # Last 50 lines
show configuration | display set     # Show config in 'set' format
show configuration | compare         # Compare candidate vs active config
show configuration | no-more         # Disable paging (show all at once)
```

### Output Modifiers
| Modifier | Function | Example |
|---|---|---|
| `\| match <pattern>` | Grep (case-sensitive) | `show route \| match 10.0.1` |
| `\| except <pattern>` | Inverse grep | `show interfaces terse \| except down` |
| `\| count` | Count output lines | `show route \| count` |
| `\| last <N>` | Last N lines | `show log messages \| last 20` |
| `\| find <pattern>` | Start output from first match | `show config \| find protocols` |
| `\| no-more` | Disable paging | `show config \| no-more` |
| `\| display xml` | XML output | For scripting/automation |
| `\| display json` | JSON output | For scripting/automation |
| `\| save <file>` | Save output to file | `show tech-support \| save /var/tmp/ts.txt` |

---

## 3. Configuration Mode

### Navigation within Config Hierarchy
```junos
[edit]
user@device# edit protocols bgp      # Enter 'protocols bgp' hierarchy
[edit protocols bgp]

user@device# up                       # Go up one level
[edit protocols]

user@device# up 2                     # Go up two levels
[edit]

user@device# top                      # Go to top of hierarchy
[edit]

user@device# edit interfaces xe-0/0/0 unit 0
[edit interfaces xe-0/0/0 unit 0]
```

### Viewing Configuration
```junos
# Show current level (hierarchical format)
show

# Show as 'set' commands (flat format — easier to copy/paste)
show | display set

# Show specific section
show interfaces
show protocols bgp

# Show from any level
show interfaces xe-0/0/0

# Compare candidate config with active (committed) config
show | compare

# Show inherited configuration (from groups/apply-groups)
show | display inheritance
```

### Making Changes
```junos
# Set a value
set system host-name LEAF-A01-01

# Delete a value
delete system host-name

# Rename
rename interfaces xe-0/0/0 to xe-0/0/1

# Copy
copy interfaces xe-0/0/0 to xe-0/0/1

# Deactivate (keeps config but doesn't apply)
deactivate protocols ospf

# Reactivate
activate protocols ospf

# Insert (for ordered lists like firewall filters)
insert term NEW-TERM before term EXISTING-TERM
```

---

## 4. Commit Model

JunOS uses a **candidate configuration** model:
1. You make changes to the **candidate config** (not yet active)
2. You **commit** to apply changes to the **active config**
3. If something goes wrong, you **rollback**

### Commit Commands

| Command | Description | When to Use |
|---|---|---|
| `commit check` | Validate syntax/semantics without applying | Always run first |
| `commit confirmed <minutes>` | Apply but auto-rollback after N minutes if not confirmed | **Production changes — ALWAYS USE** |
| `commit` | Apply permanently | After confirming `commit confirmed` works |
| `commit comment "message"` | Apply with audit comment | Every production change |
| `commit synchronize` | Apply on all RE (dual-RE systems) | Multi-RE chassis |
| `commit and-quit` | Apply and exit config mode | Quick changes |

### Safe Change Workflow
```junos
# 1. Make changes
set interfaces xe-0/0/0 description "Uplink to SPINE-01"

# 2. Review what will change
show | compare
# [edit interfaces xe-0/0/0]
# +   description "Uplink to SPINE-01";

# 3. Validate
commit check
# configuration check succeeds

# 4. Apply with safety net (5 min auto-rollback)
commit confirmed 5 comment "Add interface description for SPINE-01 uplink"

# 5. Verify the change works as expected
run show interfaces xe-0/0/0

# 6. If good, confirm (prevent auto-rollback)
commit

# 7. If bad, do nothing — auto-rollback happens in 5 minutes
# Or manually: rollback 0 → commit (immediate rollback)
```

### Rollback
```junos
# Show available rollback points (up to 49 saved)
show system rollback ?

# Compare current config with rollback N
show system rollback compare 1     # Compare with previous commit

# Rollback to a specific point
rollback 1                         # Load the config from 1 commit ago
show | compare                     # Review what will change
commit                             # Apply the rollback
```

---

## 5. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Tab` | Auto-complete command |
| `Ctrl+A` | Move cursor to beginning of line |
| `Ctrl+E` | Move cursor to end of line |
| `Ctrl+W` | Delete word before cursor |
| `Ctrl+U` | Delete entire line |
| `Ctrl+C` | Abort current command |
| `Ctrl+Z` | Exit configuration mode (like `exit`) |
| `Space` | Page down (in paged output) |
| `q` | Quit paged output |
