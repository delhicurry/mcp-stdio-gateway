# MCP Stdio Gateway (MSG)

**Gateway architecture to bundle multiple local-only (stdio + env vars) MCP servers and expose them as multi-tenant cloud resources.**

> This is **not** a tunnel. MSG acts as a process manager and gateway — it dynamically spawns, authenticates, and terminates stdio MCP server processes per request.

## The Problem

Many official MCP servers (Kintone, GitHub, Slack, etc.) only support the `stdio` transport. This design has three fundamental limitations:

1. **Not reachable from cloud agents.** ChatGPT, Claude, Manus, and other cloud-based agents require HTTP (Streamable HTTP) endpoints. stdio servers cannot be called directly.
2. **No Dynamic Authentication.** Credentials (API tokens, etc.) are hardcoded as environment variables at process startup. A single running process cannot serve multiple users with different credentials.
3. **No multi-server bundling.** Each stdio server runs as an isolated process. There is no standard way to expose multiple servers through a single unified HTTP endpoint.

Workarounds like OpenAI Secure MCP Tunnel only address problem #1 while leaving #2 and #3 unsolved — and they introduce vendor lock-in.

## How MSG Solves This

MSG is a FastAPI application that acts as a **Gateway** in front of any number of stdio MCP servers:

| Problem | MSG Solution |
|---|---|
| Not reachable from cloud agents | Exposes a standard HTTP endpoint for each registered server |
| No Dynamic Authentication | Reads credentials from the `x-mcp-credentials` HTTP header and **injects them as environment variables** when spawning the child process |
| No multi-server bundling | All servers are registered in `servers.yaml` and routed via `/mcp/{server_name}/...` |
| Vendor lock-in (OpenAI Tunnel) | Works with any MCP client (Claude, Manus, custom agents, etc.) |

## Architecture

```
[Cloud Agent (Manus, Claude, ChatGPT, etc.)]
       |
       | HTTP  (x-mcp-credentials: {"TOKEN": "..."})
       v
+-------------------------------+
|   MCP Stdio Gateway (MSG)     |
|   FastAPI                     |
|                               |
|  /mcp/kintone/tools/call  ----+--> spawn: npx @kintone/mcp-server
|  /mcp/github/tools/call   ----+--> spawn: npx @modelcontextprotocol/server-github
|  /mcp/slack/tools/call    ----+--> spawn: npx @modelcontextprotocol/server-slack
|                               |
|  Credentials injected as      |
|  env vars at spawn time       |
+-------------------------------+
       |
       | stdio (per request, dynamically spawned)
       v
[stdio MCP Server Process]
       |
       v
[External SaaS (Kintone / GitHub / Slack / ...)]
```

**Key design decisions:**

- **Stateless per request**: A child process is spawned for each request and terminated when the response is returned. No shared state between requests.
- **Dynamic credential injection**: The `x-mcp-credentials` header carries a JSON object. The gateway extracts the required keys (defined per server in `servers.yaml`) and passes them as environment variables to the spawned process.
- **Server registry**: `servers.yaml` is the single source of truth. Adding a new stdio MCP server requires only a new entry — no code changes.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
# Node.js (v18+) and npx must be available on your system
```

### 2. Configure Servers

Edit `servers.yaml` to register your stdio MCP servers:

```yaml
servers:
  kintone:
    command: "npx"
    args: ["-y", "@kintone/mcp-server"]
    env_keys:
      - "KINTONE_BASE_URL"
      - "KINTONE_API_TOKEN"

  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env_keys:
      - "GITHUB_PERSONAL_ACCESS_TOKEN"

  slack:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-slack"]
    env_keys:
      - "SLACK_BOT_TOKEN"
      - "SLACK_TEAM_ID"
```

### 3. Run the Gateway

```bash
uvicorn app.main:app --reload
```

### 4. Call Any Registered Server

The `x-mcp-credentials` header carries all required credentials as a JSON string. The gateway routes the request to the correct server based on `{server_name}` in the URL path.

**List tools (Kintone):**
```bash
curl -X GET "http://127.0.0.1:8000/mcp/kintone/tools" \
  -H 'x-mcp-credentials: {"KINTONE_BASE_URL": "https://example.cybozu.com", "KINTONE_API_TOKEN": "your_token"}'
```

**List tools (GitHub):**
```bash
curl -X GET "http://127.0.0.1:8000/mcp/github/tools" \
  -H 'x-mcp-credentials: {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxxx"}'
```

**Call a tool (Slack):**
```bash
curl -X POST "http://127.0.0.1:8000/mcp/slack/tools/call" \
  -H "Content-Type: application/json" \
  -H 'x-mcp-credentials: {"SLACK_BOT_TOKEN": "xoxb-xxxx", "SLACK_TEAM_ID": "T0123"}' \
  -d '{"tool_name": "slack_post_message", "arguments": {"channel": "#general", "text": "Hello from MSG"}}'
```

## Deployment to AWS AgentCore Runtime

MSG is stateless and container-friendly. It runs on AWS AgentCore Runtime, Fargate, Lambda, or any container platform.

1. **Build the Docker image:**
   ```bash
   docker build -t mcp-stdio-gateway .
   ```
   The Dockerfile pre-installs all registered MCP server packages globally (`npm install -g`) to eliminate `npx` download overhead at runtime.

2. **Deploy as an AgentCore Runtime Harness.**

3. **Pass credentials securely:** Use AgentCore Identity (Outbound Auth) to retrieve tokens from AWS Secrets Manager and include them in the `x-mcp-credentials` header when calling the gateway.

## Design Comparison

| Approach | Multi-server | Dynamic Auth | Vendor-free | No local process required |
|---|---|---|---|---|
| **MSG (this project)** | Yes | Yes | Yes | Yes |
| OpenAI Secure MCP Tunnel | No | No | No (OpenAI only) | No |
| supergateway | No | No | Yes | Yes |
| stdio directly (local) | No | No | Yes | No |

## License

MIT
