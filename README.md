# SpecQ MCP Server v2.0

电子化学品销售攻单情报包 — MCP Server + 跨平台 Skill

## 是什么

SpecQ 把电子化学品销售的攻单流程封装为 MCP（Model Context Protocol）标准工具，任何支持 MCP 的 AI Agent 都能接入使用。

**新功能（v2.0）**：
- 🧠 **三层记忆系统**：跨会话语义搜索召回 + 多任务工作记忆
- 🌐 **联网搜索**：实时补充竞品动态和行业信息
- 📸 **多模态输入**：图片 OCR + 语音转录 + 视频关键帧
- 📄 **多格式输出**：Markdown / Word / PPT / 邮件 / 聊天消息
- 🔒 **脱敏保护**：客户名自动替换为行业标签
- 📊 **用量追踪**：调用统计 + 成交率漏斗

**一句话**：输入产品名 + 应用场景 + 销售目标，输出一份结构化的八模块攻单情报包。

## 快速开始

### 1. 前置依赖

需要一个运行中的 SpecQ FastAPI 后端服务（提供 `/api/intel/*` 和 `/api/customers/*` 接口）。

### 2. 安装

```bash
git clone https://github.com/daizehua-wq/Specq-mcp.git
cd Specq-mcp
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env，填入你的配置
```

`.env` 示例：

```ini
SPECQ_MCP_API_KEY=***
SPECQ_MCP_BASE_URL=http://localhost:8000
SPECQ_DATA_DIR=/home/ubuntu/specq_data
LLM_API_KEY=***
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
EMBEDDING_API_KEY=***
EMBEDDING_API_URL=https://open.bigmodel.cn/api/paas/v4/embeddings
EMBEDDING_MODEL=embedding-2
SEARCH_API_KEY=***  # 可选
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
        "X-API-Key": "***"
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
        "X-API-Key": "***"
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
        "SPECQ_MCP_API_KEY": "***",
        "SPECQ_MCP_BASE_URL": "http://localhost:8000",
        "LLM_API_KEY": "***",
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-chat",
        "EMBEDDING_API_KEY": "***",
        "EMBEDDING_API_URL": "https://open.bigmodel.cn/api/paas/v4/embeddings",
        "EMBEDDING_MODEL": "embedding-2"
      }
    }
  }
}
```

---

## 六个 Tool

| Tool | 功能 | 输入 | 输出 |
|---|---|---|---|
| `specq_memory` | 三层记忆（recall/save/get_plan/set_plan） | action, query/content... | 记忆操作结果 |
| `specq_search` | 联网搜索 | query, limit, source | 结构化搜索结果 |
| `specq_generate_intel` | 生成攻单情报包 | product, application, scenario, context_block, output_format | 八模块 Markdown/Word/PPT/邮件/聊天 |
| `specq_log_visit` | 多模态拜访纪要 | customer_id, content, image_paths, audio_path, video_path | 拜访记录 ID |
| `specq_extract_insights` | 暗数据洞察 | customer_id, db_path, db_query, api_url | 结构化洞察 JSON |
| `specq_feedback` | 成交闭环反馈 | product, application, outcome, lesson | 反馈记录 |

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

## 输出格式

| 格式 | 说明 |
|---|---|
| `markdown` | 标准八模块 Markdown（默认） |
| `docx` | Word 文档导出 |
| `ppt` | PPT 结构化提纲 |
| `email` | 邮件正文 + 主题 |
| `chat` | 300 字精简消息，适配飞书/微信 |

## 数据库

本项目**不含数据库**。用户需要自行准备以下数据以启用完整功能：

- 客户档案（`/api/customers/*`）
- 客户拜访记录（用于暗数据注入和 extract_insights）
- `knowledge.db`（公司档案 + 工艺化学品映射表）

---

## 架构

```
specq-mcp/
├── mcp_server.py          # 主入口（6 tool）
├── memory.py              # 记忆模块（ChromaDB + 通用 embedding）
├── search.py              # 联网搜索模块
├── multimodal.py          # 多模态输入（OCR/语音/视频）
├── output.py              # 多格式输出（docx/ppt/email/chat）
├── SKILL.md               # 跨平台 Skill 工作流
├── requirements.txt
├── .env.example
└── LICENSE
```

## 许可证

Apache License 2.0
