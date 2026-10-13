"""数据模型与常量。

只认「diff 里的改动行」这一种坐标，所以模型刻意做得很小：
一个 :class:`Hunk` 装行号范围与正文，一个 :class:`Location` 装结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

# ---------------------------------------------------------------- 定位层级
#
# 从精确到宽泛。层与侧是**正交**的两个维度：层答「离它自己那个 hunk 有多远」，
# 侧答「行号该去哪一版里读」。

#: 在调用方指定的那个 hunk 里找到 —— 最精确的一层
LEVEL_HUNK = "hunk"
#: 在同一个集合里的**其它** hunk 里找到
LEVEL_GROUP = "group"
#: 没找到；坐标是 ``(0, 0)``
LEVEL_FAILED = "failed"

# ---------------------------------------------------- 未定位原因（仅失败时非空）

#: 片段为空或全是空白 —— 没有可定位的信息
REASON_EMPTY_SNIPPET = "empty_snippet"
#: 在某一层同一侧找到多处，无法判断是哪一处
REASON_MULTI_MATCH = "multi_match"
#: 两个层级都找过，一处也没命中
REASON_NO_MATCH = "no_match"

# ---------------------------------------------------------------- 侧
#
# 取值照抄 GitHub PR 行内评论的 `side` 参数，方便直接透传。

#: 新版的行号 —— 对应 diff 里 `+` 开头的行
SIDE_RIGHT = "RIGHT"
#: 旧版的行号 —— 对应 diff 里 `-` 开头的行
SIDE_LEFT = "LEFT"

SIDES = (SIDE_LEFT, SIDE_RIGHT)


@dataclass(frozen=True)
class Hunk:
    """一个 diff hunk。

    Attributes:
        id: 调用方给的标识。定位结果靠它指回原来那个 hunk —— 库本身不关心
            它长什么样，只要在同一个集合里唯一
        path: 文件路径（相对仓库根）。多文件一起传时用来区分来源，
            库不解析它
        old_start: 旧文件起始行号（1-based）
        old_lines: 旧文件行数；``0`` 表示该侧没有内容（纯新增）
        new_start: 新文件起始行号（1-based）
        new_lines: 新文件行数；``0`` 表示该侧没有内容（纯删除）
        content: hunk 正文，逐行带 ``+`` / ``-`` / 空格前缀，**不含** ``@@`` 头。
            这个形状与 ``git diff`` 的输出一致，所以从 diff 文本切出来的东西
            可以直接放进来
    """

    id: str
    path: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    content: str


class Location(NamedTuple):
    """一条片段的定位结果。

    Attributes:
        hunk_id: 命中的 hunk；未定位时是调用方 ``prefer`` 给的那个（没有则空串）
        start_line: 命中范围起始行，**按 ``side`` 解释**；未定位为 0
        end_line: 命中范围结束行，**按 ``side`` 解释**；未定位为 0
        level: 搜索层级，见 ``LEVEL_*``
        side: 行号属于哪一侧，见 ``SIDE_*``；未定位为 ``None``
        reason: 未定位原因，见 ``REASON_*``；定位成功为 ``None``
        candidates: 决定这次结果的候选数 —— 0 没找到、1 唯一、>1 表示在同一层
            同一侧找到多处。**>1 时只有 ``LEVEL_HUNK`` 会取首个**，
            其余情形直接判失败
    """

    hunk_id: str
    start_line: int
    end_line: int
    level: str
    side: str | None
    reason: str | None
    candidates: int = 0

    @property
    def found(self) -> bool:
        """是否定位成功。"""
        return self.level != LEVEL_FAILED
