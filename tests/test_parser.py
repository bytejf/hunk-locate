"""`parse_hunks` 的单元测试。

切 hunk 只有两种错法，都很难发现：**少切**（正文被并进上一个 hunk，行号悄悄
偏移）与**多切**（文件头被当成正文）。所以这里两边都钉住。
"""

from __future__ import annotations

from hunk_locate import parse_hunks

FULL_DIFF = """\
diff --git a/pkg/store.go b/pkg/store.go
index 1a2b3c4..5d6e7f8 100644
--- a/pkg/store.go
+++ b/pkg/store.go
@@ -10,3 +10,4 @@ func Load() {
 \tkey := "x"
-\told()
+\tnew()
+\tmore()
@@ -40,2 +41,0 @@ func Save() {
-\tdead()
-\tcode()
"""

BARE_HUNKS = """\
@@ -1,2 +1,3 @@
 a
+b
 c
@@ -9,0 +11,2 @@
+x
+y
"""


def test_full_git_diff_yields_hunks() -> None:
    """完整的 `git diff` 输出能直接吃 —— 文件头各归各，不进正文。"""
    hunks = parse_hunks(FULL_DIFF, path="pkg/store.go")

    assert len(hunks) == 2
    assert [h.id for h in hunks] == ["1", "2"]
    assert all(h.path == "pkg/store.go" for h in hunks)
    assert "\tdiff --git" not in hunks[0].content
    assert "index 1a2b3c4" not in hunks[0].content
    assert "+++ b/pkg/store.go" not in hunks[0].content


def test_header_numbers_are_parsed() -> None:
    """四个数字都按 git 的写法读出来。"""
    first, second = parse_hunks(FULL_DIFF)

    assert (first.old_start, first.old_lines, first.new_start, first.new_lines) == (10, 3, 10, 4)
    assert (second.old_start, second.old_lines, second.new_start, second.new_lines) == (
        40,
        2,
        41,
        0,
    )


def test_zero_lines_means_that_side_is_empty() -> None:
    """行数为 0 表示该侧没有内容 —— 纯删除的 hunk `new_lines == 0`。"""
    _, pure_deletion = parse_hunks(FULL_DIFF)

    assert pure_deletion.new_lines == 0
    assert pure_deletion.old_lines == 2


def test_body_keeps_every_line_verbatim() -> None:
    """正文逐字保留（含行首记号与缩进）—— 归一化是定位器的事，不是解析器的。"""
    first, _ = parse_hunks(FULL_DIFF)

    assert first.content.splitlines() == [
        ' \tkey := "x"',
        "-\told()",
        "+\tnew()",
        "+\tmore()",
    ]


def test_bare_hunk_section_without_file_header() -> None:
    """只有 hunk 段、没有文件头，也能切。"""
    hunks = parse_hunks(BARE_HUNKS)

    assert len(hunks) == 2
    assert hunks[0].content.splitlines() == [" a", "+b", " c"]
    assert hunks[1].content.splitlines() == ["+x", "+y"]


def test_omitted_line_count_means_one() -> None:
    """行数省略时是 1 行（git 的惯例），不是 0。"""
    hunks = parse_hunks("@@ -5 +7 @@\n-only\n+kept\n")

    assert len(hunks) == 1
    assert (hunks[0].old_start, hunks[0].old_lines) == (5, 1)
    assert (hunks[0].new_start, hunks[0].new_lines) == (7, 1)


def test_new_file_hunk_starts_at_zero() -> None:
    """新增文件的 hunk 是 `@@ -0,0 +1,N @@` —— 旧侧起点是 0，不是 1。"""
    (hunk,) = parse_hunks("@@ -0,0 +1,2 @@\n+a\n+b\n")

    assert (hunk.old_start, hunk.old_lines) == (0, 0)
    assert (hunk.new_start, hunk.new_lines) == (1, 2)


def test_hunk_header_context_after_the_at_signs_is_ignored() -> None:
    """`@@` 后面可以跟函数名之类的上下文，不参与解析。"""
    (hunk,) = parse_hunks("@@ -1 +1 @@ func Load() {\n-a\n+b\n")

    assert hunk.content.splitlines() == ["-a", "+b"]


def test_no_newline_marker_stays_in_the_body() -> None:
    r"""`\ No newline at end of file` 是正文的一部分。"""
    (hunk,) = parse_hunks("@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n")

    assert hunk.content.splitlines() == ["-a", "\\ No newline at end of file", "+b"]


def test_non_body_line_closes_the_hunk() -> None:
    """碰到非正文行就收口，后续内容不再并进这个 hunk。"""
    text = "@@ -1 +1 @@\n-a\n+b\ndiff --git a/x b/x\n@@ -9 +9 @@\n-q\n+r\n"

    hunks = parse_hunks(text)

    assert len(hunks) == 2
    assert hunks[0].content.splitlines() == ["-a", "+b"]


def test_empty_input_yields_nothing() -> None:
    """没有 hunk 就是空列表，不抛异常。"""
    assert parse_hunks("") == []
    assert parse_hunks("diff --git a/x b/x\nindex 1..2 100644\n") == []
