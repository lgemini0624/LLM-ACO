"""
论文用图统一生成：AHP 权重、空间剪枝簇规模、三画像对比、技术路线图等。

在项目根目录运行:  python plot_paper_figures.py
输出目录: outputs/figures/ （与 data_analysis / plot_red_spots_map 一致）
"""
import os
import sys
import json

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'outputs', 'figures')
DATA_PROCESSED = os.path.join(PROJECT_ROOT, 'data', 'processed')
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

os.makedirs(OUTPUT_DIR, exist_ok=True)

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# 论文风格：白底、中文、高 dpi
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['savefig.bbox'] = 'tight'


def fig_ahp_weights():
    """图：AHP 三目标权重（时间/成本/满意度）在家庭、研学、普通三种画像下的对比。"""
    try:
        from ahp_weights import get_ahp_weights
    except Exception:
        print("跳过 AHP 权重图：未找到 ahp_weights 或 权重.xlsx")
        return
    profiles = ['family', 'study', 'normal']
    labels_cn = {'family': '家庭游客', 'study': '研学游客', 'normal': '普通游客'}
    objectives = ['w_time', 'w_cost', 'w_satisfaction']
    obj_cn = {'w_time': '时间权重', 'w_cost': '成本权重', 'w_satisfaction': '满意度权重'}
    data = {}
    for p in profiles:
        w = get_ahp_weights(p)
        if not w:
            print("跳过 AHP 权重图：权重.xlsx 未找到或解析失败")
            return
        data[p] = [w.get(k, 0) for k in objectives]
    x = np.arange(len(objectives))
    width = 0.25
    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ['#E74C3C', '#3498DB', '#2ECC71']
    for i, p in enumerate(profiles):
        ax.bar(x + i * width, data[p], width, label=labels_cn[p], color=colors[i], edgecolor='white', linewidth=0.8)
    ax.set_ylabel('权重')
    ax.set_xticks(x + width)
    ax.set_xticklabels([obj_cn[k] for k in objectives])
    ax.legend(loc='upper right', frameon=True)
    ax.set_ylim(0, 1)
    ax.set_title('AHP 准则权重：三种游客画像对时间/成本/满意度的偏好')
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, 'fig_ahp_weights.png'))
    plt.close(fig)
    print("已生成: outputs/figures/fig_ahp_weights.png")


def fig_cluster_sizes():
    """图：空间剪枝后各簇 POI 数量（柱状图）。"""
    try:
        from spatial_pruning import get_cluster_summary
    except Exception:
        print("跳过簇规模图：未找到 spatial_pruning 或 DB 无 cluster_id")
        return
    db_path = os.path.join(DATA_PROCESSED, 'poi_spatial.db')
    if not os.path.isfile(db_path):
        print("跳过簇规模图：poi_spatial.db 不存在")
        return
    summary = get_cluster_summary(db_path)
    if summary.empty:
        print("跳过簇规模图：请先运行 python src/spatial_pruning.py --n-clusters 20")
        return
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(summary['cluster_id'].astype(str), summary['poi_count'], color='#9B59B6', edgecolor='white', linewidth=0.6)
    ax.set_xlabel('簇编号')
    ax.set_ylabel('POI 数量')
    ax.set_title('空间剪枝：K-Means 各簇 POI 数量（红点+风景景点）')
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, 'fig_cluster_sizes.png'))
    plt.close(fig)
    print("已生成: outputs/figures/fig_cluster_sizes.png")


def fig_profile_comparison():
    """图：三画像 ACO 对比（总时间、总成本、满意度、紧凑度、实际红占比）。"""
    path_json = os.path.join(DATA_PROCESSED, 'profile_comparison_results.json')
    if not os.path.isfile(path_json):
        print("跳过三画像对比图：请先运行 python run_profile_comparison.py 生成 profile_comparison_results.json")
        return
    with open(path_json, 'r', encoding='utf-8') as f:
        results = json.load(f)
    profiles = ['family', 'study', 'normal']
    labels_cn = {'family': '家庭', 'study': '研学', 'normal': '普通'}
    metrics = [
        ('total_time_h', '总时间 (h)', 'evaluation'),
        ('total_cost_yuan', '总成本 (元)', 'evaluation'),
        ('total_satisfaction', '满意度', 'evaluation'),
    ]
    ev_keys = ['compactness', 'actual_red_ratio']
    ev_cn = {'compactness': '紧凑度', 'actual_red_ratio': '实际红占比'}
    for k in ev_keys:
        metrics.append((k, ev_cn.get(k, k), 'evaluation'))
    # 归一化到 0-1 以便同图比较（或分子图）
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    colors = ['#E74C3C', '#3498DB', '#2ECC71']
    x = np.arange(len(profiles))
    width = 0.6
    # 总时间
    ax = axes[0, 0]
    vals = [results[p]['total_time_h'] for p in profiles]
    ax.bar(x, vals, width, color=colors, edgecolor='white', linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([labels_cn[p] for p in profiles])
    ax.set_ylabel('小时')
    ax.set_title('总游览时间')
    # 总成本
    ax = axes[0, 1]
    vals = [results[p]['total_cost_yuan'] for p in profiles]
    ax.bar(x, vals, width, color=colors, edgecolor='white', linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([labels_cn[p] for p in profiles])
    ax.set_ylabel('元')
    ax.set_title('总成本')
    # 满意度
    ax = axes[1, 0]
    vals = [results[p]['total_satisfaction'] for p in profiles]
    ax.bar(x, vals, width, color=colors, edgecolor='white', linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([labels_cn[p] for p in profiles])
    ax.set_ylabel('得分')
    ax.set_title('综合满意度')
    # 实际红占比
    ax = axes[1, 1]
    vals = [results[p].get('evaluation', {}).get('actual_red_ratio', 0) for p in profiles]
    if any(v != 0 for v in vals):
        ax.bar(x, vals, width, color=colors, edgecolor='white', linewidth=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels([labels_cn[p] for p in profiles])
        ax.set_ylabel('占比')
        ax.set_title('实际红色景点占比')
        ax.set_ylim(0, 1)
    else:
        ax.text(0.5, 0.5, '无红点数据', ha='center', va='center', transform=ax.transAxes)
        ax.set_title('实际红色景点占比')
    fig.suptitle('三画像 ACO 路线对比', fontsize=12, y=1.02)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, 'fig_profile_comparison.png'))
    plt.close(fig)
    print("已生成: outputs/figures/fig_profile_comparison.png")


def fig_framework():
    """图：技术路线/流程图（数据→POI 库→空间剪枝→成本矩阵→AHP→ACO→路线输出）。"""
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5)
    ax.axis('off')
    boxes = [
        (1, 2.5, '原始数据\n(景点/住宿/交通 Excel)'),
        (3, 2.5, 'POI 空间数据库\n(red_spot + attraction)'),
        (5, 2.5, '空间剪枝\n(K-Means 聚类)'),
        (7, 2.5, '成本矩阵\n(距离/时间/费用)'),
        (9, 2.5, 'AHP 权重\n(三画像偏好)'),
        (5, 1, '多目标 ACO\n(时间/成本/满意度)'),
        (5, 0.3, '三画像路线图\n(HTML 地图)'),
    ]
    for i, (x, y, text) in enumerate(boxes):
        bbox = FancyBboxPatch((x - 0.5, y - 0.3), 1, 0.6, boxstyle='round,pad=0.05',
                              facecolor='#ECF0F1', edgecolor='#2C3E50', linewidth=1.2)
        ax.add_patch(bbox)
        ax.text(x, y, text, ha='center', va='center', fontsize=8, wrap=True)
    # 箭头
    ax.annotate('', xy=(2.4, 2.5), xytext=(1.6, 2.5), arrowprops=dict(arrowstyle='->', color='#2C3E50', lw=1.5))
    ax.annotate('', xy=(4.4, 2.5), xytext=(3.6, 2.5), arrowprops=dict(arrowstyle='->', color='#2C3E50', lw=1.5))
    ax.annotate('', xy=(6.4, 2.5), xytext=(5.6, 2.5), arrowprops=dict(arrowstyle='->', color='#2C3E50', lw=1.5))
    ax.annotate('', xy=(8.4, 2.5), xytext=(7.6, 2.5), arrowprops=dict(arrowstyle='->', color='#2C3E50', lw=1.5))
    ax.annotate('', xy=(5, 1.35), xytext=(5, 2.15), arrowprops=dict(arrowstyle='->', color='#2C3E50', lw=1.5))
    ax.annotate('', xy=(5, 0.6), xytext=(5, 0.75), arrowprops=dict(arrowstyle='->', color='#2C3E50', lw=1.5))
    ax.set_title('广州红色旅游路线规划技术路线')
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, 'fig_framework.png'))
    plt.close(fig)
    print("已生成: outputs/figures/fig_framework.png")


def main():
    print("生成论文用图（输出目录: outputs/figures/）")
    fig_ahp_weights()
    fig_cluster_sizes()
    fig_profile_comparison()
    fig_framework()
    print("\n其他已有图（来自 data_analysis / plot_red_spots_map）：")
    print("  - red_spots_analysis.png  红色景点等级/行政区/评分/主题")
    print("  - spatial_distribution.png  红色景点空间分布散点")
    print("  - red_spots_by_district.png  行政区红色资源柱状")
    print("  - accommodation_types.png  住宿类型分布")
    print("  - transportation_types.png  交通类型分布")
    print("  - data/processed/red_spots_map_*.html  三画像路线交互地图")


if __name__ == '__main__':
    main()
