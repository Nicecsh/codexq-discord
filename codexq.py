#!/usr/bin/env python3
"""Read Codex quota through Hermes's configured OpenAI Codex OAuth credential.

This module deliberately uses Hermes's credential resolver instead of the local
Codex CLI. It never prints, persists, or returns the OAuth credential, account
ID, user ID, or email supplied by the upstream usage endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import subprocess
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

REQUEST_TIMEOUT_SECONDS = 20
TIMEZONE = ZoneInfo("Asia/Shanghai")


class CodexQuotaError(RuntimeError):
    """A readable error raised while fetching Hermes Codex quota."""


def _app_server_request(process: subprocess.Popen[str], request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Make one bounded JSON-RPC request to a local Codex app server."""
    if process.stdin is None or process.stdout is None:
        raise CodexQuotaError("Codex app server 的标准输入输出不可用")
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n")
    process.stdin.flush()

    deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], min(1.0, deadline - time.monotonic()))
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
            raise CodexQuotaError(f"Codex 返回错误：{response['error'].get('message', '未知错误')}")
        result = response.get("result")
        return result if isinstance(result, dict) else {}
    raise CodexQuotaError(f"等待 Codex 响应超时（{REQUEST_TIMEOUT_SECONDS} 秒）")


def fetch_local_reset_credit_expirations(expected_count: int) -> list[int | float]:
    """Best-effort expiry supplement from Codex CLI, only when its count agrees.

    Hermes's OAuth usage endpoint exposes the reset-credit count but not each
    credit's expiration.  Codex CLI's app-server exposes expirations.  Never
    merge data from a potentially different local account: require the same
    available count before returning any expiration timestamp.
    """
    if expected_count <= 0:
        return []
    codex = shutil.which("codex")
    if not codex:
        return []
    process = subprocess.Popen(
        [codex, "app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1, env=os.environ.copy(),
    )
    try:
        _app_server_request(
            process, 1, "initialize",
            {"clientInfo": {"name": "hermes-codexq", "version": "1.2.0"}, "capabilities": {"experimentalApi": True}},
        )
        payload = _app_server_request(process, 2, "account/rateLimits/read", {})
    except (CodexQuotaError, OSError):
        return []
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    reset_credits = payload.get("rateLimitResetCredits")
    if not isinstance(reset_credits, dict) or reset_credits.get("availableCount") != expected_count:
        return []
    credits = reset_credits.get("credits")
    if not isinstance(credits, list):
        return []
    expirations: list[int | float] = []
    for credit in credits:
        if not isinstance(credit, dict) or credit.get("status") != "available":
            continue
        expiration = credit.get("expiresAt")
        if not isinstance(expiration, (int, float)):
            return []
        expirations.append(expiration)
    return sorted(expirations) if len(expirations) == expected_count else []


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


def format_summary(data: dict[str, Any], reset_credit_expirations: list[int | float] | None = None) -> str:
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
        if reset_credit_expirations:
            for index, expiration in enumerate(reset_credit_expirations, start=1):
                lines.append(f"  重置券 {index}：{format_time(expiration)} 到期")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 Hermes Codex OAuth 查询当前额度")
    parser.parse_args()
    try:
        data = fetch_usage()
        reset_credits = data.get("rate_limit_reset_credits") or {}
        available = reset_credits.get("available_count") if isinstance(reset_credits, dict) else 0
        expirations = fetch_local_reset_credit_expirations(available) if isinstance(available, int) else []
        print(format_summary(data, expirations))
    except CodexQuotaError as exc:
        print(f"codexq：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
