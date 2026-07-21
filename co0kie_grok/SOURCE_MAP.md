# Grok 相关源码索引

## 直接入口

| 文件 | 关键入口 |
|---|---|
| `register_grok_http.py` | `main()`、`register_one()`、`solve_turnstile()`、`poll_code_sync()` |
| `register_grok.py` | `main()`、`register_one()`、`ensure_turnstile()`、`register_via_protocol_rt()` |
| `upload_tokens.py` | `upload_grok()` |

## 公共模块

| 文件 | Grok 相关内容 |
|---|---|
| `common/grok_oauth.py` | `convert_grok_sso_local()`，SSO 到 xAI OAuth Device Flow |
| `common/session_export.py` | `save_grok_token()` |
| `common/uploaders.py` | `upload_sub2api_grok()`、`upload_webchat2api()` |
| `common/temp_email.py` | `create_mailbox()`、`poll_verification_code()`、`_scan_once()` |
| `common/proxy_switch.py` | `set_node()`、`find_working_node()`、`concrete_nodes()` |
| `common/token_upload_state.py` | `mark_uploaded()`、`uploaded_set()` |
| `common/browser.py` | BitBrowser/AdsPower 抽象和 CDP 连接 |
| `common/mailbox.py` | Outlook Graph、Broker 和网页取码能力 |

## xconsole_client

该目录是 HTTP 主流程的协议底座，来源信息记录在 `xconsole_client/VENDORED.md`。

| 文件 | 职责 |
|---|---|
| `xconsole_client/client.py` | xAI 注册客户端、gRPC-web、server action 和 SSO 获取 |
| `xconsole_client/config.py` | endpoint、sitekey、action 等默认配置 |
| `xconsole_client/grpcweb.py` | gRPC-web 帧编码、解码及 trailer 处理 |
| `xconsole_client/fingerprint.py` | HTTP/TLS/浏览器指纹辅助 |
| `xconsole_client/sso.py` | SSO 会话处理 |
| `xconsole_client/solver.py` | YesCaptcha 等求解器封装 |
| `xconsole_client/oauth_protocol.py` | OAuth 协议基础实现 |
| `xconsole_client/xai_oauth.py` | xAI OAuth 相关逻辑 |
| `xconsole_client/mailbox.py` | vendored 邮箱抽象；主入口目前使用 `common.temp_email` |
| `xconsole_client/tempmail_transport.py` | 临时邮箱传输适配 |

## 配置、UI 与编排

| 文件 | 关联内容 |
|---|---|
| `.env.example` | Grok、临时邮箱、打码、SUB2API、webchat2api 配置模板 |
| `config.py` | 环境变量映射 |
| `webui/scripts.py` | Grok 任务 schema 和 HTTP 入口 |
| `webui/server.py` | WebUI 任务执行、环境配置和状态接口 |
| `register_three_platforms.py` | 平台命令拼装和 Grok 参数透传 |
| `run_full_flow.py` | 端到端编排和 `--grok-sub2api` 参数 |

## 文档依据

本知识库对应以下上游版本：

```text
upstream/main 470ce80 fix: stabilize ChatGPT signup and Codex flow
```

后续同步上游时，可先运行以下命令定位知识库需要更新的范围：

```powershell
git diff --name-status 470ce80..upstream/main -- `
  register_grok.py register_grok_http.py common xconsole_client webui tests `
  config.py .env.example README.md CHANGELOG.md
```

