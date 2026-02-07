"""
红色景点识别模块

划分依据（可补充的参考来源）：
- 《全国红色旅游经典景区名录》《红色旅游发展规划》等对红色景点的界定
- 爱国主义教育基地、革命遗址、烈士纪念设施等政策与行业惯例
- 核心：革命、抗战、党史、烈士纪念、爱国主义教育等相关名称/类型/地址描述

分级逻辑依据：
- core_red(≥5分)：名称/类型中明确含多重红色要素（如纪念馆+革命+党史）
- important_red(3–4分)：含明显红色设施（纪念馆、陵园、旧址等）
- general_red(1–2分)：含部分相关词（博物馆、教育基地等）
- non_red(0分)：无匹配关键词（可能遗漏别名、简称，需复核）

“基于名称的简单分类模型”含义：用机器学习（如文本分类、BERT 等）对景点名称做二分类/多分类，
  输出“是否红色/等级”，可作为与规则并行的另一路信号，与规则结果融合（如取并集或投票），不替代规则。

“与官方名录做名称模糊匹配”含义：用《全国红色旅游经典景区名录》等官方名单，与每条景点的名称/类型/地址
  做包含关系或相似度匹配；命中则至少判为 core_red，作为对关键词规则的补充，不替代现有规则。
  本项目已实现：加载 data/official_red_list_guangdong.txt，命中则 total_score 至少为 core_red 阈值。
"""
import pandas as pd
import jieba
import os


# 分级阈值（可调，便于做敏感性分析）
RED_LEVEL_THRESHOLDS = {
    'core_red': 5,
    'important_red': 3,
    'general_red': 1,
}


class RedSpotIdentifier:
    def __init__(self, known_red_path: str = None, official_list_path: str = None):
        """
        :param known_red_path: 可选，已知红色景点名称或关键词列表文件路径（每行一条），命中时至少判为 general_red。
        :param official_list_path: 可选，官方红色景区名录文件路径，命中时至少判为 core_red。
        """
        self.keyword_hierarchy = {
            'core_red': [
                '革命', '烈士', '纪念馆', '红色', '党史', '抗战', '爱国', '军事',
                '英烈', '红军', '中共', '纪念碑', '党性', '初心', '使命',
            ],
            'historical': [
                '旧址', '遗址', '故居', '陵园', '纪念园', '博物馆', '会址',
                '讲习所', '农讲所', '黄埔', '展览馆', '红色文化馆', '纪念设施',
            ],
            'education': [
                '教育基地', '爱国主义', '党史学习', '红色教育', '红色基地', '党性教育',
            ],
        }
        self._synonyms = {'紀念館': '纪念馆', '遺址': '遗址', '博物館': '博物馆'}  # 繁体/异体→简体，减少遗漏
        self._known_red_set = self._load_known_red(known_red_path) if known_red_path else set()
        self._official_phrases = self._load_official_list(official_list_path) if official_list_path else []
        self._build_domain_dict()

    def _load_known_red(self, path: str) -> set:
        """加载已知红色景点名称/关键词（每行一条），用于弥补关键词遗漏。"""
        out = set()
        if not path or not os.path.isfile(path):
            return out
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith('#'):
                        out.add(s)
        except Exception as e:
            print(f"加载已知红色名单失败 ({path}): {e}")
        return out

    def _load_official_list(self, path: str) -> list:
        """加载官方红色景区名录（每行一条），用于名称模糊匹配，作为补充不替代关键词规则。"""
        out = []
        if not path or not os.path.isfile(path):
            return out
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    s = line.strip()
                    if s and not s.startswith('#'):
                        out.append(s)
            if out:
                print(f"已加载官方名录 {len(out)} 条（《全国红色旅游经典景区名录》等），用于名称模糊匹配。")
        except Exception as e:
            print(f"加载官方名录失败 ({path}): {e}")
        return out

    def _match_official_list(self, text: str) -> bool:
        """与官方名录做名称模糊匹配：名录条在文本中出现，或文本较短且被某条包含，即视为命中。"""
        if not text or not self._official_phrases:
            return False
        t = self._normalize_text(text)
        for phrase in self._official_phrases:
            if not phrase:
                continue
            if phrase in t:
                return True
            if len(t) <= len(phrase) + 10 and t in phrase:
                return True
        return False

    def _normalize_text(self, text: str) -> str:
        """繁体/异体转简体，减少因用字差异导致的遗漏。"""
        if not text:
            return ''
        t = str(text)
        for old, new in self._synonyms.items():
            t = t.replace(old, new)
        return t

    def _build_domain_dict(self):
        """构建领域词典"""
        domain_terms = [
            '红色旅游', '革命历史', '爱国主义', '党史教育', '烈士精神',
            '抗战记忆', '革命旧址', '纪念设施', '教育基地', '红色文化'
        ]
        for term in domain_terms:
            jieba.add_word(term)

    def identify_red_spots(self, spots_df: pd.DataFrame) -> pd.DataFrame:
        """识别红色景点。数据量 10 万级时建议改用 apply(axis=1) 替代 iterrows 以提升速度。"""
        print("开始识别红色景点...")

        if spots_df.empty:
            result = spots_df.copy()
            result['red_score'] = pd.Series(dtype=float)
            result['red_level'] = pd.Series(dtype=object)
            result['red_themes'] = pd.Series(dtype=object)
            print("景点数据为空，跳过红色识别。")
            return result

        def _one_row(spot):
            s, l, t = self._calculate_red_features(spot)
            return pd.Series({'red_score': s, 'red_level': l, 'red_themes': t})
        red_features_df = spots_df.apply(_one_row, axis=1)

        # 合并红色特征到原数据
        result_df = pd.concat([spots_df.copy(), red_features_df], axis=1)

        # 统计红色景点数量
        red_counts = result_df['red_level'].value_counts()
        print("红色景点识别完成:")
        for level, count in red_counts.items():
            print(f"  {level}: {count}个")

        return result_df

    def _calculate_red_features(self, spot):
        """计算红色特征（含同义词归一化与已知名单兜底）。"""
        raw_name = str(spot.get('name', ''))
        raw_type = str(spot.get('full_type', ''))
        raw_addr = str(spot.get('address', ''))
        name = self._normalize_text(raw_name)
        full_type = self._normalize_text(raw_type)
        address = self._normalize_text(raw_addr)

        # 1. 核心红色词匹配（每类至多计一次，避免“革命纪念馆”等重叠词导致分级虚高）
        combined = name + full_type + address
        core_score = 3 if any(w in combined for w in self.keyword_hierarchy['core_red']) else 0
        historical_score = 2 if any(w in combined for w in self.keyword_hierarchy['historical']) else 0
        education_score = 1 if any(w in combined for w in self.keyword_hierarchy['education']) else 0

        total_score = core_score + historical_score + education_score

        # 已知红色名单兜底：名称或类型中含已知关键词则至少 1 分，减少遗漏
        if total_score == 0 and self._known_red_set:
            if any(kw in combined for kw in self._known_red_set):
                total_score = max(total_score, 1)

        # 官方名录模糊匹配（补充不替代）：命中《全国红色旅游经典景区名录》等则至少 core_red
        if self._official_phrases and (
            self._match_official_list(name) or self._match_official_list(full_type) or self._match_official_list(address)
        ):
            total_score = max(total_score, RED_LEVEL_THRESHOLDS['core_red'])

        # 分级逻辑（使用可配置阈值）
        t = RED_LEVEL_THRESHOLDS
        if total_score >= t['core_red']:
            level = 'core_red'
        elif total_score >= t['important_red']:
            level = 'important_red'
        elif total_score >= t['general_red']:
            level = 'general_red'
        else:
            level = 'non_red'

        # 主题提取
        themes = self._extract_themes(name, full_type)

        return total_score, level, themes

    def _extract_themes(self, name: str, full_type: str) -> list:
        """提取主题（仅此处用 jieba 分词；_calculate_red_features 用 in 匹配以保留对“农讲所”等简称的识别）。"""
        text = name + ' ' + full_type
        words = jieba.lcut(text)

        themes = []
        theme_keywords = {
            '革命历史': ['革命', '起义', '长征', '红色'],
            '烈士纪念': ['烈士', '英烈', '陵园', '纪念'],
            '抗战记忆': ['抗战', '抗日', '战争'],
            '党史教育': ['党史', '党建', '党员'],
            '爱国主义': ['爱国', '国防', '军事']
        }

        for theme, keywords in theme_keywords.items():
            if any(keyword in text for keyword in keywords):
                themes.append(theme)

        return themes if themes else ['红色文化']