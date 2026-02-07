"""
多维度成本矩阵：距离（km）、时间（h）、费用（元）。
基于 Haversine 直线距离，时间与费用由可配置模型推导。
"""
import os
import numpy as np
import pandas as pd
from math import radians, sin, cos, sqrt, atan2


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点 Haversine 距离（公里）。"""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


# 单矩阵约 8*N^2 字节，超过此数量易内存溢出（经验值 5000 约 200MB）
_MAX_POI_FOR_FULL_MATRIX = 5000


def compute_distance_matrix(poi_df: pd.DataFrame) -> np.ndarray:
    """
    计算 POI 两两直线距离矩阵（km）。
    poi_df 需含 longitude, latitude 列。
    """
    n = len(poi_df)
    if n > _MAX_POI_FOR_FULL_MATRIX:
        mem_gib = n * n * 8 / (1024 ** 3)
        raise MemoryError(
            f"POI 数量 {n} 过大，距离矩阵约需 {mem_gib:.1f} GB。"
            "请先用 --top N 限制数量（如 --top 500）。"
        )
    dist = np.zeros((n, n))
    lats = poi_df['latitude'].values
    lons = poi_df['longitude'].values
    for i in range(n):
        for j in range(n):
            if i == j:
                dist[i, j] = 0.0
            else:
                dist[i, j] = haversine_km(lats[i], lons[i], lats[j], lons[j])
    return dist


def compute_time_matrix(distance_km: np.ndarray, speed_kmh: float = 30.0) -> np.ndarray:
    """
    由距离矩阵推导时间矩阵（小时）。
    默认按 30 km/h 估算（城市路况）。
    """
    return distance_km / speed_kmh


def compute_fee_matrix(distance_km: np.ndarray, base_yuan: float = 10.0, per_km_yuan: float = 2.5) -> np.ndarray:
    """
    由距离矩阵推导出行费用矩阵（元）。
    默认模型：起步价 base_yuan + 每公里 per_km_yuan（如出租车/网约车）。
    """
    fee = base_yuan + per_km_yuan * distance_km
    np.fill_diagonal(fee, 0.0)
    return fee


def compute_cost_matrices(
    poi_df: pd.DataFrame,
    speed_kmh: float = 30.0,
    fee_base_yuan: float = 10.0,
    fee_per_km_yuan: float = 2.5,
) -> dict:
    """
    一次计算距离、时间、费用三个矩阵。
    poi_df 需含 longitude, latitude。
    返回: {
        'distance': (N,N) km,
        'time': (N,N) 小时,
        'fee': (N,N) 元,
        'poi_ids': 与矩阵行/列顺序一致的 id 列表
    }
    """
    if poi_df is None or len(poi_df) == 0:
        return {'distance': np.array([]), 'time': np.array([]), 'fee': np.array([]), 'poi_ids': []}
    distance = compute_distance_matrix(poi_df)
    time = compute_time_matrix(distance, speed_kmh=speed_kmh)
    fee = compute_fee_matrix(distance, base_yuan=fee_base_yuan, per_km_yuan=fee_per_km_yuan)
    poi_ids = poi_df['id'].astype(str).tolist()
    return {
        'distance': distance,
        'time': time,
        'fee': fee,
        'poi_ids': poi_ids,
    }


def load_poi_and_compute_matrices(
    db_path: str = None,
    poi_type: str = None,
    poi_ids: list = None,
    speed_kmh: float = 30.0,
    fee_base_yuan: float = 10.0,
    fee_per_km_yuan: float = 2.5,
) -> dict:
    """
    从 POI 数据库加载 POI，并计算多维度成本矩阵。
    :param db_path: poi_spatial.db 路径，默认 data/processed/poi_spatial.db
    :param poi_type: 仅该类型，如 'red_spot'；为 None 且 poi_ids 为 None 时用全部
    :param poi_ids: 仅这些 id；若指定则忽略 poi_type
    :return: compute_cost_matrices 的返回值
    """
    try:
        from poi_database import POIDatabase, _project_data_dir
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from poi_database import POIDatabase, _project_data_dir

    if db_path is None:
        db_path = os.path.join(_project_data_dir(), 'poi_spatial.db')
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"请先构建 POI 数据库: {db_path}")

    db = POIDatabase(db_path)
    if poi_ids is not None and len(poi_ids) > 0:
        poi_df = db.get_poi_by_ids(poi_ids)
        # 保持与 poi_ids 顺序一致
        id_order = {str(pid): i for i, pid in enumerate(poi_ids)}
        poi_df = poi_df[poi_df['id'].astype(str).isin(id_order)]
        poi_df = poi_df.assign(_order=poi_df['id'].astype(str).map(id_order)).sort_values('_order').drop(columns=['_order'])
        if poi_df.empty:
            return {'distance': np.array([]), 'time': np.array([]), 'fee': np.array([]), 'poi_ids': []}
    else:
        poi_df = db.get_poi_dataframe(poi_type=poi_type)
    poi_df = poi_df.dropna(subset=['longitude', 'latitude'])
    return compute_cost_matrices(
        poi_df,
        speed_kmh=speed_kmh,
        fee_base_yuan=fee_base_yuan,
        fee_per_km_yuan=fee_per_km_yuan,
    )
