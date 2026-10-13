"""核心：把一段代码片段对回它在 diff 里的行号。

**零 LLM，同一输入同一输出。**

## 两个维度：层 × 侧

===============  ======================  ==========================
维度              取值                    含义
===============  ======================  ==========================
**层**            ``hunk`` / ``group``    在哪个范围里找到的
                 / ``failed``
**侧**            ``LEFT`` / ``RIGHT``    命中的是新版还是旧版的行
===============  ======================  ==========================

层和侧**正交**：层答「离它自己那个 hunk 有多远」，侧答「行号该去哪一版里读」。

## 为什么删除行也要能挂

``side`` 照抄 GitHub 的 PR 行内评论模型。它的限制从来不是「只能评论新行」，
而是**「行必须在 diff 里」** —— 删除行是一等公民，hunk 之外的行才会被拒。

所以「这段代码被删掉了」这类片段不该丢进失败桶：它引用的**证据**是被删的那几行，
把行号挂回**旧版**才是精确的答案。

## 一个片段可能对应两套坐标 —— 按行首记号拆

片段的行首 ``+`` / ``-`` 记号**带不带都行**，而这个记号是关于「哪一侧」的唯一
提示。于是先按记号拆成几组，再按固定优先级依次搜：

=====  ==============  ==========
优先级  needle          搜哪一侧
=====  ==============  ==========
1      ``+`` 行        RIGHT
2      无记号的        RIGHT
3      ``-`` 行        LEFT
4      无记号的        LEFT
=====  ==============  ==========

**层优先于侧**：本 hunk 内的 LEFT 命中比别处的 RIGHT 命中精确得多，所以把一层里
的四组都比完，再进下一层。

规则是「**第一个有命中的就定案**」：混着抄（``-旧`` + ``+新``）时落在 ``+`` 那侧
—— 片段讲的是替换出来的新代码。同一侧多命中仍按层分：本 hunk 层取首个（两个候选
都在同一段改动里，取首个比丢进失败桶划算）、其余层放弃。
"""

from __future__ import annotations

from collections.abc import Sequence

from hunk_locate.models import (
    LEVEL_FAILED,
    LEVEL_GROUP,
    LEVEL_HUNK,
    REASON_EMPTY_SNIPPET,
    REASON_MULTI_MATCH,
    REASON_NO_MATCH,
    SIDE_LEFT,
    SIDE_RIGHT,
    Hunk,
    Location,
)

# 正文行首记号 → 该行属于哪一侧。空串表示抄来时把记号抹掉了，那就要两侧都试
# （见模块 docstring 的优先级表）
MARKER_SIDE: dict[str, str] = {"+": SIDE_RIGHT, "-": SIDE_LEFT}


def _marker(line: str) -> str:
    """取一行的 diff 记号。

    Args:
        line: 可能带 ``+`` / ``-`` 前缀的一行

    Returns:
        ``+`` / ``-``；没有记号时为空串
    """
    return line[:1] if line[:1] in MARKER_SIDE else ""


def normalize(line: str) -> str:
    """归一化一行：去掉 diff 行首的 ``+`` / ``-`` 记号与首尾空白。

    **大小写不动** —— ``Err`` 与 ``err`` 是两个东西。缩进也不影响：缩进通常不
    承载语义，而且抄写时常常被重新缩进过，不该因此定位失败。

    Args:
        line: 候选行（可能带前缀，也可能不带）

    Returns:
        归一化后的文本
    """
    body = line[1:] if _marker(line) else line
    return body.strip()


def _needles(snippet: str) -> dict[str, list[str]]:
    """按行首记号把片段拆成三组归一化后的行。

    空行一律丢掉：diff 里增删一个空行会渲染成孤零零一个 ``+`` / ``-``，归一化后
    是空串；让它参与比对只会把连续匹配打断。

    Args:
        snippet: 待定位的代码片段

    Returns:
        ``{"+": [...], "-": [...], "": [...]}``；空串那组是记号被抹掉了的
    """
    groups: dict[str, list[str]] = {marker: [] for marker in (*MARKER_SIDE, "")}
    for line in snippet.splitlines():
        text = normalize(line)
        if text:
            groups[_marker(line)].append(text)
    return groups


def _search_plan(groups: dict[str, list[str]]) -> list[tuple[str, list[str]]]:
    """按优先级列出 ``(侧, needle)``。

    Args:
        groups: :func:`_needles` 拆出来的三组

    Returns:
        搜索计划；片段里全是空行时为空列表
    """
    plus, minus, plain = groups["+"], groups["-"], groups[""]
    plan: list[tuple[str, list[str]]] = []
    if plus:
        plan.append((SIDE_RIGHT, plus))
    if plain:
        plan.append((SIDE_RIGHT, plain))
    if minus:
        plan.append((SIDE_LEFT, minus))
    if plain:
        plan.append((SIDE_LEFT, plain))
    return plan


def _side_lines(hunk: Hunk, side: str) -> list[tuple[int, str]]:
    """hunk 里**某一侧**的改动行，带该侧的行号。

    ``RIGHT`` 取 ``+`` 行、行号从 ``new_start`` 起；``LEFT`` 取 ``-`` 行、从
    ``old_start`` 起。

    **两个计数器各走各的**：``+`` 行只推进新版计数、``-`` 行只推进旧版计数，
    而上下文行（`` `` 开头）**两侧都推进**。这条是行号算对的关键，三处漏一处
    都不行：

    - 拿对面那侧的行推进本侧 → 改一行删一行的 hunk 会整体偏移
    - 上下文行不推进 → 从第一个上下文行起一直偏（``-U0`` 的 diff 里没有上下文行，
      所以只吃 ``-U0`` 时这个错永远不显形）

    两种偏移的结果都**不报错、不越界，读起来完全正常**，只是指向隔壁几行。

    Args:
        hunk: 一个 hunk
        side: ``LEFT`` / ``RIGHT``

    Returns:
        ``(该侧行号, 归一化后的正文)`` 列表
    """
    right = side == SIDE_RIGHT
    old_no, new_no = hunk.old_start, hunk.new_start
    lines: list[tuple[int, str]] = []
    for line in hunk.content.splitlines():
        head = line[:1]
        if head == "+":
            # 新增行只属于新版本 —— 它不占旧版本的号
            if right:
                lines.append((new_no, normalize(line)))
            new_no += 1
        elif head == "-":
            if not right:
                lines.append((old_no, normalize(line)))
            old_no += 1
        elif head == " " or line == "":
            # **上下文行两侧都占号**。漏掉这一步，行号会从第一个上下文行开始
            # 一直偏 —— 而 `-U0` 的 diff 里根本没有上下文行，所以在只吃 `-U0`
            # 的场景下这个错永远不显形（hunk-locate 吃得下任意 diff，会）
            old_no += 1
            new_no += 1
        # `\ No newline at end of file` 不占号
    return lines


def _matches(needle: list[str], lines: list[tuple[int, str]]) -> list[tuple[int, int]]:
    """在一侧的行里找 needle，返回所有命中的 ``(起始行, 结束行)``。

    两边都先去掉空行再比（理由同 :func:`_needles`）。

    Args:
        needle: 归一化并去掉空行后的片段（**非空**，调用方保证）
        lines: 带行号的一侧内容

    Returns:
        命中的行号区间列表，按位置升序
    """
    surface = [(number, text) for number, text in lines if text]
    width = len(needle)
    return [
        (surface[index][0], surface[index + width - 1][0])
        for index in range(len(surface) - width + 1)
        if [text for _, text in surface[index : index + width]] == needle
    ]


def locate(hunks: Sequence[Hunk], snippet: str, *, prefer: str | None = None) -> Location:
    """把一段代码片段挂到行号上。

    先试 ``prefer`` 指的那个 hunk（层 1），再试同一个序列里的其它 hunk（层 2）；
    **每层里都按 :func:`_search_plan` 的顺序试完两侧**才算这层没命中。

    Args:
        hunks: 候选 hunk（通常是同一个文件或同一个审查单元里的全部）
        snippet: 待定位的代码片段，行首可带 ``+`` / ``-``，也可以不带
        prefer: 期望命中的 hunk id。给了就先在它里面找 —— 层 1 比层 2 精确，
            因为候选面小得多。不给则直接进层 2

    Returns:
        定位结果。**失败不抛异常**，返回 ``level=failed`` 与原因，
        坐标是 ``(0, 0)``
    """
    plan = _search_plan(_needles(snippet))
    # 片段里的信息量可能为零：空串、纯空白、纯空行。它没有可定位的东西，
    # 但也不该被当成「没找到」—— 两种情形的排查方向完全不同
    if not plan:
        return Location(prefer or "", 0, 0, LEVEL_FAILED, None, REASON_EMPTY_SNIPPET)

    if prefer is not None:
        own = next((item for item in hunks if item.id == prefer), None)
        if own is not None:
            for side, needle in plan:
                hits = _matches(needle, _side_lines(own, side))
                if hits:
                    # 同一个 hunk 里多命中**取第一个**，不放弃：两个候选都在同一段
                    # 改动里，取首个比丢进失败桶划算（代价只是行号可能偏几行）。
                    # 代价靠 candidates 带出去，让调用方自己决定要不要盯着
                    return Location(
                        prefer, hits[0][0], hits[0][1], LEVEL_HUNK, side, None, len(hits)
                    )

    # 层 1 没中才走层 2 —— 它已经在最精确的那层找过两侧了
    for side, needle in plan:
        found = [
            (item.id, start, end)
            for item in hunks
            for start, end in _matches(needle, _side_lines(item, side))
        ]
        if len(found) == 1:
            hit_id, start, end = found[0]
            return Location(hit_id, start, end, LEVEL_GROUP, side, None, 1)
        if len(found) > 1:
            # 歧义即放弃：调用方看到 (0, 0) 知道要人工确认，看到错误行号会以为是对的
            return Location(prefer or "", 0, 0, LEVEL_FAILED, None, REASON_MULTI_MATCH, len(found))
    return Location(prefer or "", 0, 0, LEVEL_FAILED, None, REASON_NO_MATCH)
