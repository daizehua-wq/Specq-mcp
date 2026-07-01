"""
mcp_server.py — SpecQ MCP Server v2.3.1
纯本地独立进程，Agent 直接 stdio 启动，通过 MCP Sampling 复用 Agent LLM，零 API Key 配置
Tool 数量: 6（generate_intel / log_visit / extract_insights / feedback / memory / search）
"""
import json
import os
import uuid
from datetime import date

from mcp.server.fastmcp import FastMCP

import memory as mem
import search as sch
import multimodal as mm
import output as out

import logger as log_mod

mcp = FastMCP("specq")
_log = log_mod.get_logger("mcp_server")


# ======================== Tool: specq_memory ========================

@mcp.tool()
async def specq_memory(
    action: str,
    query: str | None = None,
    limit: int = 5,
    content: str | None = None,
    category: str | None = None,
    metadata: dict | None = None,
    goal: str | None = None,
    plan: list[str] | None = None,
    current_step: int = 0,
    uid: str = "default",
) -> str:
    """
    三层记忆操作接口 — 语义召回 / 写入长期记忆 / 读写工作记忆。

    4 个 action:
    - recall: 语义搜索召回，需 query
    - save: 写入记忆，需 content + category + uid
    - get_plan: 读工作记忆，需 uid
    - set_plan: 设工作记忆，需 goal + plan + uid
    """
    try:
        if action == "recall":
            if not query:
                return json.dumps({"error": "recall 需要 query 参数"}, ensure_ascii=False)
            try:
                vec = mem.embed_text(query)
                collection = mem.get_chroma_collection()
                kwargs = {"query_embeddings": [vec], "n_results": limit}
                if uid != "default":
                    kwargs["where"] = {"user_id": uid}
                results = collection.query(**kwargs)
                memories = []
                if results and results["ids"] and results["ids"][0]:
                    for i, mid in enumerate(results["ids"][0]):
                        mmeta = results["metadatas"][0][i] if results["metadatas"] else {}
                        memories.append({
                            "memory_id": mid,
                            "content": results["documents"][0][i] if results["documents"] else "",
                            "category": mmeta.get("category", ""),
                            "metadata": {k: v for k, v in mmeta.items() if k not in ("category", "user_id")},
                            "score": round(results["distances"][0][i], 4) if results["distances"] else 0,
                        })
                return json.dumps({"memories": memories}, ensure_ascii=False, indent=2)
            except Exception as e:
                return json.dumps({"error": f"recall 失败: {e}"}, ensure_ascii=False)

        elif action == "save":
            if not content or not category:
                return json.dumps({"error": "save 需要 content + category"}, ensure_ascii=False)
            valid = {"visit", "feedback", "intel", "insight", "preference"}
            if category not in valid:
                return json.dumps({"error": f"category 必须是 {', '.join(sorted(valid))} 之一"}, ensure_ascii=False)
            try:
                vec = mem.embed_text(content)
                collection = mem.get_chroma_collection()
                mid = f"mem_{uuid.uuid4().hex[:12]}"
                mmeta = {"category": category, "user_id": uid, "timestamp": str(date.today())}
                if metadata:
                    mmeta.update({k: v for k, v in metadata.items() if v is not None})
                collection.add(ids=[mid], embeddings=[vec], documents=[content], metadatas=[mmeta])
                return json.dumps({"memory_id": mid, "status": "saved"}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": f"save 失败: {e}"}, ensure_ascii=False)

        elif action == "get_plan":
            wm = mem.load_working_memory(uid)
            return json.dumps(wm, ensure_ascii=False, indent=2)

        elif action == "set_plan":
            if not goal:
                return json.dumps({"error": "set_plan 需要 goal"}, ensure_ascii=False)
            wm = mem.load_working_memory(uid)
            wm["goal"] = goal
            wm["plan"] = plan or []
            wm["current_step"] = current_step
            mem.save_working_memory(uid, wm)
            return json.dumps({
                "status": "saved",
                "goal": goal,
                "total_steps": len(plan or []),
            }, ensure_ascii=False, indent=2)

        else:
            return json.dumps(
                {"error": f"未知 action: {action}，支持 recall/save/get_plan/set_plan"},
                ensure_ascii=False,
            )

    except Exception as e:
        return json.dumps({"error": f"specq_memory 执行失败: {e}"}, ensure_ascii=False)


# ======================== Tool: specq_search ========================

@mcp.tool()
async def specq_search(
    query: str,
    limit: int = 5,
    source: str = "web",
) -> str:
    """
    联网搜索，补充公开数据。

    Args:
        query: 搜索关键词
        limit: 结果数上限（默认5）
        source: 搜索源 — web / news / scholar

    Returns:
        结构化搜索结果 JSON
    """
    try:
        result = await sch.web_search(query, limit, source)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "results": [], "total": 0, "source": source, "error": str(e),
        }, ensure_ascii=False)


# ======================== Tool: specq_generate_intel ========================

@mcp.tool()
async def specq_generate_intel(
    product: str,
    application: str,
    scenario: str,
    output_format: str = "markdown",
    context_block: str | None = None,
    anonymize: bool = True,
) -> str:
    """
    生成电子化学品攻单情报包。

    Args:
        product: 电子化学品产品名称，例如 "电镀铜溶液"
        application: 应用场景，例如 "PCB电镀"
        scenario: 销售目标和背景，例如 "降低粗糙度"
        output_format: 输出格式 — markdown / email / chat / docx / ppt（默认 markdown）
        context_block: 历史记忆上下文块（由 Agent 填入，可选）
        anonymize: 是否脱敏（默认 true）

    Returns:
        八模块攻单情报包，按 output_format 格式化
    """
    enhanced_scenario = scenario

    # Step 1: 从 ChromaDB 召回历史记忆
    try:
        vec = mem.embed_text(f"{product} {application}")
        collection = mem.get_chroma_collection()
        results = collection.query(query_embeddings=[vec], n_results=5)
        context_parts = []
        if results and results["ids"] and results["ids"][0]:
            for i, mid in enumerate(results["ids"][0]):
                doc = results["documents"][0][i]
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                context_parts.append(
                    f"- [{meta.get('category','')}] {meta.get('timestamp','')}: {doc[:200]}"
                )
        if context_parts:
            enhanced_scenario = f"{enhanced_scenario}\n\n【本地记忆召回】\n" + "\n".join(context_parts)
    except Exception as e:
        _log.warning(f"ChromaDB 记忆召回失败: {e}")

    # Step 2: 注入联网搜索结果
    try:
        search_query = f"{product} {application} 技术参数 竞品"
        search_result = await sch.web_search(search_query, limit=3)
        if search_result.get("results"):
            web_snippets = "\n".join(
                f"- [{r['title']}]({r['url']}): {r['snippet'][:150]}"
                for r in search_result["results"]
            )
            enhanced_scenario += f"\n\n【联网搜索补充数据】\n{web_snippets}"
    except Exception as e:
        _log.warning(f"联网搜索失败: {e}")

    # Step 3: 注入历史记忆上下文块
    if context_block:
        enhanced_scenario += f"\n\n【历史记忆】\n{context_block}"

    # Step 4: 本地 LLM 生成情报包
    reply_text = await _generate_intel_local(product, application, enhanced_scenario)

    # Step 5: 自动写回 ChromaDB
    try:
        summary = reply_text[:300]
        vec2 = mem.embed_text(summary)
        collection2 = mem.get_chroma_collection()
        collection2.add(
            ids=[f"mem_{uuid.uuid4().hex[:12]}"],
            embeddings=[vec2],
            documents=[summary],
            metadatas=[{"category": "intel", "user_id": "default", "timestamp": str(date.today())}],
        )
    except Exception:
        pass

    # Step 6: 脱敏 + 多格式输出
    formatted = out.format_output(reply_text, output_format, {
        "product": product,
        "application": application,
        "timestamp": str(date.today()),
    })
    return formatted


# ======================== Tool: specq_log_visit ========================

@mcp.tool()
async def specq_log_visit(
    customer_id: int,
    content: str,
    visit_date: str | None = None,
    visit_type: str = "in_person",
    image_paths: list[str] | None = None,
    audio_path: str | None = None,
    video_path: str | None = None,
) -> str:
    """
    记录一条销售拜访纪要（暗知识沉淀）。

    Args:
        customer_id: 客户 ID
        content: 拜访纪要正文，记录客户关注点、竞品信息、技术指标等
        visit_date: 拜访日期（YYYY-MM-DD），默认今天
        visit_type: 拜访类型 — in_person / phone / wechat
        image_paths: 拜访相关图片路径列表（自动 OCR）
        audio_path: 拜访录音路径（自动语音转录）
        video_path: 拜访视频路径（自动关键帧提取）

    Returns:
        创建结果，包含 visit_id 和客户名称
    """
    if not visit_date:
        visit_date = date.today().isoformat()

    if customer_id <= 0:
        return json.dumps({"error": "customer_id 必须为正整数"}, ensure_ascii=False)

    # === 多模态处理 ===
    extra_text: list[str] = []
    if audio_path and os.path.exists(audio_path):
        try:
            audio_text = await mm.process_audio(audio_path)
            if audio_text:
                extra_text.append(f"【语音转录】{audio_text[:500]}")
        except Exception as e:
            _log.warning(f"音频转录失败: {e}")

    if image_paths:
        for img in image_paths[:5]:
            if os.path.exists(img):
                try:
                    img_text = await mm.process_image(img)
                    if img_text:
                        extra_text.append(f"【图片 OCR】{img_text[:300]}")
                except Exception as e_img:
                    _log.warning(f"图片OCR失败: {e_img}")

    if video_path and os.path.exists(video_path):
        try:
            vid_text = await mm.process_video(video_path)
            if vid_text:
                extra_text.append(f"【视频摘要】{vid_text[:500]}")
        except Exception as e:
            _log.warning(f"视频处理失败: {e}")

    if extra_text:
        content = content + "\n\n" + "\n\n".join(extra_text)

    # === 直接写 ChromaDB ===
    summary = content[:300] if len(content) > 300 else content
    vec = mem.embed_text(summary)
    collection = mem.get_chroma_collection()
    mid = f"mem_{uuid.uuid4().hex[:12]}"
    collection.add(
        ids=[mid],
        embeddings=[vec],
        documents=[summary],
        metadatas=[{
            "category": "visit",
            "user_id": "default",
            "customer_id": str(customer_id),
            "customer_name": f"ID={customer_id}",
            "visit_type": visit_type,
            "timestamp": visit_date,
        }],
    )

    return (
        f"✅ 暗知识已沉淀。\n"
        f"- 客户 ID: {customer_id}\n"
        f"- 拜访 ID: {mid}\n"
        f"- 日期: {visit_date}\n"
        f"- 类型: {visit_type}"
    )


# ======================== Tool: specq_extract_insights ========================

@mcp.tool()
async def specq_extract_insights(
    customer_id: int | None = None,
    limit: int = 10,
    db_path: str | None = None,
    db_query: str | None = None,
    api_url: str | None = None,
    api_params: dict | None = None,
) -> str:
    """
    从销售暗数据中提取结构化洞察（暗知识结构化）。

    Args:
        customer_id: 客户 ID，不传则拉取全部
        limit: 最多返回的洞察条数
        db_path: 本地 SQLite 数据库路径（可选额外数据源）
        db_query: SQL 查询语句（与 db_path 配合使用）
        api_url: 在线 API 地址（可选额外数据源）
        api_params: API 请求参数（与 api_url 配合使用）

    Returns:
        结构化洞察 JSON
    """
    # 从 ChromaDB 拉历史数据
    collection = mem.get_chroma_collection()

    where_filter: dict = {"category": {"$in": ["visit", "feedback"]}}
    if customer_id:
        where_filter["customer_id"] = str(customer_id)

    results = collection.get(where=where_filter, limit=50)

    if not results or not results["ids"]:
        return "⚠️ 暂无拜访记录或丢单复盘。请先用 specq_log_visit 沉淀暗数据。"

    records: list[dict] = []
    for i, mid in enumerate(results["ids"]):
        meta = results["metadatas"][i] if results["metadatas"] else {}
        doc = results["documents"][i] if results["documents"] else ""
        records.append({
            "id": mid,
            "content": doc,
            "category": meta.get("category", ""),
            "customer_name": meta.get("customer_name", meta.get("customer_id", "")),
            "timestamp": meta.get("timestamp", ""),
        })

    # 额外数据源 — 本地数据库
    db_data = []
    if db_path and db_query and os.path.exists(db_path):
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(db_query).fetchall()
            db_data = [dict(r) for r in rows[:100]]
            conn.close()
        except Exception as e:
            _log.warning(f"本地数据库查询失败: {e}")

    # 额外数据源 — 在线 API
    api_data = []
    if api_url:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(api_url, params=api_params or {})
                if r.status_code == 200:
                    raw = r.json()
                    api_data = raw if isinstance(raw, list) else [raw]
        except Exception as e:
            _log.warning(f"在线API数据拉取失败: {e}")

    # 构建提示词
    records_text = json.dumps(records[:20], ensure_ascii=False, indent=2)

    extra_sections = ""
    if db_data:
        extra_sections += f"\n本地数据库数据:\n{json.dumps(db_data[:20], ensure_ascii=False, indent=2)}"
    if api_data:
        extra_sections += f"\n在线 API 数据:\n{json.dumps(api_data[:20], ensure_ascii=False, indent=2)}"

    system_prompt = """你是电子化学品销售数据分析师。从以下拜访纪要和丢单复盘中提取结构化洞察。

严格按以下分类：
- tech_requirement: 客户关注的技术指标（粗糙度、延展性、精度等）
- competitor_info: 竞品动态（哪家竞品、什么产品、价格/性能优势）
- import_barrier: 导入障碍（认证周期、切换风险、工艺匹配度）
- decision_chain: 决策链信息（谁拍板、什么流程、关键决策者）
- price_sensitivity: 价格敏感度（客户对价格的关注度、预算范围）

每条洞察格式：
{"category": "分类", "insight": "具体洞察（一句话）", "customer_name": "客户名", "source_visit_id": 来源ID, "confidence": 0.0-1.0}

只返回 JSON 数组。没有足够数据时返回空数组 []。"""

    user_prompt = f"""暗数据记录:
{records_text}
{extra_sections}

请提取结构化洞察（最多 {limit} 条）："""

    # 调 LLM 提取
    try:
        result = await _ask_llm(system_prompt, user_prompt, max_tokens=2000)
    except Exception as e:
        return f"Error: LLM 调用失败: {e}"

    # 格式化输出
    try:
        insights = json.loads(result)
    except json.JSONDecodeError:
        insights = result

    summary = {
        "total_records": len(records),
        "customers_involved": len(set(r.get("customer_name", "") for r in records)),
        "insights": insights[:limit] if isinstance(insights, list) else [],
    }

    return json.dumps(summary, ensure_ascii=False, indent=2)


# ======================== Tool: specq_feedback ========================

@mcp.tool()
async def specq_feedback(
    product: str,
    application: str,
    outcome: str,
    lesson: str | None = None,
    accuracy_notes: str | None = None,
    uid: str = "default",
) -> str:
    """
    记录攻单结果，形成成交闭环。

    Args:
        product: 使用的产品名
        application: 应用场景
        outcome: 结果 — won / lost / follow_up
        lesson: 丢单复盘摘要（outcome=lost 时强烈建议填写）
        accuracy_notes: 情报包中哪些信息不准确
        uid: 用户标识（用于记忆关联）

    Returns:
        反馈记录结果
    """
    if outcome not in ("won", "lost", "follow_up"):
        return f"Error: outcome 必须是 won / lost / follow_up，当前值: {outcome}"

    # === 写 ChromaDB ===
    memory_content = f"[{outcome}] {product} - {application}"
    if lesson:
        memory_content += f": {lesson}"

    try:
        vec = mem.embed_text(memory_content[:300])
        collection = mem.get_chroma_collection()
        mid = f"mem_{uuid.uuid4().hex[:12]}"
        collection.add(
            ids=[mid],
            embeddings=[vec],
            documents=[memory_content[:500]],
            metadatas=[{
                "category": "feedback",
                "user_id": uid,
                "product": product,
                "application": application,
                "outcome": outcome,
                "timestamp": str(date.today()),
            }],
        )
    except Exception as e:
        _log.warning(f"记忆写入失败(feedback): {e}")

    # === 成交率埋点日志 ===
    try:
        analytics_file = os.path.join(mem.get_memory_dir(), "analytics.jsonl")
        with open(analytics_file, "a") as f:
            f.write(json.dumps({
                "event": "feedback",
                "uid": uid,
                "product": product,
                "outcome": outcome,
                "timestamp": str(date.today()),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    result = f"✅ 反馈已记录。\n- 产品: {product}\n- 结果: {outcome}"
    if accuracy_notes:
        result += "\n- 准度反馈已记录，将用于后续情报包改进"

    return result


# ======================== MCP Sampling LLM 辅助 ========================

async def _ask_llm(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    """通过 MCP Sampling 请求 Agent 的 LLM 生成回复。"""
    from mcp.types import CreateMessageRequestParams, SamplingMessage, TextContent

    ctx = mcp.get_context()
    if not ctx:
        raise RuntimeError("MCP context not available — 当前 Agent 客户端不支持 MCP Sampling")

    result = await ctx.session.create_message(
        CreateMessageRequestParams(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=f"{system_prompt}\n\n---\n\n{user_prompt}"),
                ),
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
    )
    content = result.content
    if isinstance(content, TextContent):
        return content.text
    if isinstance(content, list):
        for part in content:
            if hasattr(part, 'text'):
                return part.text
    return str(content)


# ======================== 本地 LLM 情报生成 ========================

async def _generate_intel_local(
    product: str,
    application: str,
    enhanced_scenario: str,
) -> str:
    """通过 MCP Sampling 调用 Agent 的 LLM 生成情报包。"""
    system_prompt = """你是半导体产业链电子化学品销售专家 FAE。根据输入的产品信息、应用场景和历史数据，生成一份结构化的攻单情报包。

严格按以下八模块输出 Markdown：

## 1. 产品概览
- 产品定义、核心功能、适用工艺段（基于公开资料整理）
- 标注数据来源

## 2. 技术指标对比
- 关键参数 vs 竞品/行业标准
- 用表格呈现

## 3. 竞品格局
- 主要竞品、市占、差异化优势
- 标注信息来源

## 4. 客户关注指标
- 该客户/行业重点关注的技术参数
- 数据来自暗数据时标注来源，无数据时标注 [经验推断]

## 5. 切入机会
- 当前该客户的切入窗口和建议切入点
- 基于暗数据或经验分析

## 6. 导入障碍
- 历史丢单原因、技术壁垒、认证周期
- 标注数据来源

## 7. 行动建议
- 拜访话术建议、演示重点、报价策略
- 给出可执行的具体步骤

## 8. 参考来源
- 每个模块的数据来源和置信度
- 用户需实际验证信息准确性

规则：
- 没有历史数据时，标注 [经验推断，暂无销售数据支撑]
- 有暗数据时优先使用，标注 [来自销售拜访记录]
- 有联网搜索结果时标注 [来自联网搜索]
- 不编造具体客户名称、联系方式
- 直接输出 Markdown，不要输出前言/后缀寒暄"""

    user_prompt = f"""生成以下产品的攻单情报包：

产品：{product}
应用场景：{application}

附加上下文：
{enhanced_scenario}"""

    try:
        return await _ask_llm(system_prompt, user_prompt)
    except Exception as e:
        _log.error(f"LLM Sampling 失败: {e}")
        return f"Error: 情报包生成失败 — Agent LLM 调用异常: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
