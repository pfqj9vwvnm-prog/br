"""Настройки бота. Всё можно переопределить переменными окружения."""
import os
from datetime import timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

BOT_TOKEN = os.environ["BOT_TOKEN"]

# Кэш данных: как долго (сек) ответ считается свежим для обычных нажатий.
CACHE_TTL = int(os.getenv("CACHE_TTL", "15"))
# Минимальный интервал между принудительными обновлениями (кнопка 🔄), сек.
FORCE_MIN = int(os.getenv("FORCE_MIN", "5"))
# Множитель события. Пусто = не показывать.
X_LABEL = os.getenv("X_LABEL", "x2").strip()

# История онлайна для графиков: шаг записи (сек) и глубина (часы).
HISTORY_INTERVAL = int(os.getenv("HISTORY_INTERVAL", "300"))
HISTORY_HOURS = int(os.getenv("HISTORY_HOURS", "24"))
# Если сервер не отвечает, последние данные считаются годными не дольше N сек.
STALE_MAX = int(os.getenv("STALE_MAX", "600"))

# Где хранить избранное и историю. На Heroku диск временный — см. README в ответе.
DATA_DIR = os.getenv("DATA_DIR", "data")
MAX_FAVS = int(os.getenv("MAX_FAVS", "24"))

# Часовой пояс для отметок времени.
TZ_NAME = os.getenv("TZ_NAME", "Europe/Moscow")
TZ_LABEL = os.getenv("TZ_LABEL", "МСК")


def _make_tz():
    if ZoneInfo is not None:
        try:
            return ZoneInfo(TZ_NAME)
        except Exception:
            pass
    return timezone(timedelta(hours=3))  # Москва без перехода на летнее время


TZ = _make_tz()
