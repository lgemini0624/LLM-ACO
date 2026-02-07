"""
红色景点地图：点标注、行政区柱状图；可选由 ACO 传入路线绘制模拟路线。

依赖: pip install folium pandas matplotlib
用法:  python plot_red_spots_map.py
输出: data/processed/red_spots_map.html, outputs/figures/red_spots_by_district.png

对接 ACO：算出的最优顺序 path_ids 传入后画路线：
  from plot_red_spots_map import plot_map_with_route
  plot_map_with_route(route_ids=res['path_ids'])
"""
import os
import sys
import pandas as pd
from math import radians, sin, cos, sqrt, atan2

try:
    import folium
    from folium.plugins import PolyLineTextPath
except ImportError:
    print("请先安装 folium: pip install folium")
    raise

try:
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
    matplotlib.rcParams['axes.unicode_minus'] = False
except ImportError:
    plt = None

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PROCESSED = os.path.join(PROJECT_ROOT, 'data', 'processed')
CSV_PATH = os.path.join(DATA_PROCESSED, 'red_spots.csv')
SCENIC_CSV_PATH = os.path.join(DATA_PROCESSED, 'scenic_spots.csv')
OUT_PATH = os.path.join(DATA_PROCESSED, 'red_spots_map.html')
BAR_CHART_PATH = os.path.join(PROJECT_ROOT, 'outputs', 'figures', 'red_spots_by_district.png')
GUANGZHOU_CENTER = [23.13, 113.26]
# 路线段着色：行程越长体验度越低（绿=短/舒适，橙=中，红=长/差）
SEGMENT_KM_GREEN = 5.0   # < 5km 绿色
SEGMENT_KM_ORANGE = 15.0  # 5~15km 橙色，>15km 红色


def haversine_km(lat1, lon1, lat2, lon2):
    """两点 Haversine 距离（公里）。"""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def format_themes(themes):
    if pd.isna(themes):
        return "—"
    if isinstance(themes, str):
        return themes.replace("'", "").strip("[]")
    if isinstance(themes, list):
        return "、".join(str(t) for t in themes)
    return str(themes)


def plot_district_bar_chart(df_red):
    """用 df['adname'].value_counts() 生成行政区红色资源柱状图。"""
    if plt is None or df_red.empty or 'adname' not in df_red.columns:
        return
    counts = df_red['adname'].value_counts()
    if counts.empty:
        return
    os.makedirs(os.path.dirname(BAR_CHART_PATH) or '.', exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    counts.plot(kind='bar', ax=ax, color='coral', edgecolor='darkred')
    ax.set_title('各行政区红色景点数量（红色资源丰富度）')
    ax.set_xlabel('行政区')
    ax.set_ylabel('红色景点数量')
    ax.tick_params(axis='x', rotation=45)
    plt.tight_layout()
    plt.savefig(BAR_CHART_PATH, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"行政区柱状图已保存: {BAR_CHART_PATH}")


def parse_route_arg(route_arg):
    """解析 --route 参数：支持 'id1,id2,id3' 或 'id1 id2 id3'。"""
    if not route_arg:
        return []
    if isinstance(route_arg, str):
        return [x.strip() for x in route_arg.replace(',', ' ').split() if x.strip()]
    return list(route_arg)


def _load_id_to_row():
    """加载红点 + 风景景点，合并为 id -> row，供路线解析与标注。"""
    id_to_row = {}
    if os.path.isfile(CSV_PATH):
        df = pd.read_csv(CSV_PATH, encoding='utf-8-sig').dropna(subset=['longitude', 'latitude'])
        df['_type'] = 'red_spot'
        for pid in df['id'].astype(str):
            id_to_row[pid] = df[df['id'].astype(str) == pid].iloc[0]
    if os.path.isfile(SCENIC_CSV_PATH):
        df = pd.read_csv(SCENIC_CSV_PATH, encoding='utf-8-sig').dropna(subset=['longitude', 'latitude'])
        df['_type'] = 'attraction'
        for _, row in df.iterrows():
            pid = str(row.get('id', ''))
            if pid and pid not in id_to_row:
                id_to_row[pid] = row
    return id_to_row


def plot_map_with_route(route_ids=None, out_path=None):
    """
    生成地图：标明重要红色景点（核心/重要/一般）及其他风景景点；可选绘制路线，行程越长段着色越红（体验度越低）。
    :param route_ids: 景点 ID 列表（按顺序），如 aco 输出的 res['path_ids']
    :param out_path: 输出 HTML 路径
    :return: (总距离 km, 输出路径)
    """
    route_ids = parse_route_arg(route_ids or [])
    out_path = out_path or OUT_PATH
    if not os.path.isfile(CSV_PATH):
        print(f"未找到 {CSV_PATH}")
        return None, out_path

    df_red = pd.read_csv(CSV_PATH, encoding='utf-8-sig').dropna(subset=['longitude', 'latitude'])
    plot_district_bar_chart(df_red[df_red['red_level'] != 'non_red'] if 'red_level' in df_red.columns else df_red)
    m = folium.Map(location=GUANGZHOU_CENTER, zoom_start=11, tiles='OpenStreetMap')

    # 红色景点分层：核心红色、重要红色、一般红色
    for level, label, icon_color in [
        ('core_red', '核心红色景点', 'red'),
        ('important_red', '重要红色景点', 'orange'),
        ('general_red', '一般红色景点', 'lightred'),
    ]:
        df_sub = df_red[df_red['red_level'] == level] if 'red_level' in df_red.columns else pd.DataFrame()
        if df_sub.empty:
            continue
        fg = folium.FeatureGroup(name=label)
        for _, row in df_sub.iterrows():
            lat, lon = float(row['latitude']), float(row['longitude'])
            name = str(row.get('name', ''))
            themes = format_themes(row.get('red_themes'))
            popup_html = f"<b>{name}</b><br/>主题: {themes}"
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup_html, max_width=300),
                icon=folium.Icon(color=icon_color, icon='info-sign'),
            ).add_to(fg)
        fg.add_to(m)

    # 其他风景景点（非红色），最多 2000 点以免地图过慢
    if os.path.isfile(SCENIC_CSV_PATH):
        df_scenic = pd.read_csv(SCENIC_CSV_PATH, encoding='utf-8-sig').dropna(subset=['longitude', 'latitude'])
        if not df_scenic.empty:
            if len(df_scenic) > 2000:
                df_scenic = df_scenic.sample(n=2000, random_state=42)
            fg_att = folium.FeatureGroup(name='其他风景景点')
            for _, row in df_scenic.iterrows():
                lat, lon = float(row['latitude']), float(row['longitude'])
                name = str(row.get('name', ''))
                rating = row.get('rating', '')
                popup_html = f"<b>{name}</b><br/>评分: {rating}"
                folium.Marker(
                    location=[lat, lon],
                    popup=folium.Popup(popup_html, max_width=300),
                    icon=folium.Icon(color='blue', icon='leaf'),
                ).add_to(fg_att)
            fg_att.add_to(m)

    total_km = None
    id_to_row = _load_id_to_row()
    if route_ids and id_to_row:
        points = []
        for pid in route_ids:
            pid = str(pid).strip()
            if pid not in id_to_row:
                continue
            row = id_to_row[pid]
            points.append([float(row['latitude']), float(row['longitude'])])
        if len(points) >= 2:
            total_km = 0.0
            segments_km = []
            for i in range(len(points) - 1):
                d = haversine_km(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
                total_km += d
                segments_km.append(d)
            fg_route = folium.FeatureGroup(name=f'路线（总距离 {total_km:.2f} km，段色=行程体验：绿舒适/红差）')
            for i in range(len(points) - 1):
                d = segments_km[i]
                if d <= SEGMENT_KM_GREEN:
                    color = 'green'
                elif d <= SEGMENT_KM_ORANGE:
                    color = 'orange'
                else:
                    color = 'red'
                seg = folium.PolyLine(
                    locations=[points[i], points[i + 1]],
                    color=color,
                    weight=5,
                    popup=f"本段 {d:.2f} km（行程越长体验度越低）",
                )
                seg.add_to(fg_route)
            fg_route.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    m.save(out_path)
    return total_km, out_path


def main():
    if not os.path.isfile(CSV_PATH):
        print(f"未找到 {CSV_PATH}，请先运行红色景点识别生成 red_spots.csv。")
        return

    plot_map_with_route(out_path=OUT_PATH)
    print(f"已生成地图: {OUT_PATH}")
    print("用浏览器打开该 HTML 即可查看。")


if __name__ == '__main__':
    main()
