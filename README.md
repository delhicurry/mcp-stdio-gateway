# MCP Stdio Gateway (MSG)

**Gateway architecture to transform local-only (stdio + env vars) MCP servers into multi-tenant cloud resources.**

## Overview

The Model Context Protocol (MCP) ecosystem currently has many official servers (like Kintone, GitHub, Slack) that only support the `stdio` transport. This design assumes a 1:1 process model on a developer's local machine, making it impossible to:
1. Access them directly from cloud agents (like ChatGPT, Claude, Manus) without a tunnel.
2. Support multi-tenancy and Dynamic Authentication (tokens are hardcoded in environment variables at startup).

**MCP Stdio Gateway (MSG)** solves this by acting as a process manager and gateway. It receives standard HTTP requests, dynamically starts a `stdio` child process for the target MCP server, injects authentication credentials from HTTP headers into the process environment, and returns the result.

This completely eliminates the need for OpenAI Secure MCP Tunnel, removes vendor lock-in, and allows you to host your existing unmodified `stdio` MCP servers on AWS AgentCore Runtime, Fargate, or any other cloud environment.

## Features

- **Dynamic Authentication**: Pass credentials via HTTP headers per request. The gateway injects them into the child process dynamically.
- **Multi-Tenant Ready**: Because processes are spawned per request with dynamic credentials, multiple users can safely use the same gateway.
- **Server Registry**: Manage multiple different MCP servers (Kintone, GitHub, etc.) through a single `servers.yaml` configuration.
- **Zero Modifications**: Works with existing `stdio` MCP servers without changing their code.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
# Ensure Node.js and npx are installed on your system
```

### 2. Configure Servers

Edit `servers.yaml` to define your available MCP servers and required environment variables:

```yaml
servers:
  kintone:
    command: "npx"
    args: ["-y", "@kintone/mcp-server"]
    env_keys:
      - "KINTONE_BASE_URL"
      - "KINTONE_API_TOKEN"
```

### 3. Run the Gateway

```bash
uvicorn app.main:app --reload
```

### 4. Test the Endpoint

List tools for the Kintone server by passing credentials in the `x-mcp-credentials` header as a JSON string:

```bash
curl -X GET "http://127.0.0.1:8000/mcp/kintone/tools" \
  -H "x-mcp-credentials: {\"KINTONE_BASE_URL\": \"https://example.cybozu.com\", \"KINTONE_API_TOKEN\": \"your_token_here\"}"
```

Call a tool:

```bash
curl -X POST "http://127.0.0.1:8000/mcp/kintone/tools/call" \
  -H "Content-Type: application/json" \
  -H "x-mcp-credentials: {\"KINTONE_BASE_URL\": \"https://example.cybozu.com\", \"KINTONE_API_TOKEN\": \"your_token_here\"}" \
  -d '{
    "tool_name": "kintone_get_record",
    "arguments": {
      "app": "1",
      "id": "100"
    }
  }'
```

## Deployment to AWS AgentCore Runtime

This application is stateless and designed to run in containerized environments like AWS AgentCore Runtime.

1. Build the Docker image:
   ```bash
   docker build -t mcp-stdio-gateway .
   ```
2. Deploy the container as an AgentCore Runtime Harness.
3. Configure your agent to call the gateway endpoints, using AgentCore Identity (Outbound Auth) to fetch tokens from AWS Secrets Manager and pass them in the `x-mcp-credentials` header.

## Architecture

```
[Cloud Agent (Manus, Claude, etc.)]
       |
       | HTTP POST (with x-mcp-credentials header)
       v
[FastAPI Gateway]
       |
       | 1. Read servers.yaml
       | 2. Extract credentials from header
       | 3. Spawn child process (e.g., npx @kintone/mcp-server)
       | 4. Inject credentials as environment variables
       | 5. Communicate via stdio
       v
[stdio MCP Server Process]
       |
       | API Call
       v
[External SaaS (Kintone, etc.)]
```

## License
MIT
