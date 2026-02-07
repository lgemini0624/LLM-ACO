# LLM-ACO 项目说明

本仓库主要包含一个用于「广州红色旅游路线规划」的 Python 项目（`pythonProject/`），以及一个用于 Claude 工具交互的 Next.js 示例前端（`claude-chat/`）。核心流程是：原始 POI 数据 → 预处理 → 红色景点识别 → POI 空间数据库 →（可选）空间剪枝 → 成本矩阵 → 多目标 ACO 路线优化 → 导出地图与对比结果。以下内容基于仓库内脚本与文档整理。

## 仓库结构

```
/ (仓库根)
├─ pythonProject/          # 广州红色旅游路线规划主项目
│  ├─ src/                 # 核心算法与数据处理脚本
│  ├─ data/                # 已知红点/官方名录等数据
│  ├─ RUN_ORDER.md         # 详细运行顺序说明
│  ├─ run_all.py           # 一键流程脚本
│  ├─ run_profile_comparison.py
│  ├─ view_profile_results.py
│  └─ plot_paper_figures.py
├─ data/                   # 处理后的示例数据（含 red_spots.csv 等）
└─ claude-chat/            # Next.js 示例前端（Claude SDK）
```

- `pythonProject/RUN_ORDER.md` 给出了推荐的运行顺序与参数解释。该文档也说明了空间剪枝、AHP 权重读取、论文配图等功能。`pythonProject/run_all.py` 封装了一键运行流程。 【F:pythonProject/RUN_ORDER.md†L1-L107】【F:pythonProject/run_all.py†L1-L82】
- `claude-chat/` 是一个 Next.js + Anthropic SDK 示例工程，包含 `dev/build/start` 脚本。 【F:claude-chat/package.json†L1-L20】

## 核心流程概览（Python 项目）

1. **数据预处理**：读取景点/住宿/交通 Excel，统一坐标、清洗文本、解析评分，输出到 `data/processed`。【F:pythonProject/src/data_preprocessing.py†L1-L188】
2. **红色景点识别**：基于关键词、已知名单、官方名录等规则打分，分为 core/important/general/non_red，并输出主题。【F:pythonProject/src/red_spot_identifier.py†L1-L226】
3. **构建 POI 数据库**：将红点、风景景点、住宿、交通等统一写入 SQLite（`poi_spatial.db`）。【F:pythonProject/src/poi_database.py†L1-L120】
4. **空间剪枝（可选）**：对红点+风景景点做 K-Means 聚类，写回 `cluster_id`，用于限制矩阵规模。 【F:pythonProject/src/spatial_pruning.py†L1-L122】
5. **成本矩阵**：基于 Haversine 计算距离矩阵，并推导时间/费用矩阵保存为 `.npy`。【F:pythonProject/src/cost_matrix.py†L1-L104】【F:pythonProject/src/build_cost_matrices.py†L1-L120】
6. **多目标 ACO 优化**：在时间/成本/满意度三目标、红色占比目标和画像偏好下生成路线并评估。 【F:pythonProject/src/aco_optimizer.py†L1-L120】
7. **三画像对比与地图导出**：家庭/研学/普通三种画像运行 ACO，导出 HTML 地图与对比结果 JSON。 【F:pythonProject/run_profile_comparison.py†L1-L106】

## 快速开始（推荐）

在 `pythonProject/` 目录下运行：

```bash
python run_all.py
```

该脚本会依次生成风景景点 CSV、处理数据、构建 POI 数据库、空间剪枝、生成成本矩阵，并执行三画像对比。可选参数包括跳过风景 CSV、跳过剪枝、指定簇或限制 POI 数量等。 【F:pythonProject/run_all.py†L1-L82】

## 分步运行（与 RUN_ORDER 一致）

> 适用于想要自定义路径/参数的情况。

1. **生成风景景点 CSV（可选）**
   ```bash
   python src/build_scenic_spots_csv.py
   ```
   读取风景名胜 Excel 并输出 `data/processed/scenic_spots.csv`。【F:pythonProject/src/build_scenic_spots_csv.py†L1-L124】

2. **数据处理 + 红点识别 + POI 数据库**
   ```bash
   python src/main.py
   ```
   处理景点/住宿/交通数据，识别红点并写入 CSV，同时构建 `poi_spatial.db`。【F:pythonProject/src/main.py†L1-L100】

3. **空间剪枝（可选）**
   ```bash
   python src/spatial_pruning.py --n-clusters 20
   python src/spatial_pruning.py --summary
   ```
   通过 K-Means 写回 cluster_id，并输出簇规模摘要。 【F:pythonProject/src/spatial_pruning.py†L1-L147】

4. **构建成本矩阵**
   ```bash
   python src/build_cost_matrices.py --type combined --top-red 200 --top-attraction 300
   ```
   支持 `red_spot/combined` 类型、`--cluster-ids` 等参数。 【F:pythonProject/src/build_cost_matrices.py†L1-L120】

5. **三画像对比 + 地图导出**
   ```bash
   python run_profile_comparison.py
   ```
   生成 `red_spots_map_family.html` 等地图，并保存对比结果 JSON。 【F:pythonProject/run_profile_comparison.py†L1-L106】

## ACO 画像与 AHP 权重

- 画像配置（红色占比、偏好、三目标权重）由 `aco_profile_config.py` 管理。若存在 `权重.xlsx`，则 AHP 会覆盖默认权重。 【F:pythonProject/src/aco_profile_config.py†L1-L82】
- AHP 权重读取逻辑在 `ahp_weights.py`，支持从 `data/processed/权重.xlsx` 或环境变量 `AHP_WEIGHTS_PATH` 加载。 【F:pythonProject/src/ahp_weights.py†L1-L150】

## 可视化与报告输出

- **论文用图**：`plot_paper_figures.py` 生成 AHP 权重对比、簇规模、画像对比、技术路线图等。 【F:pythonProject/plot_paper_figures.py†L1-L200】
- **红点地图与行政区柱状图**：`plot_red_spots_map.py` 输出 HTML 地图与柱状图，可选叠加路线。 【F:pythonProject/plot_red_spots_map.py†L1-L169】
- **对比结果 HTML**：`view_profile_results.py` 将 JSON 转为可读 HTML。 【F:pythonProject/view_profile_results.py†L1-L160】

## 关键脚本速览

| 脚本 | 作用 |
| --- | --- |
| `src/main.py` | 数据预处理 + 红点识别 + 构建 POI 数据库【F:pythonProject/src/main.py†L1-L100】 |
| `src/data_preprocessing.py` | 景点/住宿/交通清洗与标准化【F:pythonProject/src/data_preprocessing.py†L1-L188】 |
| `src/red_spot_identifier.py` | 红色景点识别规则与分级【F:pythonProject/src/red_spot_identifier.py†L1-L226】 |
| `src/poi_database.py` | 统一 POI SQLite 数据库【F:pythonProject/src/poi_database.py†L1-L120】 |
| `src/spatial_pruning.py` | K-Means 剪枝并写回 cluster_id【F:pythonProject/src/spatial_pruning.py†L1-L147】 |
| `src/build_cost_matrices.py` | 距离/时间/费用矩阵构建【F:pythonProject/src/build_cost_matrices.py†L1-L120】 |
| `src/aco_optimizer.py` | 多目标 ACO 规划与评估【F:pythonProject/src/aco_optimizer.py†L1-L120】 |
| `run_profile_comparison.py` | 三画像对比 + 地图导出【F:pythonProject/run_profile_comparison.py†L1-L106】 |

## 数据与路径说明

- 多数脚本默认读取本地 Windows 路径（例如 `D:\Users\...`）。若在其他环境运行，请修改相关路径或传入参数。 【F:pythonProject/src/main.py†L18-L33】【F:pythonProject/src/build_scenic_spots_csv.py†L23-L28】
- 处理后的数据默认输出到 `pythonProject/data/processed/`，包括 `red_spots.csv`、`processed_accommodations.csv`、`processed_transportation.csv`、`scenic_spots.csv` 以及 `poi_spatial.db`。 【F:pythonProject/src/data_preprocessing.py†L164-L188】【F:pythonProject/src/poi_database.py†L33-L120】

## 前端（claude-chat）

`claude-chat` 是一个简洁的 Next.js 项目，依赖 `@anthropic-ai/sdk`，可用 `pnpm dev` 启动。该前端与主算法模块无直接耦合，主要用于 Claude API 交互示例。 【F:claude-chat/package.json†L1-L20】

---

如需进一步完善 README（例如增加安装步骤、依赖版本、示例输出截图等），请告知你的目标受众和使用场景。
