#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo: 用 qwen-vl（dashscope key）对 `./pic/1.png` 做图像解释并保存结果到 `./cache`。"""
import os
import json
from pathlib import Path

try:
    from src.llm_tools.image_agent import ImageAgent
except Exception:
    from llm_tools.image_agent import ImageAgent


def main():
    img_path = Path("./pic/1.png")
    if not img_path.exists():
        print("未找到 ./pic/1.png ，请先运行图片提取或手动放置一张图片到该路径。")
        return
    agent = ImageAgent()
    res = agent.explain_image(str(img_path))
    os.makedirs("./cache", exist_ok=True)
    out_file = Path("./cache/image_explain_demo.json")
    out_file.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存解释到 {out_file}")
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
