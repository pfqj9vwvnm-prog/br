"""Экраны бота: тексты и инлайн-клавиатуры.

Вся навигация построена на «маршрутах» — коротких строках в callback_data:

    m                      главное меню
    l.<фильтр>.<сорт>.<стр> список серверов  (фильтр: all | g0 | k<буква> | q<запрос>)
    t.<h|l>                топ / самые тихие
    f                      избранное
    s                      статистика
    a                      поиск по букве
    h                      помощь
    c.<idx>.<назад>        карточка сервера (в «назад» точки заменены на «-»)

Состояние целиком лежит в маршруте, поэтому кнопки работают и после перезапуска бота.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from math import ceil

from aiogram.filters.callback_data import CallbackData
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

import config
from samp import Monitor, Row, Snapshot
from servers import ALIASES, GROUP_OF, GROUPS, PORT, SERVERS
from storage import Favorites

PER_PAGE = 16   # 2 колонки × 8 рядов
TOP_N = 10

SORT_TEXT = {"n": "по порядку", "o": "по онлайну", "a": "по алфавиту"}
SORT_BTN = {"n": "↕ По порядку", "o": "↕ По онлайну", "a": "↕ А–Я"}
SORT_NEXT = {"n": "o", "o": "a", "a": "n"}
MEDALS = ["🥇", "🥈", "🥉"]
BLOCKS = "▁▂▃▄▅▆▇█"

NAME_IDX = {name: i for i, (name, _) in enumerate(SERVERS)}


# ───────────────────────── callback-данные ─────────────────────────
class Go(CallbackData, prefix="g"):
    r: str          # маршрут
    f: int = 0      # 1 — принудительно обновить данные


class Fav(CallbackData, prefix="v"):
    i: int          # индекс сервера
    r: str          # маршрут карточки, которую надо перерисовать


@dataclass
class Ctx:
    snap: Snapshot
    monitor: Monitor
    favs: Favorites
    uid: int

    @property
    def rows(self) -> list[Row]:
        return self.snap.rows


@dataclass
class Screen:
    text: str
    kb: InlineKeyboardMarkup


# ───────────────────────── форматирование ─────────────────────────
def num(x: int) -> str:
    return f"{x:,}".replace(",", "\u00a0")


def clock(ts: float) -> str:
    return datetime.fromtimestamp(ts, config.TZ).strftime("%H:%M:%S")


def hm(ts: float) -> str:
    return datetime.fromtimestamp(ts, config.TZ).strftime("%H:%M")


def ago(sec: int) -> str:
    if sec < 60:
        return f"{sec} с назад"
    if sec < 3600:
        return f"{sec // 60} мин назад"
    return f"{sec // 3600} ч назад"


def plural(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return forms[2]
    n %= 10
    return forms[0] if n == 1 else forms[1] if 2 <= n <= 4 else forms[2]


def servers_word(n: int) -> str:
    return f"{n} {plural(n, ('сервер', 'сервера', 'серверов'))}"


def bar(frac: float | None, width: int = 10) -> str:
    frac = 0.0 if frac is None else max(0.0, min(1.0, frac))
    n = round(frac * width)
    return "▰" * n + "▱" * (width - n)


def dot(r: Row) -> str:
    """Индикатор загрузки: 🟢 свободно, 🟡 заполняется, 🔴 почти полный, ⚫ нет данных."""
    if not r.usable:
        return "⚫"
    f = r.fill
    if f is None or f < 0.6:
        return "🟢"
    return "🟡" if f < 0.9 else "🔴"


def fmt_online(r: Row) -> str:
    if not r.usable:
        return "н/д"
    s = f"{num(r.online)}/{num(r.cap)}" if r.cap else num(r.online)
    return s + (" ⚠️" if r.state == "stale" else "")


def spark(vals: list[int | None], width: int = 24) -> str:
    """Мини-график из блоков ▁▂▃▄▅▆▇█."""
    n = len(vals)
    if n == 0:
        return ""
    if n > width:
        buckets: list[float | None] = []
        for b in range(width):
            part = [v for v in vals[b * n // width:(b + 1) * n // width] if v is not None]
            buckets.append(sum(part) / len(part) if part else None)
    else:
        buckets = list(vals)
    nums = [b for b in buckets if b is not None]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    out = []
    for b in buckets:
        if b is None:
            out.append("·")
        elif hi == lo:
            out.append(BLOCKS[3])
        else:
            out.append(BLOCKS[round((b - lo) / (hi - lo) * (len(BLOCKS) - 1))])
    return "".join(out)


def history_lines(series: list[tuple[int, int | None]]) -> list[str]:
    pts = [(ts, v) for ts, v in series if v is not None]
    if len(pts) < 3:
        return ["📈 История копится — график появится через несколько минут."]
    span_h = (series[-1][0] - series[0][0]) / 3600
    span = f"{span_h:.0f} ч" if span_h >= 1 else f"{max(1, round(span_h * 60))} мин"
    lo = min(pts, key=lambda p: p[1])
    hi = max(pts, key=lambda p: p[1])
    return [
        f"📈 <b>Онлайн за {span}</b>",
        f"<code>{spark([v for _, v in series])}</code>",
        f"▼ {num(lo[1])} в {hm(lo[0])}  ·  ▲ {num(hi[1])} в {hm(hi[0])}",
    ]


# ───────────────────────── поиск и фильтры ─────────────────────────
def clean_query(text: str) -> str:
    t = text.lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]", "", t)[:16]


def search(query: str) -> list[int]:
    q = clean_query(query)
    if not q:
        return []
    exact, part = [], []
    for i, (name, _) in enumerate(SERVERS):
        words = [name.lower(), *ALIASES.get(name, [])]
        if q in words:
            exact.append(i)
        elif any(q in w for w in words):
            part.append(i)
    return exact or part


def filter_idxs(flt: str) -> list[int]:
    n = len(SERVERS)
    if flt.startswith("g") and flt[1:].isdigit():
        g = int(flt[1:])
        return [i for i in range(n) if GROUP_OF[i] == g]
    if flt.startswith("k") and len(flt) > 1:
        letter = flt[1:].upper()
        return [i for i in range(n) if SERVERS[i][0].startswith(letter)]
    if flt.startswith("q"):
        return search(flt[1:])
    return list(range(n))


def filter_label(flt: str) -> str:
    if flt.startswith("g") and flt[1:].isdigit() and int(flt[1:]) < len(GROUPS):
        return GROUPS[int(flt[1:])]
    if flt.startswith("k") and len(flt) > 1:
        return f"буква «{html.escape(flt[1:].upper())}»"
    if flt.startswith("q"):
        return f"поиск «{html.escape(flt[1:])}»"
    return "все серверы"


def sort_idxs(idxs: list[int], sort: str, ctx: Ctx) -> list[int]:
    rows = ctx.rows
    if sort == "o":
        return sorted(idxs, key=lambda i: (not rows[i].usable, -(rows[i].online or 0), i))
    if sort == "a":
        return sorted(idxs, key=lambda i: SERVERS[i][0])
    return sorted(idxs)


def top_ids(ctx: Ctx, mode: str) -> list[int]:
    ranking = ctx.snap.ranking
    return ranking[:TOP_N] if mode == "h" else list(reversed(ranking))[:TOP_N]


def fav_ids(ctx: Ctx) -> list[int]:
    return [NAME_IDX[n] for n in ctx.favs.get(ctx.uid) if n in NAME_IDX]


# ───────────────────────── кнопки ─────────────────────────
def go(text: str, route: str, force: bool = False) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=Go(r=route, f=int(force)).pack())


def noop(text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data="noop")


def grid(buttons: list[InlineKeyboardButton], cols: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]


def card_route(idx: int, back: str) -> str:
    return f"c.{idx}.{back.replace('.', '-')}"


def srv_btn(r: Row, back: str, prefix: str = "") -> InlineKeyboardButton:
    if not r.usable:
        val = "н/д"
    else:
        val = ("~" if r.state == "stale" else "") + str(r.online)
    return go(f"{prefix or dot(r)} {r.name} {val}", card_route(r.idx, back))


def kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def event_line() -> list[str]:
    return [f"✨ Событие: <b>{html.escape(config.X_LABEL)}</b>"] if config.X_LABEL else []


def delta_text(ctx: Ctx) -> str:
    d = ctx.monitor.total_delta(ctx.snap)
    if not d:
        return ""
    return f"  {'▲' if d > 0 else '▼'} {num(abs(d))} за час"


# ───────────────────────── экраны ─────────────────────────
def menu_screen(ctx: Ctx) -> Screen:
    s = ctx.snap
    lines = ["<b>🚘 Black Russia · онлайн серверов</b>", ""]
    lines.append(f"👥 Сейчас играют: <b>{num(s.total)}</b>{delta_text(ctx)}")
    lines.append(f"📡 Серверов в сети: <b>{s.up}</b> из {len(s.rows)}")
    if s.leader:
        lines.append(f"🔥 Лидер: <b>{s.leader.name}</b> — {num(s.leader.online)}")
    lines += event_line()
    lines.append(f"🕒 {clock(s.ts)} {config.TZ_LABEL}")

    fav_rows = [ctx.rows[i] for i in fav_ids(ctx)]
    if fav_rows:
        body = "\n".join(f"{dot(r)} {r.name} — {fmt_online(r)}" for r in fav_rows)
        lines += ["", "⭐ <b>Избранное</b>", f"<blockquote expandable>{body}</blockquote>"]

    n = len(fav_rows)
    keyboard = [
        [go("🌐 Все серверы", "l.all.n.0"), go("🔥 Топ", "t.h")],
        [go("🔤 Поиск", "a"), go(f"⭐ Избранное ({n})" if n else "⭐ Избранное", "f")],
        [go("📊 Статистика", "s"), go("🔄 Обновить", "m", force=True)],
        [go("ℹ️ Помощь", "h")],
    ]
    return Screen("\n".join(lines), kb(keyboard))


def list_screen(ctx: Ctx, flt: str, sort: str, page: int) -> Screen:
    s = ctx.snap
    sort = sort if sort in SORT_TEXT else "n"
    idxs = sort_idxs(filter_idxs(flt), sort, ctx)
    pages = max(1, ceil(len(idxs) / PER_PAGE))
    page = min(max(page, 0), pages - 1)
    chunk = idxs[page * PER_PAGE:(page + 1) * PER_PAGE]
    here = f"l.{flt}.{sort}.{page}"

    subtotal = sum(ctx.rows[i].online for i in idxs if ctx.rows[i].usable)
    head = "🌐 <b>Серверы</b>" + (f" · стр. {page + 1}/{pages}" if pages > 1 else "")
    lines = [
        head,
        f"{filter_label(flt)} · {SORT_TEXT[sort]}",
        "",
        f"👥 Онлайн: <b>{num(subtotal)}</b> на {servers_word(len(idxs))}"
        if idxs else "😕 Ничего не найдено",
    ]
    lines += event_line()
    lines += ["", "🟢 свободно · 🟡 заполняется · 🔴 почти полный · ⚫ нет данных",
              f"🕒 {clock(s.ts)} {config.TZ_LABEL}"]

    keyboard = grid([srv_btn(ctx.rows[i], here) for i in chunk])
    if pages > 1:
        keyboard.append([
            go("‹", f"l.{flt}.{sort}.{(page - 1) % pages}"),
            noop(f"{page + 1} / {pages}"),
            go("›", f"l.{flt}.{sort}.{(page + 1) % pages}"),
        ])
    chips = [("all", "Все")] + [(f"g{i}", t) for i, t in enumerate(GROUPS)]
    keyboard += grid(
        [go(("✓ " if flt == k else "") + t, f"l.{k}.{sort}.0") for k, t in chips], cols=3
    )
    keyboard.append([go(SORT_BTN[sort], f"l.{flt}.{SORT_NEXT[sort]}.0"), go("🔤 Поиск", "a")])
    keyboard.append([go("🔄 Обновить", here, force=True), go("🏠 Меню", "m")])
    return Screen("\n".join(lines), kb(keyboard))


def top_screen(ctx: Ctx, mode: str) -> Screen:
    mode = "l" if mode == "l" else "h"
    ids = top_ids(ctx, mode)
    title = "🔥 <b>Топ-10 по онлайну</b>" if mode == "h" else "❄️ <b>10 самых тихих серверов</b>"
    lines = [title, ""]
    if not ids:
        lines.append("Данных пока нет — попробуйте обновить.")
    for n, i in enumerate(ids, 1):
        r = ctx.rows[i]
        mark = MEDALS[n - 1] if mode == "h" and n <= 3 else f"{n}."
        pct = f" {round(r.fill * 100)}%" if r.fill is not None else ""
        lines.append(f"{mark} <b>{r.name}</b> — {num(r.online)}  {bar(r.fill, 8)}{pct}")
    lines += ["", f"🕒 {clock(ctx.snap.ts)} {config.TZ_LABEL}"]

    here = f"t.{mode}"
    keyboard = grid([
        srv_btn(ctx.rows[i], here, prefix=MEDALS[n] if mode == "h" and n < 3 else f"{n + 1}.")
        for n, i in enumerate(ids)
    ])
    keyboard.append([
        go(("✓ " if mode == "h" else "") + "🔥 Топ", "t.h"),
        go(("✓ " if mode == "l" else "") + "❄️ Тихие", "t.l"),
    ])
    keyboard.append([go("🔄 Обновить", here, force=True), go("🏠 Меню", "m")])
    return Screen("\n".join(lines), kb(keyboard))


def favs_screen(ctx: Ctx) -> Screen:
    ids = fav_ids(ctx)
    if not ids:
        text = (
            "⭐ <b>Избранное</b>\n\n"
            "Здесь будут ваши любимые серверы — их онлайн виден на одном экране.\n\n"
            "Откройте любой сервер и нажмите «⭐ В избранное»."
        )
        return Screen(text, kb([[go("🌐 Выбрать сервер", "l.all.n.0")], [go("🏠 Меню", "m")]]))

    rows = [ctx.rows[i] for i in ids]
    total = sum(r.online for r in rows if r.usable)
    lines = ["⭐ <b>Избранное</b>", ""]
    lines += [f"{dot(r)} <b>{r.name}</b> — {fmt_online(r)}" for r in rows]
    lines += ["", f"👥 Всего: <b>{num(total)}</b>", f"🕒 {clock(ctx.snap.ts)} {config.TZ_LABEL}"]

    keyboard = grid([srv_btn(r, "f") for r in rows])
    keyboard.append([go("🔄 Обновить", "f", force=True), go("🏠 Меню", "m")])
    return Screen("\n".join(lines), kb(keyboard))


def stats_screen(ctx: Ctx) -> Screen:
    s = ctx.snap
    avg = s.total // s.up if s.up else 0
    fill = s.total / s.capacity if s.capacity else 0
    levels = {"🟢": 0, "🟡": 0, "🔴": 0, "⚫": 0}
    for r in s.rows:
        levels[dot(r)] += 1

    lines = ["📊 <b>Статистика</b>", ""]
    lines.append(f"👥 Общий онлайн: <b>{num(s.total)}</b>{delta_text(ctx)}")
    lines.append(f"📡 В сети: {s.up} из {len(s.rows)}  ·  ⚖️ в среднем {num(avg)}")
    lines.append(f"📦 Слоты: {bar(fill, 10)} {round(fill * 100)}%")
    if s.leader:
        lines.append(f"🔥 Лидер: <b>{s.leader.name}</b> — {num(s.leader.online)}")
    if s.quietest and s.quietest is not s.leader:
        lines.append(f"❄️ Тише всех: <b>{s.quietest.name}</b> — {num(s.quietest.online)}")

    lines += ["", "<b>Загрузка серверов</b>",
              "  ".join(f"{k} {v}" for k, v in levels.items())]

    if len(GROUPS) > 1 and s.total:
        lines += ["", "<b>По группам</b>"]
        for g, title in enumerate(GROUPS):
            part = sum(r.online for r in s.rows if r.usable and GROUP_OF[r.idx] == g)
            lines.append(f"{title}: <b>{num(part)}</b> ({round(part / s.total * 100)}%)")

    lines += [""] + history_lines(ctx.monitor.series(None))
    lines.append(f"🕒 {clock(s.ts)} {config.TZ_LABEL}")

    keyboard = [
        [go("🔥 Топ", "t.h"), go("🌐 Все серверы", "l.all.n.0")],
        [go("🔄 Обновить", "s", force=True), go("🏠 Меню", "m")],
    ]
    return Screen("\n".join(lines), kb(keyboard))


def letters_screen(ctx: Ctx) -> Screen:
    counts: dict[str, int] = {}
    for name, _ in SERVERS:
        counts[name[0]] = counts.get(name[0], 0) + 1
    text = (
        "🔤 <b>Поиск сервера</b>\n\n"
        "Выберите первую букву названия 👇\n\n"
        "💡 В личке с ботом можно просто написать название — например "
        "<code>москва</code>, <code>red</code> или <code>екб</code>."
    )
    keyboard = grid([go(f"{L} · {c}", f"l.k{L}.n.0") for L, c in sorted(counts.items())], cols=4)
    keyboard.append([go("🌐 Все серверы", "l.all.n.0"), go("🏠 Меню", "m")])
    return Screen(text, kb(keyboard))


def not_found_screen(raw: str) -> Screen:
    text = f"😕 По запросу «{html.escape(raw.strip()[:40])}» ничего не нашёл.\n\nПопробуйте выбрать сервер кнопками."
    return Screen(text, kb([
        [go("🔤 Поиск по букве", "a"), go("🌐 Все серверы", "l.all.n.0")],
        [go("🏠 Меню", "m")],
    ]))


def help_screen(ctx: Ctx) -> Screen:
    text = (
        "ℹ️ <b>Как пользоваться</b>\n\n"
        "Всё управление — кнопками под сообщением, экран обновляется на месте.\n\n"
        "🌐 <b>Все серверы</b> — список с фильтрами, сортировкой и страницами\n"
        "🔥 <b>Топ</b> — самые людные и самые тихие\n"
        "🔤 <b>Поиск</b> — по первой букве; в личке можно написать название\n"
        "⭐ <b>Избранное</b> — свои серверы на одном экране\n"
        "📊 <b>Статистика</b> — общий онлайн, загрузка и график за сутки\n\n"
        "<b>Значки</b>\n"
        "🟢 свободно · 🟡 заполняется · 🔴 почти полный · ⚫ нет данных\n"
        "⚠️ / ~ — сервер не ответил, показаны последние известные данные\n\n"
        "<b>Команды-ярлыки:</b> /menu /online /top /fav /stats"
    )
    return Screen(text, kb([[go("🏠 Меню", "m")]]))


# ───────────────────────── карточка сервера ─────────────────────────
def order_for(back: str, ctx: Ctx) -> list[int] | None:
    """Порядок серверов в родительском экране — для кнопок ‹ › в карточке."""
    p = back.split(".")
    try:
        if p[0] == "l" and len(p) == 4:
            return sort_idxs(filter_idxs(p[1]), p[2], ctx)
        if p[0] == "t":
            return top_ids(ctx, p[1])
        if p[0] == "f":
            return fav_ids(ctx)
    except IndexError:
        pass
    return None


def refocus(back: str, order: list[int], idx: int) -> str:
    """Если родитель — список, переключаем его на страницу, где лежит сервер idx."""
    p = back.split(".")
    if p[0] == "l" and len(p) == 4 and idx in order:
        p[3] = str(order.index(idx) // PER_PAGE)
        return ".".join(p)
    return back


BACK_TEXT = {"l": "↩ К списку", "t": "↩ К топу", "f": "↩ К избранному", "s": "↩ К статистике"}


def card_screen(ctx: Ctx, idx: int, back: str) -> Screen:
    if not 0 <= idx < len(ctx.rows):
        raise IndexError(idx)
    s = ctx.snap
    r = ctx.rows[idx]
    is_fav = ctx.favs.has(ctx.uid, r.name)

    lines = [f"{dot(r)} <b>{r.name}</b>" + (" ⭐" if is_fav else ""), ""]
    if r.state == "ok":
        lines.append(f"👥 Онлайн: <b>{num(r.online)}</b> из {num(r.cap)}")
    elif r.state == "stale":
        lines.append("⚠️ Сервер не ответил, показаны последние данные:")
        lines.append(f"👥 Онлайн: <b>{num(r.online)}</b> из {num(r.cap)} · {ago(r.age)}")
    else:
        lines.append("⚫ Сервер не отвечает, данных пока нет.")
    if r.usable and r.cap:
        lines.append(f"{bar(r.fill, 12)} {round(r.fill * 100)}%")
        lines.append(f"🆓 Свободно слотов: {num(max(r.cap - r.online, 0))}")
        lines.append(f"🏆 Место по онлайну: {s.rank[idx]} из {s.up}")
    lines.append(f"🌐 <code>{r.ip}:{PORT}</code>")
    lines += event_line()

    lines += [""] + history_lines(ctx.monitor.series(r.name))
    lines.append(f"🕒 {clock(s.ts)} {config.TZ_LABEL}")

    order = order_for(back, ctx)
    back_now = refocus(back, order, idx) if order else back
    here = card_route(idx, back_now)

    keyboard = [
        [InlineKeyboardButton(
            text="✖️ Убрать из избранного" if is_fav else "⭐ В избранное",
            callback_data=Fav(i=idx, r=here).pack(),
        )],
        [
            InlineKeyboardButton(text="📋 Копировать IP", copy_text=CopyTextButton(text=f"{r.ip}:{PORT}")),
            go("🔄 Обновить", here, force=True),
        ],
    ]
    if order and idx in order:
        pos = order.index(idx)
        nav = []
        if pos > 0:
            prev = order[pos - 1]
            nav.append(go(f"‹ {ctx.rows[prev].name}", card_route(prev, refocus(back, order, prev))))
        if pos < len(order) - 1:
            nxt = order[pos + 1]
            nav.append(go(f"{ctx.rows[nxt].name} ›", card_route(nxt, refocus(back, order, nxt))))
        if nav:
            keyboard.append(nav)
    keyboard.append([go(BACK_TEXT.get(back_now.split(".")[0], "↩ Назад"), back_now), go("🏠 Меню", "m")])
    return Screen("\n".join(lines), kb(keyboard))


# ───────────────────────── диспетчер маршрутов ─────────────────────────
def render(route: str, ctx: Ctx) -> Screen:
    p = route.split(".")
    try:
        kind = p[0]
        if kind == "l":
            return list_screen(ctx, p[1], p[2], int(p[3]))
        if kind == "t":
            return top_screen(ctx, p[1])
        if kind == "f":
            return favs_screen(ctx)
        if kind == "s":
            return stats_screen(ctx)
        if kind == "a":
            return letters_screen(ctx)
        if kind == "h":
            return help_screen(ctx)
        if kind == "c":
            back = p[2].replace("-", ".") if len(p) > 2 else "m"
            return card_screen(ctx, int(p[1]), back)
    except (IndexError, ValueError, KeyError):
        pass
    return menu_screen(ctx)
