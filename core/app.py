import logging
import sys

from aiogram import Bot, Dispatcher

from core.config import BOT_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("bot_core")

logger.info(f"Bot starting | token ends with ...{BOT_TOKEN[-6:]}")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
