from aiogram import Router

from .base import base_router
from .echo import echo_router


def get_main_router() -> Router:
    main_router = Router()

    main_router.include_router(base_router)
    main_router.include_router(echo_router)

    return main_router
