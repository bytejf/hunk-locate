"""从 unified diff 文本里切出 hunk。

只做一件事：把 ``@@`` 头与它后面的正文切成 :class:`~hunk_locate.models.Hunk`。
不做路径规范化、不读 git、不碰文件系统 —— 输入就是一段文本。
"""

from __future__ import annotations

import re

from hunk_locate.models import Hunk

# ``@@ -old_start[,old_lines] +new_start[,new_lines] @@`` 后接可选上下文。
# 行数省略时表示 1 行（git 的惯例）。
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# hunk 正文的行首记号：新增 / 删除 / 上下文，以及「文件末尾没有换行」那一行的 ``\``
_BODY_PREFIXES = ("+", "-", " ", "\\")


def parse_hunks(diff_text: str, *, path: str = "") -> list[Hunk]:
    """把一段 unified diff 文本切成 hunk 列表。

    容忍两种输入：完整的 ``git diff`` 输出（``diff --git`` / ``index`` /
    ``---`` / ``+++`` 这些行会被跳过），以及裸的 hunk 段。

    正文的边界是**行首记号**而不是「下一个 ``@@``」—— 这样碰到 ``diff --git``
    这类非正文行会立即收口，不会把它们混进上一个 hunk 的正文里。

    Args:
        diff_text: unified diff 文本，可以含多个 hunk
        path: 这些 hunk 属于哪个文件；纯信息，库不解析它

    Returns:
        hunk 列表，``id`` 按出现顺序从 ``"1"`` 起编号；一个都没有时返回空列表
    """
    hunks: list[Hunk] = []
    header: re.Match[str] | None = None
    body: list[str] = []

    def flush() -> None:
        """把攒着的这一段收成一个 Hunk。"""
        if header is None:
            return
        hunks.append(
            Hunk(
                id=str(len(hunks) + 1),
                path=path,
                old_start=int(header.group(1)),
                # 行数省略即 1 行
                old_lines=int(header.group(2) or 1),
                new_start=int(header.group(3)),
                new_lines=int(header.group(4) or 1),
                content="\n".join(body),
            )
        )

    for line in diff_text.splitlines():
        if (matched := _HUNK_HEADER_RE.match(line)) is not None:
            flush()
            header, body = matched, []
            continue
        if header is None:
            continue  # 第一个 @@ 之前的东西（diff --git、---、+++ …）不关心
        if line == "" or line[:1] in _BODY_PREFIXES:
            body.append(line)
            continue
        # 非正文行：收口，且**丢弃**这一段之后的内容直到下一个 @@
        flush()
        header, body = None, []

    flush()
    return hunks
