import sys
import os
import pandas as pd

# 添加src目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data_preprocessing import DataPreprocessor
from red_spot_identifier import RedSpotIdentifier


def main():
    print("=== 广州红色旅游数据分析项目 ===")

    # 初始化处理器（程序自动判断：是红色就排等级，不是则 non_red；可选加载已知名单与官方名录）
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _known_red_path = os.path.join(_project_root, 'data', 'known_red_names.txt')
    _official_list_path = os.path.join(_project_root, 'data', 'official_red_list_guangdong.txt')
    preprocessor = DataPreprocessor()
    red_identifier = RedSpotIdentifier(
        known_red_path=_known_red_path if os.path.isfile(_known_red_path) else None,
        official_list_path=_official_list_path if os.path.isfile(_official_list_path) else None,
    )

    # 定义所有文件路径（请根据本机实际路径修改；也可改为相对项目根目录）
    file_paths = {
        'spots': r'D:\Users\Lenovo\Desktop\广州城市数据\2025.06.11-广州POI带BIZ信息采集交付\广州市.csv-风景名胜-带评分.xlsx',
        'accommodations': r'D:\Users\Lenovo\Desktop\广州城市数据\2025.06.11-广州POI带BIZ信息采集交付\广州市.csv-住宿服务-带评分消费星级.xlsx',
        'transportation': r'D:\Users\Lenovo\Desktop\广州城市数据\2025.06.11-广州POI带BIZ信息采集交付\广州市_交通设施服务.xlsx'
    }

    # 1. 处理景点数据并识别红色景点
    print("\n1. 处理景点数据...")
    spots_df = preprocessor.load_excel_data(file_paths['spots'])
    if spots_df.empty:
        print("提示: 景点数据文件未找到或为空，请检查路径或将数据文件放到对应位置。")
    processed_spots = preprocessor.preprocess_spots(spots_df)

    # 识别红色景点
    print("\n2. 识别红色景点...")
    red_spots_df = red_identifier.identify_red_spots(processed_spots)
    preprocessor.save_processed_data(red_spots_df, 'red_spots.csv')

    # 2. 处理住宿数据
    print("\n3. 处理住宿数据...")
    acc_df = preprocessor.load_excel_data(file_paths['accommodations'])      # 加载住宿数据
    processed_acc = preprocessor.preprocess_accommodations(acc_df)           # 预处理住宿数据
    preprocessor.save_processed_data(processed_acc, 'processed_accommodations.csv')  # 保存住宿数据

    # 3. 处理交通数据
    print("\n4. 处理交通数据...")
    trans_df = preprocessor.load_excel_data(file_paths['transportation'])    # 加载交通数据
    processed_trans = preprocessor.preprocess_transportation(trans_df)       # 预处理交通数据
    preprocessor.save_processed_data(processed_trans, 'processed_transportation.csv')  # 保存交通数据

    print("\n=== 所有数据处理完成 ===")

    # 构建 POI 空间数据库（用于距离/时间/费用矩阵）
    print("\n5. 构建 POI 空间数据库...")
    try:
        from poi_database import build_poi_database
        build_poi_database()
    except Exception as e:
        print(f"构建 POI 数据库失败: {e}")

    # 显示统计信息
    print(f"景点数据: {len(processed_spots)} 条记录")
    red_count = len(red_spots_df[red_spots_df['red_level'] != 'non_red'])
    print(f"红色景点: {red_count} 条记录")
    print(f"住宿数据: {len(processed_acc)} 条记录")
    print(f"交通数据: {len(processed_trans)} 条记录")

    # 检查数据文件
    check_processed_data(red_spots_df)


def check_processed_data(red_spots_df):
    """检查处理后的数据"""
    try:
        print(f"\n=== 红色景点数据检查 ===")
        print(f"红色景点分布:")
        red_distribution = red_spots_df['red_level'].value_counts()  # 统计不同红色级别的数量
        for level, count in red_distribution.items():
            print(f"  {level}: {count}个")

        # 显示核心红色景点
        core_red = red_spots_df[red_spots_df['red_level'] == 'core_red']
        if not core_red.empty:
            print(f"\n核心红色景点示例:")
            for i, (idx, spot) in enumerate(core_red.head(5).iterrows()):
                print(f"  {i + 1}. {spot['name']} - 主题: {spot['red_themes']}")

        return True
    except Exception as e:
        print(f"检查数据文件失败: {e}")
        return False


if __name__ == "__main__":
    main()