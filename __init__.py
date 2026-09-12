"""Hermes plugin that exposes the bundled Codex quota checker as /codexq."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_COMMAND = Path(__file__).with_name("codexq.py")
_TIMEOUT_SECONDS = 75


def _handle_codexq(raw_args: str) -> str:
    """Run the bundled quota checker without accepting shell input."""
    if raw_args.strip():
        return "用法：`/codexq`（不接受参数）"
    if not _COMMAND.is_file():
        return "❌ 插件安装不完整：未找到 codexq.py"

    try:
        completed = subprocess.run(
            [sys.executable, str(_COMMAND)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"❌ Codex 额度查询超时（{_TIMEOUT_SECONDS} 秒）"
    except OSError as exc:
        return f"❌ 无法执行 codexq：{exc}"

    output = (completed.stdout or "").strip()
    if completed.returncode == 0 and output:
        return output
    error = (completed.stderr or output or "未知错误").strip()
    return f"❌ Codex 额度查询失败（退出码 {completed.returncode}）：{error}"


def register(ctx) -> None:
    """Register the no-argument /codexq Hermes command."""
    ctx.register_command(
        "codexq",
        handler=_handle_codexq,
        description="查询当前 Codex 额度",
    )
