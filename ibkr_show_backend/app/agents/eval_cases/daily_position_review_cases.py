from app.agents.eval_harness import EvalCase


CASES = [
    EvalCase(
        case_id="daily_review_account_attribution_before_news",
        agent_name="daily_position_review",
        title="账户涨跌应账户归因优先于新闻叙事",
        tags=["attribution", "account_first"],
        input={"report_date": "2026-05-20"},
        expected_output_fields=["summary", "account_conclusion", "data_limitations"],
    ),
    EvalCase(
        case_id="daily_review_public_data_missing_limitations",
        agent_name="daily_position_review",
        title="公开数据不足必须写 data_limitations",
        tags=["data_missing"],
        input={"report_date": "2026-05-21"},
        expected_behavior={"data_missing": True},
        expected_output_fields=["summary", "data_limitations"],
    ),
    EvalCase(
        case_id="daily_review_small_move_no_over_attribution",
        agent_name="daily_position_review",
        title="单日小波动不能强行归因到单一新闻",
        tags=["attribution", "small_move"],
        input={"report_date": "2026-05-22"},
        expected_output_fields=["summary", "data_limitations"],
        forbidden_behavior=["唯一原因", "完全因为"],
    ),
    EvalCase(
        case_id="daily_review_mstr_no_btc_without_data",
        agent_name="daily_position_review",
        title="MSTR 缺 BTC 数据时不能凭空归因 BTC",
        tags=["mstr", "btc", "data_missing"],
        input={"report_date": "2026-05-23", "symbol": "MSTR.US"},
        expected_behavior={"data_missing": True},
        expected_output_fields=["summary", "data_limitations"],
    ),
]
