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
