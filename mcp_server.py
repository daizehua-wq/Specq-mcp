"""
mcp_server.py — SpecQ MCP Server v2.0
把 /api/intel/generate 包装成 MCP tools，6 个 tool 覆盖情报生成全链路
认证: SPECQ_MCP_API_KEY（从 .env 读取）
运行: python mcp_server.py  (在 8001 端口，独立于 FastAPI)
Tool 数量: 6（generate_intel / log_visit / extract_insights / feedback / memory / search）
新增依赖: chromadb, requests, python-docx（三层记忆 + 联网搜索 + 多模态 + 多格式输出）
"""
import json
import os
import uuid
from datetime import date

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

import memory as mem
import search as sch
import multimodal as mm
import output as out

load_dotenv()

mcp = FastMCP("specq", host="0.0.0.0", port=8001)


# ======================== 配置辅助函数 ========================

def _get_api_key() -> str:
    return os.getenv("SPECQ_MCP_API_KEY", "")


def _get_base_url() -> str:
    return os.getenv("SPECQ_MCP_BASE_URL", "http://localhost:8000")


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
    import httpx
    api_key = _get_api_key()
    base_url = _get_base_url()

    async with httpx.AsyncClient() as client:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        # === 构建增强 scenario ===
        enhanced_scenario = scenario

        # 注入联网搜索结果
        try:
            search_query = f"{product} {application} 技术参数 竞品"
            search_result = await sch.web_search(search_query, limit=3)
            if search_result.get("results"):
                web_snippets = "\n".join(
                    f"- [{r['title']}]({r['url']}): {r['snippet'][:150]}"
                    for r in search_result["results"]
                )
                enhanced_scenario += f"\n\n【联网搜索补充数据】\n{web_snippets}"
        except Exception:
            pass

        # 注入历史记忆上下文块
        if context_block:
            enhanced_scenario += f"\n\n【历史记忆】\n{context_block}"

        # === Phase C: 暗数据注入 ===
        try:
            r_customers = await client.get(
                f"{base_url}/api/customers",
                headers=headers,
            )
            if r_customers.status_code == 200:
                customers_data = r_customers.json()
                customers = customers_data if isinstance(customers_data, list) else customers_data.get("items", [])
                dark_insights = []
                for c in customers[:3]:
                    cid = c.get("id") or c.get("customer_id")
                    if not cid:
                        continue
                    rv = await client.get(
                        f"{base_url}/api/customers/{cid}",
                        headers=headers,
                    )
                    if rv.status_code == 200:
                        detail = rv.json()
                        visits = detail.get("recent_visits", [])
                        for v in visits[:3]:
                            dark_insights.append({
                                "customer": c.get("name", f"ID={cid}"),
                                "industry": c.get("industry", "未知"),
                                "content": v.get("summary", v.get("content", "")),
                                "date": v.get("visit_date", ""),
                            })
                if dark_insights:
                    insights_text = "\n".join(
                        f"- [{d['customer']}] {d['date']}: {d['content'][:200]}"
                        for d in dark_insights[:5]
                    )
                    enhanced_scenario = (
                        f"{enhanced_scenario}\n\n"
                        f"【销售暗数据参考——来自真实拜访记录，优先使用】\n"
                        f"{insights_text}"
                    )
        except Exception:
            pass

        # === 调用情报生成 API ===
        resp = await client.post(
            f"{base_url}/api/intel/generate",
            json={
                "product": product,
                "application": application,
                "scenario": enhanced_scenario,
            },
            headers=headers,
            timeout=120.0,
        )
        if resp.status_code != 200:
            return f"Error: SpecQ 服务返回 {resp.status_code}: {resp.text[:500]}"

        data = resp.json()
        reply_text = data.get("reply", "（情报包生成失败）")

        # === 脱敏后处理 ===
        if anonymize and reply_text:
            # MVP 阶段：Prompt 层约束脱敏，不做正则硬替换
            pass

        # === 多格式输出 ===
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
        customer_id: 客户 ID（必须先通过 CRM 创建客户档案）
        content: 拜访纪要正文，记录客户关注点、竞品信息、技术指标等
        visit_date: 拜访日期（YYYY-MM-DD），默认今天
        visit_type: 拜访类型 — in_person / phone / wechat
        image_paths: 拜访相关图片路径列表（自动 OCR）
        audio_path: 拜访录音路径（自动语音转录）
        video_path: 拜访视频路径（自动关键帧提取）
        api_key: API Key（可选，默认从环境变量读取）

    Returns:
        创建结果，包含 visit_id 和客户名称
    """
    import httpx

    expected_key = _get_api_key()

    if not visit_date:
        visit_date = date.today().isoformat()

    # === 多模态处理 ===
    extra_text: list[str] = []
    if audio_path and os.path.exists(audio_path):
        try:
            audio_text = await mm.process_audio(audio_path)
            if audio_text:
                extra_text.append(f"【语音转录】{audio_text[:500]}")
        except Exception:
            pass

    if image_paths:
        for img in image_paths[:5]:
            if os.path.exists(img):
                try:
                    img_text = await mm.process_image(img)
                    if img_text:
                        extra_text.append(f"【图片 OCR】{img_text[:300]}")
                except Exception:
                    pass

    if video_path and os.path.exists(video_path):
        try:
            vid_text = await mm.process_video(video_path)
            if vid_text:
                extra_text.append(f"【视频摘要】{vid_text[:500]}")
        except Exception:
            pass

    if extra_text:
        content = content + "\n\n" + "\n\n".join(extra_text)

    # === 调用 CRM API 存储拜访记录 ===
    base_url = _get_base_url()
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": expected_key or "internal",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{base_url}/api/customers/{customer_id}",
            headers=headers,
        )
        if r.status_code != 200:
            return f"Error: 客户 ID={customer_id} 不存在"
        customer_name = r.json().get("name", f"ID={customer_id}")

        r2 = await client.post(
            f"{base_url}/api/customers/{customer_id}/visits",
            headers=headers,
            json={
                "summary": content,
                "visit_date": visit_date,
                "visit_type": visit_type,
            },
        )
        if r2.status_code != 201:
            return f"Error: 创建拜访纪要失败 ({r2.status_code}): {r2.text}"

        visit = r2.json()

    # === 自动写入长期记忆 ===
    try:
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
                "timestamp": visit_date,
            }],
        )
    except Exception:
        pass

    return (
        f"✅ 暗知识已沉淀。\n"
        f"- 客户: {customer_name}\n"
        f"- 拜访 ID: {visit.get('id', '?')}\n"
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
        customer_id: 客户 ID，不传则拉取全部客户
        limit: 最多返回的洞察条数
        db_path: 本地 SQLite 数据库路径（可选额外数据源）
        db_query: SQL 查询语句（与 db_path 配合使用）
        api_url: 在线 API 地址（可选额外数据源）
        api_params: API 请求参数（与 api_url 配合使用）
        api_key: API Key（可选，默认从环境变量读取）

    Returns:
        结构化洞察 JSON
    """
    import httpx

    expected_key = _get_api_key()

    base_url = _get_base_url()
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": expected_key or "internal",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. 拉客户列表（或指定客户）
        if customer_id:
            r = await client.get(
                f"{base_url}/api/customers/{customer_id}",
                headers=headers,
            )
            if r.status_code != 200:
                return f"Error: 客户 ID={customer_id} 不存在"
            customers = [r.json()]
        else:
            r = await client.get(
                f"{base_url}/api/customers",
                headers=headers,
            )
            if r.status_code != 200:
                return f"Error: 获取客户列表失败 ({r.status_code})"
            data = r.json()
            customers = data.get("items", [])

        if not customers:
            return "⚠️ 暂无客户数据。请先用 specq_log_visit 沉淀暗数据。"

        # 2. 拉每个客户的详细数据
        all_visits = []
        all_losses = []
        for c in customers[:5]:
            cid = c.get("id")
            if not cid:
                continue
            cname = c.get("name", f"ID={cid}")
            try:
                rd = await client.get(
                    f"{base_url}/api/customers/{cid}",
                    headers=headers,
                )
                if rd.status_code == 200:
                    detail = rd.json()
                    visits = detail.get("recent_visits", [])
                    for v in visits:
                        v["_customer_name"] = cname
                    all_visits.extend(visits)
                    losses = detail.get("recent_loss_reviews", [])
                    for lo in losses:
                        lo["_customer_name"] = cname
                    all_losses.extend(losses)
            except Exception:
                pass

        if not all_visits and not all_losses:
            return "⚠️ 暂无拜访记录或丢单复盘。"

    # 3. 额外数据源 — 本地数据库
    db_data = []
    if db_path and db_query and os.path.exists(db_path):
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(db_query).fetchall()
            db_data = [dict(r) for r in rows[:100]]
            conn.close()
        except Exception:
            pass

    # 4. 额外数据源 — 在线 API
    api_data = []
    if api_url:
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(api_url, params=api_params or {})
                if r.status_code == 200:
                    raw = r.json()
                    api_data = raw if isinstance(raw, list) else [raw]
        except Exception:
            pass

    # 5. 构建提示词
    visits_text = json.dumps(all_visits[:20], ensure_ascii=False, indent=2)
    losses_text = json.dumps(all_losses[:10], ensure_ascii=False, indent=2)

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
{"category": "分类", "insight": "具体洞察（一句话）", "customer_name": "客户名", "source_visit_id": 来源拜访ID, "confidence": 0.0-1.0}

只返回 JSON 数组。没有足够数据时返回空数组 []。"""

    user_prompt = f"""拜访记录:
{visits_text}

丢单复盘:
{losses_text}
{extra_sections}

请提取结构化洞察（最多 {limit} 条）："""

    # 6. 调 LLM 提取
    try:
        import openai
        llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
        llm_base = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        llm_model = os.getenv("LLM_MODEL", "deepseek-chat")
        if not llm_api_key:
            return "Error: LLM_API_KEY 未配置"

        client_llm = openai.AsyncOpenAI(api_key=llm_api_key, base_url=llm_base)
        resp = await client_llm.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=4000,
        )
        result = resp.choices[0].message.content or "[]"
    except Exception as e:
        return f"Error: LLM 调用失败: {e}"

    # 7. 格式化输出
    try:
        insights = json.loads(result)
    except json.JSONDecodeError:
        insights = result

    summary = {
        "total_visits": len(all_visits),
        "total_loss_reviews": len(all_losses),
        "customers_analyzed": len(set(v.get("_customer_name") for v in all_visits)),
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
        api_key: API Key（可选，默认从环境变量读取）

    Returns:
        反馈记录结果
    """
    import httpx

    expected_key = _get_api_key()

    if outcome not in ("won", "lost", "follow_up"):
        return f"Error: outcome 必须是 won / lost / follow_up，当前值: {outcome}"

    base_url = _get_base_url()
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": expected_key or "internal",
    }

    # === 调用反馈 API ===
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{base_url}/api/intel/feedback",
            json={
                "product": product,
                "application": application,
                "outcome": outcome,
                "lesson": lesson or "",
                "accuracy_notes": accuracy_notes or "",
            },
            headers=headers,
        )

        if resp.status_code != 200:
            return f"Error: 反馈记录失败 ({resp.status_code}): {resp.text}"

        data = resp.json()
        msg = data.get("message", "反馈已记录")
        lid = data.get("loss_review_id")
        result = f"✅ {msg}"
        if lid:
            result += f"\n- 丢单复盘 ID: {lid}"
        if accuracy_notes:
            result += "\n- 准度反馈已记录，将用于后续情报包改进"

    # === 自动写入长期记忆 ===
    if outcome and lesson:
        try:
            memory_content = f"[{outcome}] {product} - {application}: {lesson}"
            vec = mem.embed_text(memory_content)
            collection = mem.get_chroma_collection()
            mid = f"mem_{uuid.uuid4().hex[:12]}"
            collection.add(
                ids=[mid],
                embeddings=[vec],
                documents=[memory_content],
                metadatas=[{
                    "category": "feedback",
                    "user_id": uid,
                    "product": product,
                    "outcome": outcome,
                    "timestamp": str(date.today()),
                }],
            )
        except Exception:
            pass

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

    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
