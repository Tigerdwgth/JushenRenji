"""飞书多维表格上报 (POSTPONED).

未实现, 等用户配置 lark app_id / secret 后再补. 见 README Roadmap Task #3.

预期签名 (实现时遵守):

    push_to_lark(
        rows: list[dict],          # get_recent() 的输出, 已含 platform/post_id/...
        *,
        app_id: str | None = None, # 默认读 LARK_APP_ID
        app_secret: str | None = None,
        app_token: str | None = None,    # 多维表格 base 的 app_token
        table_id: str | None = None,
    ) -> dict                      # {"ok": bool, "inserted": N, "errors": [...]}
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


def push_to_lark(
    rows: Iterable[Dict[str, Any]],
    *,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
    app_token: Optional[str] = None,
    table_id: Optional[str] = None,
) -> Dict[str, Any]:
    """STUB. 配置 lark app credentials 后实现.

    实现要点 (写在这里以免实现时忘):

    - 优先复用用户全局 lark-cli skill (lark-base): subprocess 调
      ``lark-cli base record create --app-token ... --table-id ... --records ...``.
    - lark-cli 不可用时退到原生 OpenAPI:
        POST https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create
      字段名建议: 日期(date) / 平台(platform) / 视频ID(post_id) / 标题(title) /
      播放(views) / 点赞(likes) / 评论(comments) / 分享(shares) / 收藏(favorites).
    - PK = (platform, post_id, date), 重复时走 batch_update 而不是 batch_create.
    """
    raise NotImplementedError(
        "飞书多维表格上报待实现: 请配置 LARK_APP_ID / LARK_APP_SECRET / "
        "LARK_BASE_APP_TOKEN / LARK_BASE_TABLE_ID 后重试. "
        "详见 README Roadmap Task #3."
    )
