"""unit tests for src/arxiv_source_analyzer.py

全部用 unittest.mock 替换网络与 LLM 调用, 不访问真实 arxiv。
"""

import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from unittest import mock

from src import arxiv_source_analyzer as asa


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _make_tarball_bytes(file_specs):
    """把 {name: content_bytes} 打包为 tar.gz bytes。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in file_specs.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_malicious_tarball_bytes():
    """path traversal: 含 ../etc/passwd 的 tarball。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../etc/passwd")
        content = b"evil\n"
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
        info2 = tarfile.TarInfo(name="main.tex")
        content2 = b"\\documentclass{article}\\begin{document}hi\\end{document}"
        info2.size = len(content2)
        tar.addfile(info2, io.BytesIO(content2))
    return buf.getvalue()


# ----------------------------------------------------------------------
# 1. fetch_source
# ----------------------------------------------------------------------

class TestFetchSource(unittest.TestCase):

    def test_fetch_source_mock_request(self):
        """mock requests.get 返回 fixture tarball bytes → 文件落盘"""
        tarball_bytes = _make_tarball_bytes({
            "main.tex": b"\\documentclass{article}\\begin{document}x\\end{document}",
        })
        with tempfile.TemporaryDirectory() as cache:
            fake_resp = mock.MagicMock()
            fake_resp.iter_content.return_value = [tarball_bytes]
            fake_resp.raise_for_status = mock.MagicMock()
            with mock.patch("requests.get", return_value=fake_resp) as mget:
                path = asa.fetch_source("2410.11758", cache_root=cache, timeout=5)

            self.assertTrue(os.path.exists(path))
            self.assertEqual(os.path.getsize(path), len(tarball_bytes))
            mget.assert_called_once()
            # 2nd call: 命中缓存, 不应再调 requests
            with mock.patch("requests.get") as mget2:
                path2 = asa.fetch_source("2410.11758", cache_root=cache, timeout=5)
                mget2.assert_not_called()
            self.assertEqual(path, path2)


# ----------------------------------------------------------------------
# 2. extract_source path traversal
# ----------------------------------------------------------------------

class TestExtractSource(unittest.TestCase):

    def test_extract_source_path_traversal(self):
        """tarball 含 `../etc/passwd` 路径 → 抛 ValueError"""
        data = _make_malicious_tarball_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            tarball = os.path.join(tmp, "evil.tar.gz")
            with open(tarball, "wb") as f:
                f.write(data)
            dst = os.path.join(tmp, "out")
            with self.assertRaises(ValueError):
                asa.extract_source(tarball, dst)
            # 未意外在 tmp/etc/passwd 创建
            self.assertFalse(os.path.exists(os.path.join(tmp, "etc", "passwd")))

    def test_extract_source_size_limit(self):
        """fake 60MB tarball → 抛 SizeLimitError"""
        # 伪造 tar entry size=60MB, 但实际内容远小 (直接改 TarInfo.size)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(name="main.tex")
            big = b"x" * (60 * 1024 * 1024 + 1024)
            info.size = len(big)
            tar.addfile(info, io.BytesIO(big))
        data = buf.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            tarball = os.path.join(tmp, "big.tar.gz")
            with open(tarball, "wb") as f:
                f.write(data)
            dst = os.path.join(tmp, "out")
            with self.assertRaises(asa.SizeLimitError):
                asa.extract_source(tarball, dst, max_mb=50)


# ----------------------------------------------------------------------
# 3. find_main_tex
# ----------------------------------------------------------------------

class TestFindMainTex(unittest.TestCase):

    def test_find_main_tex_multi_candidate(self):
        """3 个 tex, 选 main.tex"""
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in [
                ("intro.tex", "\\section{Intro}"),
                ("main.tex", "\\documentclass{article}\\begin{document}\\end{document}"),
                ("tmp.tex", "\\section{Tmp}"),
            ]:
                with open(os.path.join(tmp, name), "w") as f:
                    f.write(content)
            main = asa.find_main_tex(tmp)
            self.assertIsNotNone(main)
            self.assertEqual(os.path.basename(main), "main.tex")


# ----------------------------------------------------------------------
# 4. resolve_includes cycle
# ----------------------------------------------------------------------

class TestResolveIncludes(unittest.TestCase):

    def test_resolve_includes_cycle(self):
        """a.tex \\input{b}, b.tex \\input{a} → 深度截断, 不死循环"""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.tex"), "w") as f:
                f.write("AAA\\input{b}\n")
            with open(os.path.join(tmp, "b.tex"), "w") as f:
                f.write("BBB\\input{a}\n")
            result = asa.resolve_includes(os.path.join(tmp, "a.tex"), tmp, depth=5)
            # 应能结束, 至少含 AAA, BBB
            self.assertIn("AAA", result)
            self.assertIn("BBB", result)
            # 不应无限长
            self.assertLess(len(result), 10000)


# ----------------------------------------------------------------------
# 5. expand_user_macros
# ----------------------------------------------------------------------

class TestExpandMacros(unittest.TestCase):

    def test_expand_user_macros_simple(self):
        tex = r"\newcommand{\mycls}{Transformer} \mycls is fast. \mycls."
        out = asa.expand_user_macros(tex)
        self.assertIn("Transformer is fast", out)
        self.assertIn("Transformer.", out)


# ----------------------------------------------------------------------
# 6. extract_figure_envs (tikz + raster)
# ----------------------------------------------------------------------

class TestExtractFigureEnvs(unittest.TestCase):

    def test_extract_figure_envs_tikz(self):
        tex = r"""
\begin{figure}
\centering
\begin{tikzpicture}
\node (a) at (0,0) {A};
\node (b) at (2,0) {B};
\end{tikzpicture}
\caption{Our proposed architecture for fast inference.}
\label{fig:main}
\end{figure}
"""
        with tempfile.TemporaryDirectory() as tmp:
            specs = asa.extract_figure_envs(tex, tmp)
            self.assertEqual(len(specs), 1)
            s = specs[0]
            self.assertEqual(s["kind"], "tikz")
            self.assertIn("architecture", s["caption"].lower())
            self.assertEqual(s["label"], "fig:main")

    def test_extract_figure_envs_raster_fallback(self):
        """含 \\includegraphics{fig.pdf} → kind=raster_pdf"""
        with tempfile.TemporaryDirectory() as tmp:
            # 造 figs/fig.pdf
            os.makedirs(os.path.join(tmp, "figs"), exist_ok=True)
            pdf_path = os.path.join(tmp, "figs", "fig.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4\nfake\n")
            tex = r"""
\begin{figure}
\includegraphics{figs/fig.pdf}
\caption{Raster figure.}
\label{fig:r}
\end{figure}
"""
            specs = asa.extract_figure_envs(tex, tmp)
            self.assertEqual(len(specs), 1)
            s = specs[0]
            self.assertEqual(s["kind"], "raster_pdf")
            self.assertTrue(s["source_path"].endswith("fig.pdf"))


# ----------------------------------------------------------------------
# 7. parse_tikz_structure basic
# ----------------------------------------------------------------------

class TestParseTikz(unittest.TestCase):

    def test_parse_tikz_structure_basic(self):
        body = r"""
\begin{tikzpicture}
\node [draw, fill=blue!30] (a) at (0,0) {A};
\node [draw, fill=red!30] (b) at (2,0) {B};
\draw (a) -> (b);
\end{tikzpicture}
"""
        struct = asa.parse_tikz_structure(body)
        self.assertIsNotNone(struct)
        self.assertEqual(len(struct["components"]), 2)
        self.assertEqual(len(struct["connections"]), 1)
        self.assertEqual(struct["connections"][0]["from"], "a")
        self.assertEqual(struct["connections"][0]["to"], "b")
        # layout 应是 left-to-right (x_spread=2 > y_spread=0)
        self.assertEqual(struct["layout_direction"], "left-to-right")


# ----------------------------------------------------------------------
# 8. select_main_figure_by_caption
# ----------------------------------------------------------------------

class TestSelectMainFigure(unittest.TestCase):

    def test_select_main_figure_by_caption_multi(self):
        specs = [
            {"caption": "Training loss curve.", "kind": "raster_pdf"},
            {"caption": "Overall architecture of our model.", "kind": "tikz"},
            {"caption": "Ablation results table.", "kind": "raster_png"},
        ]
        # mock LLM 返回 index=1
        with mock.patch.object(asa, "_llm_select_figure_index", return_value=1):
            chosen = asa.select_main_figure_by_caption(specs, paper_context="")
        self.assertIs(chosen, specs[1])

    def test_select_main_figure_single(self):
        specs = [{"caption": "X", "kind": "tikz"}]
        chosen = asa.select_main_figure_by_caption(specs, paper_context="")
        self.assertIs(chosen, specs[0])


# ----------------------------------------------------------------------
# 9. to_figure_analysis_dict schema
# ----------------------------------------------------------------------

class TestSchema(unittest.TestCase):

    def test_to_figure_analysis_dict_schema(self):
        struct = {
            "components": [
                {"id": "a", "raw_label": "A", "color": "blue", "shape": "rectangle",
                 "bbox_normalized": [0.1, 0.1, 0.3, 0.3], "_x_cm": 1, "_y_cm": 1},
                {"id": "b", "raw_label": "B", "color": "red", "shape": "rectangle",
                 "bbox_normalized": [0.5, 0.1, 0.7, 0.3], "_x_cm": 3, "_y_cm": 1},
            ],
            "connections": [
                {"from": "a", "to": "b", "type": "arrow", "label": "",
                 "description": ""}
            ],
            "canvas_size": [1000, 700],
            "layout_direction": "left-to-right",
        }
        result = asa.to_figure_analysis_dict(struct, (1000, 700), "arxiv_latex_tikz")
        # 与 _merge_analyses 输出的关键字段子集对齐
        required_keys = {
            "figure_type", "layout_direction", "components", "connections",
            "data_flow", "key_innovation", "animation_suggestion",
            "has_neural_network", "nn_layers", "has_precise_bbox",
            "eb_element_count", "canvas_size", "source",
        }
        self.assertTrue(required_keys.issubset(set(result.keys())))
        self.assertTrue(result["has_precise_bbox"])
        self.assertEqual(result["source"], "arxiv_latex_tikz")
        self.assertEqual(len(result["components"]), 2)
        # 每个 component 至少有 name/position/color/shape/bbox_normalized
        for c in result["components"]:
            self.assertIn("name", c)
            self.assertIn("position", c)
            self.assertIn("color", c)
            self.assertIn("shape", c)
            self.assertIn("bbox_normalized", c)
            self.assertEqual(len(c["bbox_normalized"]), 4)
        # connection from/to 被映射为 component.name
        names = {c["name"] for c in result["components"]}
        for cn in result["connections"]:
            self.assertIn(cn["from"], names)
            self.assertIn(cn["to"], names)


# ----------------------------------------------------------------------
# 10. try_structured_figure: raster-only → None (no tikz)
# ----------------------------------------------------------------------

class TestTryStructuredFigure(unittest.TestCase):

    def test_try_structured_figure_fallback_on_no_tikz(self):
        """mock extract_figure_envs 返回全 raster 且无有效源 → 最终返回 None"""
        with tempfile.TemporaryDirectory() as cache:
            aid = "9999.99999"
            src_dir = os.path.join(cache, "arxiv_src", aid)
            os.makedirs(src_dir, exist_ok=True)
            with open(os.path.join(src_dir, ".manifest.json"), "w") as f:
                json.dump({"fetched_at": "now"}, f)
            with open(os.path.join(src_dir, "main.tex"), "w") as f:
                f.write(r"\documentclass{article}\begin{document}\end{document}")

            # 让 extract 阶段返回全 raster (都没有实际 PDF 内容)
            fake_specs = [{
                "body": "", "caption": "fake", "label": "fig:r",
                "kind": "raster_pdf", "source_path": "/no/such/file.pdf",
            }]
            with mock.patch.object(asa, "extract_figure_envs",
                                    return_value=fake_specs), \
                 mock.patch.object(asa, "compile_tex_to_pdf", return_value=None):
                result = asa.try_structured_figure(
                    arxiv_id=aid,
                    method_image_path="/nope.png",
                    cache_root=cache,
                )
            self.assertIsNone(result)

    def test_try_structured_figure_timeout_graceful(self):
        """mock fetch_source 抛 TimeoutError → 返回 None 不抛"""
        with tempfile.TemporaryDirectory() as cache:
            # 用真实 fetch (没 manifest)
            with mock.patch.object(asa, "fetch_source",
                                    side_effect=TimeoutError("boom")):
                result = asa.try_structured_figure(
                    arxiv_id="1234.56789",
                    method_image_path="/nope.png",
                    cache_root=cache,
                )
            self.assertIsNone(result)


# ----------------------------------------------------------------------
# 14. integration: analyze_and_prepare front-door
# ----------------------------------------------------------------------

class TestAnalyzeAndPrepareFrontDoor(unittest.TestCase):

    def test_integration_analyze_and_prepare_latex_front_door(self):
        """mock try_structured_figure 返回 fake latex analysis
        + mock analyze_figure_with_vision_llm 返回 vision
        → analyze_and_prepare 返回含 source=arxiv_latex 的 dict
        """
        from src import figure_analyzer as fa

        fake_latex = {
            "figure_type": "architecture",
            "layout_direction": "left-to-right",
            "components": [
                {"name": "Node_A", "chinese_name": "", "type": "module",
                 "position": "left", "color": "blue", "shape": "rectangle",
                 "size": "medium", "children": [], "description": "",
                 "bbox_normalized": [0.1, 0.1, 0.3, 0.3]},
                {"name": "Node_B", "chinese_name": "", "type": "module",
                 "position": "right", "color": "red", "shape": "rectangle",
                 "size": "medium", "children": [], "description": "",
                 "bbox_normalized": [0.5, 0.1, 0.7, 0.3]},
            ],
            "connections": [{"from": "Node_A", "to": "Node_B",
                             "type": "arrow", "label": "", "description": ""}],
            "data_flow": "", "key_innovation": "", "animation_suggestion": "",
            "has_neural_network": False, "nn_layers": [],
            "has_precise_bbox": True, "eb_element_count": 2,
            "canvas_size": [1000, 700], "source": "arxiv_latex_tikz",
        }
        fake_vision = {
            "figure_type": "architecture",
            "key_innovation": "Fast routing",
            "data_flow": "A goes to B",
            "animation_suggestion": "Show A then B",
            "has_neural_network": True,
            "nn_layers": ["attention"],
            "components": [
                {"name": "Encoder", "chinese_name": "编码器",
                 "description": "Extract features"},
                {"name": "Decoder", "chinese_name": "解码器",
                 "description": "Generate output"},
            ],
            "connections": [],
        }

        with mock.patch("src.arxiv_source_analyzer.try_structured_figure",
                         return_value=fake_latex), \
             mock.patch.object(fa, "analyze_figure_with_vision_llm",
                                return_value=fake_vision), \
             mock.patch.dict(os.environ, {"JSR_DISABLE_LATEX_SOURCE": ""},
                              clear=False):
            # method_image_path 不存在, 但 front-door 路径不校验, 直接调 try_structured_figure
            result = fa.analyze_and_prepare(
                image_path="/tmp/nope.png",  # 仅占位
                paper_context="fake ctx",
                arxiv_id="2410.11758",
            )
        self.assertIsNotNone(result["analysis"])
        self.assertEqual(result["analysis"]["source"], "arxiv_latex_tikz")
        # 语义字段由 vision 补齐
        self.assertEqual(result["analysis"]["key_innovation"], "Fast routing")
        self.assertTrue(result["analysis"]["has_neural_network"])
        # vision 覆盖了 name/chinese_name/description
        comp_names = [c["name"] for c in result["analysis"]["components"]]
        self.assertIn("Encoder", comp_names)
        self.assertIn("Decoder", comp_names)
        # eb_manim_elements 字段存在
        self.assertIn("eb_manim_elements", result)


if __name__ == "__main__":
    unittest.main()
