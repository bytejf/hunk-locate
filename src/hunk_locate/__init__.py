"""把一段代码片段对回它在 git diff 里的行号。

零依赖、零 LLM、同一输入同一输出。

    >>> from hunk_locate import parse_hunks, locate
    >>> hunks = parse_hunks(diff_text, path="pkg/store.go")
    >>> result = locate(hunks, "- if err != nil {")
    >>> result.found, result.side
    (True, 'LEFT')
"""

from hunk_locate.locator import MARKER_SIDE, locate, normalize
from hunk_locate.models import (
    LEVEL_FAILED,
    LEVEL_GROUP,
    LEVEL_HUNK,
    REASON_EMPTY_SNIPPET,
    REASON_MULTI_MATCH,
    REASON_NO_MATCH,
    SIDE_LEFT,
    SIDE_RIGHT,
    SIDES,
    Hunk,
    Location,
)
from hunk_locate.parser import parse_hunks

__all__ = [
    "LEVEL_FAILED",
    "LEVEL_GROUP",
    "LEVEL_HUNK",
    "MARKER_SIDE",
    "REASON_EMPTY_SNIPPET",
    "REASON_MULTI_MATCH",
    "REASON_NO_MATCH",
    "SIDES",
    "SIDE_LEFT",
    "SIDE_RIGHT",
    "Hunk",
    "Location",
    "locate",
    "normalize",
    "parse_hunks",
]
