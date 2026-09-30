"""Сумма прописью: 5878.56 → «5 878 (пять тысяч восемьсот семьдесят восемь) рублей 56 коп.»"""

from __future__ import annotations

_ONES_M = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_ONES_F = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
          "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
_GROUPS = [  # (форма для 1, для 2-4, для 5+, женский род?)
    ("", "", "", False),
    ("тысяча", "тысячи", "тысяч", True),
    ("миллион", "миллиона", "миллионов", False),
    ("миллиард", "миллиарда", "миллиардов", False),
]


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if 2 <= n % 10 <= 4 else forms[2]


def _triplet(n: int, female: bool) -> list[str]:
    ones = _ONES_F if female else _ONES_M
    words = []
    if n >= 100:
        words.append(_HUNDREDS[n // 100])
    n %= 100
    if 10 <= n <= 19:
        words.append(_TEENS[n - 10])
    else:
        if n >= 20:
            words.append(_TENS[n // 10])
        if n % 10:
            words.append(ones[n % 10])
    return words


def int_to_words(n: int, female: bool = False) -> str:
    if n == 0:
        return "ноль"
    parts, group = [], 0
    while n > 0:
        n, chunk = divmod(n, 1000)
        if chunk:
            one, few, many, fem = _GROUPS[group]
            words = _triplet(chunk, fem if group else female)
            if group:
                words.append(_plural(chunk, (one, few, many)))
            parts.append(" ".join(words))
        group += 1
    return " ".join(reversed(parts))


def rubles_words(amount: float) -> str:
    """«5 878 (пять тысяч восемьсот семьдесят восемь) рублей 56 коп.»"""
    kop_total = round(float(amount) * 100)
    rub, kop = divmod(kop_total, 100)
    grouped = f"{rub:,}".replace(",", " ")
    word = _plural(rub, ("рубль", "рубля", "рублей"))
    return f"{grouped} ({int_to_words(rub)}) {word} {kop:02d} коп."


def money_plain(amount: float) -> str:
    """5878.56 → «5 878,56»."""
    return f"{float(amount):,.2f}".replace(",", " ").replace(".", ",")
