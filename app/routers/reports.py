"""帳票 API: 残高試算表 / 総勘定元帳 / 月次推移表 / 消費税集計表 / 決算書。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import db
from .. import posting

router = APIRouter(prefix="/api", tags=["reports"])


def _fy(conn, fy_id: int):
    fy = conn.execute("SELECT * FROM fiscal_years WHERE id=?", (fy_id,)).fetchone()
    if not fy:
        raise HTTPException(404, "会計期間が見つかりません")
    return fy


@router.get("/fiscal-years/{fy_id}/reports/trial-balance")
def trial_balance(fy_id: int, date_from: str | None = None, date_to: str | None = None, by_sub: bool = False):
    with db() as conn:
        fy = _fy(conn, fy_id)
        return posting.trial_balance(conn, fy_id, date_from or fy["start_date"], date_to or fy["end_date"], by_sub)


@router.get("/fiscal-years/{fy_id}/reports/ledger")
def ledger(fy_id: int, account_id: int, date_from: str | None = None, date_to: str | None = None, sub_id: int | None = None):
    with db() as conn:
        fy = _fy(conn, fy_id)
        return posting.ledger(conn, fy_id, account_id, date_from or fy["start_date"], date_to or fy["end_date"], sub_id)


@router.get("/fiscal-years/{fy_id}/reports/monthly")
def monthly(fy_id: int):
    with db() as conn:
        _fy(conn, fy_id)
        return posting.monthly_trend(conn, fy_id)


@router.get("/fiscal-years/{fy_id}/reports/tax-summary")
def tax_summary(fy_id: int, date_from: str | None = None, date_to: str | None = None):
    with db() as conn:
        fy = _fy(conn, fy_id)
        return posting.tax_summary(conn, fy_id, date_from or fy["start_date"], date_to or fy["end_date"])


@router.get("/fiscal-years/{fy_id}/reports/financial-statements")
def financial_statements(fy_id: int, date_to: str | None = None):
    with db() as conn:
        _fy(conn, fy_id)
        return posting.financial_statements(conn, fy_id, date_to)
