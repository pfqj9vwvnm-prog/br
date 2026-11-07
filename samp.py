"""Опрос серверов (SA-MP/CRMP query), снимки данных и фоновый мониторинг."""
import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field

import config
from servers import PORT, SERVERS
from storage import History

log = logging.getLogger(__name__)


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, fut):
        self.fut = fut

    def datagram_received(self, data, addr):
        if not self.fut.done():
            self.fut.set_result(data)

    def error_received(self, exc):
        if not self.fut.done():
            self.fut.set_exception(exc)


async def query(ip: str, timeout: float = 1.5, tries: int = 2):
    """SA-MP/CRMP query ('i'): возвращает (online, max) или None."""
    loop = asyncio.get_running_loop()
    packet = b"SAMP" + bytes(map(int, ip.split("."))) + struct.pack("<H", PORT) + b"i"
    for _ in range(tries):
        fut = loop.create_future()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _Proto(fut), remote_addr=(ip, PORT)
        )
        try:
            transport.sendto(packet)
            data = await asyncio.wait_for(fut, timeout)
            if data[:4] == b"SAMP" and len(data) >= 16:
                # 11 байт заголовок, 1 байт пароль, затем players и maxplayers (uint16 LE)
                return struct.unpack_from("<HH", data, 12)
        except (asyncio.TimeoutError, OSError):
            pass
        finally:
            transport.close()
    return None


@dataclass
class Row:
    idx: int
    name: str
    ip: str
    online: int | None
    cap: int | None          # максимум слотов
    state: str               # "ok" — ответил сейчас, "stale" — старые данные, "down" — данных нет
    age: int = 0             # сколько секунд назад получены данные (для stale)

    @property
    def usable(self) -> bool:
        return self.state != "down"

    @property
    def fill(self) -> float | None:
        if not self.usable or not self.cap:
            return None
        return self.online / self.cap


@dataclass
class Snapshot:
    ts: float                # unix-время получения
    rows: list[Row]
    total: int = 0
    up: int = 0
    capacity: int = 0
    ranking: list[int] = field(default_factory=list)   # idx по убыванию онлайна
    rank: dict[int, int] = field(default_factory=dict)  # idx -> место (с 1)

    def __post_init__(self):
        usable = [r for r in self.rows if r.usable]
        self.up = len(usable)
        self.total = sum(r.online for r in usable)
        self.capacity = sum(r.cap or 0 for r in usable)
        self.ranking = [r.idx for r in sorted(usable, key=lambda r: (-r.online, r.idx))]
        self.rank = {i: n for n, i in enumerate(self.ranking, 1)}

    @property
    def leader(self) -> Row | None:
        return self.rows[self.ranking[0]] if self.ranking else None

    @property
    def quietest(self) -> Row | None:
        return self.rows[self.ranking[-1]] if self.ranking else None


class Monitor:
    def __init__(self, history: History | None = None):
        self.history = history or History()
        self.last: Snapshot | None = None
        self._mono = 0.0
        self._lock = asyncio.Lock()
        self._last_ok: dict[str, tuple[int, int, float]] = {}

    # ---------- получение данных ----------
    async def get(self, force: bool = False) -> Snapshot:
        """Свежий снимок. Обычные запросы кэшируются на CACHE_TTL,
        принудительные (🔄) — на FORCE_MIN, чтобы не заспамить серверы."""
        async with self._lock:
            limit = config.FORCE_MIN if force else config.CACHE_TTL
            if self.last and time.monotonic() - self._mono < limit:
                return self.last
            return await self._refresh()

    async def _refresh(self, record: bool = False) -> Snapshot:
        results = await asyncio.gather(*(query(ip) for _, ip in SERVERS))
        now = time.time()
        rows = []
        for i, ((name, ip), res) in enumerate(zip(SERVERS, results)):
            if res:
                self._last_ok[name] = (res[0], res[1], now)
                rows.append(Row(i, name, ip, res[0], res[1], "ok"))
                continue
            prev = self._last_ok.get(name)  # не ответил — берём последнее известное
            if prev and now - prev[2] <= config.STALE_MAX:
                rows.append(Row(i, name, ip, prev[0], prev[1], "stale", int(now - prev[2])))
            else:
                rows.append(Row(i, name, ip, None, prev[1] if prev else None, "down"))
        snap = Snapshot(now, rows)
        self.last, self._mono = snap, time.monotonic()

        if record or now - self.history.last_ts >= config.HISTORY_INTERVAL - 1:
            self.history.add(int(now), {r.name: r.online for r in rows if r.usable})
            self.history.save()
        return snap

    async def run(self) -> None:
        """Фоновый сбор истории, чтобы графики жили даже без активных пользователей."""
        while True:
            try:
                async with self._lock:
                    if self.last is None or time.time() - self.history.last_ts >= config.HISTORY_INTERVAL - 1:
                        await self._refresh(record=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Сбой фонового опроса")
            await asyncio.sleep(min(30, config.HISTORY_INTERVAL))  # проверяем, не пора ли писать точку

    # ---------- история ----------
    def series(self, name: str | None, hours: float = 24):
        return self.history.series(name, time.time() - hours * 3600)

    def total_delta(self, snap: Snapshot, minutes: int = 60) -> int | None:
        """Изменение общего онлайна за ~час (по ближайшей точке истории)."""
        target = snap.ts - minutes * 60
        best = None
        for ts, vals in self.history.rows:
            if abs(ts - target) <= 15 * 60 and (best is None or abs(ts - target) < abs(best[0] - target)):
                best = (ts, sum(vals.values()))
        return None if best is None else snap.total - best[1]
