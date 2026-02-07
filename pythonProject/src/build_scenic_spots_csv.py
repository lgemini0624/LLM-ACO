"""
从「广州市-风景名胜-带评分」Excel 生成 data/processed/scenic_spots.csv，供 POI 数据库以 poi_type=attraction 导入。

用法（在项目根目录）:
  python src/build_scenic_spots_csv.py
  python src/build_scenic_spots_csv.py --input "D:/path/to/广州市.csv-风景名胜-带评分.xlsx"
  python src/build_scenic_spots_csv.py --out data/processed/scenic_spots.csv
"""
import os
import sys
import argparse
import pandas as pd

# 保证可导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _project_data_dir():
    _src = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(_src), 'data', 'processed')


# 默认 Excel 路径（广州城市数据交付目录）
DEFAULT_XLSX = r"D:\Users\Lenovo\Desktop\广州城市数据\2025.06.11-广州POI带BIZ信息采集交付\广州市.csv-风景名胜-带评分.xlsx"

# 列名映射：Excel 可能列名 -> 标准列名
COLUMN_ALIASES = {
    'id': ['id', 'ID', '编号', 'poi_id'],
    'name': ['name', '名称', '标题', 'title', 'poi_name'],
    'longitude': ['longitude', '经度', 'lng', 'lon', 'wgs84Lng', 'longitude_wgs84'],
    'latitude': ['latitude', '纬度', 'lat', 'wgs84Lat', 'latitude_wgs84'],
    'rating': ['rating', '评分', 'rating_score', '星级', '分数'],
    'address': ['address', '地址', 'addr', '详细地址'],
    'adname': ['adname', '区县', '行政区', '区域', 'district', 'adname_district'],
    'subtype': ['subtype', '类型', '分类', 'category', 'smallType', 'midType'],
}

# 仅做「精确/别名」匹配的列，避免误匹配（如 pname 被当成 name、省份 被当成 名称）
EXACT_ONLY_ALIASES = {'name', 'id'}


def _find_column(df, standard_name):
    """在 DataFrame 列名中查找与 standard_name 对应的列（不区分大小写、去除空格，支持中文列名）。
    对 name/id 只做精确或别名相等，避免把 pname/省份 当成 name。"""
    candidates = COLUMN_ALIASES.get(standard_name, [standard_name])
    exact_only = standard_name in EXACT_ONLY_ALIASES
    for c in df.columns:
        c2 = str(c).strip()
        for alias in candidates:
            a = str(alias).strip()
            if c2 == a or c2.lower() == a.lower():
                return c
            if not exact_only and (a in c2 or c2 in a):
                return c
    return None


def build_scenic_spots_csv(
    input_path: str,
    out_path: str,
    sheet_name: int = 0,
) -> int:
    """
    从 Excel 读取风景名胜表，规范列名并写出 scenic_spots.csv。
    返回写入行数。
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"未找到文件: {input_path}")
    df = pd.read_excel(input_path, sheet_name=sheet_name, header=0)
    # 规范列名
    name_col = _find_column(df, 'name')
    lng_col = _find_column(df, 'longitude')
    lat_col = _find_column(df, 'latitude')
    if not name_col or not lng_col or not lat_col:
        raise ValueError(
            f"Excel 中需包含 名称、经度、纬度 列。当前列: {list(df.columns)}。"
            "请检查表头或修改 src/build_scenic_spots_csv.py 中 COLUMN_ALIASES。"
        )
    rating_col = _find_column(df, 'rating')
    address_col = _find_column(df, 'address')
    adname_col = _find_column(df, 'adname')
    subtype_col = _find_column(df, 'subtype')
    id_col = _find_column(df, 'id')

    out_df = pd.DataFrame()
    out_df['name'] = df[name_col].astype(str)
    out_df['longitude'] = pd.to_numeric(df[lng_col], errors='coerce')
    out_df['latitude'] = pd.to_numeric(df[lat_col], errors='coerce')
    out_df['rating'] = pd.to_numeric(df[rating_col], errors='coerce') if rating_col else None
    out_df['address'] = df[address_col].astype(str) if address_col else ''
    out_df['adname'] = df[adname_col].astype(str) if adname_col else ''
    out_df['subtype'] = df[subtype_col].astype(str) if subtype_col else ''

    if id_col and id_col in df.columns:
        out_df['id'] = df[id_col].astype(str)
    else:
        # 生成 id：attraction_0, attraction_1, ...
        out_df['id'] = ['attraction_' + str(i) for i in range(len(out_df))]

    # 去掉经纬度缺失的行
    out_df = out_df.dropna(subset=['longitude', 'latitude'])
    out_df = out_df[out_df['longitude'].between(-180, 180) & out_df['latitude'].between(-90, 90)]
    if out_df.empty:
        raise ValueError("过滤后无有效经纬度数据，请检查 Excel 中经度、纬度列。")

    # 列顺序：id, name, longitude, latitude, rating, address, adname, subtype
    out_df = out_df[['id', 'name', 'longitude', 'latitude', 'rating', 'address', 'adname', 'subtype']]
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding='utf-8-sig')
    return len(out_df)


def main():
    parser = argparse.ArgumentParser(description='从风景名胜 Excel 生成 scenic_spots.csv')
    parser.add_argument('--input', '-i', default=DEFAULT_XLSX, help='输入 Excel 路径')
    parser.add_argument('--out', '-o', default=None, help='输出 CSV 路径，默认 data/processed/scenic_spots.csv')
    parser.add_argument('--sheet', type=int, default=0, help='Excel 工作表索引，默认 0')
    args = parser.parse_args()

    out_path = args.out
    if out_path is None:
        out_path = os.path.join(_project_data_dir(), 'scenic_spots.csv')

    try:
        n = build_scenic_spots_csv(args.input, out_path, sheet_name=args.sheet)
        print(f"已生成 {out_path}，共 {n} 条风景景点。")
        print("请运行 main.py 或 poi_database.build() 重新构建 POI 数据库以导入 attraction 类型。")
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    except ValueError as e:
        print(e)
        sys.exit(1)


if __name__ == '__main__':
    main()
