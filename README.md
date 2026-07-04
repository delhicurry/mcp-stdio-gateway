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

### 4. Discover Required Credentials (MSG Custom)

The MCP specification does not define a way to ask a server "what credentials do you need?". MSG provides custom endpoints so clients can discover this dynamically before establishing a session.

**List all registered servers and their required credentials:**
```bash
curl -X GET "http://127.0.0.1:8000/mcp/servers"
```

**Get info for a specific server:**
```bash
curl -X GET "http://127.0.0.1:8000/mcp/kintone/info"
```
*(These custom endpoints do not require authentication.)*

### 5. Call Any Registered Server (MCP Compliant)

Once you know the required credentials, pass them in the `x-mcp-credentials` header as a JSON string. The gateway dynamically spawns the process, injects the credentials, and routes the MCP request.

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
| **MSG (this project)** | Yes | **Yes** | Yes | Yes |
| Docker MCP Gateway | Yes | No (startup-time only) | Yes | Partial (Docker required) |
| OpenAI Secure MCP Tunnel | No | No | No (OpenAI only) | No |
| supergateway | No | No | Yes | Yes |
| stdio directly (local) | No | No | Yes | No |

## Comparison with Docker MCP Gateway

[Docker MCP Gateway](https://docs.docker.com/ai/mcp-catalog-and-toolkit/mcp-gateway/) is Docker's open-source solution for orchestrating MCP servers, and shares the same core concept as MSG: bundling multiple stdio MCP servers behind a single gateway endpoint.

However, there is a fundamental architectural difference:

| Aspect | Docker MCP Gateway | MSG |
|---|---|---|
| **Process isolation** | Docker container per server | Child process (npx/node) per request |
| **Credential injection** | `--secrets` file at startup (fixed) | `x-mcp-credentials` HTTP header per request (dynamic) |
| **Multi-tenant support** | **No** — credentials are fixed at startup | **Yes** — each request can carry different credentials |
| **Client connectivity** | Primarily stdio (remote HTTP is optional) | HTTP-first; works with any MCP client over the network |
| **Cloud hosting** | Docker environment required | Deployable to Lambda, AgentCore Runtime, Fargate, etc. |
| **Server registry** | Docker MCP Catalog (Docker Hub) + custom YAML | `servers.yaml` only (lightweight, no Docker dependency) |

**The key differentiator of MSG is Dynamic Authentication.**

Docker MCP Gateway injects credentials once at startup, meaning a single running gateway instance is bound to a single set of credentials. This works well for individual developer setups but does not support multi-tenant scenarios where different users authenticate with different tokens.

MSG reads credentials from the `x-mcp-credentials` HTTP header on every request and injects them as environment variables when spawning the child process. This means a single MSG instance can serve multiple tenants simultaneously, each with their own credentials — without any shared state between requests.

This design makes MSG particularly suited for cloud deployments where multiple users or agents need to access the same set of MCP servers with their own authentication context.

## License

MIT
