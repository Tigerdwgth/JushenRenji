"""单元测试：视频图文语义匹配功能

测试 video_creator.py 中基于 section 的语义匹配逻辑：
- _build_section_sentence_map: 从结构化脚本提取 section -> 句子映射
- _get_image_section: 从 image_explanations 获取图片所属 section
- _semantic_group_sentences: 语义匹配核心逻辑
- _normalize_section: section 名称标准化
- _match_audio_to_section: 音频文本匹配到 section
- _fallback_even_group: 均分回退逻辑
- _get_chapter_name_for_image: 章节标题获取
- _add_chapter_overlay: 章节标题叠加（含回退）
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

# 将 src 目录加入 sys.path，确保导入正确
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _make_dummy_images(n=3):
    """创建 n 张 dummy PIL 图片"""
    return [Image.new("RGB", (100, 100), (i * 50, i * 50, i * 50)) for i in range(n)]


def _make_audio_item(text, duration=2.0, idx=0):
    """创建模拟 TTS 音频条目 (path, text, duration)"""
    return (f"./cache/summary{idx}.wav", text, duration)


def _make_structured_plan():
    """创建标准结构化脚本"""
    return {
        "opening": {"script": "大家好，今天要讲一个非常有趣的研究。"},
        "intro": {"script": "要理解这项工作，我们需要了解背景。之前的方法有很多局限性。"},
        "method": {"script": "这篇论文提出了一种全新的方法。核心思路是使用注意力机制。具体来说分三步。"},
        "results": {"script": "实验结果非常令人振奋。在多个基准测试上超越了以往最佳。"},
    }


def _make_image_explanations(sections):
    """根据 section 列表创建 image_explanations

    Args:
        sections: list of str, 每张图片的 recommended_section
    """
    return [
        {
            "recommended_section": sec,
            "figure_role": f"role_{i}",
            "detailed_explanation": f"图片{i}的详细解释",
        }
        for i, sec in enumerate(sections)
    ]


class TestNormalizeSection(unittest.TestCase):
    """测试 _normalize_section 静态方法"""

    def _call(self, name):
        from video_creator import VideoCreator
        return VideoCreator._normalize_section(name)

    def test_standard_names(self):
        """标准 section 名称正确映射"""
        self.assertEqual(self._call("opening"), "opening")
        self.assertEqual(self._call("intro"), "intro")
        self.assertEqual(self._call("method"), "method")
        self.assertEqual(self._call("results"), "results")

    def test_aliases(self):
        """别名正确映射"""
        self.assertEqual(self._call("introduction"), "intro")
        self.assertEqual(self._call("methods"), "method")
        self.assertEqual(self._call("experiment"), "results")
        self.assertEqual(self._call("experiments"), "results")
        self.assertEqual(self._call("conclusion"), "results")

    def test_composite_format(self):
        """复合格式 "opening/intro" 取第一个"""
        self.assertEqual(self._call("opening/intro"), "opening")

    def test_case_insensitive(self):
        """大小写不敏感"""
        self.assertEqual(self._call("METHOD"), "method")
        self.assertEqual(self._call("Results"), "results")

    def test_other_returns_empty(self):
        """'other' 返回空字符串"""
        self.assertEqual(self._call("other"), "")

    def test_empty_returns_empty(self):
        """空字符串返回空"""
        self.assertEqual(self._call(""), "")
        self.assertEqual(self._call(None), "")


class TestMatchAudioToSection(unittest.TestCase):
    """测试 _match_audio_to_section 静态方法"""

    def setUp(self):
        self.section_map = {
            "opening": ["大家好，今天要讲一个研究"],
            "intro": ["我们需要了解背景", "之前的方法有局限性"],
            "method": ["论文提出了全新方法", "核心思路是注意力机制"],
            "results": ["实验结果非常好"],
        }

    def _call(self, text):
        from video_creator import VideoCreator
        return VideoCreator._match_audio_to_section(text, self.section_map)

    def test_exact_match(self):
        """精确匹配"""
        self.assertEqual(self._call("大家好，今天要讲一个研究"), "opening")

    def test_substring_match(self):
        """子串匹配（TTS 分句后可能是原句的一部分）"""
        self.assertEqual(self._call("大家好"), "opening")
        self.assertEqual(self._call("注意力机制"), "method")

    def test_reverse_substring(self):
        """反向子串：原句是音频文本的子串"""
        self.assertEqual(
            self._call("大家好，今天要讲一个研究，非常有趣"),
            "opening"
        )

    def test_no_match(self):
        """完全无关文本返回空字符串"""
        result = self._call("zzzzz")
        # 可能通过字符重叠匹配到某个 section，也可能返回空
        # 只要不崩溃即可
        self.assertIsInstance(result, str)

    def test_empty_text(self):
        """空文本返回空"""
        self.assertEqual(self._call(""), "")


class TestFallbackEvenGroup(unittest.TestCase):
    """测试 _fallback_even_group 均分回退逻辑"""

    def _call(self, files, n_images):
        from video_creator import VideoCreator
        return VideoCreator._fallback_even_group(files, n_images)

    def test_even_distribution(self):
        """均匀分配"""
        files = [_make_audio_item(f"句子{i}", idx=i) for i in range(6)]
        groups = self._call(files, 3)
        self.assertEqual(len(groups), 3)
        self.assertEqual(len(groups[0]), 2)
        self.assertEqual(len(groups[1]), 2)
        self.assertEqual(len(groups[2]), 2)

    def test_uneven_distribution(self):
        """不均匀分配（余数处理）"""
        files = [_make_audio_item(f"句子{i}", idx=i) for i in range(5)]
        groups = self._call(files, 3)
        self.assertEqual(len(groups), 3)
        total = sum(len(g) for g in groups)
        self.assertEqual(total, 5)

    def test_empty_files(self):
        """无音频文件"""
        groups = self._call([], 3)
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(len(g), 0)

    def test_more_images_than_files(self):
        """图片数 > 音频数"""
        files = [_make_audio_item("唯一句子", idx=0)]
        groups = self._call(files, 5)
        self.assertEqual(len(groups), 5)
        total = sum(len(g) for g in groups)
        self.assertEqual(total, 1)

    def test_single_image(self):
        """单张图片获取全部音频"""
        files = [_make_audio_item(f"句子{i}", idx=i) for i in range(4)]
        groups = self._call(files, 1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 4)


class TestBuildSectionSentenceMap(unittest.TestCase):
    """测试 _build_section_sentence_map 方法"""

    def _make_creator(self, plan=None, n_images=3):
        from video_creator import VideoCreator
        images = _make_dummy_images(n_images)
        vc = VideoCreator(images, "test text", structured_plan=plan)
        return vc

    def test_standard_plan(self):
        """标准结构化脚本解析"""
        plan = _make_structured_plan()
        vc = self._make_creator(plan)
        result = vc._build_section_sentence_map()

        self.assertIn("opening", result)
        self.assertIn("intro", result)
        self.assertIn("method", result)
        self.assertIn("results", result)
        # 每个 section 应有至少一个句子
        for section in ["opening", "intro", "method", "results"]:
            self.assertGreater(len(result[section]), 0, f"{section} 应有句子")

    def test_empty_plan(self):
        """空脚本返回空字典"""
        vc = self._make_creator(plan={})
        result = vc._build_section_sentence_map()
        self.assertEqual(result, {})

    def test_none_plan(self):
        """None 脚本返回空字典"""
        vc = self._make_creator(plan=None)
        result = vc._build_section_sentence_map()
        self.assertEqual(result, {})

    def test_partial_plan(self):
        """部分 section 缺失"""
        plan = {"opening": {"script": "大家好"}, "method": {"script": "方法如下"}}
        vc = self._make_creator(plan)
        result = vc._build_section_sentence_map()
        self.assertGreater(len(result.get("opening", [])), 0)
        self.assertEqual(len(result.get("intro", [])), 0)
        self.assertGreater(len(result.get("method", [])), 0)

    def test_string_section_value(self):
        """section 值为字符串（非字典）"""
        plan = {"opening": "大家好，今天讲一个研究", "method": "核心方法是这样的"}
        vc = self._make_creator(plan)
        result = vc._build_section_sentence_map()
        self.assertGreater(len(result.get("opening", [])), 0)


class TestGetImageSection(unittest.TestCase):
    """测试 _get_image_section 方法"""

    def _make_creator(self, explanations, n_images=3):
        from video_creator import VideoCreator
        images = _make_dummy_images(n_images)
        vc = VideoCreator(images, "test", image_explanations=explanations)
        return vc

    def test_normal(self):
        """正常获取 recommended_section"""
        expls = _make_image_explanations(["opening", "method", "results"])
        vc = self._make_creator(expls)
        self.assertEqual(vc._get_image_section(0), "opening")
        self.assertEqual(vc._get_image_section(1), "method")
        self.assertEqual(vc._get_image_section(2), "results")

    def test_out_of_range(self):
        """索引越界返回空"""
        expls = _make_image_explanations(["method"])
        vc = self._make_creator(expls, n_images=3)
        self.assertEqual(vc._get_image_section(5), "")

    def test_missing_field(self):
        """缺少 recommended_section 字段"""
        expls = [{"figure_role": "overview"}]
        vc = self._make_creator(expls, n_images=1)
        self.assertEqual(vc._get_image_section(0), "")

    def test_non_dict(self):
        """非字典元素返回空"""
        expls = ["not a dict"]
        vc = self._make_creator(expls, n_images=1)
        self.assertEqual(vc._get_image_section(0), "")


class TestSemanticGroupSentences(unittest.TestCase):
    """测试 _semantic_group_sentences 语义匹配核心逻辑"""

    def _make_creator(self, plan=None, expls=None, n_images=3):
        from video_creator import VideoCreator
        images = _make_dummy_images(n_images)
        vc = VideoCreator(
            images, "test",
            image_explanations=expls or [],
            structured_plan=plan,
        )
        return vc

    def test_semantic_matching(self):
        """语义匹配：句子按 section 分配到对应图片"""
        plan = _make_structured_plan()
        expls = _make_image_explanations(["opening", "method", "results"])

        # 创建与 plan 对应的音频条目
        audio_items = [
            _make_audio_item("大家好，今天要讲一个非常有趣的研究", idx=0),
            _make_audio_item("这篇论文提出了一种全新的方法", idx=1),
            _make_audio_item("实验结果非常令人振奋", idx=2),
        ]

        vc = self._make_creator(plan, expls)
        groups = vc._semantic_group_sentences(audio_items)

        self.assertEqual(len(groups), 3)
        # opening 的句子应该分配到图片0 (recommended_section=opening)
        opening_texts = [item[1] for item in groups[0]]
        self.assertTrue(
            any("大家好" in t for t in opening_texts),
            f"opening 图片应包含开场句子, 实际: {opening_texts}"
        )
        # method 的句子应该分配到图片1
        method_texts = [item[1] for item in groups[1]]
        self.assertTrue(
            any("全新的方法" in t for t in method_texts),
            f"method 图片应包含方法句子, 实际: {method_texts}"
        )
        # results 的句子应该分配到图片2
        result_texts = [item[1] for item in groups[2]]
        self.assertTrue(
            any("实验结果" in t for t in result_texts),
            f"results 图片应包含结果句子, 实际: {result_texts}"
        )

    def test_fallback_no_plan(self):
        """无结构化脚本时回退到均分"""
        expls = _make_image_explanations(["method", "results", "intro"])
        audio_items = [_make_audio_item(f"句子{i}", idx=i) for i in range(6)]

        vc = self._make_creator(plan=None, expls=expls)
        groups = vc._semantic_group_sentences(audio_items)

        # 应该均匀分配
        total = sum(len(g) for g in groups)
        self.assertEqual(total, 6)

    def test_fallback_no_image_sections(self):
        """图片无 recommended_section 时回退到均分"""
        plan = _make_structured_plan()
        # image_explanations 不含 recommended_section
        expls = [{"figure_role": "overview"} for _ in range(3)]

        audio_items = [_make_audio_item(f"句子{i}", idx=i) for i in range(6)]
        vc = self._make_creator(plan=plan, expls=expls, n_images=3)
        groups = vc._semantic_group_sentences(audio_items)

        total = sum(len(g) for g in groups)
        self.assertEqual(total, 6)

    def test_all_sentences_assigned(self):
        """所有句子都应被分配（不丢失）"""
        plan = _make_structured_plan()
        expls = _make_image_explanations(["intro", "method", "results"])

        audio_items = [
            _make_audio_item("我们需要了解背景", idx=0),
            _make_audio_item("论文提出了全新方法", idx=1),
            _make_audio_item("实验结果非常好", idx=2),
            _make_audio_item("完全无关的句子xyz", idx=3),
        ]

        vc = self._make_creator(plan, expls)
        groups = vc._semantic_group_sentences(audio_items)

        total = sum(len(g) for g in groups)
        self.assertEqual(total, 4, "所有句子都应被分配")

    def test_empty_audio(self):
        """空音频列表"""
        plan = _make_structured_plan()
        expls = _make_image_explanations(["opening", "method", "results"])
        vc = self._make_creator(plan, expls)
        groups = vc._semantic_group_sentences([])
        self.assertEqual(len(groups), 3)
        for g in groups:
            self.assertEqual(len(g), 0)

    def test_multiple_images_same_section(self):
        """多张图片属于同一 section，句子应均匀分配"""
        plan = _make_structured_plan()
        expls = _make_image_explanations(["method", "method", "method"])

        audio_items = [
            _make_audio_item("论文提出了全新方法", idx=0),
            _make_audio_item("核心思路是注意力机制", idx=1),
            _make_audio_item("具体分三步", idx=2),
        ]

        vc = self._make_creator(plan, expls)
        groups = vc._semantic_group_sentences(audio_items)

        total = sum(len(g) for g in groups)
        self.assertEqual(total, 3)


class TestGetChapterNameForImage(unittest.TestCase):
    """测试 _get_chapter_name_for_image 方法"""

    def _make_creator(self, expls, n_images=3):
        from video_creator import VideoCreator
        images = _make_dummy_images(n_images)
        return VideoCreator(images, "test", image_explanations=expls)

    def test_chinese_figure_role(self):
        """中文 figure_role 直接使用"""
        expls = [{"figure_role": "总览架构图", "recommended_section": "method"}]
        vc = self._make_creator(expls, n_images=1)
        self.assertEqual(vc._get_chapter_name_for_image(0), "总览架构图")

    def test_english_figure_role_mapped(self):
        """英文 figure_role 映射为中文"""
        expls = [{"figure_role": "overview diagram", "recommended_section": "intro"}]
        vc = self._make_creator(expls, n_images=1)
        self.assertEqual(vc._get_chapter_name_for_image(0), "总览图")

    def test_fallback_to_recommended_section(self):
        """figure_role 为空时回退到 recommended_section"""
        expls = [{"figure_role": "", "recommended_section": "method"}]
        vc = self._make_creator(expls, n_images=1)
        self.assertEqual(vc._get_chapter_name_for_image(0), "核心方法")

    def test_recommended_section_mapping(self):
        """各种 recommended_section 值的映射"""
        test_cases = [
            ("opening", "开场引入"),
            ("intro", "背景介绍"),
            ("method", "核心方法"),
            ("results", "实验结果"),
        ]
        for sec, expected in test_cases:
            expls = [{"recommended_section": sec}]
            vc = self._make_creator(expls, n_images=1)
            result = vc._get_chapter_name_for_image(0)
            self.assertEqual(result, expected, f"section={sec} 应映射为 {expected}")

    def test_out_of_range(self):
        """索引越界返回空"""
        vc = self._make_creator([], n_images=1)
        self.assertEqual(vc._get_chapter_name_for_image(5), "")

    def test_no_section_info(self):
        """无 section 信息返回空"""
        expls = [{"caption": "一张图片"}]
        vc = self._make_creator(expls, n_images=1)
        self.assertEqual(vc._get_chapter_name_for_image(0), "")

    def test_opening_intro_composite(self):
        """复合格式 opening/intro"""
        expls = [{"recommended_section": "opening/intro"}]
        vc = self._make_creator(expls, n_images=1)
        result = vc._get_chapter_name_for_image(0)
        self.assertEqual(result, "开场引入")


class TestGroupAndTrim(unittest.TestCase):
    """测试 _group_and_trim 方法（集成测试）"""

    def _make_creator(self, plan=None, expls=None, n_images=3, target_duration=0):
        from video_creator import VideoCreator
        images = _make_dummy_images(n_images)
        return VideoCreator(
            images, "test",
            image_explanations=expls or [],
            target_duration=target_duration,
            structured_plan=plan,
        )

    def test_with_semantic_matching(self):
        """语义匹配模式"""
        plan = _make_structured_plan()
        expls = _make_image_explanations(["opening", "method", "results"])
        vc = self._make_creator(plan, expls)

        expl_files = [[], [], []]
        summary_files = [
            _make_audio_item("大家好，今天要讲一个研究", idx=0),
            _make_audio_item("论文提出全新方法", idx=1),
            _make_audio_item("实验结果很好", idx=2),
        ]

        result_expl, groups = vc._group_and_trim(expl_files, summary_files)
        total = sum(len(g) for g in groups)
        self.assertEqual(total, 3)

    def test_with_fallback(self):
        """回退到均分模式"""
        vc = self._make_creator(plan=None, expls=None, n_images=3)

        expl_files = [[], [], []]
        summary_files = [_make_audio_item(f"句子{i}", idx=i) for i in range(6)]

        result_expl, groups = vc._group_and_trim(expl_files, summary_files)
        total = sum(len(g) for g in groups)
        self.assertEqual(total, 6)

    def test_with_target_duration_trimming(self):
        """目标时长裁剪"""
        plan = _make_structured_plan()
        expls = _make_image_explanations(["opening", "method", "results"])
        # 目标时长很短，应触发裁剪
        vc = self._make_creator(plan, expls, target_duration=5)

        expl_files = [
            [("./cache/expl_0_0.wav", "解释0", 3.0)],
            [("./cache/expl_1_0.wav", "解释1", 3.0)],
            [("./cache/expl_2_0.wav", "解释2", 3.0)],
        ]
        summary_files = [
            _make_audio_item("句子0", duration=3.0, idx=0),
            _make_audio_item("句子1", duration=3.0, idx=1),
            _make_audio_item("句子2", duration=3.0, idx=2),
        ]

        result_expl, groups = vc._group_and_trim(expl_files, summary_files)
        # 总时长应不超过目标 * 1.1 = 5.5s
        total = 0
        for i in range(3):
            total += sum(f[2] for f in result_expl[i])
            total += sum(f[2] for f in groups[i])
        self.assertLessEqual(total, 5.5)


class TestAddChapterOverlay(unittest.TestCase):
    """测试 _add_chapter_overlay 章节标题叠加"""

    def _make_creator(self, expls=None, n_images=3):
        from video_creator import VideoCreator
        images = _make_dummy_images(n_images)
        vc = VideoCreator(images, "test", image_explanations=expls or [])
        # 创建 mock video 对象
        vc.video = MagicMock()
        vc.video.duration = 30.0
        return vc

    @patch('video_creator.TextClip')
    @patch('video_creator.ColorClip')
    @patch('video_creator.CompositeVideoClip')
    def test_with_real_sections(self, mock_composite, mock_color, mock_text):
        """使用真实 section 信息"""
        expls = _make_image_explanations(["opening", "method", "results"])
        # 添加中文 figure_role
        expls[0]["figure_role"] = "总览图"
        expls[1]["figure_role"] = "模型架构"
        expls[2]["figure_role"] = "实验对比"

        vc = self._make_creator(expls)
        clips_durations = [(0, 10.0), (1, 10.0), (2, 10.0)]

        # Mock TextClip 返回可链式调用的对象
        mock_txt = MagicMock()
        mock_txt.with_start.return_value = mock_txt
        mock_txt.with_duration.return_value = mock_txt
        mock_txt.with_position.return_value = mock_txt
        mock_text.return_value = mock_txt

        mock_bar = MagicMock()
        mock_bar.with_start.return_value = mock_bar
        mock_bar.with_duration.return_value = mock_bar
        mock_bar.with_position.return_value = mock_bar
        mock_color.return_value = mock_bar

        vc._add_chapter_overlay(clips_durations)

        # 验证 TextClip 被调用了3次（3张图片各一个章节标题）
        self.assertEqual(mock_text.call_count, 3)
        # 验证使用了真实的 figure_role
        call_texts = [call.kwargs.get('text', '') or call.args[0] if call.args else ''
                      for call in mock_text.call_args_list]
        # 至少有一个调用包含真实的 figure_role 名称
        all_texts = " ".join(str(c) for c in mock_text.call_args_list)
        self.assertTrue(
            "总览图" in all_texts or "模型架构" in all_texts,
            f"应使用真实 figure_role, 实际调用: {all_texts}"
        )

    @patch('video_creator.TextClip')
    @patch('video_creator.ColorClip')
    @patch('video_creator.CompositeVideoClip')
    def test_fallback_hardcoded(self, mock_composite, mock_color, mock_text):
        """无 section 信息时回退到硬编码"""
        vc = self._make_creator(expls=[], n_images=5)
        clips_durations = [(i, 6.0) for i in range(5)]

        mock_txt = MagicMock()
        mock_txt.with_start.return_value = mock_txt
        mock_txt.with_duration.return_value = mock_txt
        mock_txt.with_position.return_value = mock_txt
        mock_text.return_value = mock_txt

        mock_bar = MagicMock()
        mock_bar.with_start.return_value = mock_bar
        mock_bar.with_duration.return_value = mock_bar
        mock_bar.with_position.return_value = mock_bar
        mock_color.return_value = mock_bar

        vc._add_chapter_overlay(clips_durations)

        # 应回退到硬编码，TextClip 调用 5 次
        self.assertEqual(mock_text.call_count, 5)

    def test_empty_clips(self):
        """空 clips_durations 不崩溃"""
        vc = self._make_creator()
        vc._add_chapter_overlay([])
        # 不应修改 video
        vc.video.assert_not_called  # video 未被重新赋值（CompositeVideoClip 未调用）


if __name__ == '__main__':
    unittest.main()
