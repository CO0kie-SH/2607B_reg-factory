# co0kie_grok：上游 Grok 功能知识库

本文档集基于上游 `tiantianGPU/reg-factory` 当前 `470ce80` 版本整理，覆盖 Grok 注册、临时邮箱、验证码、代理、SSO、OAuth、SUB2API、webchat2api、WebUI、编排、测试和故障处理。

> 当前主入口是根目录的 `register_grok_http.py`。`register_grok.py` 是保留的浏览器实现，并承担 Outlook 邮箱等兼容路径。

## 快速开始

```powershell
Copy-Item .env.example .env
python register_grok_http.py --count 1 --node auto
```

注册后标准凭据写入：

```text
tokens/grok/<email>.sso.json
```

启用 SUB2API 即时导入：

```powershell
python register_grok_http.py --count 1 --sub2api
```

补传已有 SSO：

```powershell
python upload_tokens.py grok
```

## 文档导航

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 总体架构、数据流、模块职责和两套实现对比 |
| [HTTP_FLOW.md](HTTP_FLOW.md) | 纯 HTTP 主流程、协议阶段、重试和退出语义 |
| [BROWSER_FLOW.md](BROWSER_FLOW.md) | 浏览器兼容流程、Outlook 取码和 Turnstile 处理 |
| [CONFIGURATION.md](CONFIGURATION.md) | CLI、环境变量、临时邮箱、代理及下游配置 |
| [TOKENS_AND_INTEGRATIONS.md](TOKENS_AND_INTEGRATIONS.md) | SSO 落盘、xAI OAuth、SUB2API、webchat2api |
| [OPERATIONS.md](OPERATIONS.md) | WebUI、批量编排、测试、排障和维护建议 |
| [SOURCE_MAP.md](SOURCE_MAP.md) | Grok 相关源码索引和关键函数入口 |

## 一句话理解

上游 Grok 功能以 `curl_cffi` 浏览器指纹和 `xconsole_client` 协议客户端完成 xAI 注册，用临时邮箱接收验证码、第三方服务求解 Turnstile，最终保存 Web SSO；随后可把 SSO 注入 webchat2api，或兑换成带 `refresh_token` 的 xAI OAuth 凭据并创建 SUB2API Grok 账号。

