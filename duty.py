"""Госпошлина по ст. 333.19 НК РФ (суды общей юрисдикции, мировые судьи): иск имущественного характера, подлежащий оценке.
Для заявления о вынесении судебного приказа берётся 50 % этой суммы. Ставки хранятся таблицей, которую можно править
в настройках: закон меняется, а код — нет. Проверка актуальности ставок — на пользователе."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Редакция ФЗ от 08.08.2024 № 259-ФЗ (для дел, возбуждённых после 08.09.2024).
# Строка: цена до (None — без границы), базовая сумма, процент от суммы свыше порога, порог («свыше N руб.»).
DEFAULT_SCALE = [
    {"up_to": 100_000, "base": 4_000, "rate": 0, "over": 0},
    {"up_to": 300_000, "base": 4_000, "rate": 3, "over": 100_000},
    {"up_to": 500_000, "base": 10_000, "rate": 2.5, "over": 300_000},
    {"up_to": 1_000_000, "base": 15_000, "rate": 2, "over": 500_000},
    {"up_to": 3_000_000, "base": 25_000, "rate": 1, "over": 1_000_000},
    {"up_to": 8_000_000, "base": 45_000, "rate": 0.7, "over": 3_000_000},
    {"up_to": 24_000_000, "base": 80_000, "rate": 0.35, "over": 8_000_000},
    {"up_to": 50_000_000, "base": 136_000, "rate": 0.3, "over": 24_000_000},
    {"up_to": 100_000_000, "base": 214_000, "rate": 0.2, "over": 50_000_000},
    {"up_to": None, "base": 314_000, "rate": 0.15, "over": 100_000_000},
]
DEFAULT_CAP = 900_000          # потолок пошлины по иску
DEFAULT_SHARE = 50.0           # судебный приказ: % от пошлины по иску


def _row_for(price: Decimal, scale: list[dict]) -> dict:
    for row in scale:
        if row.get("up_to") in (None, "") or price <= Decimal(str(row["up_to"])):
            return row
    return scale[-1]


def claim_duty(price: float, scale: list[dict] | None = None, cap: float = DEFAULT_CAP) -> Decimal:
    """Пошлина по иску имущественного характера при цене иска price."""
    scale = scale or DEFAULT_SCALE
    p = Decimal(str(price))
    row = _row_for(p, scale)
    over = Decimal(str(row.get("over") or 0))
    d = Decimal(str(row["base"])) + Decimal(str(row.get("rate") or 0)) * max(p - over, Decimal(0)) / 100
    return min(d, Decimal(str(cap)))


def court_order_duty(price: float, scale: list[dict] | None = None, share: float = DEFAULT_SHARE,
                     cap: float = DEFAULT_CAP) -> float:
    """Пошлина за заявление о вынесении судебного приказа: share % от пошлины по иску, до копеек."""
    d = claim_duty(price, scale, cap) * Decimal(str(share)) / 100
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def explain(price: float, scale: list[dict] | None = None, share: float = DEFAULT_SHARE, cap: float = DEFAULT_CAP) -> str:
    """Как посчитано — для проверки: «4 000 + 3 % от 50 000 свыше 100 000 = …; 50 % = …»."""
    scale = scale or DEFAULT_SCALE
    p = Decimal(str(price))
    row = _row_for(p, scale)
    full = claim_duty(price, scale, cap)
    over, rate, base = row.get("over") or 0, row.get("rate") or 0, row["base"]
    text = f"по иску: {base:,.0f}".replace(",", " ")
    if rate:
        text += f" + {rate} % от {max(p - Decimal(str(over)), Decimal(0)):,.2f} (сумма свыше {over:,.0f})".replace(",", " ")
    text += f" = {full:,.2f}".replace(",", " ")
    if full == Decimal(str(cap)):
        text += " (потолок)"
    return text + f"; судебный приказ {share:g} % = {court_order_duty(price, scale, share, cap):,.2f}".replace(",", " ")
