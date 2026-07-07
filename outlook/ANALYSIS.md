# Outlook 模块详细分析

本文档专门分析项目里的 Outlook 相关能力，包括流程、依赖工具、函数结构、运行时数据和后续拆分建议。

当前状态：代码还没有真正搬进 `outlook/` 包。大部分 Outlook 逻辑仍在项目根目录脚本和 `common/` 目录中。`outlook/` 目前是后续拆分目标目录。

## 1. 这一块负责什么

Outlook 相关代码承担四类职责：

1. 生产 Outlook 邮箱账号。
   - 自动注册新的 Outlook 邮箱。
   - 保存邮箱、密码、cookie。
   - 尝试提取 Microsoft Graph refresh token。
   - 把可用账号写入 `emails.txt`，供 Claude/ChatGPT/Grok/GitHub 注册流程消费。
2. 读取 Outlook 邮件。
   - 有 refresh token 时优先走 Microsoft Graph API。
   - 没有 token 或 token 失效时，回退到浏览器登录 Outlook 收信。
   - 并行注册时可以委托给 `mailbox_broker.py` 共享取码服务。
3. 修复 Outlook 账号。
   - 批量检测和解锁被 Microsoft 锁定的账号。
   - 遇到手机号验证时分类为 `needs_phone`，不强行继续。
   - 输出解锁成功、需手机、失败三类结果。
4. 给平台注册流程提供邮箱验证能力。
   - Claude：magic link。
   - ChatGPT：通常是 6 位数字验证码。
   - Grok：短字母数字 launch code。
   - GitHub：从 Outlook 收 GitHub launch code。

## 2. 文件地图

| 文件 | 职责 | 主要耦合点 |
|---|---|---|
| `outlook_reg_loop.py` | Outlook 生产者。循环注册账号，写 `_outlook_pool/` 和 `emails.txt`。 | 动态加载 `register_outlook_standalone.py`，调用 `extract_graph_tokens.py`，依赖 BitBrowser/AdsPower 和 Clash。 |
| `register_outlook_standalone.py` | 真正执行 Outlook 注册页面流程。支持 protocol、headless、browser 三种模式。 | 被 CLI 直接运行，也被 `outlook_reg_loop.py` 复用。 |
| `extract_graph_tokens.py` | 用纯 HTTP OAuth 流程从 Outlook 邮箱账号密码换取 Graph refresh token。 | 被 CLI 调用，也被 `outlook_reg_loop.append_to_emails_pool()` 调用。 |
| `common/mailbox.py` | 通用 Outlook 收信接口，封装 Graph API、浏览器取信、broker 客户端。 | 被 Claude/ChatGPT/Grok/GitHub 脚本导入。 |
| `mailbox_broker.py` | 本地共享取码服务。每个 Outlook 邮箱只登录一次，给多个子进程分发验证码或链接。 | 使用 `common/mailbox.py` 里的私有 helper。 |
| `unlock_outlook.py` | 批量解锁被锁 Outlook 账号。 | 依赖 BitBrowser/AdsPower、Playwright、可选 EZ-Captcha。 |
| `common/emails.py` | `emails.txt` 邮箱池的读取、占用、错误标记。 | 被平台注册脚本共用。 |
| `run_full_flow.py` | 把 Outlook 注册作为 Stage A 编排。 | 启动 `outlook_reg_loop.py`，监听 `emails.txt` 新增账号。 |
| `register_three_platforms.py` | 把 Outlook 邮箱分发给 Claude/ChatGPT/Grok。 | 可给子进程注入 `MAILBOX_BROKER`。 |

## 3. 总体数据流

核心数据流如下：

```text
outlook_reg_loop.py
  -> register_outlook_standalone.register_outlook()
  -> 成功得到 email/password/cookies
  -> _outlook_pool/*.json
  -> extract_graph_tokens.get_graph_token()
  -> emails.txt: email----password----refresh_token----client_id
  -> common.emails.next_email(platform)
  -> register_chatgpt.py / register_grok.py / register.py / register_github.py
  -> common.mailbox 读取 Outlook 验证邮件
```

如果走共享取码：

```text
register_three_platforms.py --broker http://127.0.0.1:8765
  -> 子进程环境变量 MAILBOX_BROKER=http://127.0.0.1:8765
  -> common.mailbox.get_code_outlook_pw()
  -> common.mailbox.fetch_from_broker()
  -> mailbox_broker.py /fetch
  -> 单个 Outlook 浏览器会话轮询 inbox/junk
```

## 4. Outlook 账号生产流程

入口：

```bash
python outlook_reg_loop.py
python outlook_reg_loop.py --count 20
python outlook_reg_loop.py --target-pool 10
```

主流程：

```text
main()
  parse args
  设置 OUTLOOK_REG_MAX_PRESS
  load_standalone()
    动态 import register_outlook_standalone.py
  init_clash()
    连接 Clash 控制器
  while True
    检查 _outlook_pool 数量
    maybe_rotate()
      切 Clash 节点并验证出口 IP 是否变化
    one_attempt()
      创建临时指纹浏览器 profile
      打开 profile，拿 CDP ws
      Playwright connect_over_cdp()
      _run_outlook_on_ctx()
        清 cookie/cache
        调用 standalone.register_outlook()
        导出 Outlook 相关 cookie
      关闭并删除 profile
    if success
      write_record()
        写 _outlook_pool/*.json
      append_to_emails_pool()
        提取 Graph token
        写 emails.txt
```

关键函数：

| 函数 | 作用 |
|---|---|
| `load_standalone()` | 从 `SELF_REG_SCRIPT_PATH` 或默认路径动态加载 `register_outlook_standalone.py`。 |
| `init_clash()` | 初始化 Clash 控制器客户端，自动选择代理组。 |
| `_rotate_excluded()` | 解析要排除的国内/直连节点。 |
| `maybe_rotate()` | 每次注册前切换节点，并验证出口 IP 是否真的变化。 |
| `clash_proxy_from_env()` | 从 `HTTP_PROXY` / `HTTPS_PROXY` 读取代理地址。 |
| `bb_create_for_outlook_reg()` | 创建 Outlook 注册专用临时浏览器 profile。 |
| `count_pool()` | 统计 `_outlook_pool/*.json` 数量。 |
| `append_to_emails_pool()` | 把成功账号写入 `emails.txt`，并尽量补上 Graph refresh token。 |
| `write_record()` | 原子写 `_outlook_pool` JSON 记录。 |
| `_run_outlook_on_ctx()` | 在已打开的浏览器 context 中执行 Outlook 注册并导出 cookies。 |
| `one_attempt()` | 单次完整注册尝试。 |

重要设计：

- `outlook_reg_loop.py` 不自己填注册表单，而是复用 `register_outlook_standalone.register_outlook()`。
- 每次尝试都创建临时指纹浏览器 profile，用完删除，减少状态污染。
- `append_to_emails_pool()` 会重试 Graph token 提取。失败不会丢弃账号，而是写 `fresh` 占位，让下游回退浏览器取码。
- `--target-pool` 只看 `_outlook_pool` 数量，不看 `emails.txt`。

## 5. Outlook 注册实现

核心文件：`register_outlook_standalone.py`

直接运行：

```bash
python register_outlook_standalone.py --count 10
python register_outlook_standalone.py --count 5 --concurrency 2
python register_outlook_standalone.py --proxy-file proxies.txt
python register_outlook_standalone.py --mode browser
```

### 5.1 三种注册模式

`register_one()` 支持三种模式：

| 模式 | 函数 | 特点 |
|---|---|---|
| `protocol` | `register_outlook_protocol()` | 纯 HTTP 表单提交，流量最低，但 Microsoft 注册页是 SPA 时基本不可用。 |
| `headless` | `_register_one_headless()` | Playwright headless，注入 stealth 和额外反检测补丁，阻断重资源。 |
| `browser` | `_register_one_browser()` | BitBrowser/AdsPower 完整 GUI profile，最重但成功率最高。 |

`--mode auto` 的 fallback：

```text
register_one()
  protocol 失败
  -> headless 失败
  -> browser
```

`outlook_reg_loop.py` 实际不走 `register_one()` 的三段 fallback，而是自己建 BitBrowser profile 后直接调用：

```python
register_outlook(page, context, idx)
```

### 5.2 注册页面流程

核心函数：

```python
async def register_outlook(page, context, idx=0, captcha_early_abort=False)
```

页面步骤：

```text
进入 https://signup.live.com/signup?lic=1
处理隐私/同意页
生成邮箱、密码、生日、姓名
填写邮箱或 prefix + outlook.com dropdown
处理邮箱已占用 / 格式错误
填写密码
填写国家和生日
可能填写 username / gamertag
填写姓/名
勾选必要 checkbox
处理 PerimeterX 按住验证
处理 captcha 后的 privacy/passkey/finish 页
可选验证账号是否能登录
返回 email,password
```

为了适配 Microsoft 多地区 UI，它做了大量兜底：

- 支持原生 `<select>` 生日下拉。
- 支持新版 combobox/dropdown。
- 支持中、英、法等多语言按钮。
- 每个阶段会输出截图到 `screenshots_outlook/`。
- 对 email、password、birthday、name、submit 都使用多组 selector。

### 5.3 PerimeterX / 人机验证逻辑

当前热路径主要靠模拟 press-and-hold：

```text
检测 hsprotect.net iframe / #px-captcha
优先进入 frame 找真实 #px-captcha 按钮坐标
找不到时退回 iframe 框坐标
使用 Bezier-like 鼠标移动轨迹
按住并带轻微漂移
检测 captcha 元素是否消失
消失后松手并等待跳转
超过 OUTLOOK_REG_MAX_PRESS 后快速放弃
```

相关配置：

| 配置 | 说明 |
|---|---|
| `OUTLOOK_REG_MAX_PRESS` | 最大按住次数。`outlook_reg_loop.py --max-press` 会设置它。 |
| `CAPSOLVER_API_KEY` | CapSolver key。存在 Arkose/PX helper，但不是当前主路径。 |
| `EZCAPTCHA_API_KEY` | EZ-Captcha key。解锁流程里仍有 PX fallback。 |

相关 helper：

| 函数 | 作用 |
|---|---|
| `solve_arkose_capsolver()` | CapSolver FunCaptcha helper。 |
| `solve_funcaptcha_ezcaptcha()` | EZ-Captcha FunCaptcha helper。 |
| `solve_perimeterx_capsolver()` | CapSolver PerimeterX helper。 |
| `solve_perimeterx_ezcaptcha()` | EZ-Captcha PerimeterX helper。 |
| `inject_arkose_token()` | 尝试把 Arkose token 注入页面。 |

注意：注册函数注释里明确提到，两个 PX 打码器对 Microsoft 当前这个 PerimeterX 按住验证效果不好，因此注册热路径主要是手势模拟。

### 5.4 Standalone 输出

直接运行 `register_outlook_standalone.py` 时：

```text
outlook_accounts/accounts_<timestamp>.txt
outlook_accounts/graph_tokens_<timestamp>.json
screenshots_outlook/*.png
```

账号格式：

```text
email----password
```

`outlook_reg_loop.py` 额外写：

```text
_outlook_pool/<timestamp>_<email>.json
emails.txt
```

`_outlook_pool/*.json` 格式：

```json
{
  "email": "...",
  "password": "...",
  "outlook_cookies": [],
  "source": "self-loop",
  "ts": "..."
}
```

## 6. Graph refresh token 提取

核心文件：`extract_graph_tokens.py`

入口：

```bash
python extract_graph_tokens.py outlook_accounts/accounts_20260413_043056.txt
python extract_graph_tokens.py --email user@outlook.com --password pass123
python extract_graph_tokens.py --concurrency 10
```

函数结构：

```text
main()
  读取账号来源
    --email/--password
    accounts_file
    自动扫描 unlock_results/unlocked_clean_*.txt
  跳过 outlook_accounts/graph_tokens_*.txt 中已有账号
  ThreadPoolExecutor 并发执行 get_graph_token()
  写 outlook_accounts/graph_tokens_<timestamp>.txt

get_graph_token(email,password)
  GET Microsoft OAuth authorize URL
  解析 PPFT / flow token / post URL / ctx
  POST 登录凭据
  跟随 Microsoft auto-submit 表单
  处理 Consent/Update
  处理 proofs/Add，提交 action=Skip
  捕获 localhost?code=...
  用 authorization_code 请求 token endpoint
  返回 refresh_token 和 client_id
```

关键常量：

| 常量 | 值/作用 |
|---|---|
| `CLIENT_ID` | Thunderbird public client：`9e5f94bc-e8a4-4e73-b8be-63364c29d753`。 |
| `REDIRECT_URI` | `http://localhost`。 |
| `SCOPE` | `offline_access https://graph.microsoft.com/Mail.Read`。 |
| `OUTPUT_DIR` | `outlook_accounts`。 |

输出格式：

```text
email----password----refresh_token----client_id
```

这个格式可直接进入 `emails.txt`。

注意点：

- `extract_graph_tokens.py` 的 session 设置是 `trust_env=True`，会使用系统代理。代码注释认为这可降低 `account.live.com` 限流。
- `common/mailbox.py` 读取 Graph 邮件时反而强制直连，因为项目经验是代理节点对 Microsoft Graph TLS 握手有时不稳定。

## 7. Outlook 收信模块

核心文件：`common/mailbox.py`

这是下游平台脚本最重要的 Outlook 接口。

### 7.1 Graph API 取码路径

函数：

| 函数 | 作用 |
|---|---|
| `_ms_session()` | 创建强制直连 Microsoft 的 requests session。 |
| `_get_access_token()` | 用 refresh token 换 Graph access token。 |
| `fetch_messages()` | 拉取某个 mail folder 的最新邮件。 |
| `get_code_by_token()` | 轮询 inbox/junk，匹配发件人/主题，提取验证码。 |
| `get_link_by_token()` | 轮询 inbox/junk，提取链接。 |

`get_code_by_token()` 流程：

```text
_get_access_token(refresh_token)
while 未超时
  for folder in ["inbox", "junkemail"]
    fetch_messages(access_token, folder)
    过滤 sender_contains / subject_contains
    如果传了 received_after，跳过更早邮件
    先扫 subject，再扫去 HTML 后的 body
    正则命中后返回 code
  长轮询中途可刷新 access token
return None
```

关键细节：

- 同时扫收件箱和垃圾箱。
- `_strip_html()` 会去掉 HTML 标签和 style，避免误把 CSS 色值当成 6 位验证码。
- `received_after` 用于 resend 后过滤旧验证码。
- Graph 读取时显式绕过代理：

```python
s.trust_env = False
s.proxies = {"http": None, "https": None}
```

### 7.2 浏览器取码路径

函数：

| 函数 | 作用 |
|---|---|
| `_outlook_login()` | 登录 Outlook，处理隐私、保持登录、passkey、继续等中间页。 |
| `_dismiss_inbox_popup()` | 关掉 Outlook 进入收件箱后的通知/引导弹窗。 |
| `_click_folder()` | 点击收件箱或垃圾邮件。不能只靠 goto junk URL。 |
| `_scan_current_folder()` | 在当前文件夹找到匹配邮件并提取验证码。 |
| `prelogin_outlook()` | 预登录 Outlook 并停在收件箱。 |
| `get_code_outlook_pw()` | 浏览器登录 Outlook 后轮询验证码。 |

浏览器取码流程：

```text
get_code_outlook_pw()
  如果 MAILBOX_BROKER 存在
    fetch_from_broker()
  否则
    如果 skip_login=False
      _outlook_login()
      goto Outlook inbox
      _dismiss_inbox_popup()
    while 未超时
      点击 Inbox
      _scan_current_folder()
      点击 Junk
      _scan_current_folder()
      sleep
```

`_scan_current_folder()` 的防错设计：

- 只扫描命中 sender/subject hints 的邮件。
- 先扫列表预览，再点开最新匹配邮件读正文。
- 不再盲扫顶部邮件，避免返回旧验证码或欢迎邮件里的数字。

`prelogin_outlook()` 的意义：

```text
先登录 Outlook 并进入收件箱
再去目标平台点击发送验证码
验证码到达后马上扫
```

这可以避免“验证码发出后才登录 Outlook，登录耗时太久导致超时或拿到旧码”。

### 7.3 Broker 客户端路径

函数：

```python
async def fetch_from_broker(email, password, sender_hint, subject_hint, regex, kind, timeout)
```

当环境变量 `MAILBOX_BROKER` 存在时，浏览器取码委托给本地服务：

```text
POST <MAILBOX_BROKER>/fetch
```

这条路径主要服务多平台注册并行场景。

## 8. 共享取码服务

核心文件：`mailbox_broker.py`

启动：

```bash
python mailbox_broker.py --host 127.0.0.1 --port 8765 --idle 480
```

HTTP 接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/fetch` | 返回验证码或 magic link。 |
| `POST` | `/release` | 关闭并删除某个邮箱的浏览器会话。 |
| `GET` | `/health` | 返回服务健康状态和当前 sessions。 |

请求示例：

```json
{
  "email": "a@outlook.com",
  "password": "password",
  "sender_hint": ["openai", "noreply"],
  "subject_hint": ["code", "verification"],
  "regex": "\\b(\\d{6})\\b",
  "kind": "code",
  "timeout": 150
}
```

核心类：

```text
Session
  email/password
  pid/browser/ctx/page
  lock
  last_used
  seen
  logged_in
  just_created

Broker
  bb
  Playwright instance
  sessions: email -> Session
  _create_lock
  idle_timeout
```

`Broker.fetch()` 流程：

```text
ensure_session()
  如果该 email 已登录，复用 session
  否则创建 BitBrowser profile
  打开浏览器，Playwright CDP 连接
  inject_stealth()
  _outlook_login()
  进入 Outlook inbox

对该 email 加 lock
统计 inbox/junk 当前匹配邮件数量 baseline
如果 session 是刚创建的
  先扫一次最新匹配邮件，规避“发码期间 broker 正在登录”的 race
循环直到 timeout
  点击 inbox/junk
  当前匹配数量 > baseline 才认为有新邮件
  kind=code 时调用 _scan_current_folder()
  kind=link 时调用 _scan_link()
  seen 集合防止同一个值重复分发
```

为什么需要 broker：

- 三个平台并行跑时，如果每个平台都登录同一个 Outlook 邮箱，Microsoft 可能触发并发登录风控。
- broker 每个邮箱只保留一个 Outlook session。
- 同邮箱的 `/fetch` 用 `asyncio.Lock` 串行，不同邮箱可以并行。

## 9. 解锁流程

核心文件：`unlock_outlook.py`

入口：

```bash
python unlock_outlook.py --input outlook_accounts/accounts_xxx.txt
python unlock_outlook.py --input emails_locked.txt --concurrency 2
python unlock_outlook.py --proxy-file proxies.txt
python unlock_outlook.py
```

流程：

```text
main()
  读取 --input，或自动扫描 outlook_accounts/accounts_*.txt
  cleanup_stale_browsers()
  load_proxies()
  asyncio.run(run())

run()
  按 concurrency 分块账号
  启动 worker()
  save_results()

worker()
  create_browser()
  open_browser()
  Playwright connect_over_cdp()
  unlock_account()
  记录 outcome
  close/delete browser profile

unlock_account()
  打开 login.live.com
  classify(text,url)
  填邮箱/密码
  处理 locked 页面
  处理 PX press-and-hold
  跳过 passkey/FIDO
  根据最终状态返回结果
```

页面状态分类函数：

```python
classify(text, url)
```

主要状态：

| 状态 | 含义 |
|---|---|
| `logged_in` | 已登录，账号可用。 |
| `fido_setup` | passkey/FIDO 设置页，脚本尝试跳过。 |
| `locked` | 账号被锁页面。 |
| `px_challenge` | PerimeterX 按住验证。 |
| `sms_verify` | 需要短信/手机验证，脚本归类为 `needs_phone`。 |
| `verify_needed` | 额外身份验证。 |
| `error_page` | 错误页，可尝试重试或返回。 |
| `net_error` | 浏览器网络错误。 |
| `email_form` / `login_form` | 登录表单阶段。 |

输出：

```text
unlock_results/unlocked_<timestamp>.txt
unlock_results/needs_phone_<timestamp>.txt
unlock_results/failed_<timestamp>.txt
unlock_results/unlocked_clean_<timestamp>.txt
screenshots_unlock/*.png
```

`unlocked_clean_*.txt` 是后续最有用的文件：

```text
email----password
```

`extract_graph_tokens.py` 默认会自动扫描它。

## 10. 邮箱池管理

核心文件：`common/emails.py`

`emails.txt` 格式：

```text
email----password----refresh_token----client_id
```

函数：

| 函数 | 作用 |
|---|---|
| `_used_file(platform)` | 返回 `emails_used_<platform>.txt`。 |
| `_error_file(platform)` | 返回 `emails_error_<platform>.txt`。 |
| `_load_used(platform)` | 读取该平台已使用和失败邮箱。 |
| `next_email(platform)` | 从 `emails.txt` 取下一个该平台未使用邮箱，并立即标记 reserved。 |
| `mark_used(platform,email,password)` | 标记该平台使用成功。 |
| `mark_error(platform,email,password,reason)` | 标记该平台使用失败。 |

关键行为：

- 占用记录是按平台分开的。
- 同一个 Outlook 邮箱可以被 Claude 使用一次、ChatGPT 使用一次、Grok 使用一次。
- `next_email()` 取出时马上写 `reserved`，避免并发拿到同一个账号。

## 11. 下游平台如何使用 Outlook

### 11.1 ChatGPT

文件：`register_chatgpt.py`

Outlook 使用方式：

```text
从 common.emails.next_email("chatgpt") 取邮箱
如果 refresh_token 存在且不是 fresh
  get_code_by_token()
否则
  单独开 Outlook 浏览器窗口
  prelogin_outlook()
  发送 ChatGPT 验证码
  get_code_outlook_pw()
```

关键点：

- Outlook 预登录使用独立浏览器 profile，不和 ChatGPT 注册页共享 context。
- 避免 Outlook 页面干扰 auth.openai.com 的 session。
- resend 时复用已登录 Outlook 窗口。
- 有 Graph token 时优先只走 Graph，减少浏览器登录开销。

### 11.2 Grok

文件：`register_grok.py`

Outlook 使用方式：

```text
prelogin_via_direct_browser()
get_code_via_direct_browser()
  如果 MAILBOX_BROKER 存在
    fetch_from_broker()
  否则复用预登录窗口或新开 noproxy 邮箱窗口
```

Grok 验证码 regex：

```text
\b((?=[A-Z0-9-]*[A-Z])[A-Z0-9]{2,4}-[A-Z0-9]{2,4})\b
```

### 11.3 Claude

文件：`register.py`

Outlook 使用方式：

- 自带 `get_magic_link_by_token()`，通过 Graph API 读取 Claude magic link。
- 自带 `get_magic_link_outlook_pw()`，浏览器登录 Outlook 读取 magic link。
- 如果 `MAILBOX_BROKER` 存在，则委托 broker，`kind="link"`。

后续重构点：

- Claude 的 Graph magic-link 逻辑和 `common/mailbox.get_link_by_token()` 有重叠，可以收口。

### 11.4 GitHub

文件：`register_github.py`

Outlook 使用方式：

- 从 `_outlook_pool/*.json` 读取邮箱和密码。
- 用 `common.mailbox.get_code_outlook_pw()` 通过浏览器登录 Outlook 收 GitHub launch code。
- 当前不使用 Graph token，因为 `_outlook_pool` 记录里没有 token。

## 12. 依赖工具和外部服务

| 工具/服务 | 使用位置 | 作用 |
|---|---|---|
| BitBrowser Local API | 注册、broker、解锁、平台取码窗口 | 创建指纹浏览器 profile，打开浏览器，提供 CDP ws。 |
| AdsPower Local API | 通过 `bitbrowser.BitBrowser()` adapter 兼容 | BitBrowser 替代方案。 |
| Playwright | 所有浏览器自动化流程 | 驱动注册、登录、收信、解锁页面。 |
| Clash/mihomo | `outlook_reg_loop.py` | 切换出口节点，降低同 IP 连续注册的失败率。 |
| Microsoft signup/login | 注册、解锁、Graph 授权 | 真实 Outlook 注册和登录入口。 |
| Microsoft Graph API | `common/mailbox.py`、`extract_graph_tokens.py` | 读取邮件和换 access token。 |
| CapSolver | 注册 helper | Arkose/PX helper，不是当前主注册热路径。 |
| EZ-Captcha | 解锁和注册 helper | unlock 中有 PX fallback。 |
| `check_outlook_status` 可选模块 | `verify_registered_outlook()` | 注册后验证账号密码是否能登录；缺失时跳过。 |

## 13. 运行时数据

| 路径 | 生产者 | 消费者 |
|---|---|---|
| `emails.txt` | `outlook_reg_loop.py`、WebUI 导入、手动导入 | `common/emails.py` 和平台脚本。 |
| `_outlook_pool/*.json` | `outlook_reg_loop.py` | `register_github.py`，也可人工检查。 |
| `outlook_accounts/accounts_*.txt` | `register_outlook_standalone.py` | `unlock_outlook.py`、`extract_graph_tokens.py`。 |
| `outlook_accounts/graph_tokens_*.txt` | `extract_graph_tokens.py` | 可合并进 `emails.txt`。 |
| `unlock_results/unlocked_clean_*.txt` | `unlock_outlook.py` | `extract_graph_tokens.py` 自动扫描。 |
| `screenshots_outlook/` | `register_outlook_standalone.py` | 调试注册页变化。 |
| `screenshots_unlock/` | `unlock_outlook.py` | 调试解锁状态机。 |
| `emails_used_<platform>.txt` | `common/emails.py` | 防止同平台重复使用邮箱。 |
| `emails_error_<platform>.txt` | 平台脚本 | 防止重复使用该平台失败账号。 |

## 14. 主要环境变量

| 变量 | 说明 |
|---|---|
| `FINGERPRINT_BROWSER` | `bitbrowser` 或 `adspower`。 |
| `BITBROWSER_API` | BitBrowser 本地 API，默认 `http://127.0.0.1:54345`。 |
| `ADSPOWER_API` / `ADSPOWER_API_KEY` / `ADSPOWER_GROUP_ID` | AdsPower 本地 API 配置。 |
| `OUTLOOK_PROXIES` | Outlook standalone 默认住宅代理池，逗号或换行分隔。 |
| `CLASH_API` / `CLASH_SECRET` / `CLASH_GROUP` / `CLASH_PROXY` | Clash 控制器和代理配置。 |
| `OUTLOOK_REG_MAX_PRESS` | Outlook 注册按住验证最大次数。 |
| `CAPSOLVER_API_KEY` | 可选打码 key。 |
| `EZCAPTCHA_API_KEY` / `EZCAPTCHA_API_BASE` | 可选 EZ-Captcha 配置。 |
| `MAILBOX_BROKER` | 设置后平台脚本把 Outlook 收信委托给 broker。 |
| `GROK_BROKER_TIMEOUT` | Grok 使用 broker 时的短超时。 |
| `SELF_REG_SCRIPT_PATH` | 覆盖 `outlook_reg_loop.py` 加载的 standalone 脚本路径。 |
| `BB_CORE_VERSION` | `outlook_reg_loop.py` 创建 BitBrowser profile 时使用的内核版本。 |

## 15. 当前架构问题

拆分前要注意这些耦合：

1. 根目录路径耦合较强。
   - `outlook_reg_loop.py` root-relative 动态 import `register_outlook_standalone.py`。
   - WebUI schema 指向根目录脚本名。
   - README 和现有命令都引用根目录脚本。
2. `common/mailbox.py` 其实几乎是 Outlook 专属，但被平台脚本直接导入。
3. `mailbox_broker.py` 导入了 `common/mailbox.py` 的私有函数：
   - `_outlook_login`
   - `_click_folder`
   - `_scan_current_folder`
4. Claude 的 `register.py` 有一套重复的 Graph magic-link 读取逻辑，和 `common/mailbox.get_link_by_token()` 重叠。
5. 运行时路径硬编码较多：
   - `emails.txt`
   - `_outlook_pool`
   - `outlook_accounts`
   - `unlock_results`
   - `screenshots_outlook`
   - `screenshots_unlock`
6. `register_outlook_standalone.py` 内有一些历史 helper，尤其打码相关 helper，不一定仍在热路径。
7. 还没有 package 边界。直接移动文件会破坏 import、subprocess 路径和 WebUI。

## 16. 建议拆分顺序

建议逐步做，不要一次性搬文件。

### Phase 1：先建 wrapper，不改行为

建议目标结构：

```text
outlook/
  __init__.py
  registration.py
  producer.py
  graph_tokens.py
  mailbox.py
  broker.py
  unlock.py
  pool.py
  paths.py
  README.md
  ANALYSIS.md
```

先创建 wrapper module，把现有 root/common 函数 re-export 出来。这样新代码可以开始依赖 `outlook.*`，旧 CLI 路径仍然可用。

### Phase 2：先迁移收信模块

优先把 `common/mailbox.py` 移到 `outlook/mailbox.py`，然后让原文件变成兼容层：

```python
from outlook.mailbox import *
```

再逐步改平台脚本 import。

### Phase 3：迁移 Graph token 脚本

`extract_graph_tokens.py` 边界最清晰，适合作为第一个 CLI 迁移对象。

建议：

```text
outlook/graph_tokens.py  # 真实现
extract_graph_tokens.py  # root wrapper，只调用 outlook.graph_tokens.main()
```

### Phase 4：迁移 broker 和 unlock

把：

```text
mailbox_broker.py -> outlook/broker.py
unlock_outlook.py -> outlook/unlock.py
```

根目录保留薄 wrapper，确保 WebUI 和 README 命令暂时不坏。

### Phase 5：最后迁移注册生产

最后处理：

```text
register_outlook_standalone.py -> outlook/registration.py
outlook_reg_loop.py -> outlook/producer.py
```

它们对路径、截图目录、动态 import、运行时输出耦合最多，应最后动。

### Phase 6：更新 WebUI 和文档

等 wrapper 和迁移稳定后再更新：

- `webui/scripts.py`
- `README.md`
- `PROJECT_OVERVIEW.md`
- `outlook/README.md`

## 17. 快速索引

常用命令：

```bash
python outlook_reg_loop.py --count 1 --timeout 180
python register_outlook_standalone.py --count 1 --mode browser
python mailbox_broker.py --port 8765
python unlock_outlook.py --input outlook_accounts/accounts_xxx.txt
python extract_graph_tokens.py outlook_accounts/accounts_xxx.txt
```

最重要函数：

```text
outlook_reg_loop.main()
outlook_reg_loop.one_attempt()
outlook_reg_loop.append_to_emails_pool()

register_outlook_standalone.register_outlook()
register_outlook_standalone.register_one()
register_outlook_standalone.register_outlook_protocol()
register_outlook_standalone._register_one_headless()
register_outlook_standalone._register_one_browser()

extract_graph_tokens.get_graph_token()

common.mailbox.get_code_by_token()
common.mailbox.get_link_by_token()
common.mailbox.prelogin_outlook()
common.mailbox.get_code_outlook_pw()
common.mailbox.fetch_from_broker()

mailbox_broker.Broker.fetch()
mailbox_broker.h_fetch()

unlock_outlook.unlock_account()
unlock_outlook.worker()
unlock_outlook.save_results()

common.emails.next_email()
common.emails.mark_used()
common.emails.mark_error()
```

