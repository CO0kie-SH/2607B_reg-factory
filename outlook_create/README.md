# Outlook create 子项目

> 版本记录：`26.7.13A`  
> 更新时间：2026-07-13  
> 作用范围：只整理主项目中的 Outlook 注册/入池流程，不存放账号、密码、RT/AT 或运行产物。

## 这个目录做什么

`outlook_create/` 用来把主项目里的 Outlook 注册链路单独说明清楚，便于后续继续改写、调参、补脚本。

它覆盖三块内容：

1. `outlook_reg_loop.py`：主推荐入口，循环创建 Outlook 账号、抽 Graph RT、写入账号池。
2. `register_outlook_standalone.py`：底层注册执行器，包含 protocol/headless/browser 三种模式。
3. `common/human_mouse.py`、`extract_graph_tokens.py`、`_clash_verge.py` 等辅助模块。

## 快速运行

### 运行主循环，尝试 1 次

```powershell
.\outlook_create\scripts\run_outlook_loop.ps1 -Count 1
```

### 固定当前节点，不做 Clash 节点轮换

```powershell
.\outlook_create\scripts\run_outlook_loop.ps1 -Count 1 -NoRotate
```

### 直接跑 standalone 执行器

```powershell
.\outlook_create\scripts\run_outlook_standalone.ps1 -Count 1 -Mode browser -Concurrency 1
```

### 静态检查 Outlook 注册结构

```powershell
py -3 .\outlook_create\scripts\inspect_outlook_create.py
```

该检查脚本只做源码结构、入口参数、环境变量和产物路径扫描，不读取或输出 `.env`、账号密码、RT/AT 完整值。

## 文档索引

| 文件 | 内容 |
|---|---|
| [`FLOW_ANALYSIS.md`](FLOW_ANALYSIS.md) | Outlook 注册主流程、函数结构、状态流转、输出文件 |
| [`UPDATE_2026-07-13.md`](UPDATE_2026-07-13.md) | 今天合并的上游更新记录 |
| [`scripts/run_outlook_loop.ps1`](scripts/run_outlook_loop.ps1) | 对 `outlook_reg_loop.py` 的 PowerShell 包装脚本 |
| [`scripts/run_outlook_standalone.ps1`](scripts/run_outlook_standalone.ps1) | 对 `register_outlook_standalone.py` 的 PowerShell 包装脚本 |
| [`scripts/inspect_outlook_create.py`](scripts/inspect_outlook_create.py) | 注册链路静态结构检查脚本 |

## 推荐入口选择

| 目标 | 推荐入口 | 原因 |
|---|---|---|
| 稳定补充 Outlook 账号池 | `outlook_reg_loop.py` | 带节点轮换、Graph RT 抽取、池写入和 no-graph 暂存 |
| 单独调试注册页面 | `register_outlook_standalone.py --mode browser` | 直连 BitBrowser，可观察完整浏览器过程 |
| 测试 protocol/headless/browser fallback | `register_outlook_standalone.py --mode auto` | 会按 protocol → headless → browser 逐级回退 |
| 只补抽已存在账号 RT | `extract_graph_tokens.py` 或 `graph_refresh_token/` | 不重新注册，只走 Graph OAuth |

## 敏感文件边界

本目录不应保存以下文件：

```text
.env
emails.txt
outlook_no_graph.txt
_outlook_pool/*.json
outlook_accounts/*
graph_refresh_token/out/*
outlook/db/*.csv
outlook/out/*.csv
```

这些文件可能包含邮箱、密码、refresh_token、access_token 或邮件元数据。
