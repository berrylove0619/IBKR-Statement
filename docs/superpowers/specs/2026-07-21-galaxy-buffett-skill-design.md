# Galaxy Buffett - Daily Stock Analysis 设计说明

## 目标

创建一个只为当前用户服务的单入口 Skill：`galaxy-buffett-daily-stock-analysis`。它每天读取 IBKR-Statement 已导入的最新持仓快照，筛选可信的美股、宏观和科技新闻，解释这些事件对实际持仓的影响，并生成可快速阅读、可追溯证据的中文晨报。

显示名称为 **Galaxy Buffett - Daily Stock Analysis**。Skill 负责分析方法与输出纪律；IBKR-Statement 继续负责本地数据、缓存、调度和 HTML 报告。不增加登录系统、云端账户、自动交易或券商凭证保存。

## 用户体验

- 用户每天早上约 07:30 打开任务，先看到“一分钟结论”和今天是否需要行动。
- 报告覆盖市场大事、重要财报、科技圈重大事件和全部持仓扫描。
- 只有与当前持仓直接相关、或存在清晰二阶传导路径的事件，才进入持仓建议。
- 每条重要结论可追溯到英文专业来源；不使用中国新闻网站作为新闻证据。
- 建议使用“观察 / 持有 / 条件式加减仓 / 风险控制”表达，不替用户自动下单，也不把未经证实的消息转成交易动作。

## 单入口架构

```text
07:30 每日任务
    -> IBKR-Statement 最新成功导入的持仓快照
    -> Galaxy Buffett Skill
        -> 新闻证据门槛
        -> 全持仓相关性扫描
        -> 条件加载分析参考
        -> 一次组合级综合判断
    -> 本地 HTML 晨报与证据链接
```

Skill 不再串行调用 `global-stock-data`、财报、价值投资、市场情绪等多个 Skill。经验证有效的规则会沉淀为本 Skill 的 references，并按事件类型条件加载。

## 文件结构

```text
skills/galaxy-buffett-daily-stock-analysis/
├── SKILL.md
├── agents/openai.yaml
└── references/
    ├── news-evidence.md
    ├── portfolio-analysis.md
    ├── earnings-playbook.md
    ├── macro-risk.md
    ├── long-term-quality.md
    ├── tech-supply-chain.md
    └── morning-report-contract.md
```

`SKILL.md` 只保留触发条件、主流程、硬性门槛和 reference 路由。详细分析方法按需读取，避免每天把所有框架都装入上下文。

## 数据与证据边界

允许的新闻证据源共六类：

1. SEC EDGAR；
2. 公司官方 Investor Relations；
3. Reuters；
4. CNBC；
5. MarketWatch；
6. Nasdaq。

SEC 与公司 IR 是一手来源；其余为独立英文专业媒体。搜索引擎和聚合页只能发现线索，不能作为独立证据。新浪、腾讯、东方财富及其他中文新闻网站不得作为新闻来源、事件证据或仓位建议依据。

重要事件进入仓位建议前，原则上需要“一手来源 + 一家独立媒体”，或“两家相互独立的白名单媒体”。仅有一手材料时可标记为等待独立确认；单一媒体、匿名爆料或传闻只能放入观察区。转载同一通讯社内容不得重复计数。

## 最终回归规则

- 没有任何候选 URL 或来源时，使用 `evidence_gap` 标记证据缺口，验证状态写“不适用”。`evidence_gap` 不是第五种验证状态，且不得进入任何动作依据。
- 没有最新成功 IBKR 导入时，用户或题设提供的证券仅为临时范围；正式覆盖显示“未验证”，不得生成 coverage 分数或声称全持仓覆盖。
- 环境不允许写本地文件时，仍返回从 `<!doctype html>` 到 `</html>` 的完整 HTML 代码块，并明确未保存文件；不得降为 Markdown 草案。

## 条件加载与 Token 控制

每天固定读取：

- `news-evidence.md`
- `portfolio-analysis.md`
- `morning-report-contract.md`

仅在触发时读取：

- 有持仓公司临近或刚发布财报：`earnings-playbook.md`
- 周度宏观复盘或异常宏观冲击：`macro-risk.md`
- 月度复盘或投资逻辑发生变化：`long-term-quality.md`
- AI、半导体、数据中心、光通信或关键供应链命中持仓：`tech-supply-chain.md`

每日先用确定性规则做全持仓扫描，再选择最多 6 个需要展开的持仓。最终只做一次组合级综合分析；只有财报命中且确实需要深挖时，允许增加一次专项分析。报告默认限制为重大市场事件 5 条、科技事件 4 条、重点持仓 6 个，其余合并为“无重大变化”。

## 持仓建议纪律

- 必须使用最新成功导入时间和实际持仓；数据缺失或过期时明确提示，不能猜测。
- 新闻影响分成直接、二阶、宏观共同因子和无实质关联。
- 每个动作写明触发条件、反证条件、时间范围和主要风险。
- 没有新证据时，默认结论可以是“维持原计划”，而不是为了每天产生动作而交易。
- 单一来源、传闻、短时价格波动或泛行业新闻不能独立触发加仓、减仓或清仓。
- 输出是研究辅助，不是收益保证；任何动作仍由用户确认并在 IBKR 自行执行。

## 安装与维护

项目内目录是唯一真源，并纳入版本控制：

`/Users/galaxyimac/Melo DEV/Melo Stock/IBKR-Statement/skills/galaxy-buffett-daily-stock-analysis`

验证通过后复制安装到：

`/Users/galaxyimac/.codex/skills/galaxy-buffett-daily-stock-analysis`

以后需求变化先修改项目内版本，通过基线、结构校验和压力测试后再同步安装，避免全局安装版本与项目版本悄悄分叉。
