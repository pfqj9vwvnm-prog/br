import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, CallbackQuery, Message

import config
from samp import Monitor
from screens import Ctx, Fav, Go, Screen, clean_query, not_found_screen, render, search
from servers import SERVERS
from storage import Favorites

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

favs = Favorites()
monitor = Monitor()


# ───────────────────────── вспомогательное ─────────────────────────
async def build(route: str, uid: int, force: bool = False) -> Screen:
    snap = await monitor.get(force=force)
    return render(route, Ctx(snap, monitor, favs, uid))


async def edit(cb: CallbackQuery, screen: Screen) -> None:
    """Меняем текущее сообщение на месте; если нельзя — шлём новое."""
    msg = cb.message
    if isinstance(msg, Message):
        try:
            await msg.edit_text(screen.text, reply_markup=screen.kb)
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return  # экран не изменился — это нормально
            log.warning("edit_text не удался (%s), отправляю новое сообщение", e)
    chat_id = msg.chat.id if msg else cb.from_user.id
    await bot.send_message(chat_id, screen.text, reply_markup=screen.kb)


async def answer(cb: CallbackQuery, text: str | None = None) -> None:
    with suppress(TelegramBadRequest):  # «query is too old» и т.п. — не критично
        await cb.answer(text)


async def reply_screen(m: Message, route: str, intro: str = "") -> None:
    uid = m.from_user.id if m.from_user else 0
    try:
        screen = await build(route, uid)
    except Exception:
        log.exception("не удалось построить экран %s", route)
        await m.answer("Не удалось получить онлайн, попробуй позже.")
        return
    await m.answer(intro + screen.text, reply_markup=screen.kb)


def command_to(route: str, intro: str = ""):
    async def handler(m: Message):
        await reply_screen(m, route, intro)

    return handler


# ───────────────────────── команды ─────────────────────────
dp.message.register(
    command_to("m", "Привет! Всё управление — кнопками под сообщением 👇\n\n"), CommandStart()
)
dp.message.register(command_to("m"), Command("menu"))
dp.message.register(command_to("l.all.n.0"), Command("online"))
dp.message.register(
    command_to("l.all.n.0"), F.text.func(lambda t: t.strip().lower() in {"онлайн", "online"})
)
dp.message.register(command_to("t.h"), Command("top"))
dp.message.register(command_to("f"), Command("fav", "favorites"))
dp.message.register(command_to("s"), Command("stats"))
dp.message.register(command_to("h"), Command("help"))


# ───────────────────────── кнопки ─────────────────────────
@dp.callback_query(Go.filter())
async def on_go(cb: CallbackQuery, callback_data: Go):
    prev = monitor.last
    try:
        screen = await build(callback_data.r, cb.from_user.id, force=bool(callback_data.f))
    except Exception:
        log.exception("ошибка построения экрана %s", callback_data.r)
        await answer(cb, "Не удалось получить данные, попробуй ещё раз")
        return
    await edit(cb, screen)
    toast = None
    if callback_data.f:
        toast = "Обновлено ✅" if monitor.last is not prev else "Данные уже свежие"
    await answer(cb, toast)


@dp.callback_query(Fav.filter())
async def on_fav(cb: CallbackQuery, callback_data: Fav):
    i = callback_data.i
    if not 0 <= i < len(SERVERS):
        await answer(cb, "Такого сервера больше нет")
        return
    res = favs.toggle(cb.from_user.id, SERVERS[i][0])
    toast = {
        True: "⭐ Добавлено в избранное",
        False: "Убрано из избранного",
        None: f"Лимит избранного — {config.MAX_FAVS} серверов",
    }[res]
    screen = await build(callback_data.r, cb.from_user.id)
    await edit(cb, screen)
    await answer(cb, toast)


@dp.callback_query(F.data == "noop")
async def on_noop(cb: CallbackQuery):
    await answer(cb)


# ───────────────────────── поиск текстом (только в личке) ─────────────────────────
@dp.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def on_text(m: Message):
    q = clean_query(m.text)
    found = search(q)
    if not found:
        screen = not_found_screen(m.text)
        await m.answer(screen.text, reply_markup=screen.kb)
    elif len(found) == 1:
        await reply_screen(m, f"c.{found[0]}.m")
    else:
        await reply_screen(m, f"l.q{q}.n.0")


# ───────────────────────── запуск ─────────────────────────
async def main():
    with suppress(Exception):
        await bot.set_my_commands([
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="online", description="Все серверы"),
            BotCommand(command="top", description="Топ по онлайну"),
            BotCommand(command="fav", description="Избранное"),
            BotCommand(command="stats", description="Статистика"),
            BotCommand(command="help", description="Помощь"),
        ])
    collector = asyncio.create_task(monitor.run())
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        collector.cancel()
        with suppress(asyncio.CancelledError):
            await collector
        monitor.history.save()


if __name__ == "__main__":
    asyncio.run(main())
