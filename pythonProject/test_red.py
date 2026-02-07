"""
红色景点识别 — 启动脚本：运行识别并打印/查看结果。

用法（在项目根目录下）：
  python test_red.py

若已配置 Excel 路径且文件存在：从 Excel 加载景点 -> 预处理 -> 红色识别 -> 保存并打印统计与示例。
若 Excel 不存在：从 data/processed/red_spots.csv 读取已有结果并打印统计与示例。
"""
import sys
import os

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

import pandas as pd
from data_preprocessing import DataPreprocessor
from red_spot_identifier import RedSpotIdentifier


def run_from_excel():
    """从 Excel 跑完整流程并输出结果。"""
    file_path = r'D:\Users\Lenovo\Desktop\广州城市数据\2025.06.11-广州POI带BIZ信息采集交付\广州市.csv-风景名胜-带评分.xlsx'
    if not os.path.isfile(file_path):
        return None
    preprocessor = DataPreprocessor()
    spots_df = preprocessor.load_excel_data(file_path)
    if spots_df.empty:
        return None
    processed = preprocessor.preprocess_spots(spots_df)
    known_path = os.path.join(PROJECT_ROOT, 'data', 'known_red_names.txt')
    official_path = os.path.join(PROJECT_ROOT, 'data', 'official_red_list_guangdong.txt')
    red_identifier = RedSpotIdentifier(
        known_red_path=known_path if os.path.isfile(known_path) else None,
        official_list_path=official_path if os.path.isfile(official_path) else None,
    )
    red_df = red_identifier.identify_red_spots(processed)
    out_path = os.path.join(PROJECT_ROOT, 'data', 'processed', 'red_spots.csv')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    red_df.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"已保存: {out_path}")
    return red_df


def run_from_csv():
    """从已有 red_spots.csv 读取并返回。"""
    path = os.path.join(PROJECT_ROOT, 'data', 'processed', 'red_spots.csv')
    if not os.path.isfile(path):
        return None
    return pd.read_csv(path, encoding='utf-8-sig')


def print_results(df: pd.DataFrame):
    """打印统计与示例。"""
    if df is None or df.empty:
        print("无数据可展示。")
        return
    print("\n" + "=" * 50)
    print("红色景点识别 — 运行结果")
    print("=" * 50)
    if 'red_level' not in df.columns:
        print("表中无 red_level 列，请先运行识别流程。")
        return
    dist = df['red_level'].value_counts()
    print("\n【等级分布】")
    for level, count in dist.items():
        print(f"  {level}: {count} 个")
    red_count = len(df[df['red_level'] != 'non_red'])
    print(f"\n红色景点合计: {red_count} 个")

    core = df[df['red_level'] == 'core_red']
    if not core.empty:
        print("\n【核心红色景点示例】(前 10 个)")
        for i, (_, row) in enumerate(core.head(10).iterrows()):
            name = row.get('name', '')
            themes = row.get('red_themes', '')
            print(f"  {i+1}. {name}  主题: {themes}")

    important = df[df['red_level'] == 'important_red']
    if not important.empty:
        print("\n【重要红色景点示例】(前 5 个)")
        for i, (_, row) in enumerate(important.head(5).iterrows()):
            print(f"  {i+1}. {row.get('name', '')}")


def main():
    print("=== 红色景点识别 · 启动脚本 ===\n")
    df = run_from_excel()
    if df is None:
        print("未找到 Excel 或加载失败，改为读取已有 red_spots.csv ...")
        df = run_from_csv()
    print_results(df)


if __name__ == "__main__":
    main()
