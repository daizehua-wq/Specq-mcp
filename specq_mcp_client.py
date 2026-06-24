"""
specq_mcp_client.py — SpecQ MCP Client for WorkBuddy (stdio ↔ remote HTTP SSE)
==============================================================================

WorkBuddy 只支持本地 command+args 模式启动 MCP Server。
这个脚本作为本地 stdio 代理，将 MCP 请求转发到远程 SpecQ MCP Server（HTTP SSE）。

用法：
  1. 将此文件下载到本地（clone 或直接下载）
  2. 安装 pip 依赖：pip install mcp httpx
  3. 在 WorkBuddy 中配置 ~/.workbuddy/mcp.json：

{
  "mcpServers": {
    "specq": {
      "command": "python",
      "args": ["specq_mcp_client.py"],
      "env": {
        "SPECQ_MCP_URL": "http://119.91.223.127:8001/mcp",
        "SPECQ_MCP_API_KEY": "your-api-key"
      }
    }
  }
}

不需要启动任何额外服务。WorkBuddy 会自动启动此脚本并建立连接。
"""

import asyncio
import json
import os
import sys
from typing import Any

import httpx

# ---- 配置 ----
SPECQ_MCP_URL = os.getenv("SPECQ_MCP_URL", "http://119.91.223.127:8001/mcp")
SPECQ_API_KEY = ***"SPECQ_MCP_API_KEY", "")


# ---- MCP 协议透传 ----
class SpecQMCPClient:
    """stdio → HTTP SSE MCP 透传客户端"""

    def __init__(self):
        self.session_id: str | None = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_jsonrpc(self, method: str, params: dict | None = None) -> dict:
        """发送 JSON-RPC 请求到远程 SpecQ MCP Server"""
        req_id = self._next_id()
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if SPECQ_API_KEY:
            ***"X-API-Key"] = SPECQ_API_KEY
        if self.session_id:
            ***"Mcp-Session-Id"] = self.session_id

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
            resp = await http.post(SPECQ_MCP_URL, json=payload, headers=headers)

            # 提取 Session ID
            mcp_session = resp.headers.get("Mcp-Session-Id")
            if mcp_session:
                self.session_id = mcp_session

            if resp.status_code != 200:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
                    },
                }

            content_type = resp.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                # SSE 响应：解析
                result = self._parse_sse(resp.text)
            else:
                result = resp.json()

        return result

    def _parse_sse(self, text: str) -> dict:
        """解析 SSE text/event-stream 响应"""
        for line in text.strip().split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                data = line[6:]
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    return {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": data}]}}
        return {"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": text}]}}

    async def initialize(self) -> dict:
        """MCP initialize 握手"""
        return await self._send_jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "specq-workbuddy", "version": "1.0.0"},
        })

    async def list_tools(self) -> list[dict]:
        """获取远程 tool 列表并转为 MCP Tool 格式"""
        result = await self._send_jsonrpc("tools/list")
        return result.get("result", {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> list[dict]:
        """调用远程 tool"""
        result = await self._send_jsonrpc("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        content = result.get("result", {}).get("content", [])
        if not content and "result" in result:
            # 有些服务端可能返回不同的结构
            r = result["result"]
            if isinstance(r, dict) and "content" in r:
                content = r["content"]
            elif isinstance(r, str):
                content = [{"type": "text", "text": r}]
            else:
                content = [{"type": "text", "text": json.dumps(r, ensure_ascii=False)}]
        return content


# ---- MCP stdio Server 包装 ----

async def run_stdio():
    """启动 stdio MCP Server，将请求透传到远程 SpecQ MCP"""
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationCapabilities
    from mcp.server.stdio import stdio_server

    client = SpecQMCPClient()

    try:
        init_result = await client.initialize()
    except Exception as e:
        print(f"❌ 无法连接 SpecQ MCP Server ({SPECQ_MCP_URL}): {e}", file=sys.stderr)
        sys.exit(1)

    server = Server("specq")

    @server.list_tools()
    async def handle_list_tools():
        try:
            return await client.list_tools()
        except Exception as e:
            print(f"list_tools 失败: {e}", file=sys.stderr)
            return []

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict):
        try:
            content = await client.call_tool(name, arguments)
            return content
        except Exception as e:
            print(f"call_tool '{name}' 失败: {e}", file=sys.stderr)
            return [{"type": "text", "text": f"Error: {e}"}]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationCapabilities(sampling=None, experimental=None),
            NotificationOptions(),
        )


if __name__ == "__main__":
    asyncio.run(run_stdio())
