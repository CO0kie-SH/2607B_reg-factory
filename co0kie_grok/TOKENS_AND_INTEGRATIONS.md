# Grok 凭据与下游集成

## 标准 SSO 文件

`common.session_export.save_grok_token()` 生成：

```json
{
  "email": "ACCOUNT_EMAIL",
  "sso": "SSO_TOKEN",
  "ts": 1784650000
}
```

文件路径：

```text
tokens/grok/<安全化邮箱名>.sso.json
```

## SUB2API 远端转换

`upload_sub2api_grok()` 的步骤：

1. 登录 SUB2API 管理端。
2. 按名称查找分组，并校验分组平台为 `grok`。
3. 调用 `POST /api/v1/admin/grok/sso-to-oauth`。
4. 请求包含 `sso_tokens`、`group_ids`、并发、优先级、倍率和可选 `proxy_id`。
5. 仅在返回一个 `created` 且没有 `failed` 时判定成功。

创建类请求只发送一次，避免网络超时后自动重放产生重复账号。

## 本机 OAuth 回退

当 SUB2API 远端 SSO 转换未创建账号，并且调用方提供 `local_proxy` 时，系统执行 `common.grok_oauth.convert_grok_sso_local()`：

1. 将 SSO 写入 `.x.ai` 域的 `sso` 和 `sso-rw` Cookie。
2. 校验 Web SSO 仍然有效。
3. 请求 xAI OAuth Device Code。
4. 自动访问验证链接、确认授权。
5. 轮询 token endpoint，处理 `authorization_pending` 和 `slow_down`。
6. 要求响应包含 `refresh_token`。
7. 从 JWT 合并 email、sub、team_id 等声明。
8. 通过 SUB2API 管理 API 创建 Grok OAuth 账号。

OAuth scope 包含：

```text
openid profile email offline_access grok-cli:access api:access
conversations:read conversations:write
```

凭据包含 `access_token`、`refresh_token`、`token_type`、`client_id`、`scope`、`expires_at`、`base_url`，以及可用时的 `email`、`id_token`、`sub`、`team_id`。

## webchat2api 注入

`upload_webchat2api()` 调用：

```text
POST /api/remote-account/inject
Authorization: Bearer ADMIN_KEY
```

核心载荷：

```json
{
  "accounts": [{"token": "SSO_TOKEN", "provider": "grok", "type": "sso"}],
  "strategy": "merge",
  "source_id": "flowpilot-grok-sso",
  "source_name": "FlowPilot Grok SSO",
  "provider": "grok"
}
```

## 批量补传和幂等

```powershell
python upload_tokens.py grok
```

该命令扫描 `tokens/grok/*.sso.json`，按已配置目标上传。`common.token_upload_state` 保存已完成的“平台 + 目标 + 邮箱”组合，减少重复导入。

