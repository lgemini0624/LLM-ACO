"""
POI 空间数据库：从处理后的 CSV 构建统一 POI 表，支持按类型/区域查询。
"""
import os
import sqlite3
import pandas as pd


def _project_data_dir():
    _src = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(_src), 'data', 'processed')


class POIDatabase:
    """POI 空间数据库（SQLite），统一存储景点、住宿、交通等 POI。"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            _dir = _project_data_dir()
            db_path = os.path.join(_dir, 'poi_spatial.db')
        self.db_path = db_path

    def build(self, data_dir: str = None):
        """从 data/processed 下的 CSV 构建/重建数据库。"""
        if data_dir is None:
            data_dir = _project_data_dir()
        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS poi (
                id TEXT PRIMARY KEY,
                name TEXT,
                poi_type TEXT,
                subtype TEXT,
                longitude REAL,
                latitude REAL,
                rating REAL,
                address TEXT,
                adname TEXT,
                cluster_id INTEGER
            )
        """)
        conn.execute("DELETE FROM poi")
        # 若表已存在但无 cluster_id（旧库），补列
        try:
            cur = conn.execute("PRAGMA table_info(poi)")
            cols = [row[1] for row in cur.fetchall()]
            if 'cluster_id' not in cols:
                conn.execute("ALTER TABLE poi ADD COLUMN cluster_id INTEGER")
        except Exception:
            pass

        # 红色景点
        path_red = os.path.join(data_dir, 'red_spots.csv')
        if os.path.isfile(path_red):
            df = pd.read_csv(path_red, encoding='utf-8-sig')
            for _, r in df.iterrows():
                if pd.notna(r.get('longitude')) and pd.notna(r.get('latitude')):
                    conn.execute(
                        "INSERT OR REPLACE INTO poi (id, name, poi_type, subtype, longitude, latitude, rating, address, adname, cluster_id) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                        (
                            str(r.get('id', '')),
                            str(r.get('name', '')),
                            'red_spot',
                            str(r.get('red_level', '')),
                            float(r['longitude']),
                            float(r['latitude']),
                            float(r['rating']) if pd.notna(r.get('rating')) else None,
                            str(r.get('address', '')),
                            str(r.get('adname', '')),
                        )
                    )
            print(f"  已导入红色景点: {len(df)} 条")

        # 风景/普通景点（来自 scenic_spots.csv，由 build_scenic_spots_csv.py 从「广州市-风景名胜-带评分」Excel 生成）
        path_scenic = os.path.join(data_dir, 'scenic_spots.csv')
        if os.path.isfile(path_scenic):
            df = pd.read_csv(path_scenic, encoding='utf-8-sig')
            n = 0
            for _, r in df.iterrows():
                if pd.notna(r.get('longitude')) and pd.notna(r.get('latitude')):
                    conn.execute(
                        "INSERT OR REPLACE INTO poi (id, name, poi_type, subtype, longitude, latitude, rating, address, adname, cluster_id) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                        (
                            str(r.get('id', '')),
                            str(r.get('name', '')),
                            'attraction',
                            str(r.get('subtype', '')),
                            float(r['longitude']),
                            float(r['latitude']),
                            float(r['rating']) if pd.notna(r.get('rating')) else None,
                            str(r.get('address', '')),
                            str(r.get('adname', '')),
                        )
                    )
                    n += 1
            print(f"  已导入风景景点(attraction): {n} 条")

        # 住宿（subtype 存 smallType 如四星级宾馆，便于 ACO 按星级定价：五星500/四星400/三星300/其他200）
        path_acc = os.path.join(data_dir, 'processed_accommodations.csv')
        if os.path.isfile(path_acc):
            df = pd.read_csv(path_acc, encoding='utf-8-sig')
            n = 0
            for _, r in df.iterrows():
                if pd.notna(r.get('longitude')) and pd.notna(r.get('latitude')):
                    sub = str(r.get('smallType', r.get('acc_type', '')))
                    conn.execute(
                        "INSERT OR REPLACE INTO poi (id, name, poi_type, subtype, longitude, latitude, rating, address, adname, cluster_id) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                        (
                            str(r.get('id', '')),
                            str(r.get('name', '')),
                            'accommodation',
                            sub,
                            float(r['longitude']),
                            float(r['latitude']),
                            None,
                            str(r.get('address', '')),
                            str(r.get('adname', '')),
                        )
                    )
                    n += 1
            print(f"  已导入住宿: {n} 条")

        # 交通
        path_trans = os.path.join(data_dir, 'processed_transportation.csv')
        if os.path.isfile(path_trans):
            df = pd.read_csv(path_trans, encoding='utf-8-sig')
            n = 0
            for _, r in df.iterrows():
                if pd.notna(r.get('longitude')) and pd.notna(r.get('latitude')):
                    conn.execute(
                        "INSERT OR REPLACE INTO poi (id, name, poi_type, subtype, longitude, latitude, rating, address, adname, cluster_id) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                        (
                            str(r.get('id', '')),
                            str(r.get('name', '')),
                            'transportation',
                            str(r.get('trans_type', '')),
                            float(r['longitude']),
                            float(r['latitude']),
                            None,
                            str(r.get('address', '')),
                            str(r.get('adname', '')),
                        )
                    )
                    n += 1
            print(f"  已导入交通: {n} 条")

        conn.commit()
        conn.close()
        print(f"POI 空间数据库已构建: {self.db_path}")

    def get_poi_dataframe(self, poi_type: str = None, poi_ids: list = None, cluster_ids: list = None) -> pd.DataFrame:
        """返回 POI 表 DataFrame，可选按类型、id 列表或空间剪枝簇过滤。cluster_ids 与空间剪枝（K-Means）配合使用。"""
        conn = sqlite3.connect(self.db_path)
        sql, params = "SELECT * FROM poi", []
        conditions = []
        if poi_type:
            conditions.append("poi_type = ?")
            params.append(poi_type)
        if poi_ids is not None and len(poi_ids) > 0:
            placeholders = ','.join('?' * len(poi_ids))
            conditions.append(f"id IN ({placeholders})")
            params.extend(poi_ids)
        if cluster_ids is not None and len(cluster_ids) > 0:
            ph = ','.join('?' * len(cluster_ids))
            conditions.append(f"cluster_id IN ({ph})")
            params.extend(cluster_ids)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        df = pd.read_sql(sql, conn, params=tuple(params) if params else None)
        conn.close()
        return df

    def get_poi_by_type(self, poi_type: str) -> pd.DataFrame:
        """按类型查询：red_spot / attraction / accommodation / transportation。"""
        return self.get_poi_dataframe(poi_type=poi_type)

    def get_red_and_attraction_dataframe(
        self,
        top_red: int = None,
        top_attraction: int = None,
        cluster_ids: list = None,
    ) -> pd.DataFrame:
        """返回红色景点 + 风景景点的合并 DataFrame，用于 combined 成本矩阵。支持空间剪枝：仅取 cluster_ids 内的 POI。"""
        conn = sqlite3.connect(self.db_path)
        if cluster_ids is not None and len(cluster_ids) > 0:
            ph = ','.join('?' * len(cluster_ids))
            df_red = pd.read_sql(
                f"SELECT * FROM poi WHERE poi_type = 'red_spot' AND cluster_id IN ({ph}) ORDER BY id",
                conn,
                params=tuple(cluster_ids),
            )
            df_att = pd.read_sql(
                f"SELECT * FROM poi WHERE poi_type = 'attraction' AND cluster_id IN ({ph}) ORDER BY id",
                conn,
                params=tuple(cluster_ids),
            )
        else:
            df_red = pd.read_sql("SELECT * FROM poi WHERE poi_type = 'red_spot' ORDER BY id", conn)
            df_att = pd.read_sql("SELECT * FROM poi WHERE poi_type = 'attraction' ORDER BY id", conn)
        conn.close()
        df_red = df_red.dropna(subset=['longitude', 'latitude'])
        df_att = df_att.dropna(subset=['longitude', 'latitude'])
        if top_red is not None and len(df_red) > top_red:
            df_red = df_red.head(top_red)
        if top_attraction is not None and len(df_att) > top_attraction:
            df_att = df_att.head(top_attraction)
        if df_red.empty and df_att.empty:
            return pd.DataFrame()
        if df_red.empty:
            return df_att
        if df_att.empty:
            return df_red
        return pd.concat([df_red, df_att], ignore_index=True)

    def get_poi_by_ids(self, poi_ids: list) -> pd.DataFrame:
        """按 id 列表查询，保持与 poi_ids 一致顺序（若需）。"""
        return self.get_poi_dataframe(poi_ids=poi_ids)

    def get_cluster_ids_by_place_name(self, place_name: str) -> list:
        """根据地名（区县/行政区）查询包含该区域的 cluster_id 列表，供智能控制器选簇使用。"""
        if not place_name or not str(place_name).strip():
            return []
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "SELECT DISTINCT cluster_id FROM poi WHERE adname LIKE ? AND cluster_id IS NOT NULL ORDER BY cluster_id",
            (f"%{str(place_name).strip()}%",),
        )
        rows = cur.fetchall()
        conn.close()
        return [int(r[0]) for r in rows if r[0] is not None]


def build_poi_database(db_path: str = None, data_dir: str = None) -> POIDatabase:
    """构建 POI 空间数据库并返回句柄。"""
    db = POIDatabase(db_path)
    db.build(data_dir)
    return db
