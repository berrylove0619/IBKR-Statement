# forward_relevance_fixed

## Prompt

先完整阅读并严格使用 `<PROJECT_ROOT>/skills/galaxy-buffett-daily-stock-analysis/SKILL.md` 及其中按要求读取的 references。不要使用任何其他投资 Skill。不要浏览网络、不要修改文件。

场景：用户只持有 AAPL、MSFT、BRK.B 和短债 ETF；候选信息中有多条 AI 芯片、数据中心、光通信、亚洲供应链新闻，还有一项宏观利率事件。用户要求知道哪些真正影响当前持仓，以及今天应该做什么。请给出一份简短晨报草案。

## Output

未保存文件；以下为符合 V2 缺失数据分支的完整 HTML：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Galaxy Buffett 晨报离线测试</title>
  <style>
    body{margin:0;background:#f5f7fb;color:#172033;font:15px/1.65 system-ui,sans-serif}
    header,.report-tabs,main,footer{max-width:920px;margin:16px auto;padding:0 20px}
    .report-tabs{display:flex;gap:8px}.report-tabs button{padding:10px 16px;border:1px solid #ccd5e2;background:#fff;border-radius:8px}
    .report-tabs button[aria-selected="true"]{background:#142744;color:#fff}
    section,.notice{background:#fff;border:1px solid #dce3ed;border-radius:10px;padding:18px;margin:14px 0}
    .notice{border-left:4px solid #c48a00}dt{font-weight:700}dd{margin:0 0 8px;color:#586579}
    @media(max-width:640px){header,.report-tabs,main,footer{padding:0 12px}.report-tabs button{flex:1}}
  </style>
  <noscript><style>#portfolio-panel[hidden]{display:block}</style></noscript>
</head>
<body>
  <header>
    <h1>Galaxy Buffett Morning Brief</h1>
    <p>离线合同测试｜新闻与账户数据均未调用</p>
  </header>

  <nav class="report-tabs" role="tablist" aria-label="晨报视图">
    <button id="market-tab" data-panel="market-panel" aria-controls="market-panel" aria-selected="true" role="tab">每日市场</button>
    <button id="portfolio-tab" data-panel="portfolio-panel" aria-controls="portfolio-panel" aria-selected="false" role="tab">我的持仓</button>
  </nav>

  <main id="market-panel" role="tabpanel" aria-labelledby="market-tab" data-news-shortfall="true">
    <section>
      <h2>今日重要新闻</h2>
      <p><strong>达到证据门槛的重要事件不足 10 条</strong>：本离线场景没有候选 URL、原始页面或专业英文来源，因此不生成填充新闻。</p>
      <p>新闻数量：0｜预计阅读时间：不足 1 分钟｜证据状态：evidence_gap</p>
    </section>
    <section id="month-end-calendar">
      <h2>月底前重点财报与重大事件</h2>
      <p>日期来源未提供；本离线场景不猜测财报或宏观事件日期，也不添加当前持仓星标。</p>
    </section>
  </main>

  <main id="portfolio-panel" role="tabpanel" aria-labelledby="portfolio-tab" hidden>
    <section>
      <h2>账户情况</h2>
      <dl>
        <dt>数据源</dt><dd>Interactive Brokers (IBKR) plugin</dd>
        <dt>账户状态</dt><dd>source_unavailable</dd>
        <dt>新鲜度</dt><dd>unknown</dd>
        <dt>插件查询时间</dt><dd>未提供</dd>
        <dt>正式覆盖</dt><dd>未验证；没有创建任何正式持仓卡片</dd>
      </dl>
      <p class="notice">AAPL、MSFT、BRK.B 和代码未提供的短债 ETF 仅是用户给定的临时观察范围，不作为 IBKR 持仓，不生成持仓建议。</p>
    </section>
    <section>
      <h2>组合风险</h2>
      <p>净值、现金、集中度、保证金、币种和财报暴露均未验证；刷新插件数据后复核。</p>
    </section>
  </main>

  <footer>
    <p>本报告仅供研究辅助，不构成收益保证或自动交易指令；任何交易由用户确认并在 IBKR 自行执行。</p>
  </footer>
  <script>
    document.querySelectorAll(".report-tabs button").forEach(function(button){
      button.addEventListener("click",function(){
        document.querySelectorAll(".report-tabs button").forEach(function(item){
          var active=item===button;
          item.setAttribute("aria-selected",String(active));
          document.getElementById(item.dataset.panel).hidden=!active;
        });
      });
    });
  </script>
</body>
</html>
```
