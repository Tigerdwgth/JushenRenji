# ManimCE LaTeX 安全规则

## 必须遵守
1. 公式用 `MathTex(r"...")` ，文字用 `Text("...")`
2. 始终用 raw string: `r"..."`
3. `\left(` 和 `\right)` 必须在同一个字符串参数中
4. 禁止 `substrings_to_isolate` — 会破坏括号匹配
5. 禁止 `set_color_by_tex()` — 不可靠
6. 禁止 `TransformMatchingTex` — 用 FadeOut + FadeIn 替代

## 着色正确方式
```python
# 方式1：拆分为多个参数（每个参数是独立的 LaTeX）
eq = MathTex("E", "=", "mc^2")
eq[0].set_color(RED)
eq[2].set_color(BLUE)

# 方式2：SurroundingRectangle 高亮
rect = SurroundingRectangle(eq[2], color=BLUE, buff=0.1)
```

## 布局规则
- 画框: X[-7,7], Y[-4,4]
- 同时最多 5 个元素
- font_size <= 28, 公式 scale <= 1.0
- 分步展示: FadeOut 旧内容再 FadeIn 新内容
