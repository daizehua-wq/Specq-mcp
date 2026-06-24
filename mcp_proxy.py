"""
mcp_proxy.py — SpecQ MCP Proxy for WorkBuddy
将远程 SpecQ MCP Server (HTTP SSE) 代理为本地 stdio MCP

WorkBuddy 只支持 command+args 本地启动模式，无法直接连远程 HTTP MCP。
这个 proxy 在本地以 stdio 运行，把请求转发到远程 SpecQ MCP Server。

使用方式 (WorkBuddy mcp.json):
{
  "mcpServers": {
    "specq": {
      "command": "python",
      "args": ["mcp_proxy.py"],
      "env": {
        "SPECQ_MCP_URL": "http://119.91.223.127:8001/mcp",
        "SPECQ_MCP_API_KEY": "your-api-key"
      }
    }
  }
}
"""

import os
import sys
import json
import asyncio
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationCapabilities
from mcp.server.stdio import stdio_server


SPECQ_MCP_URL = os.getenv("SPECQ_MCP_URL", "http://119.91.223.127:8001/mcp")
SPECQ_API_KEY = os.getenv("SPECQ_MCP_API_KEY", "")


async def run():
    """启动 stdio → HTTP SSE proxy"""
    server = Server("specq-proxy")

    # 从远程 SpecQ MCP 获取 tool 列表
    async with httpx.AsyncClient(timeout=30.0) as http:
        headers = {"Accept": "text/event-stream"}
        if SPECQ_API_KEY:
            headers["X-API-Key"] = SPECQ_API_KEY

        # 先获取 session
        try:
            init_resp = await http.post(
                f"{SPECQ_MCP_URL.rstrip('/')}",
                json={
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "specq-proxy", "version": "1.0.0"},
                    },
                },
                headers=headers,
            )
        except Exception as e:
            print(f"❌ 无法连接 SpecQ MCP Server: {e}", file=sys.stderr)
            print(f"   URL: {SPECQ_MCP_URL}", file=sys.stderr)
            sys.exit(1)

    # TODO: 完整的 SSE 会话管理
    # 当前 MVP 版本：直接透传 tool 调用到远程 HTTP endpoint

    @server.list_tools()
    async def list_tools():
        """从远程 SpecQ 获取 tool 列表"""
        async with httpx.AsyncClient(timeout=30.0) as http:
            headers = {"Content-Type": "application/json"}
            if SPECQ_API_KEY:
                headers["X-API-Key"] = SPECQ_API_KEY

            resp = await http.post(
                f"{SPECQ_MCP_URL.rstrip('/')}",
                json={
                    "jsonrpc": "2.0",
                    "id": "list_tools",
                    "method": "tools/list",
                },
                headers=headers,
            )
            data = resp.json()
            return data.get("result", {}).get("tools", [])

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        """转发 tool 调用到远程 SpecQ MCP"""
        async with httpx.AsyncClient(timeout=120.0) as http:
            headers = {"Content-Type": "application/json"}
            if SPECQ_API_KEY:
                headers["X-API-Key"] = SPECQ_API_KEY

            resp = await http.post(
                f"{SPECQ_MCP_URL.rstrip('/')}",
                json={
                    "jsonrpc": "2.0",
                    "id": "call_tool",
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments,
                    },
                },
                headers=headers,
            )
            data = resp.json()
            result = data.get("result", {})
            content = result.get("content", [])
            if content:
                return [type("TextContent", (), {
                    "type": "text",
                    "text": content[0].get("text", json.dumps(result, ensure_ascii=False)),
                    "annotations": None,
                })()]
            return [type("TextContent", (), {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, indent=2),
                "annotations": None,
            })()]

    capabilities = InitializationCapabilities(
        sampling=None,
        experimental=None,
    )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            capabilities,
            NotificationOptions(),
        )


if __name__ == "__main__":
    asyncio.run(run())
