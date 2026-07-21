# Grok 配置参考

## 最小配置

```dotenv
CLASH_PROXY=http://127.0.0.1:7897
TEMP_EMAIL_PROVIDER=yyds
YYDS_BASE_URL=https://maliapi.215.im
YYDS_API_KEY=TOKEN
CAPSOLVER_API_KEY=TOKEN
```

Turnstile 服务也可使用 `YESCAPTCHA_API_KEY` 或 `EZCAPTCHA_API_KEY`。代码尝试顺序是 YesCaptcha、CapSolver、EZCaptcha。

## 注册相关环境变量

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `CLASH_PROXY` | `http://127.0.0.1:7897` | HTTP 主流程出口代理 |
| `GROK_BROWSER_CORE_VERSION` | `146` | 浏览器版 Chromium core |
| `GROK_USE_TEMP_EMAIL` | `false` | 浏览器版是否优先临时邮箱；HTTP 版始终使用临时邮箱 |
| `TEMP_EMAIL_PROVIDER` | `yyds` | provider 或逗号分隔故障转移链 |
| `GROK_BROKER_TIMEOUT` | `40` | 浏览器版共享邮箱 broker 超时 |
| `YESCAPTCHA_API_KEY` | 空 | Turnstile 第一顺位 |
| `YESCAPTCHA_API_BASE` | 官方地址 | YesCaptcha API 根地址 |
| `CAPSOLVER_API_KEY` | 空 | Turnstile 第二顺位 |
| `EZCAPTCHA_API_KEY` | 空 | Turnstile 第三顺位 |
| `EZCAPTCHA_API_BASE` | 官方地址 | EZCaptcha API 根地址 |

## 临时邮箱 provider

上游 `common/temp_email.py` 支持：

- `moemail`
- `yyds`
- `gptmail`
- `cfmail`
- `custom`

自测命令：

```powershell
python -m common.temp_email doctor
python -m common.temp_email doctor yyds
python -m common.temp_email yyds
```

`custom` provider 使用配置驱动的 REST 映射，可配置创建邮箱、列邮件、读邮件的 URL、方法、头、请求体以及 JSON 字段路径。

## SUB2API 与 webchat2api

```dotenv
SUB2API_URL=https://SUB2API_HOST
SUB2API_EMAIL=ADMIN_EMAIL
SUB2API_PASSWORD=ADMIN_PASSWORD
SUB2API_GROK_GROUP=grok
SUB2API_GROK_PROXY_ID=0

WEBCHAT2API_URL=https://WEBCHAT_HOST
WEBCHAT2API_KEY=ADMIN_KEY
```

注意事项：

- SUB2API 目标分组的平台必须是 `grok`。
- `SUB2API_GROK_PROXY_ID=0` 表示不指定远端代理。
- HTTP 注册使用 `--sub2api` 时会在启动阶段校验 SUB2API 三项登录配置。

## HTTP CLI 完整表

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--count/-n` | `1` | 数量 |
| `--node` | `auto` | 节点名称或自动探测 |
| `--provider` | `.env` | 临时邮箱 provider 链 |
| `--sub2api` | 关闭 | 即时导入 |
| `--sub2api-group` | 配置值 | 覆盖目标分组 |
| `--mailbox-attempts` | `6` | 每个账号最多换邮箱次数 |
| `--code-timeout` | `75` | 每个邮箱等码秒数 |
| `--rotate-every` | `5` | auto 模式批量轮换间隔；0 关闭 |

