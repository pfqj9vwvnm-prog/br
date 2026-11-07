"""Хранилище: избранное пользователей и история онлайна (JSON-файлы)."""
import json
import logging
import os
from collections import deque

import config

log = logging.getLogger(__name__)


def _load(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        log.exception("Не удалось прочитать %s — начинаю с чистого листа", path)
        return None


def _save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)  # атомарно: файл никогда не окажется «половинчатым»
    except OSError:
        log.exception("Не удалось сохранить %s", path)


class Favorites:
    """Избранные серверы пользователя: хранятся по имени, а не по номеру."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config.DATA_DIR, "favorites.json")
        self._data: dict[str, list[str]] = _load(self.path) or {}

    def get(self, uid: int) -> list[str]:
        return list(self._data.get(str(uid), []))

    def has(self, uid: int, name: str) -> bool:
        return name in self._data.get(str(uid), [])

    def count(self, uid: int) -> int:
        return len(self._data.get(str(uid), []))

    def toggle(self, uid: int, name: str) -> bool | None:
        """True — добавлен, False — убран, None — достигнут лимит."""
        lst = self._data.setdefault(str(uid), [])
        if name in lst:
            lst.remove(name)
            if not lst:
                del self._data[str(uid)]
            _save(self.path, self._data)
            return False
        if len(lst) >= config.MAX_FAVS:
            return None
        lst.append(name)
        _save(self.path, self._data)
        return True


class History:
    """Кольцевая история онлайна: [(unix_ts, {имя_сервера: онлайн})]."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config.DATA_DIR, "history.json")
        maxlen = max(2, config.HISTORY_HOURS * 3600 // config.HISTORY_INTERVAL + 2)
        self.rows: deque[tuple[int, dict[str, int]]] = deque(maxlen=maxlen)
        self._restore()

    def _restore(self) -> None:
        raw = _load(self.path)
        if not raw:
            return
        try:
            names = raw["names"]
            for ts, vals in raw["rows"]:
                self.rows.append(
                    (int(ts), {n: v for n, v in zip(names, vals) if v >= 0})
                )
        except Exception:
            log.exception("История повреждена — игнорирую")
            self.rows.clear()

    @property
    def last_ts(self) -> int:
        return self.rows[-1][0] if self.rows else 0

    def add(self, ts: int, values: dict[str, int]) -> None:
        self.rows.append((ts, values))

    def save(self) -> None:
        names = sorted({n for _, vals in self.rows for n in vals})
        rows = [[ts, [vals.get(n, -1) for n in names]] for ts, vals in self.rows]
        _save(self.path, {"names": names, "rows": rows})

    def series(self, name: str | None, since: float) -> list[tuple[int, int | None]]:
        """Ряд значений за период. name=None — суммарный онлайн."""
        out = []
        for ts, vals in self.rows:
            if ts < since:
                continue
            if name is None:
                out.append((ts, sum(vals.values()) if vals else None))
            else:
                out.append((ts, vals.get(name)))
        return out
