"""
mcp_server.py — SpecQ MCP Server v1.0
电子化学品销售攻单情报包的 MCP 协议封装

4 个 tool：
  - specq_generate_intel: 生成八模块攻单情报包
  - specq_log_visit: 沉淀拜访纪要（暗数据）
  - specq_extract_insights: 从暗数据中提取结构化洞察
  - specq_feedback: 记录成交/丢单反馈，形成闭环

依赖：
  - FastAPI 后端（提供 /api/intel/* 和 /api/customers/* 接口）
  - .env 中配置 SPECQ_MCP_API_KEY 和 SPECQ_MCP_BASE_URL

运行：
  pip install fastmcp httpx openai python-dotenv
  cp .env.example .env  # 编辑配置
  python mcp_server.py  # 默认 8001 端口

许可证：Apache License 2.0
"""
import os
from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("specq", host="0.0.0.0", port=8001)


@mcp.tool()
async def specq_generate_intel(
    product: str,
    application: str,
    scenario: str,
) -> str:
    """
    生成电子化学品攻单情报包。

    Args:
        product: 电子化学品产品名称，例如 "电镀铜溶液"
        application: 应用场景，例如 "PCB电镀"
        scenario: 销售目标和背景，例如 "深南电路，降低粗糙度"

    Returns:
        八模块攻单情报包 Markdown
    """
    api_key = os.getenv("SPECQ_MCP_API_KEY", "")
    base_url = os.getenv("SPECQ_MCP_BASE_URL", "http://localhost:8000")

    import httpx
    async with httpx.AsyncClient() as client:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key

        # === 暗数据注入（Phase C）===
        # 从 CRM 拉取客户历史拜访记录，注入到情报包生成 prompt 中
        enhanced_scenario = scenario
        try:
            r_customers = await client.get(
                f"{base_url}/api/customers",
                headers=headers,
            )
            if r_customers.status_code == 200:
                customers_data = r_customers.json()
                customers = (
                    customers_data
                    if isinstance(customers_data, list)
                    else customers_data.get("items", [])
                )
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
                        f"{scenario}\n\n"
                        f"【销售暗数据参考——来自真实拜访记录，优先使用】\n"
                        f"{insights_text}"
                    )
        except Exception:
            pass

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
            return f"Error: 后端服务返回 {resp.status_code}: {resp.text[:500]}"
        data = resp.json()
        return data.get("reply", "（情报包生成失败）")


@mcp.tool()
async def specq_log_visit(
    customer_id: int,
    content: str,
    visit_date: str | None = None,
    visit_type: str = "in_person",
    api_key: str | None = None,
) -> str:
    """
    记录一条销售拜访纪要（暗知识沉淀）。

    Args:
        customer_id: 客户 ID（必须先通过 CRM 创建客户档案）
        content: 拜访纪要正文，记录客户关注点、竞品信息、技术指标等
        visit_date: 拜访日期（YYYY-MM-DD），默认今天
        visit_type: 拜访类型 — in_person（面访）/ phone（电话）/ wechat（微信）
        api_key: API Key（可选，默认从环境变量读取）

    Returns:
        创建结果，包含 visit_id 和客户名称
    """
    import httpx
    from datetime import date

    expected_key = os.getenv("SPECQ_MCP_API_KEY", "")
    if expected_key and (api_key or "") != expected_key:
        return "Error: API Key 无效"

    if not visit_date:
        visit_date = date.today().isoformat()

    base_url = os.getenv("SPECQ_MCP_BASE_URL", "http://localhost:8000")
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
        return (
            f"✅ 暗知识已沉淀。\n"
            f"- 客户: {customer_name}\n"
            f"- 拜访 ID: {visit.get('id', '?')}\n"
            f"- 日期: {visit_date}\n"
            f"- 类型: {visit_type}"
        )


@mcp.tool()
async def specq_extract_insights(
    customer_id: int | None = None,
    limit: int = 10,
    api_key: str | None = None,
) -> str:
    """
    从销售暗数据中提取结构化洞察（暗知识结构化）。

    读取 CRM 中的拜访纪要和丢单复盘，由 LLM 提取：
    - tech_requirement: 客户关注的技术指标
    - competitor_info: 竞品动态
    - import_barrier: 导入障碍
    - decision_chain: 决策链信息
    - price_sensitivity: 价格敏感度

    Args:
        customer_id: 客户 ID，不传则拉取全部客户
        limit: 最多返回的洞察条数
        api_key: API Key（可选，默认从环境变量读取）

    Returns:
        结构化洞察 JSON，每条含 category、insight、source、confidence
    """
    import json
    import httpx

    expected_key = os.getenv("SPECQ_MCP_API_KEY", "")
    if expected_key and (api_key or "") != expected_key:
        return "Error: API Key 无效"

    base_url = os.getenv("SPECQ_MCP_BASE_URL", "http://localhost:8000")
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

        # 2. 拉每个客户的详细数据（含拜访纪要和丢单复盘）
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
            return "⚠️ 暂无拜访记录或丢单复盘。请先用 specq_log_visit 沉淀暗数据。"

        # 3. 构建提示词
        visits_text = json.dumps(all_visits[:20], ensure_ascii=False, indent=2)
        losses_text = json.dumps(all_losses[:10], ensure_ascii=False, indent=2)

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

请提取结构化洞察（最多 {limit} 条）："""

        # 4. 调 LLM 提取
        try:
            import openai
            llm_api_key = os.getenv("LLM_API_KEY", "")
            llm_base = os.getenv("LLM_BASE_URL", "")
            llm_model = os.getenv("LLM_MODEL", "")
            if not llm_api_key or not llm_model:
                return "Error: LLM_API_KEY 和 LLM_MODEL 未配置。请编辑 .env 文件。"
            if not llm_base:
                return "Error: LLM_BASE_URL 未配置。请编辑 .env 文件。"

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

    # 5. 格式化输出
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


@mcp.tool()
async def specq_feedback(
    product: str,
    application: str,
    outcome: str,
    lesson: str | None = None,
    accuracy_notes: str | None = None,
    api_key: str | None = None,
) -> str:
    """
    记录攻单结果，形成成交闭环。

    情报包使用后的反馈：成交了还是丢了？情报包哪些地方不准？

    Args:
        product: 使用的产品名（与 generate_intel 的一致）
        application: 应用场景
        outcome: 结果 — won（成交）/ lost（丢单）/ follow_up（继续跟进）
        lesson: 丢单复盘摘要（outcome=lost 时强烈建议填写）
        accuracy_notes: 情报包中哪些信息不准确
        api_key: API Key（可选，默认从环境变量读取）

    Returns:
        反馈记录结果
    """
    import httpx

    expected_key = os.getenv("SPECQ_MCP_API_KEY", "")
    if expected_key and (api_key or "") != expected_key:
        return "Error: API Key 无效"

    if outcome not in ("won", "lost", "follow_up"):
        return f"Error: outcome 必须是 won / lost / follow_up，当前值: {outcome}"

    base_url = os.getenv("SPECQ_MCP_BASE_URL", "http://localhost:8000")
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": expected_key or "internal",
    }

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

        if resp.status_code == 200:
            data = resp.json()
            msg = data.get("message", "反馈已记录")
            lid = data.get("loss_review_id")
            result = f"✅ {msg}"
            if lid:
                result += f"\n- 丢单复盘 ID: {lid}"
            if accuracy_notes:
                result += f"\n- 准度反馈已记录，将用于后续情报包改进"
            return result
        else:
            return f"Error: 反馈记录失败 ({resp.status_code}): {resp.text}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
