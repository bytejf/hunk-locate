# hunk-locate

[![CI](https://github.com/bytejf/hunk-locate/actions/workflows/ci.yml/badge.svg)](https://github.com/bytejf/hunk-locate/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Zero deps](https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square)](pyproject.toml)

**把一段代码片段对回它在 git diff 里的行号。** 零依赖、零模型调用、同一输入同一输出。

```python
from hunk_locate import parse_hunks, locate

hunks = parse_hunks(diff_text, path="pkg/store.go")
found = locate(hunks, "- if err != nil {")

found.hunk_id, found.side, found.start_line, found.end_line
# ('3', 'LEFT', 25, 27)
```

---

## 为什么需要这个

只要一个工具想**在 diff 的具体某一行上留下东西** —— 行内评论、代码建议、
注解、变更标记 —— 它就会撞上同一个问题：

> 我手里有一段代码，但我要的是**坐标**。

而坐标没那么简单，有三处容易做错：

**1. 行号只有一种，但版本有两个。** 同一个「第 25 行」，在新版和旧版里指的不是
同一处代码。GitHub / GitLab 的行内评论因此都带一个 `side`（`LEFT` / `RIGHT`）。
删除掉的行是**一等公民** —— 平台真正的约束从来不是「只能评论新行」，
而是「**行必须在 diff 里**」。把删除行丢掉，等于丢掉一整类发现。

**2. 片段可能带着 diff 的记号，也可能不带。** 行首的 `+` / `-` 是关于「哪一侧」
的唯一提示，但它常常被顺手抹掉。两种都得能处理。

**3. 行号算错不会有任何信号。** 计数多推一格，结果只是指向隔壁几行 ——
不报错、不越界、读起来完全正常。所以这个库的测试逐条钉住推进规则。

`hunk-locate` 把这部分做成一个确定性函数：给它 hunk 和一个片段，它给你坐标，
或者**明确告诉你为什么给不出来**。

## 安装

```bash
pip install hunk-locate
```

没有运行时依赖，纯标准库。

## 用法

### 从 diff 文本开始

```python
from hunk_locate import parse_hunks, locate

diff_text = """
@@ -10,2 +10,3 @@ func Load() {
 \tkey := "x"
-\told()
+\tnew()
+\tmore()
"""

hunks = parse_hunks(diff_text, path="pkg/store.go")
locate(hunks, "new()", prefer="1")
# Location(hunk_id='1', start_line=11, end_line=11, level='hunk',
#          side='RIGHT', reason=None, candidates=1)
```

注意 `+new()` 落在 **11** 而不是 10 —— 前面那行上下文占了新版的第一行。

`parse_hunks` 吃得下完整的 `git diff` 输出（`diff --git` / `index` / `---` / `+++`
那些行会被跳过），也吃得下裸的 hunk 段。

### 直接构造 hunk

已经有自己的 diff 表示时，不用重新解析：

```python
from hunk_locate import Hunk, locate

hunks = [
    Hunk(
        id="a",
        path="store.go",
        old_start=25,
        old_lines=3,
        new_start=24,
        new_lines=0,
        content="-\tif err != nil {\n-\t\treturn\n-\t}",
    ),
]

found = locate(hunks, "if err != nil {\n\treturn\n}", prefer="a")
assert (found.side, found.start_line, found.end_line) == ("LEFT", 25, 27)
```

### 给一个提示：这段大概在哪

知道片段「应该」属于哪个 hunk 时，传 `prefer` —— 先在那个 hunk 里找，
找不到再退回到全部 hunk。层 1 的候选面小得多，命中更可信：

```python
found = locate(hunks, "return nil", prefer="a")
```

### 结果怎么读

```python
found.found  # 定位成功了吗（level != 'failed'）
found.hunk_id  # 命中的 hunk；失败时是你 `prefer` 给的那个
found.side  # 'LEFT' / 'RIGHT'；失败时是 None
found.start_line  # 按 side 解释；失败时是 0
found.end_line
found.level  # 'hunk'（在 prefer 里）/ 'group'（在别处）/ 'failed'
found.reason  # 失败原因，见下
found.candidates  # 决定这次结果的候选数；>1 说明同一层同一侧有多处
```

| `reason` | 含义 | 该怎么办 |
|---|---|---|
| `empty_snippet` | 片段是空的 / 纯空白 | 上游没给锚点 —— 和「找不到」不是一回事 |
| `multi_match` | 同一层同一侧找到多处，无法判断 | 让上游把片段取长一点 |
| `no_match` | 全部找过，一处也没中 | 片段可能不在这次改动里 |

**失败不抛异常。** 调用方拿到的永远是同一个结构，只是 `found` 是 `False`。

## 设计要点

**层 × 侧是两个正交维度。** 层答「离它自己那个 hunk 有多远」，侧答「行号该去哪
一版里读」。搜索顺序是**层优先于侧** —— 本 hunk 里的 `LEFT` 命中，比别处的
`RIGHT` 命中可信得多。

**按行首记号拆成几组，固定优先级依次搜：**

| 优先级 | needle | 搜哪一侧 |
|---|---|---|
| 1 | `+` 行 | RIGHT |
| 2 | 无记号的 | RIGHT |
| 3 | `-` 行 | LEFT |
| 4 | 无记号的 | LEFT |

规则是「**第一个有命中的就定案**」。所以一半 `-` 一半 `+` 的片段（「把 A 换成
B」）落在 `+` 那侧 —— 它讲的是替换**之后**的代码。

**匹配永远单侧，但行号两侧都要看着。** 带记号的片段只跟同侧的行比，不跨侧；
而行号推进是「`+` 只推新版计数、`-` 只推旧版计数、**上下文行两侧都推**」。
这三条漏任何一条，算出来的行号都读起来完全正常 —— 只是指向隔壁几行。
第三条尤其容易漏：`-U0` 的 diff 里没有上下文行，只吃 `-U0` 时它永远不显形。

**多命中的处理是分层的**，不是一刀切：

- 在 `prefer` 指的那个 hunk 里 → **取第一个**。两个候选都在同一段改动里，
  取首个比判失败划算，代价只是行号可能偏几行。`candidates` 可用于区分该情况。
- 跨 hunk → **放弃**。两个候选可能根本是无关代码，猜错比不给更糟。

**归一化只去空白与记号，不动大小写。** `Err` 和 `err` 是两个东西。缩进也不影响：
缩进通常不承载语义，而且抄写时常常被重新缩进过。

## 边界

- **只匹配 diff 里的改动行。** 这是刻意的 —— 平台的行内评论也只能挂在改动行上，
  「文件里有、但这次没改」的行挂不出去。
- **不做模糊匹配。** 片段要么逐行对上，要么就是没命中。这个库的整个价值是
  「同一输入同一输出」，容错换来的是不可复现。
- **不读 git、不碰文件系统。** 输入就是文本和对象。
- **不解析路径。** `Hunk.path` 是给调用方区分来源用的，库不碰它。

## 开发

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
```

## License

[MIT](LICENSE)
