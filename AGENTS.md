# AGENTS.md

本文件记录本项目内代理执行时需要遵循的额外约定。

## 用户偏好

- 全程使用中文。
- 当任务与“论文视频生成 / 上传 / 补发 / 上传结果核验 / B站 cookie 更新”相关时，优先使用项目内技能 `skills/paper-video-generate-publish/SKILL.md`。
- 当用户要求“更新最新视频”“发送/发布到 B站 和 小红书”等同类任务，且未额外指定审核、确认、改文案或改参数时：
  - 不要连续追问澄清问题。
  - 直接按默认流程执行生成与发布。
  - 默认使用用户给定的查询词；若用户未给定，则沿用项目既有默认流程。
  - 默认自动发布到 `bilibili,xiaohongshu`。
  - 默认使用程序自动生成的标题、简介、标签与封面，不额外等待人工确认。
- 当用户要求“补发 B站”或“只重传 B站”时：
  - 默认复用现有 `output/` 中最近一次已生成的视频与封面。
  - 优先走仅 B 站补发流程，不重新生成整条视频。
- 当用户要求“更新 cookie”时：
  - 默认更新 `config.yaml` 中 `bilibili_cookies` 的 4 个核心字段：`sessdata`、`bili_jct`、`dedeuserid`、`dedeuserid_ckmd5`。
  - 忽略 `set-cookie`、`Path`、`Domain`、`Expires`、`SameSite` 等响应头元信息。
- 只有在缺少执行所必需的信息且无法从仓库或现有配置中推断时，才提出最少量的问题。
