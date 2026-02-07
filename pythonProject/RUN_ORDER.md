# 全部代码运行顺序

在**项目根目录**（`D:\PycharmProjects\pythonProject`）下执行。

---

## 方式一：一键运行（推荐）

```bash
cd D:\PycharmProjects\pythonProject
python run_all.py
```

可选参数：
- `--skip-scenic`：跳过「风景景点 CSV」生成（若已有 `data/processed/scenic_spots.csv`）
- `--skip-pruning`：跳过空间剪枝（不跑 K-Means）
- `--cluster-ids 1,2`：空间剪枝后只对簇 1、2 建矩阵（需先跑剪枝）
- `--top-red 200 --top-attraction 300`：建矩阵时红点/风景景点各取前 N 条

示例（空间剪枝 + 只对簇 1、2 建矩阵）：
```bash
python run_all.py --cluster-ids 1,2
```

---

## 方式二：分步运行

### 1. 生成风景景点 CSV（可选，用于「红点+风景景点」）

若需要把**所有风景名胜**纳入路线（不仅红色），先运行：

```bash
python src/build_scenic_spots_csv.py
```

默认读取：`D:\Users\Lenovo\Desktop\广州城市数据\2025.06.11-广州POI带BIZ信息采集交付\广州市.csv-风景名胜-带评分.xlsx`  
输出：`data/processed/scenic_spots.csv`

### 2. 数据处理 + 建 POI 库

```bash
python src/main.py
```

会：处理景点/住宿/交通 Excel → 识别红色景点 → 保存 `red_spots.csv`、`processed_accommodations.csv`、`processed_transportation.csv` → 构建 `data/processed/poi_spatial.db`（若存在 `scenic_spots.csv` 会一并导入为 attraction）。

### 3. 空间剪枝（可选，避免矩阵过大）

```bash
python src/spatial_pruning.py --n-clusters 20
python src/spatial_pruning.py --summary
```

第一句：对红点+风景景点做 K-Means，把 `cluster_id` 写回 DB。  
第二句：查看各簇 POI 数量，便于选 1–2 个目标簇。

### 4. 构建成本矩阵

**仅红色景点（约 500 点）：**
```bash
python src/build_cost_matrices.py --type red_spot --top 500
```

**红点+风景景点（推荐）：**
```bash
python src/build_cost_matrices.py --type combined --top-red 200 --top-attraction 300
```

**空间剪枝后只对簇 1、2 建矩阵：**
```bash
python src/build_cost_matrices.py --type combined --cluster-ids 1,2
```

### 5. 三画像 ACO 对比 + 导出地图

```bash
python run_profile_comparison.py
```

会跑家庭/研学/普通三种画像的 ACO，并导出：
- `data/processed/red_spots_map_family.html`
- `data/processed/red_spots_map_study.html`
- `data/processed/red_spots_map_normal.html`

用浏览器打开上述 HTML 即可查看路线图。

---

## 可选：AHP 权重

若已准备 `权重.xlsx`（游客类型对准则的兴趣权重），可放在以下任一路径，程序会自动读取：

- `data/processed/权重.xlsx`
- `D:\Users\Lenovo\Desktop\广州城市数据\2025.06.11-广州POI带BIZ信息采集交付\权重.xlsx`
- 或设置环境变量 `AHP_WEIGHTS_PATH` 指向该文件

无需改代码，运行 `run_profile_comparison.py` 时会自动使用 AHP 权重。

---

## 论文用图

写论文时可用以下图，统一生成脚本：

```bash
# 先跑完三画像对比（生成 profile_comparison_results.json），再生成论文图
python run_profile_comparison.py
python plot_paper_figures.py
```

**plot_paper_figures.py 会生成：**

| 文件名 | 说明 |
|--------|------|
| fig_ahp_weights.png | AHP 三目标权重（时间/成本/满意度）在家庭、研学、普通三种画像下的对比 |
| fig_cluster_sizes.png | 空间剪枝后各簇 POI 数量（需先运行 spatial_pruning） |
| fig_profile_comparison.png | 三画像 ACO 对比：总时间、总成本、满意度、实际红占比 |
| fig_framework.png | 技术路线图：数据→POI 库→剪枝→成本矩阵→AHP→ACO→路线 |

**已有图（来自 data_analysis / plot_red_spots_map）：**

| 文件名 | 说明 |
|--------|------|
| red_spots_analysis.png | 红色景点等级/行政区/评分/主题四宫格 |
| spatial_distribution.png | 红色景点空间分布散点 |
| red_spots_by_district.png | 行政区红色资源柱状 |
| accommodation_types.png | 住宿类型分布 |
| transportation_types.png | 交通类型分布 |
| data/processed/red_spots_map_*.html | 三画像路线交互地图（可截图或导出为图） |

所有图输出到 `outputs/figures/`，dpi=300，适合直接插入论文。

---

## 依赖

- Python 3.7+
- 常用库：pandas, numpy, scikit-learn, openpyxl（读 Excel）, matplotlib
- 若报缺库：`pip install pandas numpy scikit-learn openpyxl matplotlib`
