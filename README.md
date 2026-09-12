# codexq-discord

一个 Hermes 插件：把本机已登录的 Codex CLI 额度查询包装为 Discord 原生斜杠指令 `/codexq`。

## 特性

- 注册无参数的 `/codexq` 指令。
- 通过 `codex app-server --stdio` 查询当前账号的限额。
- 输出 5 小时窗口、周窗口、额外余额和重置券（服务端返回时）。
- 不读取、打印或写入 OAuth token、API key、账号邮箱或本机绝对路径。
- 不接受用户参数，不通过 shell 执行命令。

## 前置条件

1. 已安装 [Codex CLI](https://developers.openai.com/codex/cli/)，且 `codex` 位于 `PATH`。
2. 已完成 Codex CLI 登录（例如执行 `codex login`）。
3. Hermes 已配置并连接 Discord。

## 安装

将此目录放到当前 Hermes profile 的插件目录中，例如：

```bash
cp -R codexq-discord ~/.hermes/plugins/codexq-discord
hermes gateway restart
```

在 Discord 中输入：

```text
/codexq
```

> 斜杠命令同步由 Discord 网关完成；首次同步可能需要短暂等待。

## 安全说明

- 插件仅启动本地 `codex app-server --stdio` 并请求 `account/rateLimits/read`。
- 默认输出仅显示额度摘要；不会使用 `--json`，从而避免把潜在账户元数据发送到聊天平台。
- 代码不包含任何令牌、账号、Webhook、服务器地址或个人本机路径。
- `.gitignore` 排除 `.env`、虚拟环境、缓存和编辑器配置。

## 开发验证

```bash
python3 -m py_compile __init__.py codexq.py
python3 -m unittest discover -s tests -v
python3 codexq.py --help
```

## 许可

MIT
