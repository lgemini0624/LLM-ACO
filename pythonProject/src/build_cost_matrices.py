"""
构建多维度成本矩阵（距离、时间、费用）并保存。

用法：
  python src/build_cost_matrices.py --type red_spot --top 500       # 仅红色景点
  python src/build_cost_matrices.py --type combined --top-red 200 --top-attraction 300   # 红点+景点一起
  python src/build_cost_matrices.py --type combined --cluster-ids 1,2   # 空间剪枝：仅对簇 1、2 建矩阵（约 500–1000 点）
"""
import os
import sys
import argparse
import gc
import numpy as np

# 保证可导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from poi_database import POIDatabase
from cost_matrix import compute_cost_matrices


def _project_paths():
    src = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(src)
    data_dir = os.path.join(root, 'data', 'processed')
    db_path = os.path.join(data_dir, 'poi_spatial.db')
    out_dir = data_dir
    return db_path, out_dir, data_dir


def main():
    parser = argparse.ArgumentParser(description='构建 POI 成本矩阵（距离、时间、费用）')
    parser.add_argument('--type', default=None,
                        choices=['red_spot', 'attraction', 'accommodation', 'transportation', 'combined'],
                        help='POI 类型：red_spot/attraction/combined 等；combined=红点+风景景点一起建矩阵')
    parser.add_argument('--top', type=int, default=None, help='仅取前 N 条（单类型时用）')
    parser.add_argument('--top-red', type=int, default=None, help='combined 时红色景点取前 N 条')
    parser.add_argument('--top-attraction', type=int, default=None, help='combined 时风景景点取前 N 条')
    parser.add_argument('--cluster-ids', type=str, default=None, help='空间剪枝：仅对指定簇建矩阵，逗号分隔如 1,2（需先运行 spatial_pruning.py）')
    parser.add_argument('--speed', type=float, default=30.0, help='估算速度 km/h，用于时间矩阵')
    parser.add_argument('--fee-base', type=float, default=10.0, help='费用模型起步价（元）')
    parser.add_argument('--fee-per-km', type=float, default=3.0, help='费用模型每公里（元），与论文假设一致')
    args = parser.parse_args()

    db_path, out_dir, data_dir = _project_paths()
    if not os.path.isfile(db_path):
        print(f"未找到 {db_path}，请先运行 main.py 生成 POI 数据库。")
        return

    cluster_ids = None
    if args.cluster_ids:
        cluster_ids = [int(x.strip()) for x in args.cluster_ids.split(',') if x.strip()]
        if not cluster_ids:
            cluster_ids = None

    db = POIDatabase(db_path)
    if args.type == 'combined':
        top_red = args.top_red if args.top_red is not None else (200 if not cluster_ids else None)
        top_att = args.top_attraction if args.top_attraction is not None else (300 if not cluster_ids else None)
        poi_df = db.get_red_and_attraction_dataframe(
            top_red=top_red,
            top_attraction=top_att,
            cluster_ids=cluster_ids,
        )
    else:
        poi_df = db.get_poi_dataframe(poi_type=args.type, cluster_ids=cluster_ids)
        poi_df = poi_df.dropna(subset=['longitude', 'latitude'])
        n_total = len(poi_df)
        MAX_POI = 5000
        if n_total > MAX_POI and args.top is None:
            mem_gib = n_total * n_total * 8 / (1024 ** 3)
            print(f"错误: POI 数量 {n_total} 过大，成本矩阵约需 {mem_gib:.1f} GB 内存，易溢出。")
            print("请使用 --top N 或 --cluster-ids 1,2（空间剪枝）限制数量。")
            sys.exit(1)
        if args.top is not None and n_total > args.top:
            poi_df = poi_df.head(args.top)
    if poi_df.empty:
        print("无有效 POI，退出。（若使用 --cluster-ids，请先运行: python src/spatial_pruning.py）")
        return

    n = len(poi_df)
    if args.type == 'combined':
        n_red = (poi_df['poi_type'] == 'red_spot').sum()
        n_att = (poi_df['poi_type'] == 'attraction').sum()
        msg = f"计算成本矩阵: {n} 个 POI (红点={n_red}, 风景景点={n_att})"
        if cluster_ids:
            msg += f" [空间剪枝: 簇 {cluster_ids}]"
        print(msg)
    else:
        print(f"计算成本矩阵: {n} 个 POI" + (f" (类型={args.type})" if args.type else "") + (f" [簇 {cluster_ids}]" if cluster_ids else ""))

    # 数据类型：ID 字符串，经纬度 float32 以省内存（cost_matrix 内部可再转）
    poi_df = poi_df.astype({'id': str, 'longitude': np.float32, 'latitude': np.float32}, errors='ignore')
    result = compute_cost_matrices(
        poi_df,
        speed_kmh=args.speed,
        fee_base_yuan=args.fee_base,
        fee_per_km_yuan=args.fee_per_km,
    )

    prefix = f"cost_matrix_{args.type or 'all'}"
    if args.type == 'combined':
        if cluster_ids:
            prefix += f"_clusters_{'_'.join(map(str, cluster_ids))}"
        else:
            prefix += f"_red{args.top_red or 200}_att{args.top_attraction or 300}"
    elif args.top:
        prefix += f"_top{args.top}"
    if cluster_ids and args.type != 'combined':
        prefix += f"_clusters_{'_'.join(map(str, cluster_ids))}"

    np.save(os.path.join(out_dir, f"{prefix}_distance.npy"), result['distance'])
    np.save(os.path.join(out_dir, f"{prefix}_time.npy"), result['time'])
    np.save(os.path.join(out_dir, f"{prefix}_fee.npy"), result['fee'])
    with open(os.path.join(out_dir, f"{prefix}_poi_ids.txt"), 'w', encoding='utf-8') as f:
        f.write('\n'.join(result['poi_ids']))
    print(f"已保存至 {out_dir}:")
    print(f"  {prefix}_distance.npy, {prefix}_time.npy, {prefix}_fee.npy, {prefix}_poi_ids.txt")
    print(f"  矩阵形状: ({n}, {n})")
    del poi_df
    del result
    gc.collect()


if __name__ == '__main__':
    main()
