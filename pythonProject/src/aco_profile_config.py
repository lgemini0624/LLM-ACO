"""
用户画像配置：家庭、研学、普通 三种画像的红色占比与启发式偏好。

用于 ACO 比例弹性路径与多维语义匹配。若存在 权重.xlsx（AHP 问卷权重），则三目标权重 W 由 AHP 确定。
"""
from typing import List, Dict, Any, Optional

# 红色景点目标占比（0~1），实现“比例弹性路径”
# 家庭：红色占比偏低；研学：偏高；普通：最低
RED_RATIO_PREFERENCE = {
    'family': 0.3,
    'study': 0.6,
    'normal': 0.2,
}

# 家庭画像：subtype/名称语义偏好（纪念馆、博物馆加分；陵园降权）
FAMILY_SUBTYPE_PREFER = ['纪念馆', '博物馆', '展览馆', '纪念园']
FAMILY_SUBTYPE_AVOID = ['陵园', '墓']

# 研学画像：核心红色极高权重，最小停留时间（小时）体现深度
STUDY_MIN_STAY_CORE_RED = 2.0
STUDY_EDUCATION_WEIGHT = 2.0   # core_red 启发式乘数
STUDY_CORE_RED_HIGH_PRIORITY = True

# 普通画像：无特殊 subtype 过滤，以评分和距离为主
NORMAL_SUBTYPE_PREFER = []
NORMAL_SUBTYPE_AVOID = []

# 默认三目标权重（时间、成本、满意度），AHP 未加载时使用
DEFAULT_W = (0.4, 0.3, 0.3)


def get_profile_config(profile: str, ahp_weights_path: Optional[str] = None) -> Dict[str, Any]:
    """返回画像配置字典，供 ACOOptimizer 使用。若存在 AHP 权重文件，则 W 由 AHP 确定。"""
    p = profile.lower() if profile else 'normal'
    try:
        from ahp_weights import get_ahp_weights
        ahp = get_ahp_weights(p, ahp_weights_path)
        if ahp:
            w_time = ahp.get('w_time', DEFAULT_W[0])
            w_cost = ahp.get('w_cost', DEFAULT_W[1])
            w_sat = ahp.get('w_satisfaction', DEFAULT_W[2])
            w_tuple = (w_time, w_cost, w_sat)
        else:
            w_tuple = DEFAULT_W
    except Exception:
        w_tuple = DEFAULT_W

    base = {
        'w_time': w_tuple[0],
        'w_cost': w_tuple[1],
        'w_satisfaction': w_tuple[2],
    }
    if p == 'family':
        return {
            **base,
            'target_red_ratio': RED_RATIO_PREFERENCE['family'],
            'subtype_prefer': FAMILY_SUBTYPE_PREFER,
            'subtype_avoid': FAMILY_SUBTYPE_AVOID,
            'min_stay_core_red': 1.0,
            'education_weight': 1.0,
            'core_red_high_priority': False,
        }
    if p == 'study':
        return {
            **base,
            'target_red_ratio': RED_RATIO_PREFERENCE['study'],
            'subtype_prefer': [],
            'subtype_avoid': [],
            'min_stay_core_red': STUDY_MIN_STAY_CORE_RED,
            'education_weight': STUDY_EDUCATION_WEIGHT,
            'core_red_high_priority': STUDY_CORE_RED_HIGH_PRIORITY,
        }
    # normal
    return {
        **base,
        'target_red_ratio': RED_RATIO_PREFERENCE['normal'],
        'subtype_prefer': NORMAL_SUBTYPE_PREFER,
        'subtype_avoid': NORMAL_SUBTYPE_AVOID,
        'min_stay_core_red': 1.0,
        'education_weight': 1.0,
        'core_red_high_priority': False,
    }
