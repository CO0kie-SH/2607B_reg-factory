# Grok 浏览器兼容流程

## 入口与用途

```powershell
python register_grok.py --count 1 --node auto
```

该实现保留了更广的邮箱兼容能力、真实浏览器 Cloudflare 处理和协议回退。主页面地址为：

```text
https://accounts.x.ai/sign-up?redirect=grok-com&return_to=%2F
```

## 邮箱来源优先级

1. CLI `--email` 指定邮箱。
2. `--latest-rt` 选择最新可用 Graph refresh token 账号。
3. `GROK_USE_TEMP_EMAIL=true` 使用 `common.temp_email`。
4. 默认从 `emails.txt` Outlook 池取号。

Outlook 验证码路径包括：

- Graph refresh token 直接读取邮件。
- 邮箱 broker 共享取码。
- 直连 BitBrowser/AdsPower 打开 Outlook 网页取码。
- 发码前预登录 Outlook，减少发码后登录耗时导致的漏码。

## 浏览器与指纹

- 通过 `common.browser` 适配 BitBrowser 或 AdsPower。
- Chromium core 默认由 `GROK_BROWSER_CORE_VERSION=146` 控制。
- 注入 `GROK_STEALTH_JS`，处理常见自动化特征。
- 注册浏览器走 Clash 节点；Outlook 页面可能采用直连浏览器，避免代理下邮箱页面加载失败。

## Cloudflare 与 Turnstile

浏览器实现包含三层处理：

1. 检测 `Just a moment`、`__cf_chl` 等页面级挑战。
2. 用真实鼠标事件点击交互式 Turnstile，让 clearance 与当前节点 IP 对齐。
3. 提取 sitekey，使用 YesCaptcha、CapSolver 或 EZCaptcha 获取 token 并注入页面。

`ensure_turnstile()` 先给被动验证时间，再按配置进入打码回退。

## 协议回退

`register_via_protocol_rt()` 使用既有邮箱、refresh token、client id 和密码调用 HTTP 协议组件。当页面流程异常时，浏览器版可转向协议路径继续发码、验码和建号。

## 主要 CLI

| 参数 | 作用 |
|---|---|
| `--count/-n` | 注册数量 |
| `--concurrency/-c` | 并发数，默认 1 |
| `--timeout/-t` | 单任务总超时，默认 600 秒 |
| `--node` | Clash 节点或 `auto` |
| `--keep-on-fail` | 失败后保留浏览器环境 |
| `--email` / `--password` | 指定邮箱账号 |
| `--latest-rt` | 使用最近生成的 Graph RT 账号 |
| `--sub2api` | 成功后导入 SUB2API |
| `--sub2api-group` | 覆盖 Grok 分组 |
| `--mailbox-attempts` | 临时邮箱/取码尝试次数 |

