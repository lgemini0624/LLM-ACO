"""
一键运行全部流程：数据处理 → POI 库 → 空间剪枝（可选）→ 成本矩阵 → 三画像 ACO 对比。

在项目根目录执行:  python run_all.py
可选参数:
  --skip-scenic    跳过「风景景点 CSV」生成（若已有 data/processed/scenic_spots.csv 可跳过）
  --skip-pruning   跳过空间剪枝（不跑 K-Means，建矩阵时不用 --cluster-ids）
  --cluster-ids    空间剪枝后只对指定簇建矩阵，逗号分隔如 1,2（需先跑剪枝，否则忽略）
  --top-red        建矩阵时红色景点取前 N，默认 200（combined）或 500（仅红点）
  --top-attraction 建矩阵时风景景点取前 N，默认 300（combined）
"""
import os
import sys
import subprocess
import argparse

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))


def run(cmd: list, desc: str) -> bool:
    print("\n" + "=" * 60)
    print(f"  {desc}")
    print("=" * 60)
    ret = subprocess.run(cmd, shell=False)
    if ret.returncode != 0:
        print(f"失败: {desc} (exit {ret.returncode})")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="一键运行全部流程")
    parser.add_argument("--skip-scenic", action="store_true", help="跳过风景景点 CSV 生成")
    parser.add_argument("--skip-pruning", action="store_true", help="跳过空间剪枝（K-Means）")
    parser.add_argument("--cluster-ids", type=str, default=None, help="空间剪枝后只对指定簇建矩阵，如 1,2")
    parser.add_argument("--top-red", type=int, default=None, help="combined 时红色景点取前 N")
    parser.add_argument("--top-attraction", type=int, default=None, help="combined 时风景景点取前 N")
    args = parser.parse_args()

    # 1. 风景景点 CSV（可选）
    if not args.skip_scenic:
        if run([sys.executable, "src/build_scenic_spots_csv.py"], "1. 生成风景景点 CSV (scenic_spots.csv)"):
            pass
        else:
            print("提示: 若无需风景景点可加 --skip-scenic；若路径不对请修改 build_scenic_spots_csv.py 中默认路径。")
            # 不退出，继续用仅红点

    # 2. 数据处理 + 建 POI 库
    if not run([sys.executable, "src/main.py"], "2. 数据处理 + 建 POI 空间数据库"):
        sys.exit(1)

    # 3. 空间剪枝（可选）
    if not args.skip_pruning:
        run([sys.executable, "src/spatial_pruning.py", "--n-clusters", "20"], "3. 空间剪枝（K-Means 聚类，cluster_id 写回 DB）")
    else:
        print("\n[跳过] 3. 空间剪枝（--skip-pruning）")

    # 4. 成本矩阵
    build_cmd = [sys.executable, "src/build_cost_matrices.py", "--type", "combined"]
    if args.cluster_ids and not args.skip_pruning:
        build_cmd += ["--cluster-ids", args.cluster_ids]
    if args.top_red is not None:
        build_cmd += ["--top-red", str(args.top_red)]
    if args.top_attraction is not None:
        build_cmd += ["--top-attraction", str(args.top_attraction)]
    if not run(build_cmd, "4. 构建成本矩阵（红点+风景景点，或按簇）"):
        # 若 combined 失败（如无 attraction），退化为仅红点
        print("尝试仅红色景点建矩阵...")
        run([sys.executable, "src/build_cost_matrices.py", "--type", "red_spot", "--top", "500"], "4. 构建成本矩阵（仅红点）")

    # 5. 三画像 ACO 对比
    if not run([sys.executable, "run_profile_comparison.py"], "5. 三画像 ACO 对比 + 导出地图"):
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  全部流程完成。地图见 data/processed/red_spots_map_family.html 等。")
    print("=" * 60)


if __name__ == "__main__":
    main()
