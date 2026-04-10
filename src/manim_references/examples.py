"""ManimCE 参考示例 - 来自 manim_skill 最佳实践"""
from manim import *

class ColorCodedEquation(Scene):
    """展示公式着色的正确方式"""
    def construct(self):
        # 方法1：多部分 MathTex（推荐，最安全）
        eq = MathTex("E", "=", "m", "c^2")
        eq[0].set_color(YELLOW)  # E
        eq[2].set_color(BLUE)    # m
        eq[3].set_color(RED)     # c^2
        self.play(Write(eq))
        self.wait()

class EquationDerivation(Scene):
    """展示公式推导的正确方式：FadeOut旧的 + FadeIn新的"""
    def construct(self):
        # 第1步
        step1 = MathTex(r"x^2 - 5x + 6 = 0").shift(UP)
        self.play(Write(step1))
        self.wait()

        # 第2步：淡出旧的，淡入新的（不要用TransformMatchingTex）
        step2 = MathTex(r"(x-2)(x-3) = 0").shift(UP)
        self.play(FadeOut(step1), FadeIn(step2))
        self.wait()

        # 第3步
        step3 = MathTex(r"x = 2 \text{ or } x = 3")
        step3.next_to(step2, DOWN, buff=0.8)
        box = SurroundingRectangle(step3, color=GREEN, buff=0.15)
        self.play(Write(step3), Create(box))
        self.wait()

class CleanArchitectureDiagram(Scene):
    """展示模型架构图的正确方式"""
    def construct(self):
        title = Text("Model Architecture", font_size=28, color=YELLOW).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=0.8)

        # 模块用 Rectangle + Text，组合成 VGroup
        def make_module(name, color, w=2.5, h=0.7):
            box = Rectangle(width=w, height=h, color=color, fill_opacity=0.2)
            txt = Text(name, font_size=18, color=color).move_to(box)
            return VGroup(box, txt)

        enc = make_module("Encoder", BLUE).shift(UP*1.5)
        attn = make_module("Attention", ORANGE).shift(ORIGIN)
        dec = make_module("Decoder", GREEN).shift(DOWN*1.5)

        a1 = Arrow(enc.get_bottom(), attn.get_top(), buff=0.1, stroke_width=2)
        a2 = Arrow(attn.get_bottom(), dec.get_top(), buff=0.1, stroke_width=2)

        self.play(FadeIn(enc), run_time=0.6)
        self.play(GrowArrow(a1), run_time=0.4)
        self.play(FadeIn(attn), run_time=0.6)
        self.play(GrowArrow(a2), run_time=0.4)
        self.play(FadeIn(dec), run_time=0.6)
        self.wait()

        # 高亮关键模块
        self.play(Indicate(attn, color=YELLOW, scale_factor=1.05))
        self.wait()

class SafeFormulaDisplay(Scene):
    """LaTeX 公式的安全写法"""
    def construct(self):
        # 安全写法1：单一完整字符串（不拆分）
        f1 = MathTex(r"A = \mathrm{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}\right)V")
        f1.scale(0.85)
        self.play(Write(f1))
        self.wait()

        # 安全写法2：简单的多部分（不含括号嵌套）
        f2 = MathTex(r"\mathcal{L}", "=", r"\mathcal{L}_{\text{a}}", "+", r"\lambda", r"\mathcal{L}_{\text{p}}")
        f2[0].set_color(WHITE)
        f2[2].set_color(BLUE)
        f2[4].set_color(YELLOW)
        f2[5].set_color(GREEN)
        f2.next_to(f1, DOWN, buff=1)
        self.play(FadeOut(f1), Write(f2))
        self.wait()

        # 高亮用 SurroundingRectangle（不要用 set_color_by_tex + substrings_to_isolate）
        rect = SurroundingRectangle(f2[2], color=BLUE, buff=0.1)
        label = Text("Action Loss", font_size=18, color=BLUE).next_to(rect, DOWN, buff=0.2)
        self.play(Create(rect), FadeIn(label))
        self.wait()
