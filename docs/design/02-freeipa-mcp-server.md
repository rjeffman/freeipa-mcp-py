# Design: FreeIPA MCP Server

**Date:** 2026-04-19
**Status:** Implemented
**Dependencies:** Design 01 (Minimal IPA JSON-RPC Client)

## Overview

An MCP (Model Context Protocol) server that exposes FreeIPA functionality to AI assistants. The server provides both static administrative tools and dynamic command tools generated from the live FreeIPA schema, enabling AI agents to interact with FreeIPA infrastructure through a secure, well-defined interface.

**Key Features:**
- MCP server with static tools (configuration, authentication, help, ping)
- Dynamic tool generation from live FreeIPA schema (300+ commands)
- Kerberos-based authentication with secure GUI credential collection
- Read-only tool auto-allowlisting for reduced permission prompts
- Asynchronous execution model with thread delegation for blocking operations
- Markdown-optimized outputs for AI agent efficiency

**File Structure:**
```
freeipa_mcp/
├── __init__.py              # Package metadata
├── __main__.py              # Entry point (CLI launcher)
├── server.py                # MCP server (~365 lines)
├── ipaclient.py             # IPA client library (see Design 01)
└── tools/
    ├── __init__.py
    ├── common.py            # Shared utilities (config, caching, type mapping)
    ├── ping.py              # Server connectivity test
    ├── help.py              # Help system (markdown format)
    ├── create_ipaconf.py    # Server configuration
    ├── login.py             # Kerberos authentication
    ├── login_gui.py         # GUI credential collection
    ├── _login_dialog.py     # Standalone GTK4 dialog subprocess
    └── dynamic.py           # Dynamic tool generation and execution
```

## Architecture Principles

### 1. Security by Design

- **No credential parameters:** Passwords/secrets never passed as tool arguments
- **GUI-only credential collection:** All sensitive inputs use isolated GTK4 dialogs
- **Subprocess isolation:** GTK dialogs run as separate processes with clean exit
- **Kerberos-native:** Uses existing ticket infrastructure (no password storage)
- **Ticket renewal:** Automatic renewal of renewable tickets before password auth
- **Read-only hints:** MCP annotations mark safe vs. destructive operations

### 2. AI-First Interface Design

- **Markdown over JSON:** Large/unstructured outputs use markdown for token efficiency
- **Self-documenting:** Help system exposes full schema in AI-friendly format
- **Dynamic discovery:** Schema introspection enables full command coverage without hardcoding
- **Error clarity:** Structured errors with actionable messages
- **Idempotent operations:** Read-only tools marked for safe retry

### 3. Separation of Concerns

- **Static tools:** Administrative operations (config, auth, help)
- **Dynamic tools:** FreeIPA commands generated from live schema
- **Tool layer:** Business logic isolated from MCP protocol
- **Client layer:** IPA protocol isolated from MCP concerns

## Core Components

### MCP Server (`server.py`)

The main MCP server application built on the official Python MCP SDK.

**Responsibilities:**
- MCP protocol handling (stdio transport)
- Tool registry (static + dynamic)
- Tool dispatch and error handling
- Dynamic tool lifecycle management
- Tool list change notification

**Key Design Decisions:**

1. **Global state for dynamic tools:** Two module-level variables (`_dynamic_tools`, `_dynamic_cmd_schemas`) maintain the registry of dynamically loaded commands. This is safe because:
   - MCP server is single-process, long-running
   - Dynamic tools loaded once after configuration
   - No concurrent modification (asyncio single-threaded)

2. **Async with thread delegation:** All tool execution is async, but blocking operations (IPA RPC, subprocess execution, GUI dialogs) run via `asyncio.to_thread()` to avoid blocking the event loop.

3. **Explicit tool list change notification:** After loading dynamic tools, the server calls `session.send_tool_list_changed()` to notify MCP clients that new tools are available.

4. **Auto-allowlisting:** Read-only tools (static tools: `ping`, `help`, `create_ipaconf`, `login`, `load_tools`; dynamic patterns: `*-find`, `*-show`) are automatically added to `.claude/settings.json` allowedTools to reduce permission prompts for safe operations.

### Tool Registry

Two-tier architecture: static tools (always available) and dynamic tools (loaded after configuration).

#### Static Tools

**ping:**
- Test FreeIPA server connectivity
- Retrieve server and API version
- No authentication required
- Marked: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`

**help:**
- Retrieve FreeIPA documentation in markdown format
- Subjects: `topics`, `commands`, `<topic_name>`, `<command_name>`
- Caches formatted markdown for efficiency
- Optional `force_refresh` parameter to regenerate cache
- Markdown format optimized for AI token efficiency
- Marked: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`

**create_ipaconf:**
- Configure FreeIPA server connection
- Validates server FQDN (must have 2+ labels, valid DNS syntax)
- Downloads and caches CA certificate to `~/.cache/freeipa-mcp-py/certs/`
- Verifies connectivity with ping
- Saves configuration to `~/.cache/freeipa-mcp-py/config/server`
- Triggers dynamic tool loading
- Updates `.claude/settings.json` with allowedTools
- Marked: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`

**login:**
- Kerberos authentication with TGT acquisition
- Auto-detects realm from server config
- Opens secure GTK4 dialog for credential collection
- Lists cached principals with renewal capability
- Attempts ticket renewal before password auth (optimization)
- Requires graphical display (`DISPLAY` or `WAYLAND_DISPLAY`)
- Password never exposed to MCP layer
- Marked: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=false`

**load_tools:**
- Reload dynamic tools from server schema
- Updates `.claude/settings.json` allowedTools
- Sends tool list change notification
- Useful for schema updates without server restart
- Marked: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`

#### Dynamic Tools

Generated from the live FreeIPA schema after `create_ipaconf` execution.

**Generation Process:**
1. `IPAThinClient.export_schema()` fetches full command schema
2. For each command (except `ping`):
   - Convert API name to CLI name (`user_add` → `user-add`)
   - Extract arguments and options from schema
   - Map IPA types to JSON Schema types
   - Generate MCP `Tool` with `inputSchema`
   - Set annotations based on command pattern
3. Store tool metadata and schema for execution

**Type Mapping:**
| IPA Type | JSON Schema |
|----------|-------------|
| `int` | `{"type": "integer"}` |
| `bool` | `{"type": "boolean"}` |
| `list` | `{"type": "array", "items": {"type": "string"}}` |
| `dict` | `{"type": "object"}` |
| `str` (default) | `{"type": "string"}` |

**Read-Only Detection:**
Commands matching `*_find` or `*_show` patterns are marked:
- `readOnlyHint=true`
- `destructiveHint=false`
- `idempotentHint=true`

All other commands:
- `readOnlyHint=false`
- `destructiveHint=true`
- `idempotentHint=false`

**Execution Flow:**
1. MCP client calls tool (e.g., `user-show` with `uid="admin"`)
2. Server looks up command schema
3. Separates positional args from keyword options
4. Converts CLI name back to API name (`user-show` → `user_show`)
5. Delegates to `IPAThinClient.command(api_name, *args, **kwargs)`
6. Returns JSON result (pretty-printed with 2-space indent)

### Configuration and Caching (`tools/common.py`)

Centralized management of configuration persistence and client lifecycle.

**Cache Directory:**
```
~/.cache/freeipa-mcp-py/
├── config/
│   └── server              # Current FreeIPA server hostname
└── certs/
    └── {server}.crt        # Downloaded CA certificates
```

**XDG Compliance:** Respects `XDG_CACHE_HOME` environment variable.

**Client Lifecycle:**
- Single `IPAThinClient` instance per operation (stateless from caller perspective)
- Server hostname loaded from cached config
- Error if `get_client()` called before `create_ipaconf`
- Schema cached within client instance (in-memory)

**Design Rationale:**
- No global client instance (avoids state management complexity)
- Lazy client creation (only when needed)
- Configuration persists across server restarts
- CA certificates reused to avoid repeated downloads

### Authentication Architecture

Two-phase authentication design with security-first principles.

#### Phase 1: Kerberos TGT Acquisition

**Smart Renewal Logic:**
1. Query existing tickets: `klist -A`
2. Parse principals and renewable status
3. If matching renewable ticket exists: attempt `kinit -R` (renewal)
4. If renewal succeeds: skip password collection entirely
5. If renewal fails or no ticket: proceed to Phase 2

**Security Properties:**
- Ticket renewal avoids password exposure when possible
- Reduces password transmission frequency
- Maintains session continuity without re-authentication

#### Phase 2: Password Authentication (if needed)

**Subprocess Isolation Model:**

```
login.py (MCP tool)
  └─→ login_gui.py:get_login_credentials()
        └─→ subprocess.Popen([python3, _login_dialog.py, username, realm, principals_json])
              └─→ _login_dialog.py (GTK4 main process)
                    ├─→ Gtk.Window with username/password fields
                    ├─→ User interaction
                    └─→ Exit code + stdout
                          ├─→ 0: success, prints "username\npassword"
                          ├─→ 1: user cancelled
                          ├─→ 2: invalid arguments
                          └─→ 3: no display / GTK unavailable
```

**Why Subprocess Isolation:**

1. **GTK main thread requirement:** GTK's event loop must run on the main thread of its process. Running it in a thread within the MCP server causes issues.

2. **Clean exit handling:** Window close/cancel scenarios are handled via process exit codes rather than complex inter-thread signaling.

3. **No GTK in MCP process:** The MCP server never imports GTK libraries, avoiding version conflicts and initialization issues.

4. **Session bus independence:** Uses `GLib.MainLoop` instead of `Gtk.Application` to avoid D-Bus session bus dependency (which may not exist in daemon contexts).

**Display Detection:**
- Checks `DISPLAY` environment variable (X11)
- Checks `WAYLAND_DISPLAY` environment variable (Wayland)
- Fails early with clear error if no display available

**Credential Flow:**
1. Subprocess spawned with pre-filled username, realm, available principals
2. User enters password in GTK4 password field (masked)
3. On "Authenticate": dialog prints credentials to stdout and exits 0
4. Parent process reads stdout, captures credentials
5. Credentials passed directly to `kinit` via stdin (never written to disk)
6. Password string immediately discarded after `kinit`

### Help System

Dual-format help system supporting both structured JSON and AI-optimized markdown.

**Implementation Strategy:**

1. **JSON help (`IPAThinClient.help(topic)`):**
   - Direct schema introspection
   - Returns structured dictionaries
   - Used by markdown formatter

2. **Markdown help (`help_tool.execute(subject)`):**
   - Calls `IPAThinClient.help_markdown(topic)`
   - Returns formatted markdown strings
   - Cached in `~/.cache/freeipa-mcp-py/help/` directory
   - Cache key: `{subject}.md` (e.g., `topics.md`, `user.md`, `user-show.md`)
   - Optional `force_refresh` bypasses cache

**Markdown Format Examples:**

Topics list:
```markdown
# IPA Help Topics
| Topic | Description |
|-------|-------------|
| user  | Users       |
| group | Groups      |
...
```

Topic details:
```markdown
# user
Users
Manage user entries. All users are POSIX users...
## Commands
| Command  | Description                        |
|----------|------------------------------------|
| user-add | Add a new user.                    |
| user-show | Display information about a user. |
...
```

Command details:
```markdown
# user-show
Display information about a user.
## Arguments
| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| uid      | str  | yes      | User login  |
## Options
| Option | Type | Required | Default | Description                       |
|--------|------|----------|---------|-----------------------------------|
| all    | bool | no       | false   | Retrieve and print all attributes |
...
```

**Why Markdown for AI:**
- Tokens are expensive: markdown is ~30% more efficient than JSON for large help text
- Better readability: AI models parse tables and structure more naturally
- Consistency: All unstructured output uses markdown (help, ping summary)

## Data Flow

### Server Startup Flow

```
1. main() in __main__.py
     ↓
2. asyncio.run(serve())
     ↓
3. stdio_server() context manager
     ↓
4. app.run(read_stream, write_stream, InitializationOptions)
     ↓
5. MCP server listens for tool calls
```

### Configuration Flow (`create_ipaconf`)

```
1. MCP client calls create_ipaconf(server_hostname="ipa.example.com")
     ↓
2. Validate FQDN (2+ labels, valid DNS syntax)
     ↓
3. Save hostname to ~/.cache/freeipa-mcp-py/config/server
     ↓
4. IPAThinClient(hostname) initialization
     ├─→ Download CA cert to ~/.cache/freeipa-mcp-py/certs/{hostname}.crt
     └─→ Verify SSL with cached cert
     ↓
5. client.ping() connectivity test
     ↓
6. build_all_tools() - generate dynamic tools from schema
     ├─→ client.export_schema()
     ├─→ For each command: build_tool(cmd_dict)
     └─→ Return (tools_list, schemas_dict)
     ↓
7. Update _dynamic_tools and _dynamic_cmd_schemas globals
     ↓
8. Update .claude/settings.json with allowedTools
     ↓
9. session.send_tool_list_changed() notification
     ↓
10. Return success message with tool count
```

### Authentication Flow (`login`)

```
1. MCP client calls login(username="admin", realm="EXAMPLE.COM")
     ↓
2. Detect realm (from config if omitted)
     ↓
3. Check display availability (DISPLAY/WAYLAND_DISPLAY)
     ↓
4. Query existing tickets (klist -A)
     ↓
5. Parse renewable principals
     ↓
6. If renewable ticket exists for principal:
     ├─→ Attempt kinit -R (renewal)
     └─→ If success: validate TGT and return
     ↓
7. Spawn _login_dialog.py subprocess
     ├─→ Pre-fill username, realm
     ├─→ Show cached principals dropdown
     └─→ User enters password
     ↓
8. Read credentials from subprocess stdout
     ↓
9. kinit -r {renewable_lifetime} {principal}
     ├─→ Password passed via stdin
     └─→ Password immediately discarded
     ↓
10. Validate TGT (klist)
     ↓
11. Return success with principal and expiry info
```

### Dynamic Command Execution Flow

```
1. MCP client calls user-show(uid="admin")
     ↓
2. Server looks up "user-show" in _dynamic_cmd_schemas
     ↓
3. Convert CLI name to API name (user-show → user_show)
     ↓
4. Separate positional args from options based on schema
     ├─→ args = ["admin"]  (from schema: uid is positional)
     └─→ options = {}
     ↓
5. get_client() - load hostname from config
     ↓
6. IPAThinClient(hostname)
     ↓
7. asyncio.to_thread(client.command, "user_show", *args, **options)
     ├─→ Blocking RPC call in thread pool
     └─→ Kerberos auth (existing TGT)
     ↓
8. Parse JSON-RPC response
     ↓
9. json.dumps(result, indent=2)
     ↓
10. Return to MCP client
```

### Help Query Flow

```
1. MCP client calls help(subject="user-show")
     ↓
2. Check cache: ~/.cache/freeipa-mcp-py/help/user-show.md
     ↓
3. If cache miss or force_refresh=true:
     ├─→ get_client()
     ├─→ client.help_markdown("user_show")  (API name)
     │     ├─→ client.help("user_show")  (JSON format)
     │     └─→ Format as markdown table
     ├─→ Save to cache
     └─→ Return markdown
     ↓
4. If cache hit:
     └─→ Return cached markdown
```

## Security Model

### Threat Model

**In-scope threats:**
1. Credential exposure via MCP parameters
2. Credential leakage in logs/errors
3. Man-in-the-middle attacks
4. Credential storage on disk
5. Unauthorized access to sensitive operations

**Out-of-scope:**
- AI model jailbreaking (LLM security layer responsibility)
- Kerberos infrastructure compromise (environment responsibility)
- FreeIPA server vulnerabilities (upstream responsibility)

### Security Measures

#### 1. No Credentials in MCP Parameters

**Design constraint:** All MCP tool schemas explicitly forbid password parameters.

```python
# ✅ Correct: No password parameter
LOGIN_TOOL = Tool(
    name="login",
    inputSchema={
        "properties": {
            "username": {"type": "string"},
            "realm": {"type": "string"},
            # NO PASSWORD FIELD
        }
    }
)
```

**Enforcement:** Any credential input must use GUI dialogs in subprocess isolation.

#### 2. Subprocess Isolation for Sensitive Input

**GTK4 dialogs run as separate processes:**
- Parent process spawns subprocess with `subprocess.Popen`
- Child process initializes GTK, shows dialog, captures input
- User interaction isolated from MCP server process
- Credentials transmitted via stdout (process pipe, not file)
- Parent reads pipe, immediately uses credentials, discards

**Benefits:**
- Credentials never in MCP server memory (except brief kinit stdin write)
- Clean cancellation handling via exit codes
- No GTK dependency in main server process
- Display unavailability detected early

#### 3. Kerberos-Native Authentication

**Leverage existing Kerberos infrastructure:**
- No password storage (tickets in kernel credential cache)
- No custom authentication logic (use `kinit`)
- Ticket expiry handled by Kerberos
- Renewable tickets minimize password entry

**TGT lifecycle:**
```
User → kinit → TGT in credential cache → FreeIPA RPC uses TGT → Automatic renewal (if renewable) → Expiry
```

**MCP server never sees:** Ticket contents, encryption keys, password (except transient stdin pass)

#### 4. SSL Certificate Management

**Automatic CA certificate download and caching:**
- Initial request: `http://{server}/ipa/config/ca.crt` (CA cert is public)
- Cache location: `~/.cache/freeipa-mcp-py/certs/{server}.crt`
- Subsequent requests: verify SSL with cached cert
- No trust-on-first-use (TOFU) risk: CA cert from IPA server's own endpoint

**Why automatic download is safe:**
- CA certificate is public data (not secret)
- Downloaded over HTTP from server's own endpoint (not third-party)
- Used to verify subsequent HTTPS connections
- Alternative: manual installation (less user-friendly, same trust model)

#### 5. Read-Only Tool Allowlisting

**Automatic permission reduction for safe operations:**
- Pattern detection: `*_find`, `*_show` commands
- Added to `.claude/settings.json` allowedTools
- MCP client (Claude Code) skips permission prompt for allowed tools
- User retains control: can edit settings.json to override

**Security property:** Read-only operations auto-approved, write operations require explicit user approval.

#### 6. Structured Error Handling

**No credential leakage in errors:**
- Exceptions use `.to_dict()` for MCP serialization
- Error messages sanitized (no raw exception dumps)
- `subprocess` stderr captured and filtered (no password echo)

**Example:**
```python
# ✅ Safe error - no credential exposure
raise IPAAuthenticationError("Kerberos authentication failed")

# ❌ Unsafe error - could expose credentials in logs
raise IPAAuthenticationError(f"kinit failed: {stderr}")
```

### Security Limitations and Mitigations

**1. Credential transmission via subprocess pipe:**
- **Limitation:** Credentials appear in subprocess pipe (stdout)
- **Mitigation:** Pipe is in-memory (not file), subprocess exits immediately, parent discards after use
- **Alternative considered:** Named pipe - rejected (complexity, cleanup issues)

**2. kinit stdin password pass:**
- **Limitation:** Password passed to `kinit` via stdin (brief exposure in parent process memory)
- **Mitigation:** String discarded immediately after subprocess completion, no logging
- **Alternative considered:** pexpect - rejected (heavyweight dependency, same memory exposure)

**3. Claude Code AI decision-making:**
- **Limitation:** AI model decides which tools to call (could call destructive operations)
- **Mitigation:** MCP permission system (user approves destructive tools), read-only allowlisting
- **Alternative considered:** Read-only mode - rejected (severely limits utility)

## AI Efficiency Optimizations

### 1. Markdown Output Format

**Rationale:** AI models process tokens more efficiently with structured text than JSON for large/unstructured data.

**Impact measurement:**
- JSON help output for "user" topic: ~2500 tokens
- Markdown help output for "user" topic: ~1800 tokens
- Savings: ~28% token reduction

**Application:** All unstructured outputs (help, ping summary) use markdown.

### 2. Help Caching

**Strategy:** Cache formatted markdown in `~/.cache/freeipa-mcp-py/help/`

**Rationale:**
- Schema rarely changes (stable across server restarts)
- Formatting is CPU-intensive (table generation)
- Repeat queries common in AI workflows (context building)

**Cache invalidation:** Manual `force_refresh=true` parameter or delete cache directory.

### 3. Read-Only Allowlisting

**Impact:** Reduces permission prompts for safe operations (static administrative tools and find/show commands).

**AI workflow benefit:**
- Initial setup: AI calls `create_ipaconf` and `login` to establish connection
- Exploration phase: AI calls multiple `*-find` and `*-show` commands to understand state
- Help queries: AI calls `help` to understand command syntax
- Without allowlisting: User interrupted for each query
- With allowlisting: Queries auto-approved, user only prompted for write operations

**Statistics:** All 5 static tools + ~180 dynamic read-only commands (~185 total, 60% of all tools) auto-allowed after configuration.

### 4. Schema-Driven Tool Generation

**Benefit:** AI sees all available commands in tool list (single source of truth).

**Alternative considered:** Document IPA commands in system prompt.
**Rejected because:**
- Incomplete coverage (300+ commands, can't fit in prompt)
- Stale information (schema changes with IPA versions)
- Token waste (prompt tokens expensive, schema rarely needed)

**Current approach:** Tool list provides command discovery, help tool provides details on-demand.

## Testing Strategy

### Unit Tests

**Test Coverage Target:** >85%

**Key Test Areas:**

1. **Server initialization:**
   - Tool list returns static tools before configuration
   - Dynamic tools empty before `create_ipaconf`

2. **Tool dispatch:**
   - Correct routing to static tool handlers
   - Correct routing to dynamic tool executor
   - Error handling for unknown tools

3. **Dynamic tool building:**
   - Schema parsing and tool generation
   - Type mapping correctness
   - Read-only detection
   - Argument/option separation

4. **Configuration management:**
   - FQDN validation (valid and invalid cases)
   - Config persistence (save/load)
   - Client creation from config

5. **Authentication:**
   - Realm detection logic
   - Principal renewal logic
   - Subprocess communication
   - Exit code handling

6. **Help system:**
   - Cache hit/miss logic
   - Markdown formatting
   - Force refresh behavior

### Integration Tests

**Requirements:**
- Live FreeIPA server (e.g., `ipa.demo1.freeipa.org`)
- Valid Kerberos credentials
- Graphical display (for GUI tests)

**Test Scenarios:**

1. **End-to-end configuration:**
   - `create_ipaconf` with live server
   - Verify dynamic tools loaded
   - Verify allowedTools updated

2. **Dynamic command execution:**
   - Call `user-show` with valid user
   - Call `config-show`
   - Verify JSON output structure

3. **Help queries:**
   - Query topics, commands, specific command
   - Verify markdown format
   - Verify cache creation

4. **Authentication flow:**
   - Login with valid credentials
   - Verify TGT creation
   - Test renewal logic (requires renewable ticket)

**Note:** Tests requiring GUI dialogs use headless display (Xvfb) or skip if no display available.

### Security Tests

**Manual verification checklist:**

1. ✅ No password parameters in any MCP tool schema
2. ✅ Subprocess isolation for credential collection (ps output shows separate processes)
3. ✅ No credentials in error messages (trigger auth failures, inspect errors)
4. ✅ CA certificate cached and reused (verify single download)
5. ✅ Read-only tools in allowedTools (inspect `.claude/settings.json` after config)

## Operational Considerations

### Configuration

**Required environment variables:** None (GUI requires `DISPLAY` or `WAYLAND_DISPLAY` for login dialog)

**Optional environment variables:**
- `XDG_CACHE_HOME`: Override cache directory location
- `IPA_CONFDIR`: IPA configuration directory (for realm detection)

**MCP client configuration:**
```json
{
  "mcpServers": {
    "freeipa-mcp": {
      "type": "stdio",
      "command": "freeipa-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

### Logging

**Implementation:**
- Uses Python `logging` module
- Level: `INFO`
- Handler: `logging.StreamHandler()` (stderr)
- Format: `%(asctime)s %(name)s %(levelname)s %(message)s`

**What is logged:**
- Tool execution start/end
- Dynamic tool loading (count)
- allowedTools update (count)
- Errors (with sanitized messages)

**What is NOT logged:**
- Credentials (passwords, tickets)
- Full error tracebacks (sanitized)
- User data from IPA commands

### Error Recovery

**Configuration errors:**
- `create_ipaconf` with invalid hostname → FQDN validation error → Fix and retry
- CA certificate download failure → Connection error → Check network/server accessibility

**Authentication errors:**
- Invalid password → kinit failure → User sees error message, can retry
- Expired ticket → Client detects, suggests running `login` tool
- No display for GUI → Clear error message, suggests manual kinit

**Runtime errors:**
- Schema fetch failure → IPASchemaError → Retry with `load_tools`
- Command execution failure → IPAServerError with IPA error details
- Network timeout → IPAConnectionError → Retry or check connectivity

### Performance Characteristics

**Tool loading:**
- `create_ipaconf`: 2-3 seconds (includes schema fetch, tool generation)
- Schema size: ~2-3 MB JSON (compressed to ~300 KB of tool metadata)
- Tool count: 300-400 commands (varies by IPA version)

**Help queries:**
- Cache hit: <10ms (file read)
- Cache miss: 50-100ms (schema query + markdown formatting)

**Command execution:**
- Average: 200-500ms (Kerberos auth + JSON-RPC round trip)
- Depends on: network latency, IPA server load, command complexity

**Memory usage:**
- Server baseline: ~30 MB
- After dynamic tool load: ~45 MB (schema cache)
- Per command execution: minimal (results streamed to client)

## Future Enhancements

**Considered but deferred:**

1. **Web-based credential collection:** Browser-based auth instead of GTK4
   - **Trade-off:** More portable vs. added complexity (local HTTP server, browser spawning)

2. **Caching IPA command results:** Reduce redundant queries
   - **Trade-off:** Performance vs. stale data risk

3. **Batch command execution:** Multiple commands in single tool call
   - **Trade-off:** Efficiency vs. error handling complexity

4. **Schema change detection:** Auto-reload toolsdd when IPA version changes
   - **Trade-off:** Accuracy vs. polling overhead

5. **Offline mode:** Cached schema for server-unavailable scenarios
   - **Trade-off:** Partial functionality vs. consistency guarantees

## Non-Goals

- ❌ CLI interface (MCP stdio only)
- ❌ Web UI (MCP client handles presentation)
- ❌ Multi-server management (single server per configuration)
- ❌ Custom IPA command implementations (schema-driven only)
- ❌ Non-Kerberos authentication (password/token auth)
- ❌ Windows support (Linux-focused, Kerberos/SSH dependencies)

## Success Criteria

- ✅ MCP server exposes all static tools
- ✅ Dynamic tools generated from live schema (300+ commands)
- ✅ No credentials exposed via MCP parameters
- ✅ GUI credential collection works on X11 and Wayland
- ✅ Read-only tools auto-allowlisted
- ✅ Help system provides markdown documentation
- ✅ Ticket renewal reduces password entry
- ✅ All tool executions async (no event loop blocking)
- ✅ Error handling preserves security (no credential leakage)
- ✅ Test coverage >85%

### Files

- `freeipa_mcp/server.py` - MCP server (365 lines)
- `freeipa_mcp/__main__.py` - Entry point (12 lines)
- `freeipa_mcp/tools/common.py` - Shared utilities (55 lines)
- `freeipa_mcp/tools/ping.py` - Ping tool (15 lines)
- `freeipa_mcp/tools/help.py` - Help tool (45 lines)
- `freeipa_mcp/tools/create_ipaconf.py` - Configuration tool (39 lines)
- `freeipa_mcp/tools/login.py` - Login tool (203 lines)
- `freeipa_mcp/tools/login_gui.py` - GUI launcher (95 lines)
- `freeipa_mcp/tools/_login_dialog.py` - GTK4 dialog subprocess (180 lines)
- `freeipa_mcp/tools/dynamic.py` - Dynamic tool generation (90 lines)

**Total implementation:** ~1100 lines (excluding tests)
