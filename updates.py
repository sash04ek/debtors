"""Проверка обновлений: узнаёт последний релиз на GitHub. Ничего не скачивает и не передаёт — только читает публичную страницу релиза."""

from __future__ import annotations

import json
import re
import urllib.request

import courts

REPO = "sash04ek/debtors"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"


def parse_version(text: str) -> tuple[int, ...] | None:
    """«1.0.19» или «v1.0.19» → (1, 0, 19); «разработка» и прочее — None."""
    m = re.fullmatch(r"\s*v?(\d+(?:\.\d+){1,3})\s*", str(text or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def fetch_latest(timeout: float = 6) -> dict:
    """Последний опубликованный релиз: {"tag", "url", "notes"}. Исключение — нет сети или ответ непонятен."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": "Debtors-update-check", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=courts.ssl_context()) as r:
        data = json.loads(r.read().decode("utf-8"))
    return {"tag": str(data["tag_name"]), "url": str(data.get("html_url") or RELEASES_URL), "notes": str(data.get("body") or "")}


def check(current: str, fetch=fetch_latest) -> tuple[str, dict | None]:
    """(статус, релиз): «newer» — есть новая версия, «current» — установлена последняя,
    «dev» — сборка без номера версии (проверять нечего), «error» — не удалось узнать."""
    if parse_version(current) is None:
        return "dev", None
    try:
        info = fetch()
    except Exception:
        return "error", None
    if parse_version(info.get("tag", "")) is None:
        return "error", None
    return ("newer" if is_newer(info["tag"], current) else "current"), info
