# Graph refresh token 提取流程

本文档专门说明项目中 Outlook / Microsoft Graph refresh token 的提取流程。本目录现在包含一个独立子项目实现：`oauth_graph.py`。它不会修改根目录现有流程，默认从本目录 `.env` 读取单个 Outlook 账号密码，并把结果写到本目录 `out/`。

## 0. 子项目本地运行

本目录结构：

```text
graph_refresh_token/
  .env                 # 本机账号密码，Git 忽略
  .env.example         # 模板
  requirements.txt     # 子项目最小依赖
  oauth_graph.py       # 独立授权码流程实现
  out/                 # 运行后生成，Git 忽略
```

推荐先创建子项目自己的虚拟环境，再安装依赖：

```powershell
py -3 -m venv graph_refresh_token/.venv
graph_refresh_token/.venv/Scripts/python.exe -m pip install -r graph_refresh_token/requirements.txt
```

### 方法一：使用 `.env`

编辑：

```text
graph_refresh_token/.env
```

填入：

```env
OUTLOOK_EMAIL=你的_outlook_邮箱
OUTLOOK_PASSWORD=你的_outlook_密码
```

运行：

```powershell
graph_refresh_token/.venv/Scripts/python.exe graph_refresh_token/oauth_graph.py
```

### 方法二：使用 PowerShell 环境变量

不改 `.env`，直接在当前 PowerShell 会话设置：

```powershell
$env:OUTLOOK_EMAIL="你的_outlook_邮箱"
$env:OUTLOOK_PASSWORD="你的_outlook_密码"
graph_refresh_token/.venv/Scripts/python.exe graph_refresh_token/oauth_graph.py
```

### 方法三：使用命令行参数

```powershell
graph_refresh_token/.venv/Scripts/python.exe graph_refresh_token/oauth_graph.py --email "你的_outlook_邮箱" --password "你的_outlook_密码"
```

这种方式会把密码留在命令历史里，只适合临时测试。

成功后会输出：

```text
graph_refresh_token/out/<email>.txt
```

其中 `<email>.txt` 的内容格式为四列，`refresh_token` 放在第 4 位：

```text
email----password----client_id----refresh_token
```

默认不会在控制台打印完整 `refresh_token`。如果你需要临时打印，可以加：

```powershell
py -3 graph_refresh_token/oauth_graph.py --print-token
```

常用开关：

| 参数 | 作用 |
|---|---|
| `--env <path>` | 指定其他 `.env` 文件。 |
| `--email <email>` | 临时覆盖 `.env` 中的邮箱。 |
| `--password <password>` | 临时覆盖 `.env` 中的密码；不推荐，因为命令历史会留下密码。 |
| `--out-dir <path>` | 临时指定输出目录；默认 `graph_refresh_token/out`。 |
| `--no-proxy` | 忽略当前 shell 的 `HTTP_PROXY` / `HTTPS_PROXY`。 |
| `GRAPH_OUTPUT_DIR=out` | 通过环境变量或 `.env` 指定输出目录。 |
| `SAVE_DEBUG_HTML=1` | 失败时保存最后一个未知页面，便于分析 Microsoft 中间页变化。 |

如果失败信息是：

```text
Microsoft requires adding security proof for this account (proofs/Add fShowSkip=false)
```

说明这个账号被 Microsoft 强制要求添加备用邮箱或手机号安全信息。该页面没有跳过入口，仅靠 Outlook 邮箱账号和密码不能完成 OAuth 授权，也就不能拿到 Graph refresh token。处理方式是在浏览器里登录该 Outlook 账号，按提示手动添加备用邮箱或手机号并完成安全校验，然后回到本工具重新运行。

## 1. 这个流程解决什么问题

平台注册时需要读取 Outlook 邮件验证码或 magic link。读取 Outlook 邮箱有两条路径：

1. 浏览器登录 Outlook 收信。
   - 优点：不需要 token。
   - 缺点：慢，容易遇到 Microsoft 登录中间页、passkey、并发登录风控。
2. Microsoft Graph API 收信。
   - 优点：快，不开浏览器，适合 ChatGPT 等频繁取码流程。
   - 缺点：必须先拿到能访问 `https://graph.microsoft.com/Mail.Read` 的 refresh token。

`extract_graph_tokens.py` 的目标就是把：

```text
email----password
```

转换成：

```text
email----password----refresh_token----client_id
```

然后写入 `outlook_accounts/graph_tokens_<时间戳>.txt`，或者由 `outlook_reg_loop.py` 直接写进 `emails.txt`。

## 2. 核心文件和相关模块

| 文件 | 作用 |
|---|---|
| `extract_graph_tokens.py` | 纯 HTTP OAuth 授权码流程，提取 Graph refresh token。 |
| `outlook_reg_loop.py` | Outlook 注册成功后调用 `get_graph_token()`，把 token 写入 `emails.txt`。 |
| `common/mailbox.py` | 用 refresh token 换 access token，再调用 Graph API 读取邮件。 |
| `register_chatgpt.py` | 如果邮箱记录中有 Graph token，优先用 `get_code_by_token()` 取验证码。 |
| `register_three_platforms.py` | 把 `--token` / `--client-id` 透传给 ChatGPT 等子流程。 |

## 3. 常量和 OAuth 参数

当前实现使用 Microsoft 个人账号消费者租户 OAuth 端点。

| 常量 | 值 | 说明 |
|---|---|---|
| `CLIENT_ID` | `9e5f94bc-e8a4-4e73-b8be-63364c29d753` | Thunderbird public client ID，支持个人 Microsoft 账号。 |
| `REDIRECT_URI` | `http://localhost` | 授权码回调地址。脚本不会真的启动本地服务，而是截获重定向 URL。 |
| `SCOPE` | `offline_access https://graph.microsoft.com/Mail.Read` | 要求 refresh token 和 Graph 邮件读取权限。 |
| `OUTPUT_DIR` | `outlook_accounts` | 输出目录。 |

为什么 scope 必须是 Graph：

```text
https://graph.microsoft.com/Mail.Read
```

下游 `common/mailbox.py` 是通过：

```text
https://graph.microsoft.com/v1.0/me/mailFolders/.../messages
```

读取邮件的。如果拿的是 `outlook.office.com` 或 IMAP 资源域 token，后续不能用于 Graph REST 取码。

## 4. 入口命令

指定账号文件：

```bash
python extract_graph_tokens.py outlook_accounts/accounts_20260413_043056.txt
```

指定单个账号：

```bash
python extract_graph_tokens.py --email user@outlook.com --password pass123
```

指定并发：

```bash
python extract_graph_tokens.py accounts.txt --concurrency 10
```

不传参数时，脚本会自动扫描：

```text
unlock_results/unlocked_clean_*.txt
```

并跳过已经出现在：

```text
outlook_accounts/graph_tokens_*.txt
```

里的邮箱。

## 5. 输入和输出格式

输入文件每行至少两列：

```text
email----password
email----password----其他字段会被忽略
```

输出文件：

```text
outlook_accounts/graph_tokens_<时间戳>.txt
```

每行格式：

```text
email----password----refresh_token----client_id
```

这个格式与 `emails.txt` 兼容。

## 6. 总体流程图

```text
main()
  解析参数
  加载账号列表
    --email/--password
    或 accounts_file
    或 auto-scan unlock_results/unlocked_clean_*.txt
  跳过已提取 token 的邮箱
  ThreadPoolExecutor 并发调用 get_graph_token()
  收集成功结果
  写 outlook_accounts/graph_tokens_<timestamp>.txt

get_graph_token(email,password)
  创建 requests.Session
  GET Microsoft OAuth authorize URL
  从登录页解析 PPFT / flow token / post URL / ctx
  POST 邮箱密码到 login.live.com
  跟随 Microsoft 中间页、表单和重定向
  处理 Consent/Update
  处理 proofs/Add
  截获 localhost?code=...
  POST token endpoint 换 access_token / refresh_token
  返回 email/password/refresh_token/client_id
```

## 7. `get_graph_token()` 分步解析

### 7.1 创建 HTTP session

```python
session = requests.Session()
session.trust_env = True
```

这里会使用系统代理环境变量，例如 `HTTP_PROXY` / `HTTPS_PROXY`。代码注释认为经 Clash 访问 `account.live.com` 可降低限流或连接失败概率。

同时设置浏览器 UA：

```text
Chrome/130 Windows UA
```

### 7.2 构造授权 URL

授权 URL 形如：

```text
https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize
  ?client_id=<CLIENT_ID>
  &response_type=code
  &redirect_uri=http%3A%2F%2Flocalhost
  &scope=offline_access%20https%3A%2F%2Fgraph.microsoft.com%2FMail.Read
  &response_mode=query
```

这里使用 `consumers` tenant，面向个人 Microsoft 账号。

### 7.3 解析 Microsoft 登录页参数

脚本从 HTML 中解析：

| 字段 | 作用 |
|---|---|
| `PPFT` / `flow_token` | Microsoft 登录表单 CSRF/flow token。 |
| `urlPost` / `post_url` | 登录表单提交地址。 |
| `sCtx` / `ctx` | 登录上下文。 |

如果无法解析 `flow_token`，本账号直接失败。

### 7.4 提交邮箱密码

POST body 主要包括：

```text
login=<email>
loginfmt=<email>
passwd=<password>
PPFT=<flow_token>
ctx=<ctx>
type=11
LoginOptions=3
```

提交后 Microsoft 可能返回多种中间页。

### 7.5 处理 auto-submit 中间页

Microsoft 登录流程常出现类似：

```html
onload="DoSubmit()"
```

或 `fmHF` 自动提交表单。

脚本会提取 `<form action=...>` 和隐藏 input，再继续 POST，最多处理 5 轮。

### 7.6 手动跟随重定向

脚本手动处理 301/302/303/307：

- 如果 `Location` 是 `localhost` 且包含 `code=`，说明授权码已经拿到。
- 如果 `Location` 是 `localhost` 且包含 `error`，解析错误并失败。
- 其他重定向继续 GET。

脚本没有启动本地 HTTP server，而是把重定向 URL 包装成一个临时响应对象继续处理。

### 7.7 处理 Consent/Update

有时 Microsoft 会出现授权同意页：

```text
Consent/Update
```

页面是 React SPA，不一定有静态 form。脚本从：

```text
ServerData = {...};
```

里解析：

| 字段 | 用途 |
|---|---|
| `sClientId` | client id |
| `sRawInputScopes` | 请求 scope |
| `sRawInputGrantedScopes` | 已授权 scope |
| `sCanary` | canary token |

然后 POST：

```text
ucaction=Yes
client_id=...
scope=...
cscope=...
canary=...
```

### 7.8 处理 proofs/Add

`proofs/Add` 表示 Microsoft 要求添加安全信息。

脚本尝试从页面 form 中提取 hidden input，并追加：

```text
action=Skip
```

再 POST 表单，模拟点击 Skip。

如果页面没有 form，则本账号失败。

### 7.9 通用 form fallback

如果遇到其他 form，脚本会：

1. 提取 form action。
2. 提取 hidden input。
3. 如果 URL 或 action 含 consent，则追加：

```text
ucaccept=Yes
```

4. POST 表单。
5. 再继续处理重定向。

### 7.10 捕获授权码

成功时 URL 形如：

```text
http://localhost/?code=<authorization_code>&...
```

脚本通过：

```python
urllib.parse.urlparse()
urllib.parse.parse_qs()
```

取出 `code`。

### 7.11 换 token

POST 到：

```text
https://login.microsoftonline.com/consumers/oauth2/v2.0/token
```

body：

```text
client_id=<CLIENT_ID>
grant_type=authorization_code
code=<authorization_code>
redirect_uri=http://localhost
scope=offline_access https://graph.microsoft.com/Mail.Read
```

如果响应中有 `access_token`，脚本取出：

```text
refresh_token
```

并返回：

```python
{
    "email": email,
    "password": password,
    "refresh_token": rt,
    "client_id": CLIENT_ID,
}
```

## 8. `main()` 账号来源逻辑

`main()` 有三种加载账号方式。

### 8.1 单账号

```bash
python extract_graph_tokens.py --email a@outlook.com --password xxx
```

直接构造：

```python
[(email, password)]
```

### 8.2 指定文件

```bash
python extract_graph_tokens.py accounts.txt
```

读取每行 `----` 分隔的前两列。

### 8.3 自动扫描解锁结果

不传参数时：

```bash
python extract_graph_tokens.py
```

脚本扫描：

```text
unlock_results/unlocked_clean_*.txt
```

并读取：

```text
email----password
```

同时扫描：

```text
outlook_accounts/graph_tokens_*.txt
```

把已提取过 token 的邮箱加入 skip 集合，避免重复处理。

## 9. 并发模型

脚本用线程池并发：

```python
ThreadPoolExecutor(max_workers=args.concurrency)
```

每个任务执行：

```python
get_graph_token(email, password, idx)
```

默认并发：

```text
5
```

并发过高可能导致：

- Microsoft 登录限流。
- 代理节点连接不稳定。
- 多账号同时触发安全验证。

因此批量跑时建议先从 3 到 5 开始。

## 10. 与 `outlook_reg_loop.py` 的关系

`outlook_reg_loop.append_to_emails_pool()` 会在 Outlook 注册成功后立即调用：

```python
from extract_graph_tokens import get_graph_token
res = get_graph_token(email, password)
```

成功：

```text
email----password----真实 refresh_token----client_id
```

失败：

```text
email----password----fresh----fresh
```

写入 `emails.txt`。

这里的设计是：

- 不因为 Graph token 提取失败丢掉新注册邮箱。
- 有 token 的账号后续 ChatGPT 取码会更快。
- 没 token 的账号仍可通过浏览器登录 Outlook 取码。

## 11. 与 `common/mailbox.py` 的关系

Graph token 后续主要由 `common/mailbox.py` 使用。

读取验证码流程：

```text
get_code_by_token(email, refresh_token, client_id)
  _get_access_token(refresh_token, client_id)
    POST /token grant_type=refresh_token
  fetch_messages(access_token, "inbox")
  fetch_messages(access_token, "junkemail")
  匹配 sender/subject
  正则提取验证码
```

`common/mailbox.py` 默认 client ID 和 `extract_graph_tokens.py` 一致：

```text
9e5f94bc-e8a4-4e73-b8be-63364c29d753
```

Graph 收信时它强制直连 Microsoft：

```python
s.trust_env = False
```

原因是代码注释中提到：Graph/token 端点经代理时可能出现 TLS 抖动。

## 12. 常见失败点

| 失败点 | 表现 | 可能原因 |
|---|---|---|
| `no flow token found` | 登录页无法解析 PPFT | Microsoft 页面结构变化、被风控页替代、请求被代理/网络污染。 |
| `OAuth error` | localhost 回调带 error | 密码错、账号异常、scope 被拒、需要额外验证。 |
| `Consent/Update with no ServerData` | 同意页解析失败 | Microsoft 同意页结构变化。 |
| `proofs/Add with no form` | 安全信息页无法跳过 | 账号被要求强制添加安全信息。 |
| `stuck at ...` | 找不到可继续的 form 或 redirect | 流程进入未知页面。 |
| token endpoint 无 `access_token` | 换码失败 | 授权码无效、重定向参数不匹配、账号权限异常。 |

## 13. 调试建议

1. 先用单账号跑：

```bash
python extract_graph_tokens.py --email a@outlook.com --password xxx
```

2. 确认账号密码能登录 Outlook。
3. 如果批量失败，降低并发：

```bash
python extract_graph_tokens.py accounts.txt --concurrency 2
```

4. 检查代理。
   - `extract_graph_tokens.py` 会使用系统代理。
   - 如果代理节点质量差，可能卡在 Microsoft 登录页或中间页。
5. 检查账号是否需要手机号、安全信息或异常验证。

## 14. 后续拆分建议

建议未来把实现迁到：

```text
graph_refresh_token/
  README.md
  flow.py
```

或者作为 Outlook 包的一部分：

```text
outlook/
  graph_tokens.py
```

更推荐后者，因为 Graph token 是 Outlook 收信能力的一部分。

安全迁移方式：

1. 先创建 `outlook/graph_tokens.py`，移动真实实现。
2. 保留根目录 `extract_graph_tokens.py` 作为 wrapper：

```python
from outlook.graph_tokens import main

if __name__ == "__main__":
    main()
```

3. 修改 `outlook_reg_loop.py` 的 import：

```python
from outlook.graph_tokens import get_graph_token
```

4. 更新 WebUI、README 和文档。
