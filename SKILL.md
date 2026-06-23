# SpecQ v2.0 — 电子化学品攻单情报包 MCP Agent

> MCP Server 端点: `http://localhost:8001`（独立于 FastAPI:8000）
> 六大能力: 情报生成 / 暗数据沉淀 / 洞察提取 / 成交闭环 / 三层记忆 / 联网搜索
> 新增: 多模态输入（图片/语音/视频）+ 多格式输出（Word/PPT/Email/Chat）

---

## MCP Tool 清单

| Tool | 功能 | 关键参数 |
|---|---|---|
| `specq_generate_intel` | 生成攻单情报包 | product, application, scenario, output_format, context_block, anonymize |
| `specq_log_visit` | 记录销售拜访 | customer_id, content, visit_date, image_paths, audio_path, video_path |
| `specq_extract_insights` | 提取结构化洞察 | customer_id, limit, db_path, db_query, api_url, api_params |
| `specq_feedback` | 记录攻单反馈 | product, application, outcome, lesson, uid |
| `specq_memory` | 三层记忆操作（4 action） | action, query/content/goal/plan, uid |
| `specq_search` | 联网搜索（3 source） | query, limit, source |

`specq_memory` 的 4 种 action:
- `recall` — 语义搜索召回长期记忆
- `save` — 写入一条新记忆
- `get_plan` — 读取当前工作记忆（任务进度）
- `set_plan` — 设定/更新工作记忆

`specq_search` 的 3 种 source:
- `web` — 通用网页搜索
- `news` — 新闻搜索
- `scholar` — 学术搜索

---

## 触发条件

Agent 根据用户输入自动判断场景:

| 触发关键词/模式 | 对应场景 | 调用的 Tool |
|---|---|---|
| "生成...情报包" / "帮我查...竞品" | 场景 A: 生成情报包 | generate_intel |
| "拜访了..." / "客户说..." | 场景 B: 暗知识沉淀 | log_visit（自动 memory save）|
| "看看...洞察" / "分析..." | 场景 C: 暗知识提取 | extract_insights |
| "成交了" / "丢了" / "结果..." | 场景 D: 成交闭环 | feedback（自动 memory save）|
| "帮我做 N 个..." / 多任务 | 场景 E: 多任务管理 | memory(set_plan/get_plan) |
| 上传图片/语音/视频文件 | 场景 F: 多模态输入 | log_visit（自动 OCR/ASR） |
| "搜索..." / "网上查..." | 联网搜索 | search |

---

## 工作流

用户输入消息后，按以下顺序执行：

### 前置处理（v2.0）

1. **多模态处理** — 如输入包含图片/语音/视频文件路径
   - `specq_log_visit` 内部自动调用 OCR / 语音转录 / 视频关键帧提取
   - 提取的文本自动附加到 content 字段

2. **工作记忆检查** — `specq_memory(action="get_plan", uid="{user_id}")`
   - 如果 goal 不为 None 且 current_step < len(plan) → 用户有未完成任务
   - 提示用户: 「检测到未完成任务 [goal]，当前在第 [current_step+1]/[len(plan)] 步，是否继续？」
   - 如果 goal 为 None → 正常处理新请求

3. **长期记忆召回** — `specq_memory(action="recall", query="{客户名+产品名+场景关键词}", uid="{user_id}")`
   - 语义搜索该客户/产品/场景的相关历史记忆
   - 召回结果作为 context_block 传入 specq_generate_intel

4. **联网搜索补充** — `specq_search(query="{产品名+应用场景+技术参数}", limit=3)`
   - 搜索公开技术参数、竞品信息、行业趋势
   - 结果自动注入 generate_intel 的 scenario（内部处理，Agent 无需手动）

### 后置：常规情报生成流程

5. **提取三字段** — 从用户输入中提取 product / application / scenario
6. **调用情报生成** — `specq_generate_intel(product, application, scenario, output_format, context_block)`
7. **即时沉淀** — 情报包生成后，如有新发现/客户反馈/竞品信息，自动调用 memory save

---

## 分支场景

### 场景 A: 生成情报包
用户提供产品+应用+场景 → 走完整工作流（记忆召回 → 联网搜索 → 暗数据注入 → generate_intel）

### 场景 B: 暗知识沉淀（v2.0 增强）
```
用户: "昨天去深南电路，拍了他们的产线和白板笔记"
→ specq_log_visit(customer_id=1, content="面访深南...", image_paths=["产线.jpg", "白板.jpg"])
→ MCP Server 内部: OCR 提取图片文字 → 合并到 content → 存 CRM → 自动写 ChromaDB
```

### 场景 C: 暗知识提取（v2.0 增强）
```
用户: "提取深南电路洞察，顺便查一下本地数据库里的参数表"
→ specq_extract_insights(customer_id=1, db_path="/data/params.db", db_query="SELECT * FROM chip_params WHERE customer='深南'")
→ LLM 综合 CRM 拜访记录 + 本地 DB 数据 + 在线 API → 输出结构化洞察
```

### 场景 D: 成交闭环（v2.0 增强）
```
用户: "深南电路的单子丢了，因为他们选了安美特"
→ specq_feedback(product="电镀铜", application="PCB电镀", outcome="lost", lesson="安美特报价低15%", uid="user_1")
→ MCP Server 内部: 存反馈记录 → 自动写 ChromaDB → 写 analytics.jsonl 埋点
```

### 场景 E: 多任务管理
```
用户: "我要生成三个情报包：A客户电镀铜、B客户光刻胶、C客户清洗液"
→ specq_memory(action="set_plan", goal="生成三个情报包", plan=["电镀铜","光刻胶","清洗液"], current_step=0, uid="user_1")
```

**恢复进度:**
```
用户: 下次打开对话（新会话）
→ specq_memory(action="get_plan", uid="user_1")
→ 检测到未完成任务，提示用户是否继续
```

### 场景 F: 多模态输入（v2.0 新增）
```
用户: "这是我昨天和深南电路开会的录音，帮我沉淀"
→ specq_log_visit(customer_id=1, content="深南电路会议", audio_path="meeting.mp3")
→ MCP Server 内部: whisper 转录 → 合并到 content → 存 CRM → 写 ChromaDB
```

---

## Memory 分类体系

| category | 触发时机 | 示例内容 | 保留策略 |
|---|---|---|---|
| `visit` | `specq_log_visit` 调用后 | "拜访深南电路，客户反馈电镀铜粗糙度不达标" | 永久 |
| `feedback` | `specq_feedback` 调用后 | "[lost] 电镀铜 - PCB电镀: 安美特报价低15%" | 永久 |
| `intel` | `specq_generate_intel` 返回后 | "为深南电路生成的电镀铜八模块情报包摘要" | 90天 |
| `insight` | `specq_extract_insights` 调用后 | "深南电路: 决策链中工程总监权重最高" | 永久 |
| `preference` | 用户显式指定偏好 | "用户偏好简中输出，技术指标用SI单位" | 永久 |

---

## 脱敏规则（v2.0）

`specq_generate_intel` 默认开启 `anonymize=True`:
- 真实公司名 → `[某PCB厂商]` 类标签
- 具体人名 → `[工程总监]` 类角色
- 精确产品参数 → `[XX nm 级]` 区间化
- 价差信息 → `[约 X%~Y%]` 区间化

**MVP 阶段**: 通过 Prompt 约束脱敏，不写正则硬替换。完整脱敏依赖 CRM 客户名→脱敏标签映射表。

---

## 多格式输出路由（v2.0）

| output_format | 返回格式 | 长度限制 | 典型场景 |
|---|---|---|---|
| `markdown` | 八模块 Markdown 原文 | 不限 | 内部分析 |
| `email` | Subject + Body 邮件格式 | 2000 字 | 邮件发送 |
| `chat` | 精简摘要 | 300 字 | 微信/Slack |
| `docx` | Word 模板说明 + 原文 | 1500 字 | 正式报告 |
| `ppt` | PPT 大纲（标题提取） | 20 页 | 汇报演示 |

---

## 场景判断规则

Agent 接收到用户输入后，按以下优先级判断：

1. **多任务触发**: 包含 "N个" / "多个" / "列表" + 任务描述 → 场景 E
2. **多模态输入**: 输入含文件路径（图片/音频/视频） → 场景 F
3. **反馈闭环**: 包含 "成交" / "丢了" / "结果" → 场景 D
4. **暗知识提取**: 包含 "洞察" / "分析" / "趋势" → 场景 C
5. **暗知识沉淀**: 包含 "拜访" / "客户说" / "去了" → 场景 B
6. **情报生成**: 包含产品名 + 场景 + 需求 → 场景 A

---

## 输出规格

### 情报包输出结构（v2.0）

```markdown
# 攻单情报包: {产品名} @ {应用场景}

## 【联网搜索】
> 以下为实时搜索的技术参数和竞品动态

| 来源 | 摘要 |
|---|---|
| [Brave News] 安美特发布新型电镀铜... | 粒径控制突破... |

## 【历史记忆】
> 以下来自该客户/产品/场景的历史记忆（ChromaDB 语义召回）

| 记忆ID | 类型 | 内容摘要 | 相关度 |
|---|---|---|---|
| mem_xxx | visit | 深南电路电镀铜粗糙度... | 0.92 |

## 【销售暗数据参考】
> 以下来自真实拜访记录，优先使用

- [深南电路] 2026-06-15: 电镀铜粗糙度不达标，竞品安美特报价低于我方15%...

## 一、客户需求背景
...

## 二、技术方案对比
...
```

### 记忆召回输出格式

```json
{
  "memories": [
    {
      "memory_id": "mem_abc123",
      "content": "拜访深南电路，客户反馈电镀铜粗糙度不达标",
      "category": "visit",
      "metadata": {
        "customer": "深南电路",
        "product": "电镀铜溶液",
        "outcome": "lost",
        "timestamp": "2026-06-15"
      },
      "score": 0.92
    }
  ]
}
```

---

## 重要规则

1. **记忆优先** — 每次生成情报包前，必须先 recall 该客户/产品/场景的历史记忆，不能从零开始
2. **脱敏强制** — 所有对外输出的情报包默认脱敏（anonymize=True），内部使用可传 False
3. **多模态透明** — 图片/语音/视频处理结果自动附加到内容中，Agent 无需手动处理文件
4. **暗数据注入** — `specq_generate_intel` 内部自动注入 CRM 暗数据 + 联网搜索结果，Agent 无需手动拼接
5. **降级不中断** — 记忆召回/联网搜索/多模态处理失败不应阻断情报生成主流程
6. **工作记忆不丢** — 当用户有未完成任务时，必须提示恢复；完成任务后更新 current_step。跨会话不丢进度
7. **暗数据闭环** — feedback 返回后自动写入 ChromaDB + analytics.jsonl，Agent 无需额外操作
8. **搜索增强** — 情报包生成时自动联网搜索补充技术参数和竞品信息，Agent 无需手动调 search Tool

---

## 配置依赖

| 环境变量 | 用途 | 必填 |
|---|---|---|
| `SPECQ_MCP_API_KEY` | MCP Server 认证 | 生产环境必填 |
| `SPECQ_MCP_BASE_URL` | FastAPI 后端地址 | 默认 8000 |
| `ZHIPU_API_KEY` | 智谱 Embedding API | 必填（记忆系统） |
| `SEARCH_API_KEY` | Brave Search API Key | 联网搜索需配置 |
| `LLM_API_KEY` | LLM API Key | 必填（洞察提取） |
| `LLM_BASE_URL` | LLM API 地址 | 默认 deepseek |
| `LLM_MODEL` | LLM 模型名 | 默认 deepseek-chat |
| `SPECQ_DATA_DIR` | 数据存储目录 | 必填 |

---

## 降级策略

| 模块 | 异常处理 |
|---|---|
| memory | embedding 失败 → 返回空结果，不抛异常 |
| search | API 不可用 → 返回空列表，不阻塞主流程 |
| multimodal | 图片/音频/视频处理失败 → 跳过，用原始 content |
| output | 不支持格式 → fallback 到 markdown |
| ChromaDB | 连接失败 → 内存模式 fallback |

---

*SpecQ v2.0 — 记忆·搜索·多模态·多格式，让暗数据真正活起来*
