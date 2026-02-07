"""
空间剪枝（Spatial Pruning）：用 K-Means 对 POI 聚类，按簇建成本矩阵，避免全量矩阵溢出。

逻辑：路程≤200km、每日最多 5 景点，蚂蚁无需考虑极远点。先对红点+风景景点做 K-Means（如 20 簇），
Agent 根据用户需求选定 1–2 个目标簇，只对 1–2 簇（约 500–1000 点）生成成本矩阵。

步骤：
1. 对 red_spot + attraction 做 K-Means 聚类（默认 20 簇）。
2. 将 cluster_id 写回 poi_spatial.db，数据库具备“空间感知”，剪枝只需一行 SQL。
3. build_cost_matrices --cluster-ids 1,2 只对指定簇建矩阵（约 500–1000 点，无需稀疏矩阵）。

数据与内存：
- ID 存为字符串，经纬度用 float32 以省内存；写入 .db/.npy 后可用 del df; gc.collect() 释放。
- 若需进一步省内存，可对“不可达”边（如距离>200km）用 scipy.sparse 只存可达路径（当前 ACO 仍用稠密矩阵，剪枝后规模可控）。
"""
import os
import sys
import sqlite3
import gc
from typing import List, Optional, Tuple

# 避免 Windows 上 joblib/loky 检测物理核心时 wmic 报错（在 import sklearn 之前设置）
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd


def _project_data_dir():
    _src = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(_src), 'data', 'processed')


def _ensure_cluster_id_column(conn: sqlite3.Connection) -> None:
    """若 poi 表无 cluster_id 列则添加。"""
    cur = conn.execute("PRAGMA table_info(poi)")
    cols = [row[1] for row in cur.fetchall()]
    if 'cluster_id' not in cols:
        conn.execute("ALTER TABLE poi ADD COLUMN cluster_id INTEGER")
        conn.commit()


def run_kmeans_clustering(
    poi_df: pd.DataFrame,
    n_clusters: int = 20,
    lat_col: str = 'latitude',
    lon_col: str = 'longitude',
    random_state: int = 42,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    对 POI 经纬度做 K-Means 聚类。
    :param poi_df: 含 latitude, longitude 的 DataFrame（建议仅 red_spot + attraction）
    :param n_clusters: 簇数，默认 20
    :return: (labels 每行所属簇 0..n_clusters-1, centers 簇中心 (n_clusters, 2) [lat, lon])
    """
    from sklearn.cluster import KMeans
    X = poi_df[[lat_col, lon_col]].astype(np.float64)
    X = X.dropna()
    if len(X) < n_clusters:
        n_clusters = max(1, len(X) // 2)
    km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    labels = np.full(len(poi_df), -1, dtype=np.int32)
    valid = poi_df[[lat_col, lon_col]].notna().all(axis=1)
    labels[valid] = km.fit_predict(X.values)
    centers = km.cluster_centers_  # (n_clusters, 2) lat, lon
    return labels, centers


def assign_clusters_to_db(
    db_path: str,
    n_clusters: int = 20,
    poi_types: Tuple[str, ...] = ('red_spot', 'attraction'),
) -> Tuple[int, np.ndarray]:
    """
    对 DB 中指定类型的 POI 做 K-Means，将 cluster_id 写回 poi 表。
    :param db_path: poi_spatial.db 路径
    :param n_clusters: 簇数
    :param poi_types: 参与聚类的类型，默认仅 red_spot + attraction
    :return: (参与聚类的 POI 数, 簇中心数组 (n_clusters, 2) lat, lon)
    """
    conn = sqlite3.connect(db_path)
    _ensure_cluster_id_column(conn)
    placeholders = ','.join('?' * len(poi_types))
    df = pd.read_sql(
        f"SELECT id, longitude, latitude FROM poi WHERE poi_type IN ({placeholders})",
        conn,
        params=poi_types,
    )
    conn.close()
    df = df.dropna(subset=['longitude', 'latitude'])
    df = df.astype({'longitude': np.float32, 'latitude': np.float32})
    if df.empty:
        return 0, np.array([])
    n = len(df)
    if n < n_clusters:
        n_clusters = max(1, n // 2)
    labels, centers = run_kmeans_clustering(df, n_clusters=n_clusters, random_state=42)
    df = df.assign(cluster_id=labels)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for _, row in df.iterrows():
        cur.execute("UPDATE poi SET cluster_id = ? WHERE id = ?", (int(row['cluster_id']), str(row['id'])))
    conn.commit()
    conn.close()
    del df
    gc.collect()
    return n, centers.astype(np.float32)


def get_cluster_summary(db_path: str) -> pd.DataFrame:
    """返回各簇的 POI 数量（仅 red_spot + attraction），用于 Agent 或用户选择目标簇。"""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT cluster_id, COUNT(*) as cnt FROM poi WHERE poi_type IN ('red_spot','attraction') AND cluster_id IS NOT NULL GROUP BY cluster_id ORDER BY cluster_id"
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    if not rows:
        return pd.DataFrame(columns=['cluster_id', 'poi_count'])
    return pd.DataFrame(rows, columns=['cluster_id', 'poi_count'])


def main():
    import argparse
    _src = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(_src)
    data_dir = os.path.join(root, 'data', 'processed')
    db_path = os.path.join(data_dir, 'poi_spatial.db')

    parser = argparse.ArgumentParser(description='空间剪枝：K-Means 聚类并将 cluster_id 写回 DB')
    parser.add_argument('--db', default=db_path, help='poi_spatial.db 路径')
    parser.add_argument('--n-clusters', type=int, default=20, help='簇数，默认 20')
    parser.add_argument('--summary', action='store_true', help='仅打印各簇 POI 数量摘要')
    args = parser.parse_args()

    if args.summary:
        summary = get_cluster_summary(args.db)
        if summary.empty:
            print("未找到 cluster_id 数据，请先运行: python src/spatial_pruning.py")
            return
        print("各簇 POI 数量（red_spot + attraction）：")
        print(summary.to_string(index=False))
        return

    if not os.path.isfile(args.db):
        print(f"未找到 {args.db}，请先运行 main.py 生成 POI 数据库。")
        return
    n, centers = assign_clusters_to_db(args.db, n_clusters=args.n_clusters)
    print(f"已对 {n} 个 POI 聚类为 {args.n_clusters} 簇，cluster_id 已写回 DB。")
    print("查看各簇数量: python src/spatial_pruning.py --summary")


if __name__ == '__main__':
    main()
