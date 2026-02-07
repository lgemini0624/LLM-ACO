import pandas as pd
import numpy as np
import os


class DataPreprocessor:
    def __init__(self):
        self.red_keywords = self._load_red_keywords()

    def _load_red_keywords(self):
        """加载红色旅游关键词"""
        return {
            'core_red': ['革命', '烈士', '纪念馆', '红色', '党史', '抗战', '爱国', '军事'],
            'historical': ['旧址', '遗址', '故居', '陵园', '纪念园', '博物馆'],
            'education': ['教育基地', '爱国主义', '党史学习', '红色教育']
        }

    def load_excel_data(self, file_path: str) -> pd.DataFrame:
        """加载Excel数据文件"""
        try:
            print(f"正在加载文件: {file_path}")
            df = pd.read_excel(file_path)
            print(f"数据加载成功，形状: {df.shape}")
            print(f"列名: {df.columns.tolist()}")
            return df
        except Exception as e:
            print(f"加载文件失败: {e}")
            return pd.DataFrame()

    def preprocess_spots(self, df: pd.DataFrame) -> pd.DataFrame:
        """预处理景点数据"""
        if df.empty:
            return df

        print("开始预处理景点数据...")
        processed_df = df.copy()

        # 1. 坐标标准化
        processed_df = self._standardize_coordinates(processed_df, '风景名胜')

        # 2. 文本字段清理
        processed_df = self._clean_text_fields(processed_df)

        # 3. 评分处理
        processed_df = self._parse_rating(processed_df)

        # 4. 类型字段合并
        processed_df = self._merge_type_fields(processed_df)

        # 5. 处理缺失值
        processed_df = self._handle_missing_values(processed_df)

        print(f"景点数据预处理完成，最终形状: {processed_df.shape}")
        return processed_df

    def preprocess_accommodations(self, df: pd.DataFrame) -> pd.DataFrame:
        """预处理住宿数据"""
        if df.empty:
            return df

        print("开始预处理住宿数据...")
        processed_df = df.copy()

        # 坐标标准化
        processed_df = self._standardize_coordinates(processed_df, '住宿服务')

        # 文本字段清理
        processed_df = self._clean_text_fields(processed_df)

        # 住宿类型分类
        processed_df['acc_type'] = processed_df.apply(
            self._classify_accommodation, axis=1
        )

        # 处理缺失值
        processed_df = self._handle_missing_values(processed_df)

        print(f"住宿数据预处理完成，最终形状: {processed_df.shape}")
        return processed_df

    def preprocess_transportation(self, df: pd.DataFrame) -> pd.DataFrame:
        """预处理交通设施数据"""
        if df.empty:
            return df

        print("开始预处理交通数据...")
        processed_df = df.copy()

        # 坐标标准化
        processed_df = self._standardize_coordinates(processed_df, '交通设施')

        # 文本字段清理
        processed_df = self._clean_text_fields(processed_df)

        # 交通类型标准化
        processed_df['trans_type'] = processed_df.apply(
            self._standardize_transport_type, axis=1
        )

        # 处理缺失值
        processed_df = self._handle_missing_values(processed_df)

        print(f"交通数据预处理完成，最终形状: {processed_df.shape}")
        return processed_df

    def _standardize_coordinates(self, df: pd.DataFrame, data_type: str) -> pd.DataFrame:
        """坐标标准化"""
        df = df.copy()

        # 优先使用wgs84坐标，如果没有则使用gcj坐标
        if 'wgs84Lng' in df.columns and 'wgs84Lat' in df.columns:
            df['longitude'] = pd.to_numeric(df['wgs84Lng'], errors='coerce')
            df['latitude'] = pd.to_numeric(df['wgs84Lat'], errors='coerce')
            print(f"使用WGS84坐标系统")
        elif 'gcjLng' in df.columns and 'gcjLat' in df.columns:
            df['longitude'] = pd.to_numeric(df['gcjLng'], errors='coerce')
            df['latitude'] = pd.to_numeric(df['gcjLat'], errors='coerce')
            print(f"使用GCJ坐标系统")
        else:
            print(f"警告: {data_type}数据中未找到坐标列")
            df['longitude'] = np.nan
            df['latitude'] = np.nan

        return df

    def _clean_text_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """文本字段清理"""
        df = df.copy()

        text_columns = ['name', 'address', 'bigType', 'midType', 'smallType']

        for col in text_columns:
            if col in df.columns:
                # 填充空值并去除前后空格
                df[col] = df[col].fillna('').astype(str).str.strip()

        return df

    def _parse_rating(self, df: pd.DataFrame) -> pd.DataFrame:
        """解析评分数据"""
        if '评分' not in df.columns:
            print("未找到评分列")
            df['rating'] = np.nan
            return df

        df = df.copy()

        def parse_single_rating(rating_val):
            try:
                if (pd.isna(rating_val) or rating_val == '[]' or
                        rating_val == '' or rating_val == 'None'):
                    return np.nan
                # 尝试直接转换为数值
                return float(rating_val)
            except:
                return np.nan

        df['rating'] = df['评分'].apply(parse_single_rating)
        valid_ratings = df['rating'].notna().sum()
        print(f"评分解析完成，有效评分数量: {valid_ratings}/{len(df)}")

        return df

    def _merge_type_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """合并类型字段"""
        df = df.copy()

        type_cols = ['bigType', 'midType', 'smallType']
        available_cols = [col for col in type_cols if col in df.columns]

        if available_cols:
            # 合并所有可用的类型字段
            df['full_type'] = df[available_cols].fillna('').astype(str).agg('_'.join, axis=1)
            print(f"类型字段合并完成")
        else:
            df['full_type'] = ''
            print("未找到类型字段")

        return df

    def _classify_accommodation(self, row) -> str:
        """分类住宿类型"""
        name = str(row.get('name', '')).lower()
        full_type = str(row.get('full_type', '')).lower()

        if any(word in name + full_type for word in ['酒店', '宾馆', '饭店']):
            return 'hotel'
        elif any(word in name + full_type for word in ['民宿', '公寓', '客栈']):
            return 'homestay'
        elif any(word in name + full_type for word in ['招待所', '旅馆']):
            return 'hostel'
        else:
            return 'other'

    def _standardize_transport_type(self, row) -> str:
        """标准化交通类型"""
        name = str(row.get('name', '')).lower()
        full_type = str(row.get('full_type', '')).lower()

        if any(word in name + full_type for word in ['地铁', 'metro']):
            return 'subway'
        elif any(word in name + full_type for word in ['公交', '巴士', '车站']):
            return 'bus'
        elif any(word in name + full_type for word in ['停车场', '停车']):
            return 'parking'
        elif any(word in name + full_type for word in ['客运', '长途']):
            return 'coach'
        else:
            return 'other'

    def _handle_missing_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """处理缺失值"""
        df = df.copy()

        # 删除所有坐标都为NaN的行
        if 'longitude' in df.columns and 'latitude' in df.columns:
            initial_count = len(df)
            df = df.dropna(subset=['longitude', 'latitude'], how='all')
            final_count = len(df)
            removed_count = initial_count - final_count
            if removed_count > 0:
                print(f"删除坐标缺失行: {removed_count} 行")

        return df

    def save_processed_data(self, df: pd.DataFrame, filename: str):
        """保存处理后的数据（路径基于项目根目录，与运行目录无关）"""
        _src_dir = os.path.dirname(os.path.abspath(__file__))
        _project_root = os.path.dirname(_src_dir)
        output_dir = os.path.join(_project_root, 'data', 'processed')
        os.makedirs(output_dir, exist_ok=True)

        output_path = os.path.join(output_dir, filename)
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"数据已保存至: {output_path}")