#!/usr/bin/env python3
"""Read Codex quota through Hermes's configured OpenAI Codex OAuth credential.

This module deliberately uses Hermes's credential resolver instead of the local
Codex CLI. It never prints, persists, or returns the OAuth credential, account
ID, user ID, or email supplied by the upstream usage endpoint.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

REQUEST_TIMEOUT_SECONDS = 20
TIMEZONE = ZoneInfo("Asia/Shanghai")


class CodexQuotaError(RuntimeError):
    """A readable error raised while fetching Hermes Codex quota."""


def fetch_usage() -> dict[str, Any]:
    """Fetch usage with Hermes's own resolved Codex OAuth credential.

    Imports are intentionally delayed: source inspection and unit tests do not
    need a Hermes runtime, while the installed plugin always runs inside one.
    """
    try:
        import httpx
        from agent.codex_headers import codex_cloudflare_headers
        from hermes_cli.auth_codex import _codex_usage_probe_url, resolve_codex_runtime_credentials
    except ImportError as exc:
        raise CodexQuotaError("此命令必须在 Hermes Agent 的 Python 环境中运行") from exc

    credentials = resolve_codex_runtime_credentials()
    token = credentials.get("api_key")
    base_url = credentials.get("base_url")
    if not isinstance(token, str) or not token or not isinstance(base_url, str) or not base_url:
        raise CodexQuotaError("未找到 Hermes 配置的 Codex OAuth 凭据")

    headers = codex_cloudflare_headers(token, base_url=base_url)
    headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
    url = _codex_usage_probe_url(base_url)
    try:
        response = httpx.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise CodexQuotaError("无法连接 Codex 额度服务") from exc
    if response.status_code != 200:
        raise CodexQuotaError(f"Codex 额度服务返回 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise CodexQuotaError("Codex 额度服务返回了无效响应") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("rate_limit"), dict):
        raise CodexQuotaError("Codex 额度服务响应格式不完整")
    return payload


def format_time(timestamp: int | float | None) -> str:
    """Format an epoch timestamp in the configured display timezone."""
    if not isinstance(timestamp, (int, float)):
        return "未知"
    return datetime.fromtimestamp(timestamp, TIMEZONE).strftime("%m月%d日 %H:%M")


def _format_window(label: str, window: Any) -> str | None:
    if not isinstance(window, dict):
        return None
    used = window.get("used_percent")
    if not isinstance(used, (int, float)):
        return None
    remaining = max(0, min(100, 100 - used))
    return f"• {label}：剩余 {remaining}%（已用 {used}%），{format_time(window.get('reset_at'))} 重置"


def format_summary(data: dict[str, Any]) -> str:
    """Return quota-only output, excluding account and user metadata."""
    rate_limit = data.get("rate_limit") or {}
    credits = data.get("credits") or {}
    reset_credits = data.get("rate_limit_reset_credits") or {}

    plan = data.get("plan_type") if isinstance(data.get("plan_type"), str) else "未知"
    lines = [f"Codex 额度（{plan}）"]
    for label, key in (("5小时窗口", "primary_window"), ("周窗口", "secondary_window")):
        line = _format_window(label, rate_limit.get(key))
        if line:
            lines.append(line)
    balance = credits.get("balance") if isinstance(credits, dict) else None
    if balance is not None:
        lines.append(f"• 额外余额：${balance}")
    available = reset_credits.get("available_count") if isinstance(reset_credits, dict) else None
    if isinstance(available, int):
        lines.append(f"• 可用完整重置券：{available} 张")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 Hermes Codex OAuth 查询当前额度")
    parser.parse_args()
    try:
        print(format_summary(fetch_usage()))
    except CodexQuotaError as exc:
        print(f"codexq：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
