"""Diff input preprocessing: filter non-code files and compute diffstat.

本模块不设条数/行数截断上限(全量保留),只做输入质量净化;diffstat 基于全部
diff 条目统计,过滤仅作用于文件级 diff 正文。
"""

from __future__ import annotations

from typing import Any

# 生成性构建产物路径前缀(小写匹配即过滤)。
GENERATED_PATH_PREFIXES = (
    "dist/",
    "build/",
    "coverage/",
    "node_modules/",
    "vendor/",
    "generated/",
    "gen/",
    "out/",
    "target/",
)

# 依赖锁文件 basename;以 .lock 结尾的文件按锁文件处理。
LOCKFILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "Pipfile.lock",
    "composer.lock",
    "Gemfile.lock",
    "bun.lockb",
    "yarn.lock.json",
}

BINARY_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".ttf",
    ".woff",
    ".woff2",
    ".eot",
    ".otf",
    ".zip",
    ".gz",
    ".tar",
    ".7z",
    ".rar",
    ".jar",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
)

_NUL_MARKER = "\0"


def is_filtered_diff_file(diff_file: dict[str, Any]) -> bool:
    """判断单个 GitLab diff 条目是否需要被过滤掉。"""

    path = (diff_file.get("new_path") or diff_file.get("old_path") or "").strip("/")
    normalized = path.lower()
    basename = normalized.rsplit("/", 1)[-1]
    if basename in LOCKFILE_NAMES or basename.endswith(".lock"):
        return True
    if normalized.startswith(GENERATED_PATH_PREFIXES):
        return True
    if normalized.endswith(BINARY_SUFFIXES):
        return True
    diff_text = diff_file.get("diff") or ""
    # diff 文本含 NUL 时必然是二进制输出;不按 "binary" 单词判断,避免误伤代码行。
    if _NUL_MARKER in diff_text:
        return True
    return False


def filter_diff_files(diff_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤 lockfile、生成文件与二进制,其余全量保留。"""

    return [diff_file for diff_file in diff_files if not is_filtered_diff_file(diff_file)]


def compute_diffstat(diff_files: list[dict[str, Any]]) -> tuple[int, int, int]:
    """统计 diffstat:(文件数, 新增行, 删除行)。

    按 diff 文本逐行估算:跳过 @@ 头、+++/- 头与 \\ No newline 标记;
    其余以 + / - 开头的行计入增删。
    """

    files = len(diff_files)
    additions = 0
    deletions = 0
    for diff_file in diff_files:
        diff_text = diff_file.get("diff") or ""
        for line in diff_text.splitlines():
            if line.startswith(("+++", "---", "@@", "\\")):
                continue
            if line.startswith("+"):
                additions += 1
            elif line.startswith("-"):
                deletions += 1
    return files, additions, deletions
