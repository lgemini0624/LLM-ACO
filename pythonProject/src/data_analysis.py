import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import os
from math import radians, sin, cos, sqrt, atan2

# 基于脚本位置的项目根目录，与运行目录无关
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
_OUTPUT_FIGURES = os.path.join(_PROJECT_ROOT, 'outputs', 'figures')
_DATA_PROCESSED = os.path.join(_PROJECT_ROOT, 'data', 'processed')


class DataAnalyzer:
    def __init__(self):
        plt.rcParams['font.sans-serif'] = ['SimHei']  # 支持中文显示
        plt.rcParams['axes.unicode_minus'] = False  # 正常显示负号

    def load_processed_data(self):
        """加载处理后的数据（路径基于项目根目录）"""
        red_spots = pd.read_csv(os.path.join(_DATA_PROCESSED, 'red_spots.csv'))
        accommodations = pd.read_csv(os.path.join(_DATA_PROCESSED, 'processed_accommodations.csv'))
        transportation = pd.read_csv(os.path.join(_DATA_PROCESSED, 'processed_transportation.csv'))

        return red_spots, accommodations, transportation

    def analyze_red_spots_distribution(self, red_spots):
        """分析红色景点分布"""
        print("\n=== 红色景点分布分析 ===")

        # 按行政区统计
        district_stats = red_spots[red_spots['red_level'] != 'non_red'].groupby('adname').agg({
            'name': 'count',
            'red_score': 'mean',
            'rating': 'mean'
        }).round(2).sort_values('name', ascending=False)

        print("各行政区红色景点数量:")
        print(district_stats.head(10))

        # 可视化
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))

        # 1. 红色等级分布
        red_level_counts = red_spots[red_spots['red_level'] != 'non_red']['red_level'].value_counts()
        axes[0, 0].pie(red_level_counts.values, labels=red_level_counts.index, autopct='%1.1f%%')
        axes[0, 0].set_title('红色景点等级分布')

        # 2. 行政区分布
        top_districts = district_stats.head(10)
        axes[0, 1].bar(range(len(top_districts)), top_districts['name'])
        axes[0, 1].set_xticks(range(len(top_districts)))
        axes[0, 1].set_xticklabels(top_districts.index, rotation=45)
        axes[0, 1].set_title('红色景点数量TOP10行政区')
        axes[0, 1].set_ylabel('数量')

        # 3. 评分分布
        rating_data = red_spots[red_spots['red_level'] != 'non_red']['rating'].dropna()
        axes[1, 0].hist(rating_data, bins=20, alpha=0.7, color='skyblue')
        axes[1, 0].set_title('红色景点评分分布')
        axes[1, 0].set_xlabel('评分')
        axes[1, 0].set_ylabel('频次')

        # 4. 主题分布
        all_themes = []
        for themes in red_spots[red_spots['red_level'] != 'non_red']['red_themes']:
            if isinstance(themes, str):
                theme_list = eval(themes) if '[' in themes else [themes]
                all_themes.extend(theme_list)

        theme_counts = pd.Series(all_themes).value_counts().head(10)
        axes[1, 1].bar(range(len(theme_counts)), theme_counts.values)
        axes[1, 1].set_xticks(range(len(theme_counts)))
        axes[1, 1].set_xticklabels(theme_counts.index, rotation=45)
        axes[1, 1].set_title('红色主题分布TOP10')
        axes[1, 1].set_ylabel('数量')

        plt.tight_layout()
        plt.savefig(os.path.join(_OUTPUT_FIGURES, 'red_spots_analysis.png'), dpi=300, bbox_inches='tight')
        plt.show()

        return district_stats

    def spatial_analysis(self, red_spots, accommodations, transportation):
        """空间分析"""
        print("\n=== 空间分析 ===")

        # 筛选核心红色景点
        core_red = red_spots[red_spots['red_level'] == 'core_red']

        # 计算中心点
        center_lng = core_red['longitude'].mean()
        center_lat = core_red['latitude'].mean()

        print(f"核心红色景点中心点: ({center_lng:.4f}, {center_lat:.4f})")

        # 计算景点间的距离
        def haversine_distance(lat1, lon1, lat2, lon2):
            """计算两个坐标点之间的距离（公里）"""
            R = 6371  # 地球半径，单位公里

            lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

            dlat = lat2 - lat1
            dlon = lon2 - lon1

            a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
            c = 2 * atan2(sqrt(a), sqrt(1 - a))

            return R * c

        # 计算核心景点到中心的平均距离
        distances = []
        for _, spot in core_red.iterrows():
            if not pd.isna(spot['longitude']) and not pd.isna(spot['latitude']):
                dist = haversine_distance(center_lat, center_lng,
                                          spot['latitude'], spot['longitude'])
                distances.append(dist)

        avg_distance = np.mean(distances)
        print(f"核心红色景点到中心的平均距离: {avg_distance:.2f} 公里")

        # 空间分布可视化
        plt.figure(figsize=(12, 10))

        # 绘制所有红色景点
        all_red = red_spots[red_spots['red_level'] != 'non_red']
        colors = {'core_red': 'red', 'important_red': 'orange', 'general_red': 'yellow'}

        for level, color in colors.items():
            level_spots = all_red[all_red['red_level'] == level]
            plt.scatter(level_spots['longitude'], level_spots['latitude'],
                        c=color, label=level, alpha=0.6, s=30)

        # 标记中心点
        plt.scatter(center_lng, center_lat, c='blue', marker='*', s=200, label='中心点')

        plt.xlabel('经度')
        plt.ylabel('纬度')
        plt.title('广州红色景点空间分布')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(os.path.join(_OUTPUT_FIGURES, 'spatial_distribution.png'), dpi=300, bbox_inches='tight')
        plt.show()

        return center_lng, center_lat, avg_distance

    def accommodation_analysis(self, accommodations):
        """住宿数据分析"""
        print("\n=== 住宿数据分析 ===")

        # 住宿类型统计
        acc_type_counts = accommodations['acc_type'].value_counts()
        print("住宿类型分布:")
        for acc_type, count in acc_type_counts.items():
            print(f"  {acc_type}: {count}个")

        # 可视化
        plt.figure(figsize=(10, 6))
        acc_type_counts.plot(kind='bar', color='lightblue')
        plt.title('住宿类型分布')
        plt.xlabel('住宿类型')
        plt.ylabel('数量')
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(os.path.join(_OUTPUT_FIGURES, 'accommodation_types.png'), dpi=300, bbox_inches='tight')
        plt.show()

    def transportation_analysis(self, transportation):
        """交通设施分析"""
        print("\n=== 交通设施分析 ===")

        # 交通类型统计
        trans_type_counts = transportation['trans_type'].value_counts()
        print("交通设施类型分布:")
        for trans_type, count in trans_type_counts.items():
            print(f"  {trans_type}: {count}个")

        # 可视化
        plt.figure(figsize=(10, 6))
        trans_type_counts.plot(kind='bar', color='lightgreen')
        plt.title('交通设施类型分布')
        plt.xlabel('交通类型')
        plt.ylabel('数量')
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(os.path.join(_OUTPUT_FIGURES, 'transportation_types.png'), dpi=300, bbox_inches='tight')
        plt.show()


def main():
    """数据分析主函数"""
    analyzer = DataAnalyzer()

    # 创建输出目录（基于项目根目录）
    os.makedirs(_OUTPUT_FIGURES, exist_ok=True)

    # 加载数据
    red_spots, accommodations, transportation = analyzer.load_processed_data()

    print("=== 开始数据分析 ===")

    # 红色景点分析
    district_stats = analyzer.analyze_red_spots_distribution(red_spots)

    # 空间分析
    center_lng, center_lat, avg_distance = analyzer.spatial_analysis(
        red_spots, accommodations, transportation
    )

    # 住宿分析
    analyzer.accommodation_analysis(accommodations)

    # 交通分析
    analyzer.transportation_analysis(transportation)

    print("\n=== 数据分析完成 ===")
    print(f"分析结果已保存至 outputs/figures/ 目录")


if __name__ == "__main__":
    main()