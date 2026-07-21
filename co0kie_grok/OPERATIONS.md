# Grok 运行、测试与排障

## WebUI 和编排入口

- WebUI 的 Grok 注册任务指向 `register_grok_http.py`。
- `register_three_platforms.py` 的 Grok 分支使用 HTTP 版。
- `run_full_flow.py --platforms grok` 通过三平台注册编排进入 Grok。
- `--grok-sub2api` 和 `--grok-sub2api-group` 会逐层透传。

```powershell
python run_full_flow.py --platforms grok --grok-sub2api
python register_three_platforms.py --from-pool --platforms grok
```

## 现有测试

| 文件 | 覆盖点 |
|---|---|
| `tests/test_grok_browser.py` | 浏览器注册关键行为和回归 |
| `tests/test_grok_sub2api_flow.py` | 注册到 SUB2API 的成功语义 |
| `tests/test_sub2api_grok.py` | Grok 分组、导入请求和响应处理 |
| `tests/test_temp_email_yyds.py` | YYDS API 行为和 404 处理 |
| `tests/test_registration_schema.py` | WebUI 注册 schema |
| `tests/test_proxy_switch.py` | 节点选择与代理逻辑 |

建议回归命令：

```powershell
python -m pytest tests/test_grok_browser.py tests/test_grok_sub2api_flow.py tests/test_sub2api_grok.py tests/test_temp_email_yyds.py
```

## 常见故障矩阵

| 现象 | 可能原因 | 检查顺序 |
|---|---|---|
| 找不到可用节点 | CF 拦截、Clash API/端口错误、节点污染 | Clash 状态 → `CLASH_PROXY` → 指定节点 → auto 探测日志 |
| 注册页缺少 sitekey/action | 页面未完整加载、节点被挑战、上游页面结构变化 | HTTP 状态、RSC/静态块标记、`xconsole_client/config.py` 默认值 |
| 发码接口拒绝 | 临时邮箱域名被 xAI 拒绝 | 增加 `--mailbox-attempts`，配置 provider 故障转移 |
| 发码成功但收不到 | provider 延迟、共享域限流、超时太短 | `temp_email doctor`，增加 `--code-timeout` |
| 验证码失败 | 分隔符格式、邮件解析误匹配 | 检查 `CODE_REGEX` 和原码/去杠二次提交 |
| Turnstile 失败 | key 无效、余额、sitekey 变化、服务波动 | 按 YesCaptcha → CapSolver → EZCaptcha 日志检查 |
| 建号失败 | server action 变化、token 过期、IP 风险 | `extract_signup_error()`、重新加载注册页、换节点 |
| 建号成功但无 SSO | Cookie/RSC 链变化 | 查看 `fetch_sso_token`，确认密码登录回退结果 |
| SUB2API 分组错误 | 同名分组属于 OpenAI | 创建 `platform=grok` 分组并更新配置 |
| SUB2API 远端转换失败 | 服务端无法访问 xAI | 设置远端 `proxy_id`，或保留本机 `CLASH_PROXY` 走 OAuth 回退 |

## 维护时优先检查

1. `accounts.x.ai` gRPC 服务名、字段和 trailer 是否变化。
2. Next.js build/action ID、RSC 返回结构是否变化。
3. Turnstile sitekey 是否仍能动态提取。
4. SSO Cookie 名是否仍为 `sso`/`sso-rw`。
5. xAI Device Flow endpoint、client id 和 scope 是否变化。
6. SUB2API `/api/v1/admin/grok/sso-to-oauth` 响应结构是否变化。
7. 临时邮箱 provider 的域名目录和 JSON 字段是否变化。

