import asyncio
import logging
import os
import struct
import time

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from servers import PORT, SERVERS

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
CACHE_TTL = int(os.getenv("CACHE_TTL", "15"))  # секунд
X_LABEL = os.getenv("X_LABEL", "x2")  # пусто = не показывать множитель

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

_cache = {"ts": 0.0, "rows": None}
_last_ok: dict[str, tuple[int, int]] = {}
_lock = asyncio.Lock()


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, fut):
        self.fut = fut

    def datagram_received(self, data, addr):
        if not self.fut.done():
            self.fut.set_result(data)

    def error_received(self, exc):
        if not self.fut.done():
            self.fut.set_exception(exc)


async def query(ip: str, timeout: float = 2.0, tries: int = 2):
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


async def get_rows():
    async with _lock:
        if _cache["rows"] and time.monotonic() - _cache["ts"] < CACHE_TTL:
            return _cache["rows"]
        results = await asyncio.gather(*(query(ip) for _, ip in SERVERS))
        rows = []
        for (name, _), res in zip(SERVERS, results):
            if res:
                _last_ok[name] = res
            else:
                res = _last_ok.get(name)  # не ответил — берём последнее известное
            rows.append((name, res))
        _cache.update(ts=time.monotonic(), rows=rows)
        return rows


def build_text(rows) -> str:
    lines, total = [], 0
    x = f" {X_LABEL}" if X_LABEL else ""
    for i, (name, res) in enumerate(rows, 1):
        if res:
            online, mx = res
            total += online
            lines.append(f"{i}. {name}: {online}/{mx}{x}")
        else:
            lines.append(f"{i}. {name}: н/д")
    return (
        "<b>Онлайн серверов:</b>\n"
        f"<blockquote expandable>{chr(10).join(lines)}</blockquote>\n"
        f"<b>Общий онлайн: {total}</b>"
    )


@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("Привет! Отправь /online, чтобы узнать онлайн серверов Black Russia.")


@dp.message(Command("online"))
@dp.message(F.text.func(lambda t: t.strip().lower() == "онлайн"))
async def online(m: Message):
    try:
        await m.answer(build_text(await get_rows()))
    except Exception:
        logging.exception("query failed")
        await m.answer("Не удалось получить онлайн, попробуй позже.")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
