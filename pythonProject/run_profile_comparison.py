"""
三画像对比实验：同一份广州数据，输入家庭/研学/普通三种画像，导出三张 HTML 地图并对比评估。

用法: 在项目根目录运行  python run_profile_comparison.py
输出: data/processed/red_spots_map_family.html, red_spots_map_study.html, red_spots_map_normal.html
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from aco_optimizer import ACOOptimizer


def main():
    data_dir = os.path.join(PROJECT_ROOT, 'data', 'processed')
    out_dir = data_dir
    os.makedirs(out_dir, exist_ok=True)

    # 检查成本矩阵是否已生成（ACO 依赖 .npy 与 poi_ids.txt）
    # 支持 cost_matrix_combined（红点+风景景点）或 cost_matrix_red_spot
    import glob
    candidates = (
        glob.glob(os.path.join(data_dir, 'cost_matrix_combined*_distance.npy')) +
        glob.glob(os.path.join(data_dir, 'cost_matrix_red_spot*_distance.npy'))
    )
    if not candidates:
        print("未找到成本矩阵文件，请先构建：")
        print("  python src/build_cost_matrices.py --type combined --top-red 200 --top-attraction 300  # 红点+风景景点")
        print("  python src/build_cost_matrices.py --type red_spot --top 500  # 仅红色景点")
        sys.exit(1)
    # 取第一个匹配（若有多个，优先无 top 的，否则按文件名排序取一）
    first = sorted(candidates)[0]
    prefix_basename = os.path.basename(first).replace('_distance.npy', '')
    matrix_prefix_full = os.path.join(data_dir, prefix_basename)
    required = [f'{matrix_prefix_full}_distance.npy', f'{matrix_prefix_full}_time.npy', f'{matrix_prefix_full}_fee.npy', f'{matrix_prefix_full}_poi_ids.txt']
    missing = [p for p in required if not os.path.isfile(p)]
    if missing:
        print(f"成本矩阵不完整，缺失: {[os.path.basename(p) for p in missing]}")
        sys.exit(1)
    print(f"使用成本矩阵: {prefix_basename}")

    results = {}
    for profile in ['family', 'study', 'normal']:
        print(f"\n{'='*50}")
        print(f"画像: {profile}")
        print('='*50)
        opt = ACOOptimizer(
            matrix_prefix=prefix_basename,
            profile=profile,
            n_ants=5,
            n_iterations=12,
        )
        res = opt.run()
        results[profile] = res
        html_path = os.path.join(out_dir, f'red_spots_map_{profile}.html')
        try:
            from plot_red_spots_map import plot_map_with_route
            plot_map_with_route(route_ids=res['path_ids'], out_path=html_path)
            print(f"已导出地图: {html_path}")
        except Exception as e:
            print(f"导出地图失败 ({profile}): {e}")

    print("\n" + "="*50)
    print("三画像对比（评估指标）")
    print("="*50)
    print(f"{'画像':<10} {'总时间(h)':<12} {'总成本(元)':<12} {'满意度':<10} {'紧凑度':<10} {'节奏感(std)':<12} {'红绿匹配度':<12} {'实际红占比':<12}")
    print("-"*90)
    for profile in ['family', 'study', 'normal']:
        r = results[profile]
        ev = r.get('evaluation', {})
        compact = ev.get('compactness')
        compact_str = f"{compact:.2f}" if compact is not None else "—"
        print(f"{profile:<10} {r['total_time_h']:<12.2f} {r['total_cost_yuan']:<12.1f} {r['total_satisfaction']:<10.2f} {compact_str:<10} {ev.get('rhythm_std', 0):<12.3f} {ev.get('red_match', 0):<12.3f} {ev.get('actual_red_ratio', 0):<12.2%}")
    print("\n三张地图已保存至 data/processed/，用浏览器打开 red_spots_map_family.html / red_spots_map_study.html / red_spots_map_normal.html 查看。")

    # 保存对比结果供论文插图与每日行程表使用（plot_paper_figures.py / view_profile_results.py 会读取）
    import json
    out_json = os.path.join(out_dir, 'profile_comparison_results.json')
    serializable = {}
    for p, r in results.items():
        daily_ids = r.get('daily_path_ids', [])
        daily_names = r.get('daily_path_names', [])
        daily_time = r.get('daily_time_h', [])
        daily_cost = r.get('daily_cost_yuan', [])
        num_days = max(len(daily_ids), len(daily_names)) or max(r.get('n_days', 1), 1)
        daily_itinerary = []
        for d in range(num_days):
            if d < len(daily_ids) and d < len(daily_names):
                daily_itinerary.append({
                    'day': d + 1,
                    'path_ids': daily_ids[d],
                    'path_names': daily_names[d],
                    'time_h': daily_time[d] if d < len(daily_time) else 0,
                    'cost_yuan': daily_cost[d] if d < len(daily_cost) else 0,
                })
            else:
                # 兼容：无每日切分时按整天展示整条路径
                daily_itinerary.append({
                    'day': d + 1,
                    'path_ids': r.get('path_ids', []) if d == 0 else [],
                    'path_names': r.get('path_names', []) if d == 0 else [],
                    'time_h': r.get('total_time_h', 0) if d == 0 else 0,
                    'cost_yuan': r.get('total_cost_yuan', 0) if d == 0 else 0,
                })
        serializable[p] = {
            'total_time_h': r['total_time_h'],
            'total_cost_yuan': r['total_cost_yuan'],
            'total_satisfaction': r['total_satisfaction'],
            'n_days': r.get('n_days', 0),
            'path_length': len(r.get('path_ids', [])),
            'path_ids': r.get('path_ids', []),
            'path_names': r.get('path_names', []),
            'daily_itinerary': daily_itinerary,
            'evaluation': r.get('evaluation', {}),
        }
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"对比结果已保存: {out_json}")


if __name__ == '__main__':
    main()
