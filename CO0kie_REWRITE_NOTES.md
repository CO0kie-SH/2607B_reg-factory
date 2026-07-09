# CO0kie 项目改写说明

本文档是本 fork 的改写记录和后续重构入口。原项目说明仍以 `README.md` 为准；更完整的结构分析见 `PROJECT_OVERVIEW.md`、`outlook/ANALYSIS.md` 和 `graph_refresh_token/README.md`。

## 1. 当前改写目标

本次改写先不大规模移动原有代码，优先做三件事：

1. 梳理项目职责和接口，降低接手成本。
2. 把 Outlook 相关内容单独拆出文档目录。
3. 把 Microsoft Graph refresh token 提取流程做成独立子项目，方便单独调试和迭代。

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
