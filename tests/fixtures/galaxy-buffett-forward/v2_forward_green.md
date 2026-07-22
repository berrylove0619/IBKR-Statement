# v2_forward_green

## Prompt

Use $galaxy-buffett-daily-stock-analysis at /Users/galaxyimac/Melo DEV/Melo Stock/IBKR-Statement/skills/galaxy-buffett-daily-stock-analysis to draft a complete offline morning-report HTML for a portfolio with AAPL, MSFT, BRK.B and a short-duration Treasury ETF. Use the skill's own missing-data rules. Do not browse, call a broker, or modify files. Return the complete response you would give the user.

## Output

当前环境明确禁止联网、调用券商和写文件，因此以下内容未保存。按技能规则，IBKR 正式持仓状态为 `source_unavailable`、新鲜度为 `unknown`；AAPL、MSFT、BRK.B 和短期美债 ETF 仅列为“用户提供的临时范围”，不冒充已验证持仓，也不生成仓位建议。

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Galaxy Buffett 每日美股晨报｜2026-07-22</title>
  <style>
    :root {
      --bg: #f4f1e9;
      --surface: #fffdf8;
      --surface-muted: #f7f3e9;
      --text: #17211b;
      --muted: #667168;
      --line: #d9d5ca;
      --accent: #174f3c;
      --accent-soft: #e4efe9;
      --warning: #8a4c12;
      --warning-soft: #fff1dd;
      --danger: #8a2d2d;
      --danger-soft: #fae7e7;
      --shadow: 0 12px 34px rgba(26, 38, 30, 0.08);
      --radius: 16px;
    }

    * {
      box-sizing: border-box;
    }

    html {
      background: var(--bg);
      color: var(--text);
      font-family:
        -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      line-height: 1.65;
    }

    body {
      margin: 0;
    }

    a {
      color: var(--accent);
    }

    button,
    a {
      -webkit-tap-highlight-color: transparent;
    }

    .page-shell {
      width: min(920px, calc(100% - 32px));
      margin: 0 auto;
      padding: 34px 0 64px;
    }

    .report-header,
    .panel-section,
    .notice,
    .temporary-scope,
    .legal {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }

    .report-header {
      padding: 30px;
      border-top: 5px solid var(--accent);
    }

    .eyebrow {
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 0.78rem;
      font-weight: 750;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    h1,
    h2,
    h3 {
      line-height: 1.25;
    }

    h1 {
      margin: 0;
      font-size: clamp(1.85rem, 4vw, 2.75rem);
      letter-spacing: -0.035em;
    }

    h2 {
      margin: 0 0 18px;
      font-size: 1.4rem;
    }

    h3 {
      margin: 0 0 10px;
      font-size: 1.08rem;
    }

    p {
      margin: 0 0 12px;
    }

    p:last-child {
      margin-bottom: 0;
    }

    .subtitle {
      max-width: 700px;
      margin: 12px 0 0;
      color: var(--muted);
    }

    .meta-list,
    .account-list {
      display: grid;
      grid-template-columns: minmax(160px, 0.7fr) minmax(0, 1.3fr);
      gap: 0;
      margin: 22px 0 0;
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
    }

    .meta-list div,
    .account-list div {
      display: contents;
    }

    dt,
    dd {
      margin: 0;
      padding: 10px 14px;
      border-bottom: 1px solid var(--line);
    }

    dt {
      background: var(--surface-muted);
      color: var(--muted);
      font-weight: 650;
    }

    dd {
      background: var(--surface);
    }

    .meta-list div:last-child dt,
    .meta-list div:last-child dd,
    .account-list div:last-child dt,
    .account-list div:last-child dd {
      border-bottom: 0;
    }

    .report-tabs {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin: 20px 0;
      padding: 6px;
      position: sticky;
      top: 10px;
      z-index: 10;
      background: rgba(255, 253, 248, 0.94);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }

    .report-tabs button {
      min-height: 46px;
      padding: 10px 16px;
      border: 0;
      border-radius: 10px;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-weight: 750;
      cursor: pointer;
    }

    .report-tabs button[aria-selected="true"] {
      background: var(--accent);
      color: #fff;
    }

    .report-tabs button:focus-visible {
      outline: 3px solid rgba(23, 79, 60, 0.28);
      outline-offset: 2px;
    }

    main[role="tabpanel"] {
      display: grid;
      gap: 18px;
    }

    main[hidden] {
      display: none;
    }

    .panel-section,
    .notice,
    .temporary-scope,
    .legal {
      padding: 24px;
    }

    .notice {
      border-left: 5px solid var(--warning);
      background: var(--warning-soft);
    }

    .notice.critical {
      border-left-color: var(--danger);
      background: var(--danger-soft);
    }

    .status-line {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 9px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.78rem;
      font-weight: 750;
    }

    .badge.warning {
      background: var(--warning-soft);
      color: var(--warning);
    }

    .badge.danger {
      background: var(--danger-soft);
      color: var(--danger);
    }

    .empty-state {
      padding: 20px;
      border: 1px dashed #bbb4a6;
      border-radius: 12px;
      background: var(--surface-muted);
    }

    .empty-state strong {
      display: block;
      margin-bottom: 5px;
    }

    .calendar-row,
    .scope-row,
    .risk-row {
      padding: 14px 0;
      border-top: 1px solid var(--line);
    }

    .calendar-row:first-of-type,
    .scope-row:first-of-type,
    .risk-row:first-of-type {
      border-top: 0;
      padding-top: 0;
    }

    .calendar-row:last-child,
    .scope-row:last-child,
    .risk-row:last-child {
      padding-bottom: 0;
    }

    .scope-symbol {
      display: inline-block;
      min-width: 90px;
      font-weight: 800;
      color: var(--accent);
    }

    .scope-status {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .risk-row strong {
      display: block;
      margin-bottom: 3px;
    }

    .risk-row span {
      color: var(--muted);
    }

    .callout {
      margin-top: 16px;
      padding: 14px 16px;
      border-left: 4px solid var(--accent);
      border-radius: 8px;
      background: var(--accent-soft);
    }

    code {
      padding: 2px 5px;
      border-radius: 5px;
      background: rgba(23, 79, 60, 0.08);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.9em;
    }

    ul {
      margin: 10px 0 0;
      padding-left: 22px;
    }

    li + li {
      margin-top: 7px;
    }

    .legal {
      color: var(--muted);
      font-size: 0.91rem;
    }

    .legal strong {
      color: var(--text);
    }

    .generated-note {
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.85rem;
    }

    @media (max-width: 640px) {
      .page-shell {
        width: min(100% - 20px, 920px);
        padding-top: 18px;
      }

      .report-header,
      .panel-section,
      .notice,
      .temporary-scope,
      .legal {
        padding: 19px;
        border-radius: 13px;
      }

      .meta-list,
      .account-list {
        grid-template-columns: 1fr;
      }

      .meta-list div,
      .account-list div {
        display: block;
      }

      dt {
        padding-bottom: 4px;
        border-bottom: 0;
      }

      dd {
        padding-top: 4px;
      }

      .meta-list div:last-child dt {
        border-bottom: 0;
      }

      .report-tabs {
        top: 6px;
      }
    }
  </style>

  <noscript>
    <style>
      main[hidden] {
        display: grid !important;
        margin-top: 18px;
      }

      .report-tabs {
        display: none;
      }
    </style>
  </noscript>
</head>

<body>
  <div class="page-shell">
    <header class="report-header">
      <p class="eyebrow">Galaxy Buffett · Offline Morning Briefing</p>
      <h1>每日美股晨报</h1>
      <p class="subtitle">
        本报告处于严格离线降级模式：未连接 IBKR，未访问新闻、公司公告、
        SEC 文件、宏观数据或交易所日历。所有未知项均保留为未验证，不以推测补齐。
      </p>

      <dl class="meta-list">
        <div>
          <dt>晨报日期</dt>
          <dd>2026-07-22（Asia/Hong_Kong）</dd>
        </div>
        <div>
          <dt>新闻截止时间</dt>
          <dd>未建立——离线模式未执行新闻取证</dd>
        </div>
        <div>
          <dt>达到证据门槛的新闻</dt>
          <dd>0 条</dd>
        </div>
        <div>
          <dt>预计阅读时间</dt>
          <dd>约 3 分钟（降级版）</dd>
        </div>
        <div>
          <dt>正式账户覆盖</dt>
          <dd>未验证</dd>
        </div>
      </dl>
    </header>

    <nav class="report-tabs" role="tablist" aria-label="晨报视图">
      <button
        id="market-tab"
        data-panel="market-panel"
        aria-controls="market-panel"
        aria-selected="true"
        role="tab"
        tabindex="0"
      >每日市场</button>
      <button
        id="portfolio-tab"
        data-panel="portfolio-panel"
        aria-controls="portfolio-panel"
        aria-selected="false"
        role="tab"
        tabindex="-1"
      >我的持仓</button>
    </nav>

    <main
      id="market-panel"
      role="tabpanel"
      aria-labelledby="market-tab"
      data-news-shortfall="true"
    >
      <section class="notice critical" aria-labelledby="market-gap-title">
        <div class="status-line">
          <span class="badge danger">evidence_gap</span>
          <span class="badge warning">验证状态：不适用</span>
        </div>
        <h2 id="market-gap-title">达到证据门槛的重要事件不足 10 条</h2>
        <p>
          本次实际展示 0 条新闻。任务禁止联网，因此没有候选 URL、英文专业来源或一手材料；
          报告不能虚构市场事件，也不能用单一传闻、价格波动或无来源摘要填充数量。
        </p>
      </section>

      <section class="panel-section" aria-labelledby="coverage-title">
        <h2 id="coverage-title">市场证据覆盖</h2>
        <div class="risk-row">
          <strong>候选元数据</strong>
          <span>0 条；未执行联网扫描。</span>
        </div>
        <div class="risk-row">
          <strong>去重事件簇</strong>
          <span>0 个；没有可供去重的合格来源。</span>
        </div>
        <div class="risk-row">
          <strong>深读事件</strong>
          <span>0 个；未打开任何外部页面。</span>
        </div>
        <div class="risk-row">
          <strong>正式覆盖结论</strong>
          <span>未验证。不得据此判断今日宏观、公司、财报或科技事件。</span>
        </div>
        <div class="callout">
          恢复完整晨报需要重新执行英文专业来源取证，并对重要事件达到
          “一手材料 + 独立媒体”或“两家独立媒体”的验证门槛。
        </div>
      </section>

      <section id="month-end-calendar" class="panel-section">
        <h2>月底前重点财报与重大事件</h2>
        <div class="empty-state">
          <strong>日历未验证</strong>
          <p>
            目标窗口为 2026-07-22 至 2026 年 7 月月底。由于未联网核对公司 IR、
            官方宏观发布日历及交易所休市安排，本报告不列出任何财报日期、宏观事件、
            盘前／盘后时间或“★ 当前持仓”标记。
          </p>
          <p>
            日期来源：未提供。验证状态：不适用。证据缺口：是。
          </p>
        </div>
      </section>
    </main>

    <main
      id="portfolio-panel"
      role="tabpanel"
      aria-labelledby="portfolio-tab"
      data-account-status="source_unavailable"
      hidden
    >
      <section class="notice critical" aria-labelledby="account-status-title">
        <div class="status-line">
          <span class="badge danger">source_unavailable</span>
          <span class="badge warning">新鲜度：unknown</span>
        </div>
        <h2 id="account-status-title">IBKR 正式持仓未验证</h2>
        <p>
          本次任务禁止调用券商，因此没有读取“全部未平仓持仓”“账户财务指标”
          或“分币种余额”。按输入合同，报告必须停止持仓建议，并且不得回退本地文件、
          历史报告、记忆或用户口述来补齐正式账户数据。
        </p>
      </section>

      <section class="panel-section" aria-labelledby="account-title">
        <h2 id="account-title">账户情况</h2>
        <dl class="account-list">
          <div>
            <dt>数据源</dt>
            <dd>Interactive Brokers (IBKR) plugin</dd>
          </div>
          <div>
            <dt>插件查询时间</dt>
            <dd>未执行</dd>
          </div>
          <div>
            <dt>账户数据状态</dt>
            <dd><code>source_unavailable</code></dd>
          </div>
          <div>
            <dt>数据新鲜度</dt>
            <dd><code>unknown</code></dd>
          </div>
          <div>
            <dt>净清算值</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>现金</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>总持仓市值</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>当日盈亏</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>未实现盈亏</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>可用资金</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>初始／维持保证金</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>杠杆</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>分币种余额</dt>
            <dd>未验证</dd>
          </div>
          <div>
            <dt>已扫描／非零持仓总数</dt>
            <dd>未验证／未验证</dd>
          </div>
          <div>
            <dt>缺失组件</dt>
            <dd>全部未平仓持仓、账户财务指标、分币种余额</dd>
          </div>
          <div>
            <dt>报告生成时间</dt>
            <dd>2026-07-22（具体时刻未记录）</dd>
          </div>
        </dl>
      </section>

      <section class="temporary-scope" aria-labelledby="temporary-title">
        <h2 id="temporary-title">用户提供的临时证券范围</h2>
        <p>
          下列名称仅记录本次任务希望覆盖的范围，不计入正式
          <code>scanned_holdings</code> 或 <code>total_holdings</code>，
          不计算权重，也不生成 <code>holding-card</code>。
        </p>

        <div class="scope-row">
          <span class="scope-symbol">AAPL</span>
          <strong>Apple Inc.</strong>
          <div class="scope-status">账户归属、数量、市值、成本、币种及盈亏：未验证</div>
        </div>

        <div class="scope-row">
          <span class="scope-symbol">MSFT</span>
          <strong>Microsoft Corporation</strong>
          <div class="scope-status">账户归属、数量、市值、成本、币种及盈亏：未验证</div>
        </div>

        <div class="scope-row">
          <span class="scope-symbol">BRK.B</span>
          <strong>Berkshire Hathaway Inc. Class B</strong>
          <div class="scope-status">账户归属、合约标识、数量、市值、成本及盈亏：未验证</div>
        </div>

        <div class="scope-row">
          <span class="scope-symbol">代码未提供</span>
          <strong>短久期美国国债 ETF</strong>
          <div class="scope-status">
            具体基金、久期、费率、流动性、币种、数量、市值及账户归属：未验证
          </div>
        </div>
      </section>

      <section class="panel-section" aria-labelledby="portfolio-risk-title">
        <h2 id="portfolio-risk-title">组合风险检查</h2>

        <div class="risk-row">
          <strong>最大单一持仓与前三大集中度</strong>
          <span>未验证；缺少正式持仓市值与净清算值，禁止推算。</span>
        </div>

        <div class="risk-row">
          <strong>共同因子与相关性聚集</strong>
          <span>未验证；临时证券名称不能替代正式权重和完整持仓清单。</span>
        </div>

        <div class="risk-row">
          <strong>当月财报暴露与跳空风险</strong>
          <span>未验证；未核对公司 IR 财报日历。</span>
        </div>

        <div class="risk-row">
          <strong>现金与保证金缓冲</strong>
          <span>未验证；账户财务指标及分币种余额均缺失。</span>
        </div>

        <div class="risk-row">
          <strong>流动性、汇率与税务影响</strong>
          <span>未验证；缺少合约、币种、账户类型和持仓规模。</span>
        </div>

        <div class="risk-row">
          <strong>证据冲突与更正</strong>
          <span>没有候选来源，无法进行冲突检查；记为 evidence_gap。</span>
        </div>

        <div class="risk-row">
          <strong>今天最重要的组合风险</strong>
          <span>
            数据完整性风险：在正式持仓、账户权重和新闻证据均不可用时，
            任何具体仓位判断都可能建立在错误前提上。
          </span>
        </div>

        <div class="callout">
          持仓建议状态：已停止。没有给出“加仓、减仓、清仓、继续持有”
          或其他证券级动作；也没有创建或提交任何交易指令。
        </div>
      </section>

      <section class="panel-section" aria-labelledby="resume-title">
        <h2 id="resume-title">恢复完整分析所需数据</h2>
        <ul>
          <li>一次读取 IBKR 全部未平仓持仓，并保留所有非零持仓。</li>
          <li>一次读取账户财务指标，以验证净值、现金、保证金和杠杆。</li>
          <li>一次读取分币种余额，以验证现金、汇率和币种暴露。</li>
          <li>通过英文一手来源与独立专业媒体建立共享新闻证据池。</li>
          <li>核对公司 IR、官方宏观日历及当月最后交易日。</li>
          <li>确认短久期美国国债 ETF 的准确代码和合约。</li>
        </ul>
      </section>
    </main>

    <footer class="legal">
      <p>
        <strong>证据说明：</strong>
        本次没有候选 URL 或合格来源，所有市场与证券事件均记为
        <code>evidence_gap</code>，验证状态为“不适用”，不得进入动作依据。
      </p>
      <p>
        <strong>账户限制：</strong>
        IBKR 三项固定只读调用均未执行；未读取成交、活动订单、观察列表或历史收益，
        也未使用本地 reader、缓存、Flex CSV 或历史报告回退。
      </p>
      <p>
        <strong>研究声明：</strong>
        本报告仅供研究辅助，不构成收益保证或自动交易指令；任何交易由用户确认并在 IBKR 自行执行。
      </p>
      <p class="generated-note">
        离线降级报告 · UTF-8 单文件 · 无外部 JavaScript、CSS、字体或 CDN 依赖
      </p>
    </footer>
  </div>

  <script>
    (() => {
      const tabs = Array.from(
        document.querySelectorAll('.report-tabs [role="tab"]')
      );

      const activateTab = (selectedTab) => {
        tabs.forEach((tab) => {
          const panel = document.getElementById(tab.dataset.panel);
          const selected = tab === selectedTab;

          tab.setAttribute('aria-selected', String(selected));
          tab.tabIndex = selected ? 0 : -1;

          if (panel) {
            panel.hidden = !selected;
          }
        });

        selectedTab.focus();
      };

      tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => activateTab(tab));

        tab.addEventListener('keydown', (event) => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
            return;
          }

          event.preventDefault();

          let nextIndex = index;

          if (event.key === 'ArrowRight') {
            nextIndex = (index + 1) % tabs.length;
          } else if (event.key === 'ArrowLeft') {
            nextIndex = (index - 1 + tabs.length) % tabs.length;
          } else if (event.key === 'Home') {
            nextIndex = 0;
          } else if (event.key === 'End') {
            nextIndex = tabs.length - 1;
          }

          activateTab(tabs[nextIndex]);
        });
      });
    })();
  </script>
</body>
</html>
```
