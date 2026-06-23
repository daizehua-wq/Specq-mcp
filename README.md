# SpecQ MCP Server v1.0

电子化学品销售攻单情报包 — MCP Server + 跨平台 Skill

## 是什么

SpecQ 把电子化学品销售的攻单流程封装为 MCP（Model Context Protocol）标准工具，任何支持 MCP 的 AI Agent 都能接入使用。

**一句话**：输入产品名 + 应用场景 + 销售目标，输出一份结构化的八模块攻单情报包。

## 快速开始

### 1. 前置依赖

需要一个运行中的 SpecQ FastAPI 后端服务（提供 `/api/intel/*` 和 `/api/customers/*` 接口）。

### 2. 安装

```bash
git clone https://github.com/your-org/specq-mcp.git
cd specq-mcp
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的配置
```

`.env` 示例：

```ini
SPECQ_MCP_API_KEY=your-api-key-here
SPECQ_MCP_BASE_URL=http://localhost:8000
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

### 4. 启动

```bash
python mcp_server.py
# 服务运行在 http://0.0.0.0:8001/mcp
```

---

## 接入你的 AI Agent

### OpenClaw

```json
"mcp": {
  "servers": {
    "specq": {
      "url": "http://your-server:8001/mcp",
      "transport": "streamable-http",
      "headers": {
        "X-API-Key": "your-api-key-here"
      }
    }
  }
}
```

### Cursor

在 `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "specq": {
      "url": "http://your-server:8001/mcp",
      "transport": "streamable-http",
      "headers": {
        "X-API-Key": "your-api-key-here"
      }
    }
  }
}
```

### Claude Code

在 `claude_mcp.json`：

```json
{
  "mcpServers": {
    "specq": {
      "command": "python",
      "args": ["/path/to/specq-mcp/mcp_server.py"],
      "env": {
        "SPECQ_MCP_API_KEY": "your-api-key-here",
        "SPECQ_MCP_BASE_URL": "http://localhost:8000",
        "LLM_API_KEY": "your-llm-api-key",
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-chat"
      }
    }
  }
}
```

### 通用 MCP 客户端

任何兼容 MCP Streamable HTTP 协议的客户端，配置：

- **URL**: `http://your-server:8001/mcp`
- **Header**: `X-API-Key: your-api-key-here`

---

## 四个 Tool

| Tool | 功能 | 输入 | 输出 |
|---|---|---|---|
| `specq_generate_intel` | 生成攻单情报包 | product, application, scenario | 八模块 Markdown |
| `specq_log_visit` | 沉淀拜访纪要 | customer_id, content, visit_date, visit_type | 拜访记录 ID |
| `specq_extract_insights` | 提取暗数据洞察 | customer_id（可选）, limit | 结构化洞察 JSON |
| `specq_feedback` | 记录成交/丢单反馈 | product, application, outcome, lesson | 反馈结果 |

---

## 情报包八个模块

1. **产品概览** — 产品定义、核心功能、适用工艺段
2. **技术指标对比** — 关键参数 vs 竞品/行业标准
3. **竞品格局** — 主要竞品、差异化
4. **客户关注指标** — 该客户/行业重点技术指标
5. **切入机会** — 当前切入窗口
6. **导入障碍** — 历史丢单原因、技术壁垒
7. **行动建议** — 拜访话术、演示重点、报价策略
8. **参考来源** — 各模块数据来源 + 置信度

---

## 数据库

本项目**不含数据库**。用户需要自行准备以下数据以启用完整功能：

- 客户档案（`/api/customers/*`）
- 客户拜访记录（用于暗数据注入和 extract_insights）
- `knowledge.db`（公司档案 + 工艺化学品映射表）

---

## 许可证

Apache License 2.0
