"""Конфигурация бота — читается из переменных окружения (.env)."""
import os

from dotenv import load_dotenv

load_dotenv()

# Токен Telegram-бота от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Ключ OpenAI API (platform.openai.com)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Модель OpenAI. Актуальные имена — platform.openai.com/docs/models.
# gpt-4o-mini — дёшево и достаточно для учебного бота; gpt-4o — точнее.
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

# Путь к базе и данным
DB_PATH = os.getenv("DB_PATH", "bot.db")
DATA_DIR = os.getenv("DATA_DIR", "data")

# Сколько билетов давать в одной сессии по умолчанию
DAILY_BATCH = int(os.getenv("DAILY_BATCH", "15"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Скопируй .env.example в .env и заполни.")
