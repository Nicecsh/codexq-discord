#!/usr/bin/env python3
"""Read current Codex account rate limits through the local Codex app server.

The utility does not read, print, or persist authentication tokens. Authentication
is handled by an already logged-in Codex CLI instance.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

REQUEST_TIMEOUT_SECONDS = 45
TIMEZONE = ZoneInfo("Asia/Shanghai")


class CodexQuotaError(RuntimeError):
    """A readable error raised while querying Codex quota."""


def request(process: subprocess.Popen[str], request_id: int, method: str, params: dict) -> dict:
    """Send one JSON-RPC request and return the matching response payload."""
    if process.stdin is None or process.stdout is None:
        raise CodexQuotaError("Codex app server 的标准输入输出不可用")

    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()

    deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        ready, _, _ = select.select([process.stdout], [], [], min(1.0, remaining))
        if not ready:
            continue
        line = process.stdout.readline()
        if not line:
            raise CodexQuotaError("Codex app server 意外退出")
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if response.get("id") != request_id:
            continue
        if "error" in response:
            message = response["error"].get("message", "未知错误")
            raise CodexQuotaError(f"Codex 返回错误：{message}")
        return response.get("result", {})

    raise CodexQuotaError(f"等待 Codex 响应超时（{REQUEST_TIMEOUT_SECONDS} 秒）")


def fetch_rate_limits() -> dict:
    """Start Codex app-server and request the current account rate limits."""
    codex = shutil.which("codex")
    if not codex:
        raise CodexQuotaError("未找到 codex 命令；请确认 Codex CLI 已安装且在 PATH 中")

    process = subprocess.Popen(
        [codex, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )
    try:
        request(
            process,
            1,
            "initialize",
            {
                "clientInfo": {"name": "codexq-discord", "version": "1.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        return request(process, 2, "account/rateLimits/read", {})
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def format_time(timestamp: int | None) -> str:
    """Format an epoch timestamp in the configured display timezone."""
    if timestamp is None:
        return "未知"
    return datetime.fromtimestamp(timestamp, TIMEZONE).strftime("%m月%d日 %H:%M")


def format_summary(data: dict) -> str:
    """Return a human-readable Chinese summary without raw account metadata."""
    limits = data.get("rateLimits") or {}
    primary = limits.get("primary") or {}
    secondary = limits.get("secondary") or {}
    credits = limits.get("credits") or {}
    reset_credits = data.get("rateLimitResetCredits") or {}

    plan = limits.get("planType") or "未知"
    lines = [f"Codex 额度（{plan}）"]
    primary_used = primary.get("usedPercent")
    secondary_used = secondary.get("usedPercent")
    if primary_used is not None:
        lines.append(f"• 5小时窗口：剩余 {100 - primary_used}%（已用 {primary_used}%），{format_time(primary.get('resetsAt'))} 重置")
    if secondary_used is not None:
        lines.append(f"• 周窗口：剩余 {100 - secondary_used}%（已用 {secondary_used}%），{format_time(secondary.get('resetsAt'))} 重置")
    if credits.get("balance") is not None:
        lines.append(f"• 额外余额：${credits['balance']}")
    available = reset_credits.get("availableCount")
    if available is not None:
        lines.append(f"• 可用完整重置券：{available} 张")
        details = reset_credits.get("credits") or []
        if details and details[0].get("expiresAt"):
            lines.append(f"  到期：{format_time(details[0]['expiresAt'])}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="查询当前 Codex 账号额度")
    parser.add_argument("--json", action="store_true", help="输出 API 原始 JSON（可能包含账户元数据）")
    args = parser.parse_args()
    try:
        data = fetch_rate_limits()
    except CodexQuotaError as exc:
        print(f"codexq：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_summary(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
