# 本地工程功能与存储图

更新：2026-11-08。根据本地源码和实际目录整理，不包含账号密码、Cookie 或推送密钥。

## 1. 功能流程

```mermaid
flowchart TD
    UI[管理页面：web-ui 源码 / dist 构建结果] --> SERVER[local_server.py：本机登录与访问保护]
    SERVER --> API[src/app.py + src/api/routes：任务和账号接口]
    API --> TASK[task_service.py：任务配置]
    UI --> NODES[AccountNodesCard：当前账号 / 可用候选 / 冷却节点]
    NODES --> NODEAPI[accounts/nodes → account_nodes.py：只读本地状态]
    NODEAPI --> DB
    TASK --> DB[(data/app.sqlite3)]
    API --> SCHED[scheduler_service.py：按 Cron 调度]
    SCHED --> PROC[process_service.py：启动与停止任务进程]
    PROC --> GUARD[failure_guard.py：连续失败与暂停保护]
    GUARD --> SPIDER[spider_v2.py + scraper.py：采集任务]
    SPIDER --> POOL[account_failover.py：可配置冷却 / 账号切换 / 成功确认]
    POOL -->|同节点本轮连续两次失败| BRIDGE[browser_diagnostics：独立项目兼容入口]
    BRIDGE -->|data/browser-diagnostics-project.json| DIAG[私人内容/浏览器启动诊断：启动与连接只读诊断]
    DIAG --> DIAGREPORT[data/browser-diagnostics：逐事件 Markdown 与 JSON 报告]
    SURVEYUI[调查当前价格 / 本地搜索 / 手动 sold] --> SURVEYAPI[price_surveys.py]
    SURVEYAPI --> SURVEYSERVICE[price_survey_service.py：排队、取消、后台进程]
    SURVEYSERVICE -->|同一浏览器操作锁| PROC
    SURVEYSERVICE --> SURVEYRUN[price_survey_runner.py：单轮列表采样]
    SURVEYRUN --> SPIDER
    SPIDER --> SURVEYSTORE[price_survey_store.py：样本统计 / 历史对比]
    SURVEYSTORE --> DB
    SURVEYAPI -->|本地查询和 JSON 导出| SURVEYSTORE
    SETTINGS[设置页：总尝试次数 / 冷却小时] --> SETTINGSAPI[settings.py：校验并保存 .env]
    SETTINGSAPI --> POLICYENV[.env：ACCOUNT_ROTATION_RETRY_LIMIT / ACCOUNT_BLACKLIST_TTL]
    POLICYENV -->|每轮读取| POOL
    POOL --> CHROME[shared_chrome.py：private1 Chrome / private_2 Edge]
    POOL --> FIREFOX[firefox_worker.py + firefox_runtime.py：private_3 常驻 Firefox]
    VERIFY[verify-chrome.cmd / verify-chrome.py：手动验证并保存] --> CHROME
    VERIFY --> FIREFOX
    CHROME <-->|联网：搜索、筛选、商品详情| XY[闲鱼网站]
    FIREFOX <-->|联网：搜索、筛选、商品详情| XY
    SPIDER --> FILTER[new_listing_policy.py：上新与接口检查]
    FILTER --> ANALYZE[item_analysis_dispatcher.py：关键词或 AI 分析]
    ANALYZE --> STORE[result_storage_service.py：结果入库]
    STORE --> DB
    ANALYZE --> PUSH[notification_service.py + bark_client.py]
    PUSH -->|联网| BARK[Bark 服务 → iOS 通知]
    POOL -->|限制及冷却通知 / 新账号完成一轮后确认| PUSH
    ANALYZE -. 可选：配置 AI 时联网 .-> AI[AI API]
```

Firefox 使用 Playwright 配套运行时和独立持久配置，由本机常驻 worker 持有；任务进程通过仅监听回环地址、带随机令牌认证的接口提交工作。每轮结束保留同一个浏览器与会话，取消任务或客户端掉线会取消采集。普通日用 Firefox 不被接管。2026-11-08 实测 private_3 完成搜索、最新排序、价格筛选并解析 30 条商品；private1 初始搜索正常；private_2 当次被闲鱼要求手动验证。

## 2. 本地存储结构

```mermaid
flowchart LR
    ROOT[xianyu-monitor 工程目录] --> CODE[源码与入口]
    CODE --> PY[src/ · spider_v2.py · local_server.py]
    CODE --> WEB[web-ui/ 源码 · dist/ 网页产物]
    CODE --> CMD[start-local.ps1 · stop-local.ps1 · verify-chrome.py]
    ROOT --> DATA[业务数据：data/]
    DATA --> DB[(app.sqlite3)]
    DB --> TABLES[tasks 任务 / result_items 商品 / price_snapshots 价格 / result_blacklist_rules 排除规则]
    DB --> SURVEYTABLES[price_survey_runs 调查 / price_survey_items 历史状态 / app_metadata 调查设置与样本 JSON]
    DATA --> PROFILE[chrome-private1/ 与配置映射指定的 Edge 目录]
    DATA --> FF[firefox-private_3/：Firefox 配置 / live-state.json / worker.json]
    DATA --> POOLDB[account-failover.sqlite3：停用快照、当前账号、待确认通知]
    DATA --> MAP[account-browsers.json：1 Chrome / 2 Edge / 3 Firefox]
    DATA --> BACKUP[login-backups/：登录态和暂停记录备份]
    DATA --> POLICY[new-listing-policy.json：上新时间界线]
    ROOT --> STATE[state/private1.json、private_2.json、private_3.json：三个登录态快照]
    ROOT --> LOGS[logs/]
    LOGS --> TASKLOG[task_0.log：任务采集与失败记录]
    LOGS --> SERVERLOG[server.out.log / server.err.log：后端日志]
    LOGS --> GUARD[task-failure-guard.json：失败次数与暂停截止时间]
    ROOT --> ENV[.env：运行设置、登录密码、通知密钥]
    ROOT --> ASSETS[images/ 图片 · prompts/ 分析提示词]
    ROOT --> RUNTIME[.runtime-venv/ · .python/ · web-ui/node_modules/：运行依赖]
    ROOT --> DOC[WORKLOG_README.md：修改日志 / PROJECT_MAP_README.md：本图]
```

## 阅读说明

- 当前主要业务存储为 `data/app.sqlite3`。界面出现的 `_full_data.jsonl` 也可能只是数据库中的结果集名称，不代表同名实体文件。
- `config.json` 为旧配置/导入兼容文件；当前任务以 SQLite 与管理接口为准。
- `state/private_2.json` 是登录态快照；`data/chrome-private_2/` 是持续使用的浏览器配置目录，二者用途不同。
- `.env`、登录态快照、Chrome 配置目录和登录态备份含敏感信息，不应公开分享。
- Firefox 的 live-state.json 保存续期后的会话，worker.json 包含本机连接令牌，同样不应公开分享。新导入的账号快照优先于旧的运行快照。
- 只对当前选定账号执行定时搜索；备用和冷却账号不轮询闲鱼。冷却到期只恢复候选资格，真正被选中时才访问闲鱼。
- 账号冷却截止保存在 account-failover.sqlite3；当前默认六小时，可在设置页修改。受限时推送冷却截止与下一账号，切换后首次成功完成采集再发确认。
- 同一轮同一账号总尝试次数当前为 2（含首次），可在设置页修改；新配置从下一轮生效，已有冷却截止不回写。常驻 Firefox 也逐轮读取同一份本地配置，不需重开浏览器。
- 2026-11-08 更新：超时、登录/验证、搜索、排序筛选等采集异常共用上述次数上限，混合类型也累计。当前账号同一轮连续两次失败即本地冷却并选择下一节点；托管轮换不再叠加旧 FailureGuard 的三次任务暂停。取消不计失败，手动价格调查仍不自动重试。
- 账号节点面板位于任务页和账号页，页面可见时每 15 秒读取一次本地状态，不增加闲鱼检查次数。
- 本地图不改变任务、筛选、通知或检查频率。
- 手动价格调查默认 100 件，网页可改为 1–500；每次只执行一轮列表翻页，使用参考任务的当前可用账号，和正常监测排队使用浏览器。已有定时规则不改变。
- “本次未出现”只是有界搜索样本中缺失，不等于已售出；sold 与成交价由用户确认填写，最后标价另存。查询和导出均为本地操作。
- LOCAL_LIST_ONLY=true 时，日常新商品从列表数据分析与 Bark 推送，不自动打开详情页；详情描述和卖家资料不会采集。
