from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from .models import TradeLedgerEntry
from .storage.step04_data_storage import InMemoryStorage


def _json_response(payload: dict, status: int = 200):
    return json.dumps(payload, default=str), status, {"Content-Type": "application/json"}


def portfolio_input_page(request):
    """Cloud Function: GET /portfolio/input"""
    html = """
    <html><body>
      <h1>Portfolio Input</h1>
      <p>Submit BUY/SELL trades via POST /portfolio/trades as JSON.</p>
    </body></html>
    """
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


def upsert_portfolio_trade(request, storage: InMemoryStorage):
    """Cloud Function: POST /portfolio/trades"""
    body = request.get_json(silent=True) or {}
    required = ["user_id", "account_id", "symbol", "market", "side", "quantity", "price"]
    missing = [k for k in required if k not in body]
    if missing:
        return _json_response({"error": "missing_fields", "fields": missing}, status=400)

    trade = TradeLedgerEntry(
        trade_id=str(uuid4()),
        user_id=str(body["user_id"]),
        account_id=str(body["account_id"]),
        symbol=str(body["symbol"]),
        market=str(body["market"]),
        side=str(body["side"]).upper(),
        quantity=int(body["quantity"]),
        price=float(body["price"]),
        fee=float(body.get("fee", 0.0)),
        tax=float(body.get("tax", 0.0)),
        source=str(body.get("source", "manual_input")),
        order_id=str(body.get("order_id", "")),
        executed_at=datetime.fromisoformat(body["executed_at"]) if body.get("executed_at") else datetime.utcnow(),
    )
    storage.append_trade(trade)
    return _json_response({"ok": True, "trade_id": trade.trade_id})


def get_holdings(request, storage: InMemoryStorage):
    """Cloud Function: GET /portfolio/holdings"""
    user_id = request.args.get("user_id", "")
    account_id = request.args.get("account_id", "")
    if not user_id or not account_id:
        return _json_response({"error": "user_id and account_id are required"}, status=400)
    holdings = storage.current_holdings(user_id=user_id, account_id=account_id)
    return _json_response({"holdings": list(holdings.values())})
