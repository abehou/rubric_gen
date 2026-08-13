"""Safe source-code evidence rendering for PaperBench Code-Dev."""

from __future__ import annotations

import os
import stat
from pathlib import Path


_EXCLUDED_DIRECTORIES = {
    ".env", ".egg-info", ".git", ".github", ".venv", "__pycache__",
    "node_modules", "venv", "wandb",
}
_CODE_DEV_EXTENSIONS = {
    ".R", ".Rmd", ".c", ".cc", ".cfg", ".config", ".cpp", ".cxx",
    ".go", ".h", ".hpp", ".hxx", ".ini", ".java", ".jl", ".js",
    ".json", ".m", ".md", ".py", ".r", ".rs", ".rst", ".scala",
    ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml",
}


def render_submission_tree(workspace: Path) -> str:
    """Render regular plaintext source files under ``submission``."""

    submission = workspace / "submission"
    if submission.is_symlink() or not submission.is_dir():
        return "[No regular ./submission directory was provided.]"
    rendered: list[str] = []
    for path in sorted(submission.rglob("*")):
        relative = path.relative_to(submission)
        if any(part in _EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        value = os.lstat(path)
        if stat.S_ISDIR(value.st_mode):
            continue
        if not stat.S_ISREG(value.st_mode):
            raise ValueError(f"PaperBench submission has a non-regular entry: {path}")
        if path.suffix not in _CODE_DEV_EXTENSIONS:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rendered.append(
            f"## File: {relative.as_posix()}\n\n```text\n{content}\n```"
        )
    return "\n\n".join(rendered) or "[No readable source files were provided.]"
