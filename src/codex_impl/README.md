# codex_impl

This directory implements the plan in `md/plan_detail` from `00` to `10`.

## Mapping
- `step00_overview.py`: system profile and operating principles.
- `step01_config.py`: settings loader and default hybrid/ledger config.
- `step02_infrastructure.py`: cloud deployment and Cloud Functions endpoints.
- `collection/step03_data_collection.py`: news/price collectors.
- `storage/step04_data_storage.py`: in-memory BigQuery/MongoDB/Redis replacement + trade ledger.
- `step05_pre_market.py`: pre-market sentiment briefing helpers.
- `analysis/step06_analysis_engine.py`: numeric ensemble + agent overlay hybrid engine.
- `step07_risk_management.py`: hard/dynamic risk gate and kill switch.
- `step08_execution.py`: paper execution and holdings-only sell proposal generation.
- `step09_monitoring.py`: counters and gauges.
- `step10_stock_universe.py`: tiered stock universe manager.
- `portfolio_api.py`: Cloud Function handlers for manual portfolio/trade input.
- `app.py`: integrated `TradingSystem` orchestration.

## Holdings-only sell proposal
- BUY and SELL fills are both written to `trade_ledger`.
- Current holdings are derived with `net_quantity = SUM(BUY) - SUM(SELL)`.
- Sell recommendations are generated only if `net_quantity > 0`.
