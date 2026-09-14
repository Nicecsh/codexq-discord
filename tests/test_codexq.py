from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quota = load_module("codexq", ROOT / "codexq.py")
plugin = load_module("codexq_plugin", ROOT / "__init__.py")


class FormatSummaryTests(unittest.TestCase):
    def test_summary_keeps_quota_fields_and_drops_user_metadata(self):
        result = quota.format_summary(
            {
                "user_id": "must-not-appear",
                "account_id": "must-not-appear",
                "email": "must-not-appear@example.invalid",
                "plan_type": "plus",
                "rate_limit": {
                    "primary_window": {"used_percent": 25, "reset_at": 0},
                    "secondary_window": {"used_percent": 10, "reset_at": 0},
                },
                "credits": {"balance": "12.5"},
                "rate_limit_reset_credits": {"available_count": 2},
            }
        )
        self.assertIn("Codex 额度（plus）", result)
        self.assertIn("5小时窗口：剩余 75%", result)
        self.assertIn("周窗口：剩余 90%", result)
        self.assertIn("额外余额：$12.5", result)
        self.assertIn("可用完整重置券：2 张", result)
        self.assertNotIn("must-not-appear", result)

    def test_summary_shows_each_reset_credit_expiration(self):
        result = quota.format_summary(
            {"rate_limit": {}, "rate_limit_reset_credits": {"available_count": 2}},
            [0, 3600],
        )
        self.assertIn("重置券 1：01月01日 08:00 到期", result)
        self.assertIn("重置券 2：01月01日 09:00 到期", result)


class PluginHandlerTests(unittest.TestCase):
    def test_rejects_arguments_without_starting_process(self):
        with patch.object(plugin.subprocess, "run") as run:
            self.assertEqual(plugin._handle_codexq("unexpected"), "用法：`/codexq`（不接受参数）")
        run.assert_not_called()

    def test_returns_stdout_from_bundled_checker(self):
        completed = plugin.subprocess.CompletedProcess([], 0, stdout="额度正常\n", stderr="")
        with patch.object(plugin.subprocess, "run", return_value=completed) as run:
            self.assertEqual(plugin._handle_codexq(""), "额度正常")
        self.assertEqual(run.call_args.args[0][0], plugin.sys.executable)
        self.assertEqual(Path(run.call_args.args[0][1]).name, "codexq.py")


if __name__ == "__main__":
    unittest.main()
