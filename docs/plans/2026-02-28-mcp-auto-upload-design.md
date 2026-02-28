# MCP 自动上传修复设计（Bilibili + 小红书）

- 日期：2026-02-28
- 作用范围：`worktrees/bilibili-upload`
- 目标：修复 Bilibili / 小红书 MCP 自动上传失效问题，并将上传能力重构为可参数控制的独立开关。

## 1. 背景与问题

当前代码存在以下核心问题：

1. `src/main.py` 直接调用异步函数 `upload_video_to_bilibili_mcp(...)`，但未 `await`，导致上传行为不可靠。
2. `src/distribution/xiaohongshu.py` 将异步请求函数当作同步函数使用，导致登录检查与发布流程可能始终异常。
3. 上传流程分散在主流程中，缺少统一编排、错误隔离和结果汇总机制。

## 2. 目标与约束

## 2.1 目标

1. 增加独立上传参数 `--platforms`，由参数控制是否上传及上传平台。
2. 默认双平台上传：`bilibili,xiaohongshu`。
3. 平台失败互不影响：一个平台失败不阻断另一个平台。
4. 小红书先走“图文上传”，内容在运行时合成（暂不依赖主分支 Markdown 功能）。

## 2.2 非目标

1. 不在本次实现平台插件化抽象（避免过度设计）。
2. 不在本次打通主分支 Markdown 笔记产物读取。

## 3. 方案总览（推荐方案 2：轻量编排层）

新增一个分发编排层，把平台上传控制逻辑从 `main.py` 解耦。

- `src/main.py`
  - 负责视频生成与 CLI 参数解析
  - 调用统一编排入口
- `src/distribution/orchestrator.py`（新增）
  - 解析平台参数
  - 组装各平台 payload
  - 顺序调用平台上传并隔离异常
  - 返回统一结果摘要
- `src/distribution/bilibili.py`
  - 提供稳定同步调用入口（内部处理 async）
- `src/distribution/xiaohongshu.py`
  - 修复 async/sync 混用问题
  - 提供同步图文发布接口

## 4. CLI 与行为定义

## 4.1 参数定义

新增：

- `--platforms`
  - 格式：逗号分隔，例如 `bilibili,xiaohongshu`
  - 支持值：`bilibili`、`xiaohongshu`、`none`
  - 默认值：`bilibili,xiaohongshu`

## 4.2 行为规则

1. 未传 `--platforms`：默认双平台上传。
2. `--platforms bilibili`：仅上传 Bilibili。
3. `--platforms xiaohongshu`：仅上传小红书图文。
4. `--platforms bilibili,xiaohongshu`：两平台都上传。
5. `--platforms none` 或空值：不上传，仅生成视频。
6. 未知平台值：记录 warning 并忽略，不中断已识别平台。

## 5. 数据流设计

1. 主流程生成视频后得到：
   - `video_path`
   - `cover_path`
   - `video_title`
   - `video_desc`
   - `titles/cn_titles`（用于文案拼接）
2. 调用 `upload_generated_content(...)`：
   - Bilibili：上传视频
   - 小红书：发布图文笔记
3. 小红书图文内容（临时合成）
   - `title`：优先中文标题，截断到 20 字
   - `content`：由论文标题与简介拼接，截断到 1000 字
   - `images`：优先封面图 + `./pic/*.png` 前 N 张（默认 N=8，至少 1 张）

## 6. 错误处理与返回结构

## 6.1 失败隔离

每个平台独立 `try/except`：

- Bilibili 失败：记录失败并继续执行小红书
- 小红书失败：记录失败并保留 Bilibili 结果

## 6.2 前置校验

- Bilibili：`video_path` 必须存在
- 小红书：`images` 至少有 1 张存在文件

## 6.3 返回结构（示例）

```json
{
  "bilibili": {"ok": true, "id": "BV..."},
  "xiaohongshu": {"ok": false, "error": "not logged in"}
}
```

## 7. 验收标准

1. `--platforms bilibili` 仅触发 Bilibili。
2. `--platforms xiaohongshu` 仅触发小红书图文。
3. `--platforms bilibili,xiaohongshu` 两者都触发，单平台失败不影响另一平台。
4. `--platforms none` 不触发上传。
5. 日志输出包含每个平台开始/成功/失败以及最终 summary。

## 8. 风险与后续

1. 小红书内容仍为运行时拼接，质量受输入文本结构影响。
2. 后续可接入主分支 Markdown 产物：只需替换 orchestrator 内容组装逻辑。
3. 后续可补充重试策略与并发上传（当前先用顺序执行提升稳定性）。
