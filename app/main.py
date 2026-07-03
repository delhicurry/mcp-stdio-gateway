import json
import os
import yaml
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException, Request
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

# Load server configurations
CONFIG_PATH = os.getenv("MSG_CONFIG_PATH", "servers.yaml")
with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)
    MCP_SERVER_REGISTRY = config.get("servers", {})

app = FastAPI(
    title="MCP Stdio Gateway (MSG)",
    description="Gateway to expose local stdio MCP servers as multi-tenant cloud resources.",
    version="0.1.0",
)

class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]

@asynccontextmanager
async def mcp_session(server_name: str, credentials: Dict[str, str]):
    """
    Context manager to dynamically start and stop a stdio MCP server process.
    """
    if server_name not in MCP_SERVER_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_name}")
    
    server_def = MCP_SERVER_REGISTRY[server_name]
    
    # Build environment variables dynamically
    env = {**os.environ}
    for key in server_def.get("env_keys", []):
        if key not in credentials:
            raise HTTPException(status_code=400, detail=f"Missing credential in header: {key}")
        env[key] = credentials[key]
    
    server_params = StdioServerParameters(
        command=server_def["command"],
        args=server_def.get("args", []),
        env=env,
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"MCP Server error: {str(e)}")

@app.get("/")
def read_root():
    return {"message": "MCP Stdio Gateway is running."}

@app.get("/mcp/{server_name}/tools")
async def list_tools(
    server_name: str,
    x_mcp_credentials: str = Header(..., description="JSON string containing required environment variables"),
):
    """
    List available tools for a specific MCP server.
    """
    try:
        credentials = json.loads(x_mcp_credentials)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="x_mcp_credentials must be a valid JSON string")
        
    async with mcp_session(server_name, credentials) as session:
        tools = await session.list_tools()
        # Convert objects to dict for JSON serialization
        return {"tools": [tool.model_dump() for tool in tools.tools]}

@app.post("/mcp/{server_name}/tools/call")
async def call_tool(
    server_name: str,
    request: ToolCallRequest,
    x_mcp_credentials: str = Header(..., description="JSON string containing required environment variables"),
):
    """
    Call a tool on a specific MCP server.
    """
    try:
        credentials = json.loads(x_mcp_credentials)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="x_mcp_credentials must be a valid JSON string")
        
    async with mcp_session(server_name, credentials) as session:
        result = await session.call_tool(request.tool_name, request.arguments)
        return {"result": result.model_dump()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
