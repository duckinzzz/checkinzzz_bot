from aiogram import Bot, Dispatcher

from core.config import BOT_TOKEN
from core.log import logger

logger.info(f"Bot starting | token ends with ...{BOT_TOKEN[-6:]}")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
