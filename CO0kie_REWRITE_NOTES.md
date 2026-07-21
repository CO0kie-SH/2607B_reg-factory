# CO0kie 项目改写说明

当前版本：`26.7.13A`

本文档是本 fork 的改写记录和后续重构入口。原项目说明仍以 `README.md` 为准；更完整的结构分析见 `PROJECT_OVERVIEW.md`、`outlook/ANALYSIS.md`、`graph_refresh_token/README.md` 和 `outlook_create/README.md`。

## 1. 当前改写目标

本次改写先不大规模移动原有代码，优先做三件事：

1. 梳理项目职责和接口，降低接手成本。
2. 把 Outlook 相关内容单独拆出文档目录。
3. 把 Microsoft Graph refresh token 提取流程做成独立子项目，方便单独调试和迭代。
4. 把 Outlook 创建/注册链路单独沉淀到 `outlook_create/`，与读邮件、取 RT 子项目分开维护。

这样做的原因是原项目入口多、运行时文件多、脚本之间直接 import 较多。直接搬文件容易破坏 CLI、WebUI 和现有自动化流程，所以当前采用“先文档分层，再子项目隔离，最后逐步迁移”的方式。

## 2. 新增文档和目录

| 路径 | 作用 |
|---|---|
| `PROJECT_OVERVIEW.md` | 项目总体说明、核心流程、接口清单。 |
| `outlook/README.md` | Outlook 内容拆分目录说明。 |
| `outlook/ANALYSIS.md` | Outlook 注册、收信、Graph token、解锁等流程分析。 |
| `graph_refresh_token/README.md` | Graph refresh token 提取流程和子项目运行说明。 |
| `graph_refresh_token/oauth_graph.py` | 独立的单账号 Graph refresh token 提取脚本。 |
| `graph_refresh_token/.env.example` | 子项目环境变量模板。 |
| `graph_refresh_token/requirements.txt` | 子项目最小依赖。 |
| `outlook_create/README.md` | Outlook 创建/注册链路子项目说明。 |
| `outlook_create/FLOW_ANALYSIS.md` | 主项目 Outlook 注册流程、Graph RT 入池、节点轮换和验证码处理分析。 |
| `outlook_create/UPDATE_2026-07-13.md` | 2026-07-13 上游更新、合并和本地整理记录。 |
| `outlook_create/scripts/` | Outlook 注册主循环和 standalone 执行器的本地包装/检查脚本。 |

## 3. Graph refresh token 子项目

子项目位置：

```text
graph_refresh_token/
```

它使用 Outlook 邮箱账号和密码走 Microsoft OAuth 授权码流程，获取可用于 Microsoft Graph Mail.Read 的 refresh token。

运行方式：

```powershell
graph_refresh_token\.venv\Scripts\python.exe graph_refresh_token\oauth_graph.py
```

也支持用环境变量或命令行参数传入账号：

```powershell
$env:OUTLOOK_EMAIL="user@hotmail.com"
$env:OUTLOOK_PASSWORD="password"
graph_refresh_token\.venv\Scripts\python.exe graph_refresh_token\oauth_graph.py
```

```powershell
graph_refresh_token\.venv\Scripts\python.exe graph_refresh_token\oauth_graph.py --email "user@hotmail.com" --password "password"
```

输出目录：

```text
graph_refresh_token/out/
```

输出文件名：

```text
<邮箱>.txt
```

当前输出格式：

```text
email----password----client_id----refresh_token
```

其中 refresh token 放在第 4 位。

## 4. Outlook 安全邮箱说明

提取 RT 时如果 Microsoft 返回：

```text
proofs/Add fShowSkip=false
```

表示该 Outlook 账号必须先添加备用邮箱或手机号安全信息。这个页面没有跳过入口，仅靠账号密码无法继续 OAuth 授权。

处理方式：

1. 用浏览器登录该 Outlook 账号。
2. 按 Microsoft 提示添加备用邮箱或手机号。
3. 完成安全校验。
4. 回到 `graph_refresh_token` 子项目重新运行提取脚本。

## 5. 与原项目的关系

当前没有改动根目录主流程的行为：

```text
extract_graph_tokens.py
outlook_reg_loop.py
common/mailbox.py
webui/
```

仍按原项目方式工作。新的 `graph_refresh_token/` 是独立实验和调试入口，便于后续确认流程稳定后再迁移回主项目。

需要注意：子项目当前输出格式为：

```text
email----password----client_id----refresh_token
```

原项目 `extract_graph_tokens.py` 和 `emails.txt` 相关旧逻辑仍多处使用：

```text
email----password----refresh_token----client_id
```

后续若要打通子项目输出和主项目消费，需要统一字段顺序或增加转换逻辑。

## 6. 后续改写方向

建议后续按以下顺序推进：

1. 把 Graph RT 提取能力沉淀为可 import 的模块。
2. 保留根目录 `extract_graph_tokens.py` 作为薄 wrapper，避免破坏旧命令。
3. 统一 Outlook 账号记录格式，明确 RT 和 client_id 的字段位置。
4. 把 `outlook_reg_loop.py`、`common/mailbox.py`、`mailbox_broker.py`、`unlock_outlook.py` 逐步迁入 `outlook/` 包。
5. 为 Outlook 安全邮箱、强制手机号、安全验证页增加明确状态分类。
6. 最后再更新 WebUI schema 和根 README。

当前阶段的原则是：能独立验证的先独立验证，主流程不急着重构。

## 7. 2026-07-09 更新记录

版本号：`26.7.9A`

今天继续围绕 Outlook / Microsoft Graph 做了第二阶段拆分。

### 7.1 目录边界调整

确认职责边界：

```text
graph_refresh_token/  只负责获取和保存 RT
outlook/              负责读取 Outlook 邮箱、导出文件夹、标题和 AT 元信息
```

因此读邮箱逻辑放在：

```text
outlook/mailbox_graph.py
```

而不是 `graph_refresh_token/`。

### 7.2 Outlook 邮箱元信息读取

新增 `outlook/mailbox_graph.py`，通过 Microsoft Graph API 读取邮箱元信息。

输入：

```text
graph_refresh_token/out/<email>.txt
```

格式：

```text
email----password----client_id----refresh_token
```

输出：

```text
outlook/db/<email>.csv
outlook/out/<email>+<folder>.csv
```

`db/<email>.csv` 保存邮箱文件夹列表。

`out/<email>+<folder>.csv` 保存邮件标题和元信息，包括：

```text
subject
from
sender
received_datetime
sent_datetime
is_read
has_attachments
importance
internet_message_id
conversation_id
web_link
categories
```

当前明确不请求正文相关字段：

```text
body
bodyPreview
uniqueBody
attachments/contentBytes
$value
```

### 7.3 AT 持久化

新增命令：

```powershell
graph_refresh_token\.venv\Scripts\python.exe outlook\mailbox_graph.py --export-at
```

输出：

```text
outlook/db/at.csv
```

用途：

1. 用 RT 刷新当前 Graph access token。
2. 保存 token endpoint 返回的有效期字段。
3. 尝试解析 access token 是否为 JWT。

实际观察到个人 Outlook / Hotmail 场景下，Graph `access_token` 可能是 opaque token，不一定是 `header.payload.signature` JWT。因此 `at.csv` 里增加了：

```text
is_jwt
jwt_part_count
jwt_parse_status
expires_in
response_expires_at_utc
```

如果 `is_jwt=false`，则以 token endpoint 返回的 `expires_in` / `response_expires_at_utc` 为有效期依据。

### 7.4 Graph API 与 IMAP 的取舍

确认当前读取邮件不是 IMAP / POP3 / SMTP，而是 Microsoft Graph REST API：

```text
POST /consumers/oauth2/v2.0/token
GET  /me/mailFolders
GET  /me/mailFolders/{folder_id}/messages
```

对本项目来说，Graph 比 IMAP 更适合 Outlook：

1. 能用 RT/AT 自动续期。
2. 返回 JSON，结构稳定。
3. 可以用 `$select` 精确限制字段。
4. 更适合批量脚本化和验证码场景。

### 7.5 后续实时读取方案

记录了两种类似 IMAP `IDLE` 的后续方案：

1. Graph Change Notifications / Webhook。
2. Graph Delta Query。

当前建议先做 Delta Query，因为它适合本地脚本，不需要公网 HTTPS webhook。

未来状态文件可设计为：

```text
outlook/db/delta_state.csv
```

字段：

```text
email,folder_id,folder_name,delta_link,last_sync_at
```

建议未来 CLI：

```powershell
graph_refresh_token\.venv\Scripts\python.exe outlook\mailbox_graph.py --watch-delta --folder "收件箱" --folder "垃圾邮件" --interval 3
```

### 7.6 运行时文件约定

新增：

```text
outlook/db/.gitignore
outlook/out/.gitignore
```

这些目录会产生账号、AT、文件夹和邮件标题数据，不进入 Git。

### 7.7 RT 提取失败重试

`graph_refresh_token/oauth_graph.py` 增加默认重试规则：

```text
首次失败 -> 等待 1 秒 -> 自动重试 1 次
```

默认最多运行 2 次：

```powershell
graph_refresh_token\.venv\Scripts\python.exe graph_refresh_token\oauth_graph.py
```

可关闭重试：

```powershell
graph_refresh_token\.venv\Scripts\python.exe graph_refresh_token\oauth_graph.py --retries 0
```

可调整重试次数和间隔：

```powershell
graph_refresh_token\.venv\Scripts\python.exe graph_refresh_token\oauth_graph.py --retries 3 --retry-delay 2
```

这个优化主要用于处理 Microsoft 登录页、代理、TLS 或临时中间页导致的偶发失败。

## 8. 2026-07-12 更新记录

版本号：`26.7.12A`

本次完成 Outlook 子项目第三阶段：在 `outlook/` 内形成可独立运行的本地邮箱服务，并把 Graph 元数据能力从离线 CSV 导出扩展到页面和 JSON API。

### 8.1 aiohttp 邮箱服务

新增目录：

```text
outlook/server/
  main.py
  auth_service.py
  static/
  tests/
  log/.gitignore
```

启动命令：

```powershell
D:\0Code2\py312\python.exe outlook/server/main.py --host 127.0.0.1 --port 8780
```

服务读取 `graph_refresh_token/out/*.txt`，复用 `outlook/mailbox_graph.py` 刷新 Graph access token 和读取文件夹/邮件标题。

### 8.2 登录与权限模型

普通登录使用账号文件里的邮箱和密码，只允许访问当前邮箱。

本机免密白名单使用严格 AND 条件：

```text
Host 主机部分 == 127.0.0.1
AND
request.remote == 127.0.0.1
```

`localhost`、`X-Forwarded-For`、`X-Real-IP` 等不参与白名单判断。全邮箱会话每次请求重新检查 Host/IP，条件变化立即失效。

### 8.3 收件地址与标题 API

`mailbox_graph.py` 的标题字段增加 `toRecipients`，用于：

1. 在页面邮件表格中展示实际收件地址。
2. 从近期收件箱和垃圾邮件归集主邮箱与已观察别名。
3. 按别名查找最新邮件标题。

标准 URL：

```text
GET /api/mailboxes/user@outlook.com/recipients
GET /api/mailboxes/user@outlook.com/messages/latest
GET /api/mailboxes/user@outlook.com/messages/latest?recipient=user%2B2%40outlook.com
```

当前只返回主题，不读取 `body`、`bodyPreview`、`uniqueBody` 或附件内容。

### 8.4 运行数据和验证

`outlook/server/log/` 保存轮转服务日志、进程输出和本地 Playwright 截图。目录级 `.gitignore` 使用：

```gitignore
*
!.gitignore
```

因此提交只保留空目录规则，不包含邮箱地址、日志、截图或其他运行产物。

验证覆盖：

- 本机白名单和 `localhost` 差分。
- 普通用户自身访问与跨邮箱 `403`。
- 主邮箱和多个别名的收件地址归集。
- 每个收件地址的最新主题 API。
- 5 项单元测试、Python/JavaScript 语法检查。
- Edge/Playwright 桌面与移动端布局、控制台错误和横向溢出检查。

## 9. 2026-07-13 更新记录

版本号：`26.7.13A`

今天主要处理上游同步、Outlook 创建链路拆分，以及私有协议注册机的本地分析文档。

### 9.1 合并上游更新

检查 `upstream/main` 后发现上游新增 2 个提交：

```text
2332296 feat(outlook): 按住验证拟人化(WindMouse+OU震颤) + 节点探测轮换
ceab1e6 feat(outlook): 抽不到 Graph token 的号单独存 outlook_no_graph.txt
```

已合并到本地 `main`，合并提交为：

```text
96cd119 Merge remote-tracking branch 'upstream/main'
```

合并时仅 `CHANGELOG.md` 有冲突，处理方式是同时保留本地 `26.7.12A Outlook 本地邮箱工作台` 记录和上游 `2026-07-13 Outlook 按住验证拟人化 + 节点探测轮换` 记录。

合并后通过基础语法检查：

```powershell
py -3 -m py_compile outlook_reg_loop.py register.py register_outlook_standalone.py common/human_mouse.py outlook/mailbox_graph.py graph_refresh_token/oauth_graph.py
```

### 9.2 上游 Outlook 注册链路变化

上游新增：

```text
common/human_mouse.py
```

该模块用于 Outlook / PerimeterX 按住验证，核心函数包括：

```text
windmouse_path()
human_move_to()
tremor_offsets()
human_press_and_hold()
```

注册流程里原来的机械抖动被替换为：

```text
WindMouse 逼近轨迹 + Ornstein-Uhlenbeck 自相关震颤
```

同时 `outlook_reg_loop.py` 增加 Clash 节点探测轮换：

```text
_probe_delay()
maybe_rotate_verified()
```

运行时先对候选节点执行 `/delay` 探测，跳过超时/过慢节点，再切换到延迟最低的可用节点。

新增固定当前节点开关：

```powershell
python outlook_reg_loop.py --no-rotate
```

或：

```powershell
$env:OUTLOOK_NO_ROTATE = "1"
```

注册成功但 Graph RT 抽取失败时，现在写入：

```text
outlook_no_graph.txt
```

格式：

```text
email----password
```

该文件已加入 `.gitignore`，用于后续补抽 RT，不再直接丢弃可登录账号。

### 9.3 新增 `outlook_create/` 子项目文档和脚本

今天新增公开目录：

```text
outlook_create/
```

定位：只分析和包装“Outlook 创建/注册”链路，不负责读邮件，不保存账号、密码、RT、AT。

新增文件：

```text
outlook_create/README.md
outlook_create/FLOW_ANALYSIS.md
outlook_create/UPDATE_2026-07-13.md
outlook_create/scripts/inspect_outlook_create.py
outlook_create/scripts/run_outlook_loop.ps1
outlook_create/scripts/run_outlook_standalone.ps1
```

其中：

- `FLOW_ANALYSIS.md` 记录 `outlook_reg_loop.py`、`register_outlook_standalone.py`、`extract_graph_tokens.py` 和 `common/human_mouse.py` 的整体调用链。
- `UPDATE_2026-07-13.md` 记录今天合并的上游 Outlook 更新。
- `inspect_outlook_create.py` 只做静态检查，不输出 `.env`、密码、RT、AT。
- `run_outlook_loop.ps1` 包装 `outlook_reg_loop.py`。
- `run_outlook_standalone.ps1` 包装 `register_outlook_standalone.py`。

常用命令：

```powershell
.\outlook_create\scripts\run_outlook_loop.ps1 -Count 1
.\outlook_create\scripts\run_outlook_loop.ps1 -Count 1 -NoRotate
.\outlook_create\scripts\run_outlook_standalone.ps1 -Count 1 -Mode browser -Concurrency 1
py -3 .\outlook_create\scripts\inspect_outlook_create.py
```

已验证：

```powershell
py -3 -m py_compile outlook_create\scripts\inspect_outlook_create.py
py -3 outlook_create\scripts\inspect_outlook_create.py
```

### 9.4 私有目录 `outlook_create_Private/`

本地存在私有目录：

```text
outlook_create_Private/
```

该目录已加入 `.gitignore`：

```gitignore
outlook_create_Private/
```

确认不会提交 Git。

今天在私有目录里分析了 `outlook注册机.py`，并生成本地文档：

```text
outlook_create_Private/README.md
outlook_create_Private/docs/FLOW_ANALYSIS.md
outlook_create_Private/docs/FUNCTION_MAP.md
outlook_create_Private/docs/USAGE_AND_NOTES.md
```

私有脚本是纯协议注册机，整体流程为：

```text
GET signup 页面
-> 提取 ServerData / apiCanary / uaid
-> CheckAvailableSigninNames
-> risk/initialize
-> CaptchaRun PxCaptcha2
-> risk/verify 第一次触发 challenge
-> 等 pressToken
-> risk/verify 第二次提交 challengeSolution
-> CreateAccount
-> OAuth2 Authorization Code 提取 RT
-> 写输出文件
```

私有脚本输出格式为：

```text
email----password----client_id----refresh_token
```

主项目 `emails.txt` 使用：

```text
email----password----refresh_token----client_id
```

因此如果后续要把私有脚本产物导入主项目，需要交换第 3/4 位。

### 9.5 当前边界

当前目录职责划分如下：

| 目录 | 职责 |
|---|---|
| `graph_refresh_token/` | 已有账号的 Graph RT 提取。 |
| `outlook/` | 读取邮箱文件夹、标题元信息、本地邮箱工作台。 |
| `outlook_create/` | Outlook 创建/注册链路的公开文档和包装脚本。 |
| `outlook_create_Private/` | 本地私有协议注册机与私有分析文档，不进 Git。 |

版本 `26.7.13A` 的重点是把“创建账号”和“读取邮箱”进一步拆开：`outlook_create/` 只关心注册/入池，`outlook/` 继续关心 Graph 邮箱读取和本地工作台。

