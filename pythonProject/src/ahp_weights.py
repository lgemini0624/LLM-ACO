"""
层次分析法（AHP）权重：从 权重.xlsx 读取准则层与方案层权重，用于不同层次游客对旅游特征的兴趣程度。

准则层：景点的美观性、文化历史价值、自然环境、交通便利性、旅游费用（来自 273 份问卷）。
方案层：家庭游客、学生游客、普通游客。
映射到 ACO 三目标：交通便利性→w_time，旅游费用→w_cost，美观性+文化历史价值+自然环境→w_satisfaction。
"""
import os
from typing import Dict, Any, Optional, Tuple

# 准则到目标的映射
CRITERION_TO_OBJECTIVE = {
    '交通便利性': 'time',
    '旅游费用': 'cost',
    '美观性': 'satisfaction',
    '文化历史价值': 'satisfaction',
    '自然环境': 'satisfaction',
}

# 游客类型与内部 profile 对应（与 权重.xlsx 中「游客类型」列一致）
PROFILE_NAME_MAP = {
    'family': ['家庭游客', '家庭', 'family'],
    'study': ['研学游客', '学生游客', '学生', '研学', 'study'],
    'normal': ['普通游客', '普通', 'normal'],
}

# 权重.xlsx 标准列名（与 273 份问卷/AHP 结果表一致）
WEIGHT_COLUMNS = {
    'profile': '游客类型',
    'aesthetics': '美观性权重',
    'natural_env': '自然环境权重',
    'cost': '旅游费用权重',
    'transport': '交通便利性权重',
    'culture': '文化历史价值权重',
}


def _project_data_dir():
    _src = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(_src), 'data', 'processed')


def _find_weights_path(path: Optional[str] = None) -> Optional[str]:
    """优先使用传入路径，否则 data/processed/权重.xlsx 或 data/权重.xlsx，或环境变量 AHP_WEIGHTS_PATH。"""
    if path and os.path.isfile(path):
        return path
    for base in [_project_data_dir(), os.path.join(os.path.dirname(_project_data_dir()), '..')]:
        p = os.path.join(base, '权重.xlsx')
        if os.path.isfile(p):
            return p
    env_path = os.environ.get('AHP_WEIGHTS_PATH')
    if env_path and os.path.isfile(env_path):
        return env_path
    # 用户指定默认路径（广州城市数据交付目录下的 权重.xlsx）
    default = r"D:\Users\Lenovo\Desktop\广州城市数据\2025.06.11-广州POI带BIZ信息采集交付\权重.xlsx"
    if os.path.isfile(default):
        return default
    return None


def _normalize_weights(w_time: float, w_cost: float, w_satisfaction: float) -> Tuple[float, float, float]:
    s = w_time + w_cost + w_satisfaction
    if s <= 0:
        return 1/3, 1/3, 1/3
    return w_time/s, w_cost/s, w_satisfaction/s


def load_ahp_weights_from_excel(path: str) -> Optional[Dict[str, Dict[str, float]]]:
    """
    从 Excel 读取各画像对准则的兴趣权重，返回 { profile: { 'w_time', 'w_cost', 'w_satisfaction' } }。

    权重.xlsx 格式（与 273 份问卷/AHP 结果表一致）：
    - 游客类型：家庭游客、普通游客、研学游客
    - 美观性权重、自然环境权重、旅游费用权重、交通便利性权重、文化历史价值权重
    - 映射：交通便利性→w_time，旅游费用→w_cost，美观性+自然环境+文化历史价值→w_satisfaction（三者归一化后和为 1）
    """
    try:
        import pandas as pd
    except ImportError:
        return None
    try:
        df = pd.read_excel(path, sheet_name=0, header=0)
    except Exception:
        return None
    # 优先使用标准列名，否则按关键字匹配
    profile_col = None
    col_time = None   # 交通便利性权重
    col_cost = None   # 旅游费用权重
    col_sat = []      # 美观性权重 + 自然环境权重 + 文化历史价值权重
    for c in df.columns:
        cs = str(c).strip()
        if cs == WEIGHT_COLUMNS['profile'] or cs in ('画像', '类型', '游客类型', '方案', '游客'):
            profile_col = c
        elif cs == WEIGHT_COLUMNS['transport'] or '交通' in cs:
            col_time = c
        elif cs == WEIGHT_COLUMNS['cost'] or '费用' in cs:
            col_cost = c
        elif cs == WEIGHT_COLUMNS['aesthetics'] or '美观' in cs:
            if c not in col_sat:
                col_sat.append(c)
        elif cs == WEIGHT_COLUMNS['natural_env'] or ('自然' in cs and '文化' not in cs):
            if c not in col_sat:
                col_sat.append(c)
        elif cs == WEIGHT_COLUMNS['culture'] or ('文化' in cs or '历史' in cs):
            if c not in col_sat:
                col_sat.append(c)
    if profile_col is None:
        profile_col = df.columns[0]
    if not col_time or not col_cost or not col_sat:
        return None
    out = {}
    for _, row in df.iterrows():
        profile_name = str(row.get(profile_col, '')).strip()
        if not profile_name or profile_name == 'nan':
            continue
        w_t = _to_float(row.get(col_time, 0))
        w_c = _to_float(row.get(col_cost, 0))
        w_s = sum(_to_float(row.get(k, 0)) for k in col_sat)
        if w_t == 0 and w_c == 0 and w_s == 0:
            continue
        w_time, w_cost, w_sat = _normalize_weights(w_t, w_c, w_s)
        for key, aliases in PROFILE_NAME_MAP.items():
            if any(alias in profile_name or profile_name in alias for alias in aliases):
                out[key] = {'w_time': w_time, 'w_cost': w_cost, 'w_satisfaction': w_sat}
                break
    return out if out else None


def _to_float(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# 缓存：避免重复读表
_ahp_cache: Optional[Dict[str, Dict[str, float]]] = None
_ahp_cache_path: Optional[str] = None


def get_ahp_weights(profile: str, weights_path: Optional[str] = None) -> Optional[Dict[str, float]]:
    """
    返回指定画像的 AHP 三目标权重 (w_time, w_cost, w_satisfaction)，和为 1。
    profile: 'family' | 'study' | 'normal'
    若未找到 权重.xlsx 或解析失败，返回 None，调用方使用默认权重。
    """
    global _ahp_cache, _ahp_cache_path
    path = _find_weights_path(weights_path)
    if not path:
        return None
    if _ahp_cache is None or _ahp_cache_path != path:
        _ahp_cache = load_ahp_weights_from_excel(path)
        _ahp_cache_path = path
    if not _ahp_cache:
        return None
    p = profile.lower() if profile else 'normal'
    return _ahp_cache.get(p)


def get_ahp_weights_tuple(profile: str, weights_path: Optional[str] = None) -> Optional[Tuple[float, float, float]]:
    """返回 (w_time, w_cost, w_satisfaction) 或 None。"""
    d = get_ahp_weights(profile, weights_path)
    if not d:
        return None
    return d['w_time'], d['w_cost'], d['w_satisfaction']
