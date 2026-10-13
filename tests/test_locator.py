"""定位的单元测试。

守的主要是三件事，**错了都没有任何信号**：

- **行号算对** —— 偏几行不影响运行，只是指向隔壁代码
- **侧算对** —— 行号挂着正确的那一版；标错侧等于让读者去错误的版本里找
- **不丢片段** —— 定位失败的也照样返回结果，只是带上原因

所以这里逐条钉住行号的推进规则与搜索优先级。
"""

from __future__ import annotations

from hunk_locate import (
    LEVEL_FAILED,
    LEVEL_GROUP,
    LEVEL_HUNK,
    REASON_EMPTY_SNIPPET,
    REASON_MULTI_MATCH,
    REASON_NO_MATCH,
    SIDE_LEFT,
    SIDE_RIGHT,
    Hunk,
    locate,
    normalize,
)


def make_hunk(
    hunk_id: str = "1",
    content: str = "",
    *,
    path: str = "a.go",
    new_start: int = 10,
    old_start: int = 10,
) -> Hunk:
    """构造一个带正文的 hunk。

    两侧起始行号**分开给**，因为它们在真实 diff 里经常不同（前面有过删除就会
    错开）—— 两侧的行号各自从自己的起点数，测试里也照实分开。

    Args:
        hunk_id: hunk 标识
        content: hunk 正文（diff 原文，带 `+` / `-` 前缀）
        path: 文件路径
        new_start: 新增侧起始行号
        old_start: 删除侧起始行号

    Returns:
        Hunk
    """
    body = content.splitlines()
    return Hunk(
        id=hunk_id,
        path=path,
        old_start=old_start,
        old_lines=sum(1 for line in body if line.startswith("-")),
        new_start=new_start,
        new_lines=sum(1 for line in body if line.startswith("+")),
        content=content,
    )


# ---------------------------------------------------------------- 归一化


def test_normalize_strips_prefix_and_whitespace() -> None:
    """行首的 diff 记号与首尾空白都去掉，缩进差异不影响匹配。"""
    assert normalize("+\tfoo()  ") == "foo()"
    assert normalize("-  foo()") == "foo()"
    assert normalize("  foo()  ") == "foo()"


def test_normalize_keeps_case() -> None:
    """大小写不动 —— `Err` 与 `err` 是两个东西。"""
    assert normalize("+Err") == "Err"
    assert normalize("+Err") != normalize("+err")


# ---------------------------------------------------- 行号：两侧各数各的


def test_added_lines_number_from_new_start() -> None:
    """新增侧的行号从 `new_start` 起，**删除行不占号**。

    这是行号算错的头号原因：把对面那侧的行也推进计数器，行号会整体偏移，
    而偏移后的值读起来完全正常 —— 不报错、不越界，只是指向隔壁几行。
    """
    hunk = make_hunk(
        "H-01",
        "-\tif err != nil {\n+\tif err == nil {\n+\t\treturn nil\n+\t}",
        new_start=20,
        old_start=7,
    )

    assert locate([hunk], "if err == nil {", prefer="H-01").start_line == 20
    assert locate([hunk], "return nil", prefer="H-01").start_line == 21
    assert locate([hunk], "}", prefer="H-01").start_line == 22


def test_deleted_lines_number_from_old_start() -> None:
    """删除侧的行号从 `old_start` 起，**新增行不占号**。

    与上一条对称。两侧起点在这条用例里特意错开（7 vs 20），用错一侧会得到
    一个明显不对、但看着很正常的数。
    """
    hunk = make_hunk(
        "H-01",
        "-\tif err != nil {\n-\t\treturn nil\n+\tif err == nil {",
        new_start=20,
        old_start=7,
    )

    assert locate([hunk], "-if err != nil {", prefer="H-01").start_line == 7
    assert locate([hunk], "-return nil", prefer="H-01").start_line == 8


def test_deleted_block_gives_the_whole_range() -> None:
    """整段删除给出旧版本的区间与 LEFT 侧。

    纯删除的 hunk（`new_lines == 0`）在新版本里没有任何位置 —— 挂到被删掉的
    那几行上，`side` 标明行号是旧版本的坐标。
    """
    hunk = make_hunk("H-01", '-\tif key == "" {\n-\t\treturn ""\n-\t}', new_start=6, old_start=7)

    found = locate([hunk], 'if key == "" {\n\treturn ""\n}', prefer="H-01")

    assert found.side == SIDE_LEFT
    assert (found.start_line, found.end_line) == (7, 9)
    assert found.level == LEVEL_HUNK


# -------------------------------------------------------- 侧：命中哪一版


def test_added_code_anchors_right() -> None:
    """新增的代码挂 RIGHT，行号是新版的坐标。"""
    hunk = make_hunk("H-01", "-\tfoo()\n+\tbar()", new_start=8, old_start=11)

    found = locate([hunk], "bar()", prefer="H-01")

    assert (found.side, found.start_line) == (SIDE_RIGHT, 8)


def test_deleted_code_anchors_left() -> None:
    """被删的代码挂 LEFT，行号是旧版的坐标。"""
    hunk = make_hunk("H-01", "-\tfoo()\n+\tbar()", new_start=8, old_start=11)

    found = locate([hunk], "foo()", prefer="H-01")

    assert (found.side, found.start_line) == (SIDE_LEFT, 11)


def test_plain_snippet_prefers_the_new_side() -> None:
    """没带记号的片段先试新增侧。

    两侧都能匹配时（这份 diff 是特意造的：同一行既是删的也是加的），新增侧
    胜出 —— 关心的是改动**之后**的状态。
    """
    hunk = make_hunk("H-01", "-\tfoo()\n+\tfoo()", new_start=8, old_start=11)

    found = locate([hunk], "foo()", prefer="H-01")

    assert (found.side, found.start_line) == (SIDE_RIGHT, 8)


def test_plain_snippet_falls_back_to_the_old_side() -> None:
    """没带记号、新增侧又找不到时，落到删除侧。

    从 diff 抄的时候可能顺手把 `-` 抹掉。抹掉了也照样该定位到被删的那一行，
    而不是判失败。
    """
    hunk = make_hunk("H-01", "-\toldCall()\n+\tnewCall()", new_start=8, old_start=11)

    found = locate([hunk], "oldCall()", prefer="H-01")

    assert (found.side, found.start_line) == (SIDE_LEFT, 11)


def test_mixed_snippet_anchors_the_added_part() -> None:
    """一半 `-` 一半 `+` 的片段挂在新增侧。

    想表达「把 A 换成了 B」时会连着抄两行。这段讲的是替换**之后**的代码，
    所以按 `+` 那部分定位；`-` 那部分只当上下文，不参与定案。
    """
    hunk = make_hunk("H-01", "-\toldCall()\n+\tnewCall()", new_start=8, old_start=11)

    found = locate([hunk], "-oldCall()\n+newCall()", prefer="H-01")

    assert (found.side, found.start_line) == (SIDE_RIGHT, 8)


def test_deleted_needle_is_tried_before_plain_on_the_old_side() -> None:
    """删除侧内部，带 `-` 记号的片段比不带记号的先试。

    两个 needle 在这份 diff 里都能命中删除侧（`first()` 在 old 11、`second()`
    在 old 12），明确标了 `-` 的那个更可信，所以结果该是 12 而不是 11。
    """
    hunk = make_hunk("H-01", "-\tfirst()\n+\tadded()\n-\tsecond()", new_start=8, old_start=11)

    found = locate([hunk], "-second()\nfirst()", prefer="H-01")

    assert (found.side, found.start_line) == (SIDE_LEFT, 12)


# ------------------------------------------------------------ 匹配的细节


def test_locate_multiline_range() -> None:
    """多行片段给出首尾行号。"""
    hunk = make_hunk("H-01", "+\tfunc f() {\n+\t\treturn nil\n+\t}")

    found = locate([hunk], "func f() {\n\treturn nil\n}", prefer="H-01")

    assert found.level == LEVEL_HUNK
    assert (found.start_line, found.end_line) == (10, 12)


def test_locate_ignores_prefix_and_indent() -> None:
    """从源码抄（不带 `+`、缩进不同）也能命中。"""
    hunk = make_hunk("H-01", "+\t\tif err != nil {")

    found = locate([hunk], "if err != nil {", prefer="H-01")

    assert found.level == LEVEL_HUNK
    assert found.start_line == 10


def test_locate_blank_line_does_not_break_match() -> None:
    """片段中间的空行不打断连续匹配。

    新增一个空行在 diff 里是孤零零一个 `+`，归一化后是空串。让它参与比对，
    「抄了空行的那条片段」就永远匹配不上。
    """
    hunk = make_hunk("H-01", "+\ta := 1\n+\n+\tb := 2")

    found = locate([hunk], "a := 1\n\nb := 2", prefer="H-01")

    assert (found.start_line, found.end_line) == (10, 12)


def test_multi_hit_in_hunk_takes_first() -> None:
    """**同一个 hunk 内**多命中取第一个，并记下候选数。

    两个候选都在同一段改动里，取首个比判失败划算 —— 代价只是行号可能偏几行。
    `candidates` 带出去，让调用方自己决定要不要盯着这个频率。
    """
    hunk = make_hunk("H-01", "+\treturn nil\n+\treturn nil")

    found = locate([hunk], "return nil", prefer="H-01")

    assert found.level == LEVEL_HUNK
    assert (found.start_line, found.end_line) == (10, 10)
    assert found.candidates == 2


# ------------------------------------------------------------ 第二层


def test_other_hunk_hit_rewrites_the_id() -> None:
    """在别的 hunk 里命中要**改写 id**。

    第二层可能在另一个文件里命中，而调用方往往靠 id 反查路径。保留原 id 的话，
    路径与行号会指向不同文件 —— 两个字段各说各话，还都不报错。
    """
    hunks = [
        make_hunk("H-01", "+\tfoo()", path="pkg/a.go"),
        make_hunk("H-02", "+\tbar()", path="pkg/b.go", new_start=33),
    ]

    found = locate(hunks, "bar()", prefer="H-01")

    assert found.level == LEVEL_GROUP
    assert found.hunk_id == "H-02"
    assert found.start_line == 33


def test_other_hunk_hit_keeps_its_side() -> None:
    """别处命中也要带上侧 —— 那个 hunk 里命中的可能是删除行。"""
    hunks = [
        make_hunk("H-01", "+\tfoo()", path="pkg/a.go"),
        make_hunk("H-02", "-\tbar()", path="pkg/b.go", old_start=44),
    ]

    found = locate(hunks, "-bar()", prefer="H-01")

    assert (found.level, found.side, found.start_line) == (LEVEL_GROUP, SIDE_LEFT, 44)


def test_own_hunk_beats_a_hit_elsewhere() -> None:
    """**层优先于侧** —— 本 hunk 的删除行命中，胜过别处的删除行命中。"""
    hunks = [
        make_hunk("H-01", "-\tdup()", path="pkg/a.go", old_start=5),
        make_hunk("H-02", "-\tdup()", path="pkg/b.go", old_start=44),
    ]

    found = locate(hunks, "-dup()", prefer="H-01")

    assert (found.level, found.hunk_id, found.start_line) == (LEVEL_HUNK, "H-01", 5)


# ------------------------------------------------ 上下文行（非 -U0 的 diff）


def test_leading_context_line_advances_the_new_side() -> None:
    """上下文行**要占号**。

    `git diff -U3` 的 hunk 正文里上下文行是常态。只在本侧记号上推进计数器的话，
    第一个 `+` 行会拿到 `new_start` 而不是 `new_start + 1` —— 算出来的行号读起来
    完全正常，只是指向上一行。
    """
    hunk = make_hunk("H-01", " \tctx()\n+\tnew()", new_start=10, old_start=10)

    found = locate([hunk], "new()", prefer="H-01")

    assert (found.side, found.start_line) == (SIDE_RIGHT, 11)


def test_context_line_advances_both_sides() -> None:
    """上下文行**两侧都推进** —— 旧版和新版的计数器各自前进一格。"""
    hunk = make_hunk("H-01", "-\told()\n \tctx()\n+\tnew()", new_start=10, old_start=7)

    assert locate([hunk], "-old()", prefer="H-01").start_line == 7
    assert locate([hunk], "+new()", prefer="H-01").start_line == 11


def test_context_line_does_not_shift_the_other_side() -> None:
    """一个方向上的上下文行，不该把另一个方向也带偏。

    三种记号混在一起时最容易写错：`+` 只推新版计数、`-` 只推旧版、空格推两边。
    """
    hunk = make_hunk(
        "H-01",
        " \ta()\n-\tb()\n+\tc()\n \td()\n-\te()\n+\tf()",
        new_start=100,
        old_start=200,
    )

    assert locate([hunk], "+c()", prefer="H-01").start_line == 101
    assert locate([hunk], "+f()", prefer="H-01").start_line == 103
    assert locate([hunk], "-b()", prefer="H-01").start_line == 201
    assert locate([hunk], "-e()", prefer="H-01").start_line == 203


def test_u0_hunk_numbering_is_unchanged() -> None:
    """没有上下文行时（`-U0`），行为与「只推进本侧」完全一致。

    回归守卫：上面那条修的是「有上下文行」的场景，别把主导场景改坏了。
    """
    hunk = make_hunk("H-01", "-\ta()\n+\tb()\n+\tc()", new_start=20, old_start=7)

    assert locate([hunk], "-a()", prefer="H-01").start_line == 7
    assert locate([hunk], "+b()", prefer="H-01").start_line == 20
    assert locate([hunk], "+c()", prefer="H-01").start_line == 21


def test_no_newline_marker_does_not_advance() -> None:
    r"""`\ No newline at end of file` 不占号。"""
    hunk = make_hunk(
        "H-01",
        "-a()\n\\ No newline at end of file\n+b()",
        new_start=10,
        old_start=10,
    )

    assert locate([hunk], "+b()", prefer="H-01").start_line == 10


def test_multi_hit_across_hunks_gives_up() -> None:
    """跨 hunk 多命中放弃 —— 两个候选可能是无关代码。"""
    hunks = [
        make_hunk("H-01", "+\tfoo()", path="pkg/a.go"),
        make_hunk("H-02", "+\tbar()", path="pkg/b.go"),
        make_hunk("H-03", "+\tbar()", path="pkg/c.go"),
    ]

    found = locate(hunks, "bar()", prefer="H-01")

    assert found.level == LEVEL_FAILED
    assert found.reason == REASON_MULTI_MATCH
    assert found.hunk_id == "H-01", "未定位时保留调用方给的那个 id"


def test_no_match_fails() -> None:
    """两层都没中 → 未定位。"""
    hunks = [make_hunk("H-01", "+\tfoo()")]

    found = locate(hunks, "这不是 diff 里的任何一行", prefer="H-01")

    assert found.level == LEVEL_FAILED
    assert found.reason == REASON_NO_MATCH
    assert (found.start_line, found.end_line, found.side) == (0, 0, None)


def test_empty_snippet_fails_with_its_own_reason() -> None:
    """空片段（含纯空白、纯空行）单独记原因。

    「没给锚点」与「给了但找不到」是两回事 —— 排障方向完全不同。
    """
    hunks = [make_hunk("H-01", "+\tfoo()")]

    for raw in ("", "   ", "\n\n", "+\n-"):
        found = locate(hunks, raw, prefer="H-01")
        assert found.reason == REASON_EMPTY_SNIPPET, raw


def test_prefer_is_optional() -> None:
    """不给 `prefer` 就跳过层 1，直接在全部 hunk 里找。"""
    hunks = [make_hunk("H-01", "+\tfoo()"), make_hunk("H-02", "+\tbar()", new_start=33)]

    found = locate(hunks, "bar()")

    assert (found.level, found.hunk_id, found.start_line) == (LEVEL_GROUP, "H-02", 33)


def test_prefer_pointing_at_a_missing_hunk_still_searches() -> None:
    """`prefer` 指了个不存在的 id —— 层 1 跳过，层 2 照常找。"""
    hunks = [make_hunk("H-01", "+\tfoo()"), make_hunk("H-02", "+\tbar()", new_start=33)]

    found = locate(hunks, "bar()", prefer="H-99")

    assert (found.level, found.hunk_id) == (LEVEL_GROUP, "H-02")


def test_found_property_tracks_the_level() -> None:
    """`Location.found` 就是 `level != failed`，别再让调用方自己拼。"""
    hunk = make_hunk("H-01", "+\tfoo()")

    assert locate([hunk], "foo()", prefer="H-01").found is True
    assert locate([hunk], "nope()", prefer="H-01").found is False
