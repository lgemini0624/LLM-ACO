"""
多目标蚁群优化器（ACO）：平衡总时间、总成本、综合满意度；支持红色目标占比与用户画像。

四阶段流程：
1. 初始化与参数注入：载入矩阵与画像（target_red_ratio、家庭/研学/普通）
2. 路径构造：蚂蚁按信息素 + 综合启发式（含比例弹性：红占比低于 target 时提升红色启发式）
3. 多目标约束：每日游览时间 6~8h（不足 6h 多排行程）；必选 core_red；画像语义（家庭 subtype 偏好、研学核心红最小停留）
4. 信息素更新：挥发 + 帕累托最优路径加强

评估：空间紧凑度（总里程/凸包面积）、旅游节奏感（游览时间标准差）、红绿匹配度（实际红占比 vs target）。
"""
import os
import sys
import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional, Any

# 项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from scipy.spatial import ConvexHull
except ImportError:
    ConvexHull = None


def _data_dir():
    _src = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(_src), 'data', 'processed')


class ACOOptimizer:
    def __init__(
        self,
        matrix_prefix: str = "cost_matrix_red_spot",
        data_dir: str = None,
        db_path: str = None,
        # 用户画像：三目标权重 W = (w_time, w_cost, w_satisfaction)，和为 1
        w_time: float = 0.4,
        w_cost: float = 0.3,
        w_satisfaction: float = 0.3,
        # 红色目标占比（0~1），比例弹性路径
        target_red_ratio: float = None,
        profile: str = 'normal',
        # 约束：每日游览时间 [min_hours_per_day, max_hours_per_day]，不足 6h 则多排行程直至 6~8h
        min_hours_per_day: float = 6.0,
        max_hours_per_day: float = 8.0,
        visit_hours_attraction: float = 1.0,
        visit_hours_accommodation: float = 0.0,
        accommodation_cost_per_night: float = 300.0,
        max_attractions_per_day: int = 5,
        max_km_nearby_cluster: float = 2.0,
        max_total_km: float = 200.0,
        # ACO 参数
        n_ants: int = 20,
        n_iterations: int = 50,
        alpha: float = 1.0,
        beta: float = 2.0,
        rho: float = 0.1,
        tau_init: float = 1.0,
        seed: Optional[int] = 42,
    ):
        self.data_dir = data_dir or _data_dir()
        self.db_path = db_path or os.path.join(self.data_dir, 'poi_spatial.db')
        self.matrix_prefix = matrix_prefix
        self.min_hours_per_day = min_hours_per_day
        self.max_hours_per_day = max_hours_per_day
        self.visit_hours_attraction = visit_hours_attraction
        self.visit_hours_accommodation = visit_hours_accommodation
        self.accommodation_cost_per_night = accommodation_cost_per_night
        self.max_attractions_per_day = max_attractions_per_day
        self.max_km_nearby_cluster = max_km_nearby_cluster
        self.max_total_km = max_total_km
        self.n_ants = n_ants
        self.n_iterations = n_iterations
        self.alpha = alpha
        self.beta = beta
        self.rho = rho
        self.tau_init = tau_init
        self.rng = np.random.default_rng(seed)

        # 用户画像与红色占比（从 aco_profile_config 注入；若存在 AHP 权重则 W 由 AHP 确定）
        try:
            from aco_profile_config import get_profile_config
            self._profile_config = get_profile_config(profile)
        except ImportError:
            self._profile_config = {'target_red_ratio': 0.3, 'subtype_prefer': [], 'subtype_avoid': [], 'min_stay_core_red': 1.0, 'education_weight': 1.0, 'core_red_high_priority': False}
        self.profile = profile
        self.target_red_ratio = target_red_ratio if target_red_ratio is not None else self._profile_config.get('target_red_ratio', 0.3)
        # 三目标权重：优先使用 AHP/画像配置
        self.W = (
            self._profile_config.get('w_time', w_time),
            self._profile_config.get('w_cost', w_cost),
            self._profile_config.get('w_satisfaction', w_satisfaction),
        )

        # 第一阶段：环境载入（在 run 时执行）
        self.distance = None
        self.time_mat = None
        self.fee_mat = None
        self.poi_ids = []
        self.poi_df = None
        self.N = 0
        self.acc_indices = []
        self.core_red_indices = []
        self.red_indices = []  # 所有红色（core_red + important_red + general_red）
        self.visit_hours = None
        self.ratings = None
        self.acc_cost_per_night = None  # 按星级：五星500、四星400、三星300、其他200
        self.tau = None
        self.best_path = None
        self.best_objectives = None
        self.pareto_paths = []

    def _load_environment(self):
        """第一阶段：从 poi_spatial.db 与 .npy 载入环境。"""
        base = os.path.join(self.data_dir, self.matrix_prefix)
        dist_path = base + "_distance.npy"
        time_path = base + "_time.npy"
        fee_path = base + "_fee.npy"
        ids_path = base + "_poi_ids.txt"
        for p in [dist_path, time_path, fee_path, ids_path]:
            if not os.path.isfile(p):
                raise FileNotFoundError(f"未找到矩阵或 POI 列表: {p}")
        self.distance = np.load(dist_path)
        self.time_mat = np.load(time_path)
        self.fee_mat = np.load(fee_path)
        with open(ids_path, 'r', encoding='utf-8') as f:
            self.poi_ids = [line.strip() for line in f if line.strip()]
        self.N = len(self.poi_ids)
        if self.distance.shape[0] != self.N or self.time_mat.shape[0] != self.N or self.fee_mat.shape[0] != self.N:
            raise ValueError("矩阵维度与 poi_ids 数量不一致")

        # 从 DB 读取 name, address, adname, poi_type, subtype, rating（address/adname 用于 name 为「广东省」等泛名时回退显示）
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        db_df = pd.read_sql("SELECT id, name, address, adname, poi_type, subtype, rating FROM poi", conn)
        conn.close()
        id_to_row = db_df.set_index('id')
        self.poi_df = pd.DataFrame(index=range(self.N), columns=['id', 'name', 'address', 'adname', 'poi_type', 'subtype', 'rating'])
        self.poi_df['id'] = self.poi_ids
        for i, pid in enumerate(self.poi_ids):
            if pid in id_to_row.index:
                r = id_to_row.loc[pid]
                self.poi_df.loc[i, 'name'] = r.get('name', pid)
                self.poi_df.loc[i, 'address'] = r.get('address', '') if pd.notna(r.get('address')) else ''
                self.poi_df.loc[i, 'adname'] = r.get('adname', '') if pd.notna(r.get('adname')) else ''
                self.poi_df.loc[i, 'poi_type'] = r.get('poi_type', '')
                self.poi_df.loc[i, 'subtype'] = r.get('subtype', '')
                self.poi_df.loc[i, 'rating'] = r.get('rating') if pd.notna(r.get('rating')) else 3.0
            else:
                self.poi_df.loc[i, 'name'] = str(pid)
                self.poi_df.loc[i, 'address'] = ''
                self.poi_df.loc[i, 'adname'] = ''
                self.poi_df.loc[i, 'poi_type'] = 'red_spot'
                self.poi_df.loc[i, 'subtype'] = ''
                self.poi_df.loc[i, 'rating'] = 3.0

        self.acc_indices = [i for i in range(self.N) if self.poi_df.loc[i, 'poi_type'] == 'accommodation']
        self.core_red_indices = [i for i in range(self.N) if self.poi_df.loc[i, 'subtype'] == 'core_red']
        self.red_indices = [i for i in range(self.N) if self.poi_df.loc[i, 'subtype'] in ('core_red', 'important_red', 'general_red')]
        self.visit_hours = np.zeros(self.N)
        self.ratings = np.zeros(self.N)
        min_stay_core = self._profile_config.get('min_stay_core_red', 1.0)
        for i in range(self.N):
            t = self.poi_df.loc[i, 'poi_type']
            if t == 'accommodation':
                self.visit_hours[i] = self.visit_hours_accommodation
            elif self.poi_df.loc[i, 'subtype'] == 'core_red':
                self.visit_hours[i] = min_stay_core
            else:
                self.visit_hours[i] = self.visit_hours_attraction
            r = self.poi_df.loc[i, 'rating']
            self.ratings[i] = float(r) if pd.notna(r) else 3.0
        self.ratings = np.clip(self.ratings / 5.0, 0.0, 1.0)

        # 住宿按星级定价：五星500、四星400、三星300、其他200（元/天）
        self.acc_cost_per_night = np.full(self.N, float(self.accommodation_cost_per_night))
        for i in self.acc_indices:
            sub = str(self.poi_df.loc[i, 'subtype'])
            name = str(self.poi_df.loc[i, 'name']) if 'name' in self.poi_df.columns else ''
            text = sub + name
            if '五星' in text or '5星' in text:
                self.acc_cost_per_night[i] = 500.0
            elif '四星' in text or '4星' in text:
                self.acc_cost_per_night[i] = 400.0
            elif '三星' in text or '3星' in text:
                self.acc_cost_per_night[i] = 300.0
            else:
                self.acc_cost_per_night[i] = 200.0

        self.tau = np.full((self.N, self.N), self.tau_init)
        np.fill_diagonal(self.tau, 0.0)

        # 泛名列表：数据源常把「省份/城市」填进 name，用 address/adname 替代显示
        self._generic_names = {'广东省', '广州市', '广东省 ', '广州市 '}

        print(f"环境载入: N={self.N}, 住宿点={len(self.acc_indices)}, 红色点={len(self.red_indices)}, 核心红色={len(self.core_red_indices)}")
        print(f"用户画像={self.profile}, 红色目标占比={self.target_red_ratio}, W=(w_time,w_cost,w_sat)={self.W}")

    def _poi_display_name(self, i: int) -> str:
        """POI 显示名：name 为「广东省」等泛名时用 address 或 adname 替代。"""
        pid = self.poi_ids[i] if i in range(self.N) else str(i)
        if self.poi_df is None or i not in self.poi_df.index:
            return str(pid)
        name = str(self.poi_df.loc[i, 'name']).strip() if pd.notna(self.poi_df.loc[i, 'name']) else ''
        if name and name not in getattr(self, '_generic_names', {'广东省', '广州市'}) and not (len(name) <= 4 and (name.endswith('省') or name.endswith('市'))):
            return name
        addr = str(self.poi_df.loc[i, 'address']).strip() if 'address' in self.poi_df.columns and pd.notna(self.poi_df.loc[i, 'address']) else ''
        if addr and len(addr) > 3:
            return (addr[:36] + '…') if len(addr) > 36 else addr
        ad = str(self.poi_df.loc[i, 'adname']).strip() if 'adname' in self.poi_df.columns and pd.notna(self.poi_df.loc[i, 'adname']) else ''
        if ad:
            return f"{ad} {pid[:8]}…" if len(pid) > 8 else f"{ad} {pid}"
        return str(pid)

    def _heuristic(self, i: int, j: int) -> float:
        """综合启发式：时间/费用/满意度 + 画像语义（家庭 subtype 偏好、研学 core_red 权重）。"""
        w1, w2, w3 = self.W
        t = self.time_mat[i, j] + self.visit_hours[j]
        c = self.fee_mat[i, j]
        if self.poi_df.loc[j, 'poi_type'] == 'accommodation':
            c += self.acc_cost_per_night[j] if self.acc_cost_per_night is not None else self.accommodation_cost_per_night
        s = self.ratings[j]
        cost = w1 * t + w2 * (c / 100.0) - w3 * s
        cost = max(cost, 1e-6)
        eta = 1.0 / cost
        # 研学：core_red 极高权重
        if self._profile_config.get('core_red_high_priority') and j in self.core_red_indices:
            eta *= self._profile_config.get('education_weight', 2.0)
        # 家庭：subtype 语义偏好（纪念馆/博物馆加分，陵园降权）
        prefer = self._profile_config.get('subtype_prefer', [])
        avoid = self._profile_config.get('subtype_avoid', [])
        if prefer or avoid:
            sub = str(self.poi_df.loc[j, 'subtype'])
            name = str(self.poi_df.loc[j, 'name']) if 'name' in self.poi_df.columns else ''
            text = sub + name
            if any(k in text for k in prefer):
                eta *= 1.5
            if any(k in text for k in avoid):
                eta *= 0.5
        return max(eta, 1e-9)

    def _probability_row(self, current: int, unvisited: set, day_time: float, tau: np.ndarray, path_so_far: List[int]) -> np.ndarray:
        """当前节点到各候选的转移概率；含时间窗、必选约束、红色目标占比（比例弹性）。当日不足 min_hours 时只选景点以多排行程。"""
        probs = np.zeros(self.N)
        if day_time >= self.max_hours_per_day and self.acc_indices:
            candidates = list(self.acc_indices)
        elif day_time < self.min_hours_per_day and self.acc_indices:
            # 当日不足 6h：优先只选景点以多排行程；若无其他候选则允许回住宿避免死锁
            non_acc = unvisited - set(self.acc_indices)
            candidates = list(non_acc) if non_acc else list(unvisited)
        else:
            candidates = list(unvisited)
        if not candidates:
            return probs
        # 当前路径红色占比（仅统计景点，不含住宿）
        path_attractions = [p for p in path_so_far if p not in self.acc_indices]
        n_red_in_path = sum(1 for p in path_attractions if p in self.red_indices)
        current_red_ratio = n_red_in_path / len(path_attractions) if path_attractions else 0.0
        # 比例弹性：低于 target 时大幅提升红色启发式
        below_target = current_red_ratio < self.target_red_ratio
        unvisited_core = set(self.core_red_indices) & unvisited
        unvisited_red = set(self.red_indices) & unvisited
        eta = np.zeros(self.N)
        for j in candidates:
            eta[j] = max(self._heuristic(current, j), 1e-9)
            if j in unvisited_core:
                eta[j] *= 2.0
            if below_target and j in unvisited_red:
                eta[j] *= 2.5
        tau_row = np.maximum(tau[current, :], 1e-9)
        raw = (tau_row ** self.alpha) * (eta ** self.beta)
        raw = np.maximum(raw, 0.0)
        s = raw[candidates].sum()
        if s <= 0:
            probs[candidates] = 1.0 / len(candidates)
        else:
            for j in candidates:
                probs[j] = raw[j] / s
        return probs

    def _construct_path(self, start_index: int, tau: np.ndarray) -> Tuple[List[int], float, float, float]:
        """
        第二阶段 + 第三阶段：单蚁路径构造。
        - 每日游览时间 [6,8]h；每日有效站点≤5。
        - 连在一起的近距离景点（与上一站距离≤max_km_nearby_cluster，默认 2km）只计 0.5 有效站点，避免成片景点占满 5 个名额。
        返回 (path_indices, total_time, total_cost, total_satisfaction)。
        """
        path = [start_index]
        unvisited = set(range(self.N)) - {start_index}
        day_time = 0.0
        # 有效站点数（连在一起的近距离景点计 0.5，避免成片景点占满 5 个名额）
        day_attractions = 0.0 if start_index in self.acc_indices else 1.0
        total_time = 0.0
        total_cost = 0.0
        total_dist_km = 0.0
        total_satisfaction = self.ratings[start_index]
        current = start_index
        max_steps = self.N * 2
        steps = 0
        acc_cost = self.acc_cost_per_night if self.acc_cost_per_night is not None else np.full(self.N, self.accommodation_cost_per_night)

        while steps < max_steps:
            if not unvisited:
                break
            # 总路程限制：避免死循环
            if total_dist_km >= self.max_total_km:
                break
            # 第三阶段：当日时长 [6,8]h + 有效站点≤5（近距离景点计 0.5，连在一起的成片景点不占满名额）
            over_max = day_time >= self.max_hours_per_day
            ok_to_end_day = day_time >= self.min_hours_per_day and (day_attractions >= self.max_attractions_per_day or over_max)
            need_back = self.acc_indices and (over_max or ok_to_end_day)
            if need_back:
                acc_candidates = list(self.acc_indices)
                j = min(acc_candidates, key=lambda x: self.time_mat[current, x])
                d_km = self.distance[current, j]
                if total_dist_km + d_km > self.max_total_km:
                    break
                path.append(j)
                dt = self.time_mat[current, j] + self.visit_hours[j]
                dc = self.fee_mat[current, j] + acc_cost[j]
                total_time += dt
                total_cost += dc
                total_dist_km += d_km
                total_satisfaction += self.ratings[j]
                unvisited.discard(j)
                current = j
                day_time = 0.0
                day_attractions = 0.0
                steps += 1
                continue
            # 无住宿时：当日有效站点已满 5 则结束路径
            if day_attractions >= self.max_attractions_per_day and not self.acc_indices:
                break
            probs = self._probability_row(current, unvisited, day_time, tau, path)
            if probs.sum() <= 0:
                break
            probs /= probs.sum()
            j = self.rng.choice(self.N, p=probs)
            if j not in unvisited:
                continue
            d_km = self.distance[current, j]
            if total_dist_km + d_km > self.max_total_km:
                continue
            path.append(j)
            dt = self.time_mat[current, j] + self.visit_hours[j]
            dc = self.fee_mat[current, j]
            if self.poi_df.loc[j, 'poi_type'] == 'accommodation':
                dc += acc_cost[j]
            total_time += dt
            total_cost += dc
            total_dist_km += d_km
            total_satisfaction += self.ratings[j]
            day_time += dt
            if j not in self.acc_indices:
                # 与上一景点距离≤max_km_nearby_cluster 视为“连在一起”，只计 0.5 有效站点
                day_attractions += 0.5 if d_km <= self.max_km_nearby_cluster else 1.0
            unvisited.discard(j)
            current = j
            steps += 1
            core_visited = set(self.core_red_indices) <= (set(range(self.N)) - unvisited)
            if core_visited and current in self.acc_indices and day_time > 0:
                break

        return path, total_time, total_cost, total_satisfaction

    def _is_pareto_optimal(self, objectives_list: List[Tuple[float, float, float]], idx: int) -> bool:
        """判断第 idx 个解是否被其他解帕累托支配。目标：(min time, min cost, max satisfaction)。"""
        t, c, s = objectives_list[idx]
        for i, (ti, ci, si) in enumerate(objectives_list):
            if i == idx:
                continue
            if ti <= t and ci <= c and si >= s and (ti < t or ci < c or si > s):
                return False
        return True

    def _update_pheromone(self, paths: List[List[int]], objectives_list: List[Tuple[float, float, float]]):
        """第四阶段：挥发 + 仅对帕累托最优路径加强。"""
        self.tau *= (1.0 - self.rho)
        pareto_idx = [i for i in range(len(objectives_list)) if self._is_pareto_optimal(objectives_list, i)]
        if not pareto_idx:
            pareto_idx = [np.argmin([o[0] + o[1] - o[2] for o in objectives_list])]
        Q = 100.0
        for i in pareto_idx:
            path = paths[i]
            t, c, s = objectives_list[i]
            # 奖励与综合目标成反比（时间+成本-满意度）
            delta = Q / (1.0 + t + c / 100.0 - s)
            for k in range(len(path) - 1):
                u, v = path[k], path[k + 1]
                self.tau[u, v] += delta
                self.tau[v, u] += delta

    def run(
        self,
        start_id: Optional[str] = None,
        max_days: Optional[int] = None,
    ) -> Dict:
        """
        执行 ACO 优化。
        :param start_id: 起点 POI id，默认第一个住宿点或第一个节点
        :param max_days: 最大天数（用于早停），默认不限制
        :return: {
            'path_indices': List[int],
            'path_ids': List[str],
            'path_names': List[str],
            'total_time_h': float,
            'total_cost_yuan': float,
            'total_satisfaction': float,
            'n_days': int,
            'objectives_summary': dict
        }
        """
        self._load_environment()
        if not self.acc_indices:
            print("警告: 矩阵中无住宿点，将按单日路径优化（不强制 6~8h 时间窗回住宿）。")
        start_index = 0
        if start_id is not None:
            if start_id in self.poi_ids:
                start_index = self.poi_ids.index(start_id)
            else:
                start_index = self.acc_indices[0] if self.acc_indices else 0
        else:
            start_index = self.acc_indices[0] if self.acc_indices else 0
        if start_index not in range(self.N):
            start_index = 0

        best_path = None
        best_obj = (np.inf, np.inf, -np.inf)
        all_paths = []
        all_objectives = []

        bar_width = 24
        def _progress_bar(step: int, total: int) -> str:
            filled = int(bar_width * step / total) if total else 0
            return "[" + "#" * filled + "-" * (bar_width - filled) + "]"

        print(f"  ACO 开始: {self.n_ants} 蚁 × {self.n_iterations} 代")
        for it in range(self.n_iterations):
            paths = []
            objectives = []
            for _ in range(self.n_ants):
                path, t, c, s = self._construct_path(start_index, self.tau)
                paths.append(path)
                objectives.append((t, c, s))
                # 加权和（越小越好）
                w1, w2, w3 = self.W
                score = w1 * t + w2 * (c / 100.0) - w3 * s
                if score < (w1 * best_obj[0] + w2 * (best_obj[1] / 100.0) - w3 * best_obj[2]):
                    best_path = path
                    best_obj = (t, c, s)
            all_paths.extend(paths)
            all_objectives.extend(objectives)
            self._update_pheromone(paths, objectives)
            bar = _progress_bar(it + 1, self.n_iterations)
            print(f"\r  {bar} {it+1}/{self.n_iterations}  当前最优: time={best_obj[0]:.2f}h cost={best_obj[1]:.1f}元 sat={best_obj[2]:.2f}  ", end="", flush=True)
        print()

        self.best_path = best_path
        self.best_objectives = best_obj

        # 估算天数（按 8h 切分）
        t_total = best_obj[0]
        n_days = max(1, int(np.ceil(t_total / self.max_hours_per_day)))

        path_ids = [self.poi_ids[i] for i in best_path]
        path_names = [self._poi_display_name(i) for i in best_path]

        # 按「回住宿」切分每日行程（路径中遇到住宿点且当日已有非住宿点则为新一天）
        daily_path_indices = []
        current_day = []
        for i in range(len(best_path)):
            current_day.append(best_path[i])
            if best_path[i] in self.acc_indices and any(
                best_path[j] not in self.acc_indices for j in range(len(current_day) - 1)
            ):
                daily_path_indices.append(current_day)
                current_day = []
        if current_day:
            daily_path_indices.append(current_day)

        daily_path_ids = [[self.poi_ids[idx] for idx in seg] for seg in daily_path_indices]
        daily_path_names = [[self._poi_display_name(idx) for idx in seg] for seg in daily_path_indices]

        daily_time_h = []
        daily_cost_yuan = []
        for seg in daily_path_indices:
            t = 0.0
            c = 0.0
            for k in range(len(seg)):
                t += self.visit_hours[seg[k]]
                if k < len(seg) - 1:
                    t += self.time_mat[seg[k], seg[k + 1]]
                    c += self.fee_mat[seg[k], seg[k + 1]]
            daily_time_h.append(round(float(t), 2))
            daily_cost_yuan.append(round(float(c), 2))

        # 评估指标：空间紧凑度、旅游节奏感、红绿匹配度
        total_dist_km = 0.0
        for k in range(len(best_path) - 1):
            total_dist_km += self.distance[best_path[k], best_path[k + 1]]
        compactness = None
        if ConvexHull is not None and len(best_path) >= 3:
            try:
                points = np.array([[float(self.poi_df.loc[i, 'latitude']), float(self.poi_df.loc[i, 'longitude'])] for i in best_path])
                hull = ConvexHull(points)
                area_deg2 = hull.volume
                lat_rad = np.radians(points[:, 0].mean())
                area_km2 = area_deg2 * (111.0 * 111.0 * np.cos(lat_rad))
                area_km2 = max(area_km2, 1e-6)
                compactness = total_dist_km / area_km2
            except Exception:
                pass
        path_attractions = [i for i in best_path if i not in self.acc_indices]
        visit_durations = [self.visit_hours[i] for i in path_attractions]
        rhythm_std = float(np.std(visit_durations)) if len(visit_durations) > 1 else 0.0
        n_red = sum(1 for i in path_attractions if i in self.red_indices)
        actual_red_ratio = n_red / len(path_attractions) if path_attractions else 0.0
        red_match = 1.0 - min(abs(actual_red_ratio - self.target_red_ratio), 1.0)

        result = {
            'path_indices': best_path,
            'path_ids': path_ids,
            'path_names': path_names,
            'n_days': n_days,
            'daily_path_indices': daily_path_indices,
            'daily_path_ids': daily_path_ids,
            'daily_path_names': daily_path_names,
            'daily_time_h': daily_time_h,
            'daily_cost_yuan': daily_cost_yuan,
            'total_time_h': best_obj[0],
            'total_cost_yuan': best_obj[1],
            'total_satisfaction': best_obj[2],
            'objectives_summary': {
                'time_h': best_obj[0],
                'cost_yuan': best_obj[1],
                'satisfaction': best_obj[2],
            },
            'evaluation': {
                'compactness': compactness,
                'rhythm_std': rhythm_std,
                'red_match': red_match,
                'actual_red_ratio': actual_red_ratio,
                'total_distance_km': total_dist_km,
            },
        }
        return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description='多目标 ACO 路径优化（支持画像与红色目标占比）')
    parser.add_argument('--prefix', default='cost_matrix_red_spot', help='矩阵文件名前缀')
    parser.add_argument('--profile', default='normal', choices=['family', 'study', 'normal'], help='用户画像')
    parser.add_argument('--w-time', type=float, default=0.4, help='时间权重')
    parser.add_argument('--w-cost', type=float, default=0.3, help='成本权重')
    parser.add_argument('--w-sat', type=float, default=0.3, help='满意度权重')
    parser.add_argument('--ants', type=int, default=20)
    parser.add_argument('--iters', type=int, default=50)
    parser.add_argument('--start-id', default=None, help='起点 POI id')
    args = parser.parse_args()

    opt = ACOOptimizer(
        matrix_prefix=args.prefix,
        profile=args.profile,
        w_time=args.w_time,
        w_cost=args.w_cost,
        w_satisfaction=args.w_sat,
        n_ants=args.ants,
        n_iterations=args.iters,
    )
    res = opt.run(start_id=args.start_id)
    print("\n=== 优化结果 ===")
    print("路径顺序 (id):", res['path_ids'][:20], "..." if len(res['path_ids']) > 20 else "")
    print("路径顺序 (名称):", res['path_names'][:20], "..." if len(res['path_names']) > 20 else "")
    print("总时间 (h):", res['total_time_h'])
    print("总成本 (元):", res['total_cost_yuan'])
    print("综合满意度:", res['total_satisfaction'])
    print("估算天数:", res['n_days'])
    if 'evaluation' in res:
        ev = res['evaluation']
        print("评估: 空间紧凑度(总里程/凸包面积)={}, 旅游节奏感(游览时间标准差)={:.3f}, 红绿匹配度={:.3f}, 实际红占比={:.2%}".format(
            ev.get('compactness'), ev.get('rhythm_std', 0), ev.get('red_match', 0), ev.get('actual_red_ratio', 0)))
    return res


if __name__ == '__main__':
    main()
