"""latex_utils 单元测试（feature: latex_utils）。

覆盖 extract_equations 的多环境/去重/忽略行内/截断，
以及 validate_latex 的合法接受 / 非法拒绝 / kill switch。
真编译用例依赖系统 latex；无 latex 时 skip（不 fail）。
"""

import shutil

import pytest

from src.latex_utils import extract_equations, validate_latex


_HAS_LATEX = shutil.which("latex") is not None
_skip_no_latex = pytest.mark.skipif(not _HAS_LATEX, reason="system latex unavailable")


# ---------- extract_equations ----------

def test_extract_equations_multiple_envs():
    tex = r"""
    Some text before.
    \begin{equation}E=mc^2\end{equation}
    middle text
    \begin{align}a&=b\\c&=d\end{align}
    and then $$x+y$$ trailing.
    """
    eqs = extract_equations(tex)
    assert len(eqs) == 3
    assert eqs[0] == "E=mc^2"
    assert eqs[1] == r"a&=b\\c&=d"
    assert eqs[2] == "x+y"


def test_extract_equations_dedup():
    tex = r"""
    \begin{equation}E=mc^2\end{equation}
    text
    \begin{equation}E=mc^2\end{equation}
    """
    eqs = extract_equations(tex)
    assert eqs == ["E=mc^2"]


def test_extract_equations_ignores_inline():
    tex = r"Here is inline $z$ and $a+b$ but display $$p=q$$ counts."
    eqs = extract_equations(tex)
    assert eqs == ["p=q"]
    assert "z" not in eqs
    assert "a+b" not in eqs


def test_extract_equations_respects_max_n():
    tex = "".join(
        r"\begin{equation}x_%d=%d\end{equation}" % (i, i) for i in range(20)
    )
    eqs = extract_equations(tex, max_n=5)
    assert len(eqs) == 5
    assert eqs[0] == "x_0=0"
    assert eqs[4] == "x_4=4"


def test_extract_equations_no_cross_env_match():
    """跨环境名片段（\\begin{align}...\\end{equation}）不应被当作一对提取。"""
    tex = r"\begin{align}x\end{equation}"
    eqs = extract_equations(tex)
    assert eqs == []
    # 星号变体也必须一致：\begin{align*}...\end{align} 不匹配
    tex2 = r"\begin{align*}y\end{align}"
    assert extract_equations(tex2) == []
    # 同名且星号一致仍正常匹配
    tex3 = r"\begin{align*}z\end{align*}"
    assert extract_equations(tex3) == ["z"]


# ---------- validate_latex ----------

@_skip_no_latex
def test_validate_latex_accepts_valid():
    assert validate_latex("E = mc^2") is True
    assert validate_latex(r"\frac{a}{b} + \sum_{i=1}^n x_i") is True


@_skip_no_latex
def test_validate_latex_rejects_broken():
    assert validate_latex(r"\frac{a") is False
    assert validate_latex(r"\left( x") is False


def test_validate_latex_killswitch(monkeypatch):
    monkeypatch.setenv("JSR_DISABLE_LATEX_VALIDATE", "1")
    assert validate_latex(r"\frac{a") is True
