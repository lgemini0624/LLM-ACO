"""
智能控制器：参考 Claude Agent SDK 的 Tool Use 规范，提供「根据地名选簇」「运行算法」两个工具，
并根据用户意图自动调参（如学生画像调高 w_cost、越秀区选簇），并在费用超 400 元时闭环修正（调大 w_cost 重算）。

支持两种模式：
- 正则解析模式（默认）：用 _parse_intent 解析意图，本地执行工具。
- Claude Tool Use 模式（--claude）：由 Claude 决定何时调用哪个工具，需设置 ANTHROPIC_API_KEY。

用法:
  python src/smart_controller.py
  python src/smart_controller.py --query "我是学生，想去越秀区看红色遗址"
  python src/smart_controller.py --claude --query "家庭游客想去番禺区，预算控制在400以内"
"""
import os
import sys
import re
import json
import subprocess
import glob
from typing import Any, Dict, List, Optional, Tuple

# 保证可导入同目录与项目根
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ---------- Tool Use 规范：工具定义（JSON Schema 风格） ----------

TOOLS = [
    {
        "name": "select_cluster_by_place_name",
        "description": "根据地名（区县/行政区，如越秀区、番禺区）查询对应的 cluster_id 列表，用于后续只在该区域建矩阵并运行路线算法。",
        "input_schema": {
            "type": "object",
            "properties": {
                "place_name": {
                    "type": "string",
                    "description": "地名，如：越秀区、番禺区、天河区",
                },
            },
            "required": ["place_name"],
        },
    },
    {
        "name": "run_algorithm",
        "description": "使用 ACO 多目标优化运行红色旅游路线规划。可指定用户画像、目标簇、三目标权重（w_time, w_cost, w_satisfaction）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "profile": {
                    "type": "string",
                    "enum": ["family", "study", "normal"],
                    "description": "用户画像：family=家庭游客, study=研学/学生, normal=普通游客",
                },
                "cluster_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "空间剪枝簇 ID 列表，与 select_cluster_by_place_name 返回一致；空则使用全量矩阵",
                },
                "w_time": {"type": "number", "description": "时间权重 (0~1)，与 w_cost、w_satisfaction 和为 1"},
                "w_cost": {"type": "number", "description": "费用权重 (0~1)，调高可压低路线总费用"},
                "w_satisfaction": {"type": "number", "description": "满意度权重 (0~1)"},
            },
            "required": [],
        },
    },
]


def _data_dir() -> str:
    return os.path.join(PROJECT_ROOT, "data", "processed")


def _db_path() -> str:
    return os.path.join(_data_dir(), "poi_spatial.db")


# ---------- 工具实现 ----------

def select_cluster_by_place_name(place_name: str) -> Dict[str, Any]:
    """
    工具：根据地名选簇。
    返回该地名（adname 模糊匹配）下所有 POI 的 cluster_id 去重列表。
    """
    place_name = (place_name or "").strip()
    if not place_name:
        return {"cluster_ids": [], "message": "地名为空，未查询到簇。"}
    try:
        from poi_database import POIDatabase
        db = POIDatabase(_db_path())
        cluster_ids = db.get_cluster_ids_by_place_name(place_name)
        if not cluster_ids:
            return {
                "cluster_ids": [],
                "message": f"未找到地名「{place_name}」对应的簇（请确认已运行 spatial_pruning.py 且 DB 中有该区县数据）。",
            }
        return {
            "cluster_ids": cluster_ids,
            "message": f"已选定地名「{place_name}」对应簇: {cluster_ids}。",
        }
    except Exception as e:
        return {"cluster_ids": [], "message": f"查询簇失败: {e}"}


def _ensure_matrix_for_clusters(cluster_ids: Optional[List[int]]) -> Optional[str]:
    """
    若指定了 cluster_ids，检查对应成本矩阵是否存在；不存在则调用 build_cost_matrices 生成。
    返回矩阵前缀（不含路径）或 None（失败）。
    """
    data_dir = _data_dir()
    if cluster_ids and len(cluster_ids) > 0:
        prefix = f"cost_matrix_combined_clusters_{'_'.join(map(str, sorted(cluster_ids)))}"
        base = os.path.join(data_dir, prefix)
        required = [f"{base}_distance.npy", f"{base}_time.npy", f"{base}_fee.npy", f"{base}_poi_ids.txt"]
        if all(os.path.isfile(p) for p in required):
            return prefix
        # 构建矩阵
        cmd = [
            sys.executable,
            os.path.join(os.path.dirname(__file__), "build_cost_matrices.py"),
            "--type", "combined",
            "--cluster-ids", ",".join(map(str, cluster_ids)),
        ]
        try:
            subprocess.run(cmd, cwd=PROJECT_ROOT, check=True, capture_output=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"构建成本矩阵失败: {e}")
            return None
        return prefix if all(os.path.isfile(p) for p in required) else None
    # 无簇：使用已有任意 combined 或 red_spot 矩阵
    candidates = (
        glob.glob(os.path.join(data_dir, "cost_matrix_combined*_distance.npy")) +
        glob.glob(os.path.join(data_dir, "cost_matrix_red_spot*_distance.npy"))
    )
    if not candidates:
        return None
    first = sorted(candidates)[0]
    return os.path.basename(first).replace("_distance.npy", "")


def run_algorithm(
    profile: str = "normal",
    cluster_ids: Optional[List[int]] = None,
    w_time: Optional[float] = None,
    w_cost: Optional[float] = None,
    w_satisfaction: Optional[float] = None,
) -> Dict[str, Any]:
    """
    工具：运行 ACO 路线规划。
    若传入 w_time/w_cost/w_satisfaction，则覆盖画像默认权重（仍归一化为和 1）。
    """
    matrix_prefix = _ensure_matrix_for_clusters(cluster_ids)
    if not matrix_prefix:
        return {
            "success": False,
            "message": "未找到或无法构建成本矩阵（请先运行 build_cost_matrices.py 或 spatial_pruning + build_cost_matrices --cluster-ids）。",
            "total_cost_yuan": None,
            "total_time_h": None,
            "path_names": [],
        }
    data_dir = _data_dir()
    try:
        from aco_optimizer import ACOOptimizer
        opt = ACOOptimizer(
            matrix_prefix=matrix_prefix,
            data_dir=data_dir,
            profile=profile,
            n_ants=8,
            n_iterations=15,
        )
        # 权重覆盖：若传入则覆盖画像默认
        if w_time is not None or w_cost is not None or w_satisfaction is not None:
            wt = float(w_time) if w_time is not None else opt.W[0]
            wc = float(w_cost) if w_cost is not None else opt.W[1]
            ws = float(w_satisfaction) if w_satisfaction is not None else opt.W[2]
            s = wt + wc + ws
            if s > 0:
                opt.W = (wt / s, wc / s, ws / s)
        res = opt.run()
        return {
            "success": True,
            "message": "路线规划完成。",
            "total_cost_yuan": res.get("total_cost_yuan"),
            "total_time_h": res.get("total_time_h"),
            "total_satisfaction": res.get("total_satisfaction"),
            "path_names": res.get("path_names", []),
            "path_ids": res.get("path_ids", []),
            "n_days": res.get("n_days"),
            "evaluation": res.get("evaluation"),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"运行算法失败: {e}",
            "total_cost_yuan": None,
            "total_time_h": None,
            "path_names": [],
        }


# ---------- 智能逻辑：从自然语言解析意图并调参 ----------

COST_THRESHOLD_YUAN = 400.0
MAX_COST_RETRIES = 3

# 用户说「学生/研学」时提高费用权重的默认目标
STUDY_W_COST_DEFAULT = 0.45
# 闭环修正时每次增加的费用权重
W_COST_INCREMENT = 0.12

# ---------- Claude Tool Use：系统提示与工具执行 ----------

CLAUDE_SYSTEM_PROMPT = """你是广州红色旅游路线规划助手。用户会说出自己的身份（如学生、家庭、普通游客）和想去的地方（如越秀区、番禺区），你需要通过调用工具来完成任务。

可用工具：
1. select_cluster_by_place_name(place_name)：当用户提到具体区县/地名时先调用此工具，得到该区域对应的 cluster_id 列表。
2. run_algorithm(profile, cluster_ids, w_time, w_cost, w_satisfaction)：运行路线规划。profile 必选：用户是学生/研学用 study，家庭用 family，否则用 normal。若用户提到某区县，请把 select_cluster_by_place_name 返回的 cluster_ids 传入；未提区县则传空或不传。学生/研学用户希望省钱时，可把 w_cost 设高一些（如 0.45）。run_algorithm 内部会在总费用超过 400 元时自动调大费用权重重算，无需你多次调用。

流程建议：先根据用户提到的地名调用 select_cluster_by_place_name，再根据用户画像和得到的 cluster_ids 调用 run_algorithm。最后用自然语言总结路线结果（费用、时间、景点数等）。"""


def _execute_tool(name: str, inp: Dict[str, Any]) -> Dict[str, Any]:
    """根据工具名和输入执行对应工具，返回可 JSON 序列化的结果。run_algorithm 会走费用闭环（>400 自动重算）。"""
    inp = inp or {}
    if name == "select_cluster_by_place_name":
        return select_cluster_by_place_name(inp.get("place_name", ""))
    if name == "run_algorithm":
        profile = inp.get("profile", "normal")
        cluster_ids = inp.get("cluster_ids")
        if isinstance(cluster_ids, list) and len(cluster_ids) == 0:
            cluster_ids = None
        w_cost = inp.get("w_cost")
        return _run_with_cost_cap(
            profile=profile,
            cluster_ids=cluster_ids,
            initial_w_cost=float(w_cost) if w_cost is not None else None,
            cap_yuan=COST_THRESHOLD_YUAN,
        )
    return {"error": f"未知工具: {name}"}


def _content_block_type(block: Any) -> str:
    """兼容 dict 或 object 的 content block。"""
    if isinstance(block, dict):
        return block.get("type", "")
    return getattr(block, "type", "") or ""


def _content_block_tool_use(block: Any) -> Tuple[str, str, Dict]:
    """从 tool_use 块取出 id, name, input。"""
    if isinstance(block, dict):
        return (
            block.get("id", ""),
            block.get("name", ""),
            block.get("input") if isinstance(block.get("input"), dict) else {},
        )
    return (
        getattr(block, "id", ""),
        getattr(block, "name", ""),
        getattr(block, "input", None) or {},
    )


# 默认模型；可通过环境变量 CLAUDE_MODEL 或 ANTHROPIC_MODEL 覆盖（国内/代理渠道可能用不同模型名）
DEFAULT_CLAUDE_MODEL = "claude-3-5-sonnet-20241022"


def check_claude_connection() -> Tuple[bool, str]:
    """
    发一条最小请求判断是否接上 Claude。
    返回 (是否成功, 说明文字)。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return False, "未设置 ANTHROPIC_API_KEY。请在终端设置：$env:ANTHROPIC_API_KEY='你的key'（PowerShell）或 set ANTHROPIC_API_KEY=你的key（CMD）"
    try:
        import anthropic
    except ImportError:
        return False, "未安装 anthropic。请执行: pip install anthropic"
    model = os.environ.get("CLAUDE_MODEL") or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_CLAUDE_MODEL
    try:
        client = anthropic.Anthropic(api_key=api_key)
        client.messages.create(
            model=model,
            max_tokens=64,
            messages=[{"role": "user", "content": "回复一个字：好"}],
        )
        return True, f"Claude 连接正常（模型: {model}）"
    except Exception as e:
        err_msg = str(e).lower()
        if "model_not_found" in err_msg or "503" in err_msg or "无可用渠道" in err_msg:
            return False, (
                f"已接到 API，但当前模型「{model}」在你的渠道不可用。\n"
                "请设置环境变量为你的渠道支持的模型名，例如：\n"
                "  $env:CLAUDE_MODEL='claude-3-5-sonnet-latest'\n"
                "或咨询 API 提供方可用的 model 列表。"
            )
        if "401" in err_msg or "403" in err_msg or "invalid" in err_msg or "authentication" in err_msg:
            return False, "API Key 无效或无权访问，请检查 ANTHROPIC_API_KEY。"
        return False, f"连接异常: {e}"


def agent_run_claude(query: str, auto_plot: bool = True, model: Optional[str] = None, max_tokens: int = 4096) -> Dict[str, Any]:
    """
    使用 Claude API 的 Tool Use：由 Claude 决定何时调用 select_cluster_by_place_name / run_algorithm，
    执行工具后把结果送回 Claude，直到 Claude 不再请求工具并给出最终回复。
    若某次工具结果为 run_algorithm 且含 path_ids，则自动画图并写入 result["map_path"]。
    模型名优先使用参数 model，否则环境变量 CLAUDE_MODEL / ANTHROPIC_MODEL，最后默认 DEFAULT_CLAUDE_MODEL。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return {
            "success": False,
            "message": "未设置 ANTHROPIC_API_KEY，无法使用 Claude。请设置后重试，或使用默认正则模式（不加 --claude）。",
            "total_cost_yuan": None,
            "total_time_h": None,
            "path_names": [],
        }
    try:
        import anthropic
    except ImportError:
        return {
            "success": False,
            "message": "未安装 anthropic 包。请执行: pip install anthropic",
            "total_cost_yuan": None,
            "total_time_h": None,
            "path_names": [],
        }
    model = model or os.environ.get("CLAUDE_MODEL") or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_CLAUDE_MODEL
    client = anthropic.Anthropic(api_key=api_key)
    messages: List[Dict[str, Any]] = [{"role": "user", "content": query}]
    last_run_result: Optional[Dict[str, Any]] = None
    final_text: List[str] = []
    max_rounds = 15
    try:
        for _ in range(max_rounds):
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=CLAUDE_SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
            # 收集本轮的 text 块
            for block in resp.content:
                if _content_block_type(block) == "text":
                    text = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
                    if text:
                        final_text.append(text)
            stop_reason = getattr(resp, "stop_reason", None) or (resp.get("stop_reason") if isinstance(resp, dict) else None)
            if stop_reason != "tool_use":
                break
            tool_results = []
            for block in resp.content:
                if _content_block_type(block) != "tool_use":
                    continue
                tid, tname, tinput = _content_block_tool_use(block)
                out = _execute_tool(tname, tinput)
                if tname == "run_algorithm" and out.get("success") and out.get("path_ids"):
                    last_run_result = out
                tool_results.append({"type": "tool_result", "tool_use_id": tid, "content": json.dumps(out, ensure_ascii=False)})
            if not tool_results:
                break
            # 将 assistant content 转为 API 接受的 dict 列表（部分 SDK 返回对象）
            assistant_content = []
            for block in resp.content:
                if isinstance(block, dict):
                    assistant_content.append(block)
                else:
                    t = _content_block_type(block)
                    if t == "text":
                        assistant_content.append({"type": "text", "text": getattr(block, "text", "")})
                    elif t == "tool_use":
                        bid, bname, binput = _content_block_tool_use(block)
                        assistant_content.append({"type": "tool_use", "id": bid, "name": bname, "input": binput})
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})
    except Exception as e:
        err_msg = str(e).lower()
        if "model_not_found" in err_msg or "503" in err_msg or "无可用渠道" in err_msg:
            friendly = (
                f"已接到 API，但模型「{model}」在当前渠道不可用。"
                "请设置: $env:CLAUDE_MODEL='你的渠道支持的模型名' 后重试。"
            )
        elif "401" in err_msg or "403" in err_msg or "invalid" in err_msg or "authentication" in err_msg:
            friendly = "API Key 无效或无权访问，请检查 ANTHROPIC_API_KEY。"
        else:
            friendly = f"Claude 请求异常: {e}"
        return {
            "success": False,
            "message": friendly,
            "total_cost_yuan": None,
            "total_time_h": None,
            "path_names": [],
        }
    # 统一返回结构，便于与 agent_run 一致
    if last_run_result:
        result = {
            "success": last_run_result.get("success", True),
            "message": "\n\n".join(final_text) if final_text else last_run_result.get("message", ""),
            "total_cost_yuan": last_run_result.get("total_cost_yuan"),
            "total_time_h": last_run_result.get("total_time_h"),
            "total_satisfaction": last_run_result.get("total_satisfaction"),
            "path_names": last_run_result.get("path_names", []),
            "path_ids": last_run_result.get("path_ids", []),
            "n_days": last_run_result.get("n_days"),
            "evaluation": last_run_result.get("evaluation"),
            "_claude_final_text": final_text,
        }
    else:
        result = {
            "success": False,
            "message": "\n\n".join(final_text) if final_text else "Claude 未调用 run_algorithm 或调用未返回有效路线。",
            "total_cost_yuan": None,
            "total_time_h": None,
            "path_names": [],
            "path_ids": [],
            "_claude_final_text": final_text,
        }
    if auto_plot and result.get("path_ids"):
        map_path = _plot_route_map(result["path_ids"])
        if map_path:
            result["map_path"] = map_path
    return result


def _parse_intent(query: str) -> Dict[str, Any]:
    """
    从用户输入解析：画像、地名、是否要压低费用。
    返回 { "profile", "place_name", "prefer_low_cost" }。
    """
    q = (query or "").strip().lower()
    profile = "normal"
    if any(k in q for k in ["学生", "研学", "研学游客"]):
        profile = "study"
    elif any(k in q for k in ["家庭", "家庭游客", "带孩子"]):
        profile = "family"
    place_name = ""
    for district in ["越秀区", "番禺区", "天河区", "海珠区", "荔湾区", "白云区", "黄埔区", "花都区", "南沙区", "从化区", "增城区"]:
        if district in q or district.replace("区", "") in q:
            place_name = district
            break
    if not place_name and "越秀" in q:
        place_name = "越秀区"
    if not place_name and "番禺" in q:
        place_name = "番禺区"
    prefer_low_cost = profile == "study" or "便宜" in q or "省钱" in q or "费用" in q
    return {"profile": profile, "place_name": place_name, "prefer_low_cost": prefer_low_cost}


def _run_with_cost_cap(
    profile: str,
    cluster_ids: Optional[List[int]],
    initial_w_cost: Optional[float],
    cap_yuan: float = COST_THRESHOLD_YUAN,
) -> Dict[str, Any]:
    """
    运行算法并在总费用超过 cap_yuan 时自动调大 w_cost 重算（闭环修正），最多 MAX_COST_RETRIES 次。
    """
    w_cost = initial_w_cost
    last_result = None
    for attempt in range(MAX_COST_RETRIES):
        res = run_algorithm(profile=profile, cluster_ids=cluster_ids, w_cost=w_cost)
        last_result = res
        if not res.get("success"):
            return res
        cost = res.get("total_cost_yuan")
        if cost is None or cost <= cap_yuan:
            res["_cost_retries"] = attempt
            return res
        # 超过上限：提高费用权重，下一轮重算
        base_w = 0.33 if w_cost is None else float(w_cost)
        w_cost = min(0.7, base_w + W_COST_INCREMENT)
        last_result["_message_append"] = f"费用 {cost:.1f} 元超过 {cap_yuan} 元，已调大费用权重至 {w_cost:.2f} 并重新计算。"
    if last_result is not None:
        last_result["_cost_retries"] = MAX_COST_RETRIES
    return last_result


def _plot_route_map(path_ids: List[str], out_path: Optional[str] = None) -> Optional[str]:
    """
    根据规划结果 path_ids 自动生成旅游路线图 HTML。
    返回生成的 HTML 绝对路径，失败返回 None。
    """
    if not path_ids:
        return None
    out_path = out_path or os.path.join(_data_dir(), "smart_route_latest.html")
    out_path = os.path.abspath(out_path)
    try:
        # plot_red_spots_map 在项目根目录
        sys.path.insert(0, PROJECT_ROOT)
        from plot_red_spots_map import plot_map_with_route
        _, saved_path = plot_map_with_route(route_ids=path_ids, out_path=out_path)
        return os.path.abspath(saved_path) if saved_path else None
    except Exception as e:
        print(f"自动画图失败: {e}")
        return None


def agent_run(query: str, auto_plot: bool = True) -> Dict[str, Any]:
    """
    Agent 主流程：解析用户意图 → 选簇（若有地名）→ 确定权重（学生等调高 w_cost）→ 运行算法 → 费用超 400 则闭环修正。
    若 auto_plot=True 且规划成功，则自动生成路线图 HTML（smart_route_latest.html）。
    """
    intent = _parse_intent(query)
    profile = intent["profile"]
    place_name = intent["place_name"]
    prefer_low_cost = intent["prefer_low_cost"]

    cluster_ids: Optional[List[int]] = None
    if place_name:
        out = select_cluster_by_place_name(place_name)
        cluster_ids = out.get("cluster_ids") or None
        if cluster_ids is not None and len(cluster_ids) == 0:
            cluster_ids = None

    initial_w_cost = STUDY_W_COST_DEFAULT if prefer_low_cost else None
    result = _run_with_cost_cap(profile=profile, cluster_ids=cluster_ids, initial_w_cost=initial_w_cost, cap_yuan=COST_THRESHOLD_YUAN)
    result["_intent"] = intent
    result["_cluster_ids_used"] = cluster_ids
    if result.get("_message_append"):
        result["message"] = (result.get("message") or "") + " " + result["_message_append"]

    # 自动画图：规划成功且有 path_ids 时生成路线图
    if auto_plot and result.get("success") and result.get("path_ids"):
        map_path = _plot_route_map(result["path_ids"])
        if map_path:
            result["map_path"] = map_path
    return result


# ---------- CLI ----------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="智能控制器：根据地名选簇、运行算法，支持费用闭环修正，成功即自动生成路线图")
    parser.add_argument("--query", "-q", type=str, default="我是学生，想去越秀区看红色遗址", help="用户自然语言输入")
    parser.add_argument("--claude", action="store_true", help="使用 Claude API 的 Tool Use 解析意图并决定调用工具（需设置 ANTHROPIC_API_KEY）")
    parser.add_argument("--check-claude", action="store_true", help="仅检测是否接上 Claude（发一条最小请求），不跑规划")
    parser.add_argument("--list-tools", action="store_true", help="仅列出 Tool Use 规范下的工具定义")
    parser.add_argument("--no-plot", action="store_true", help="不自动生成路线图")
    parser.add_argument("--open-map", action="store_true", help="生成路线图后自动用浏览器打开")
    args = parser.parse_args()

    if args.list_tools:
        print(json.dumps(TOOLS, ensure_ascii=False, indent=2))
        return

    if args.check_claude:
        ok, msg = check_claude_connection()
        print("Claude 连接检测:", "成功" if ok else "失败")
        print(msg)
        return

    print("用户输入:", args.query)
    if args.claude:
        print("模式: Claude Tool Use（由 Claude 决定何时调用工具）")
        res = agent_run_claude(args.query, auto_plot=not args.no_plot)
    else:
        print("解析意图:", _parse_intent(args.query))
        res = agent_run(args.query, auto_plot=not args.no_plot)
    print("\n结果:")
    print("  成功:", res.get("success"))
    print("  消息:", res.get("message"))
    print("  总费用(元):", res.get("total_cost_yuan"))
    print("  总时间(h):", res.get("total_time_h"))
    print("  路线点数:", len(res.get("path_names") or []))
    if res.get("_cost_retries", 0) > 0:
        print("  闭环修正次数:", res["_cost_retries"])
    map_path = res.get("map_path")
    if map_path:
        print("  路线图已生成:", map_path)
        if args.open_map:
            try:
                import webbrowser
                webbrowser.open("file:///" + map_path.replace("\\", "/"))
                print("  已用默认浏览器打开路线图。")
            except Exception as e:
                print("  自动打开失败:", e, "请手动打开上述 HTML 文件。")


if __name__ == "__main__":
    main()
