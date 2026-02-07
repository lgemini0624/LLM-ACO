"""
将 profile_comparison_results.json 转为可读 HTML 页面，用浏览器打开即可查看三画像对比结果。

用法:  python view_profile_results.py
输出:  data/processed/profile_comparison_results.html
"""
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(PROJECT_ROOT, 'data', 'processed', 'profile_comparison_results.json')
OUT_HTML = os.path.join(PROJECT_ROOT, 'data', 'processed', 'profile_comparison_results.html')


def main():
    if not os.path.isfile(JSON_PATH):
        print(f"未找到 {JSON_PATH}，请先运行: python run_profile_comparison.py")
        return
    with open(JSON_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    profile_cn = {'family': '家庭游客', 'study': '研学游客', 'normal': '普通游客'}
    rows = []
    for p, r in data.items():
        ev = r.get('evaluation', {})
        rows.append({
            '画像': profile_cn.get(p, p),
            '总时间(h)': round(r.get('total_time_h', 0), 2),
            '总成本(元)': round(r.get('total_cost_yuan', 0), 1),
            '满意度': round(r.get('total_satisfaction', 0), 2),
            '路线点数': r.get('path_length', 0),
            '估算天数': r.get('n_days', 0),
            '总距离(km)': round(ev.get('total_distance_km', 0), 2) if ev else '—',
            '紧凑度': round(ev['compactness'], 2) if ev.get('compactness') is not None and isinstance(ev.get('compactness'), (int, float)) else '—',
            '实际红占比': f"{ev.get('actual_red_ratio', 0):.1%}" if ev.get('actual_red_ratio') is not None else '—',
            '红绿匹配度': round(ev.get('red_match', 0), 2) if ev.get('red_match') is not None else '—',
        })
    table_rows = ''.join(
        f"<tr><td>{r['画像']}</td><td>{r['总时间(h)']}</td><td>{r['总成本(元)']}</td><td>{r['满意度']}</td>"
        f"<td>{r['路线点数']}</td><td>{r['估算天数']}</td><td>{r['总距离(km)']}</td><td>{r['紧凑度']}</td>"
        f"<td>{r['实际红占比']}</td><td>{r['红绿匹配度']}</td></tr>"
        for r in rows
    )

    # 每日行程表与行程景点（按画像分块）
    itinerary_sections = []
    for p, r in data.items():
        profile_label = profile_cn.get(p, p)
        daily_itinerary = r.get('daily_itinerary', [])
        if not daily_itinerary and r.get('path_names'):
            daily_itinerary = [{
                'day': 1,
                'path_names': r.get('path_names', []),
                'time_h': r.get('total_time_h', 0),
                'cost_yuan': r.get('total_cost_yuan', 0),
            }]
        day_rows = []
        for day_info in daily_itinerary:
            names = day_info.get('path_names', [])
            if not names:
                continue
            time_h = day_info.get('time_h', 0)
            cost_yuan = day_info.get('cost_yuan', 0)
            spots_str = ' → '.join(n for n in names)
            day_rows.append(
                f"<tr><td>第{day_info.get('day', 0)}天</td><td>{time_h}</td><td>{cost_yuan}</td>"
                f"<td class=\"spots\">{spots_str}</td></tr>"
            )
        if not day_rows:
            itinerary_sections.append(
                f"<div class=\"itinerary-block\"><h2>{profile_label} · 每日行程表</h2>"
                "<p class=\"no-data\">暂无每日行程数据，请重新运行 run_profile_comparison.py 生成。</p></div>"
            )
            continue
        day_table = ''.join(day_rows)
        itinerary_sections.append(
            f"<div class=\"itinerary-block\">"
            f"<h2>{profile_label} · 每日行程表与行程景点</h2>"
            f"<table class=\"day-table\"><thead><tr><th>日期</th><th>当日时间(h)</th><th>当日费用(元)</th><th>行程景点（按顺序）</th></tr></thead><tbody>{day_table}</tbody></table>"
            f"</div>"
        )
    itinerary_html = ''.join(itinerary_sections)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>三画像 ACO 对比结果</title>
  <style>
    body {{ font-family: "Microsoft YaHei", "SimHei", sans-serif; margin: 24px; background: #f5f5f5; }}
    h1 {{ color: #2c3e50; }}
    h2 {{ color: #34495e; font-size: 18px; margin-top: 28px; margin-bottom: 12px; }}
    .note {{ color: #7f8c8d; font-size: 14px; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; background: white; box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #ecf0f1; }}
    th {{ background: #3498db; color: white; font-weight: 600; }}
    tr:hover {{ background: #f8f9fa; }}
    .day-table th {{ background: #27ae60; }}
    td.spots {{ max-width: 480px; word-break: break-all; }}
    .itinerary-block {{ margin-bottom: 32px; }}
    .no-data {{ color: #95a5a6; }}
    .path {{ margin-top: 24px; }}
    .path a {{ color: #2980b9; }}
  </style>
</head>
<body>
  <h1>三画像 ACO 路线对比结果</h1>
  <p class="note">数据来源: profile_comparison_results.json（由 run_profile_comparison.py 生成）</p>
  <table>
    <thead>
      <tr>
        <th>画像</th>
        <th>总时间(h)</th>
        <th>总成本(元)</th>
        <th>满意度</th>
        <th>路线点数</th>
        <th>估算天数</th>
        <th>总距离(km)</th>
        <th>紧凑度</th>
        <th>实际红占比</th>
        <th>红绿匹配度</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
  <h2>每日行程表与行程景点</h2>
  {itinerary_html}
  <p class="path">路线地图: <a href="red_spots_map_family.html">家庭</a> | <a href="red_spots_map_study.html">研学</a> | <a href="red_spots_map_normal.html">普通</a></p>
</body>
</html>
"""
    os.makedirs(os.path.dirname(OUT_HTML) or '.', exist_ok=True)
    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"已生成: {OUT_HTML}")
    print("用浏览器打开该 HTML 即可查看三画像对比结果。")


if __name__ == '__main__':
    main()
