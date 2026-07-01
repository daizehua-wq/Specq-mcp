---
name: specq-intel-sales
slug: specq-intel-sales
displayName: SpecQ 攻单情报包
description: "SpecQ — 半导体产业链销售攻单情报包。输入客户+产品，AI 自动整理暗知识（拜访记录/丢单复盘/竞品情报），生成八模块攻单策略，提高成交率。阶段一聚焦电子化学品。"
version: "2.2.0"
author: daizehua-wq
license: Apache-2.0
tags: [sales, semiconductor, intel, crm, dark-knowledge]
---

# SpecQ Skill v2.2 — 半导体产业链销售攻单情报包

> 整理暗知识（拜访记录 + 丢单复盘 + 竞品情报）→ 客户画像 + 使用场景 + 竞品动态 + 成交策略 → 提高成交率 | 阶段一聚焦电子化学品

## ⚠️ 首次安装必配

**LLM_API_KEY 是强制依赖，不配 Skill 无法工作。**

SpecQ 的核心能力（情报生成、暗数据合成、行动建议）依赖大模型。安装后**第一步**就是配置 API Key：

```bash
# 在 SpecQ 项目根目录创建 .env 文件
echo "LLM_API_KEY=你的DeepSeek_API_Key" > .env
```

> **为什么需要单独配置？**
> 
> SpecQ MCP Server 为纯本地进程，不共用 Agent 的 LLM。配一个 Key 即可，不需要部署数据库或 Web 服务。
> 
> **去哪拿 Key？** → [DeepSeek API Keys](https://platform.deepseek.com/api_keys)（新用户送 500 万 tokens）
> 
> **不想花钱？** 本地部署 Ollama + Qwen 也能跑，改 `.env` 里 `LLM_BASE_URL` 指向本地。

---

## 📦 安装指引

本 Skill 的 MCP Server 为纯本地进程，Agent 安装后自动以 stdio 模式启动，无需部署服务器。

### 前置依赖

1. Python 3.10+
2. `pip install -r requirements.txt`
3. 在项目目录创建 `.env`，至少配置 `LLM_API_KEY`

### .env 最小配置

```bash
LLM_API_KEY=sk-***
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# 可选：Embedding（用于语义记忆搜索）
EMBEDDING_API_KEY=sk-***
EMBEDDING_API_URL=https://api.deepseek.com/v1/embeddings
EMBEDDING_MODEL=deepseek-embed
```

### Agent 配置

Agent 通过 stdio 启动 MCP Server：

```json
{
  "mcpServers": {
    "specq": {
      "command": "python",
      "args": ["mcp_server.py"],
      "env": {
        "LLM_API_KEY": "<your-api-key>",
        "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-chat"
      }
    }
  }
}
```

---

## 适用场景

电子化学品销售 / 售前工程师见客户前，快速获得结构化攻单情报包。

## 触发条件

用户提供以下**任一组信息**即可触发：

| 触发模式 | 示例 |
|---|---|
| 三字段 | "帮我做XX电镀液的情报包，客户深南电路，他们关注粗糙度" |
| 查历史 | "深南电路之前聊了什么？" |
| 反馈 | "深南成交了" / "丢了，他们嫌价格贵" |
| 多任务 | "帮我做三个情报包：深南+电镀铜、景旺+蚀刻液、鹏鼎+沉铜" |

## 依赖 MCP Server（5 个 Tool）

| Tool | 输入 | 输出 | 说明 |
|---|---|---|---|
| `specq_memory` | action, query/content/category... | 记忆操作结果 | 三层记忆 |
| `specq_generate_intel` | product, application, scenario | 八模块情报包 Markdown | 核心生成 |
| `specq_extract_insights` | customer_id（可选）, limit | 结构化洞察 JSON | 暗数据提取 |
| `specq_log_visit` | customer_id, content, visit_date, visit_type | 拜访记录 ID | 沉淀拜访 |
| `specq_feedback` | product, application, outcome, lesson, accuracy_notes | 反馈记录 | 成交闭环 |

---

## v2.2 工作流（纯本地，含三层记忆）

```
用户输入
  ↓
① 工作记忆检查（specq_memory.get_plan）
  ├─ 有未完成任务 → 提示："上次 XX 还没完成，继续吗？"
  └─ 新任务 → 继续
  ↓
② 长期记忆召回（specq_memory.recall）
  → 语义搜索该客户/产品的历史拜访、丢单记录、偏好
  ↓
③ 提取三字段（product / application / scenario）
  → 如果三字段不全 → 追问
  ↓
④ 暗数据注入（ChromaDB 记忆召回 + 联网搜索）
  ├─ 有暗数据 → 注入到情报包
  └─ 无暗数据 → 标记 [经验推断]
  ↓
⑤ 生成情报包（specq_generate_intel → 本地 LLM 直连）
  ↓
⑥ 自动写回 ChromaDB（category=intel）
  ↓
⑦ 输出八模块情报包

【历史记忆】（独立上下文块）
- 2026-06-20 拜访：关注粗糙度，竞品安美特
- 2026-05-15 丢单：嫌价格高 20%

【本次情报包】（八模块）
...（带数据来源标注）...

  ↓
⑧ 更新工作记忆（specq_memory.set_plan）
  → 标记当前任务完成
  ↓
⑨ ⚠️ 必提醒："见完客户后告诉我结果，我帮你记录"
```

---

## 分支场景

### 场景 A：新客户（无历史数据）
- 长期记忆召回为空 → 直接调 generate_intel
- 模块 4/5/6 标注 `[经验推断，暂无销售数据支撑]`

### 场景 B：老客户（有记忆数据）
- 先 recall → 召回历史拜访 + 丢单记录
- 注入到独立上下文块【历史记忆】
- 情报包模块 4/5/6 有真实数据来源标注

### 场景 C：仅查历史
- recall → 结构化展示历史记忆
- 展示后追问："要基于这些信息生成情报包吗？"

### 场景 D：成交反馈
- feedback → 记录闭环
- 同时 save(category="feedback") 写入长期记忆
- outcome: won（成交）/ lost（丢单）/ follow_up（跟进中）

### 场景 E：多任务
- get_plan 检查进度 → 知道做到哪了
- set_plan 设定/更新任务列表
- 中断后恢复：用户说"继续" → get_plan → 知道从哪开始

---

## Memory 分类体系

| category | 触发时机 | 示例内容 | 保留策略 |
|---|---|---|---|
| `visit` | log_visit 后自动写 | "拜访XX客户，关注YY指标" | 永久 |
| `feedback` | feedback 后自动写 | "XX产品丢单，原因：价格高20%" | 永久 |
| `intel` | generate_intel 后自动写 | "为XX客户生成YY情报包" | 180 天 |
| `insight` | extract_insights 结构化发现 | "深南电路对粗糙度敏感度：高" | 180 天 |
| `preference` | 用户显式偏好 | "David 偏好先看竞品对比" | 永久 |

---

## 输出规格

### 情报包（八模块）

| 模块 | 内容 | 数据来源 |
|---|---|---|
| 1. 产品概览 | 产品定义、核心功能、适用工艺段 | 公开资料 + 联网搜索 |
| 2. 技术指标对比 | 关键参数 vs 竞品/行业标准 | 公开资料 + 暗数据 |
| 3. 竞品格局 | 主要竞品、市占、差异化 | 公开资料 |
| 4. 客户关注指标 | 该客户/行业重点技术指标 | 暗数据 / [经验推断] |
| 5. 切入机会 | 当前该客户的切入窗口 | 暗数据 / [经验推断] |
| 6. 导入障碍 | 历史丢单原因、技术壁垒 | 暗数据 / [经验推断] |
| 7. 行动建议 | 拜访话术、演示重点、报价策略 | LLM 综合生成 |
| 8. 参考来源 | 各模块数据来源 + 置信度 | 自动标注 |

### 历史记忆（独立上下文块）

每次情报包生成时，在输出**最前面**附加历史记忆块：

```
【历史记忆】
- 2026-06-20 拜访深南电路：关注粗糙度（Ra<0.3μm），竞品安美特
- 2026-05-15 丢单：嫌价格高 20%，建议下次报价让步
```

---

## 重要规则

1. **记忆优先**：每次对话开始必调 recall，有记忆绝不跳过
2. **来源透明**：每模块标注数据来源，暗数据标注来源，推测标注 `[经验推断]`
3. **反馈必提醒**：每次输出情报包后必提醒反馈
4. **参数不足追问**：三字段提取不全时追问，不猜测
5. **保密**：情报包不含客户真实名称，脱敏为行业标签
6. **工作记忆不丢**：多任务时记录进度，用户说"继续"能恢复

---

## MVP 边界

**做**：
- 场景 A/B/C/D/E 全部覆盖
- 三层记忆自动读写
- 纯 Markdown 输出

**不做**：
- 多轮对话深挖需求（单轮优先）
- 自动推送情报包到飞书/邮件
- 竞品实时价格
- 记忆合并/去重

---

## 常见问题

**Q: 我的客户数据安全吗？**

情报包输出中客户真实名称会被脱敏为行业标签。暗数据存储在本地 ChromaDB 和 JSON 文件中，不上传任何第三方服务器。整个 Skill 在内网环境运行。

**Q: 需要部署服务器吗？**

不需要。v2.2 起 SpecQ MCP Server 为纯本地进程，Agent 通过 stdio 直接启动，零外部依赖。

**Q: 怎么开始用？**

直接说"帮我做XX产品的情报包，客户XX，关注XX"，Skill 会自动引导补全缺失的参数。不需要先读文档。

**Q: 支持哪些输出格式？**

Markdown（默认，完整八模块）、邮件（摘要+主题）、聊天（300字精简）。Word 和 PPT 格式正在开发中。

**Q: 新客户没有历史数据怎么办？**

Skill 会自动跳过记忆召回，标注 `[经验推断]` 生成情报包。见完客户后用 `feedback` 记录结果，下次就有数据了。
