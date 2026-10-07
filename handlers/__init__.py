from aiogram import Router

from handlers.admin import build_admin_router
from handlers.attendance import build_attendance_router
from services.session import CheckinSession
from services.subjects import Subjects


def get_main_router(
    session: CheckinSession, subjects: Subjects, admin_ids: frozenset[int]
) -> Router:
    main_router = Router()

    main_router.include_router(
        build_admin_router(session=session, subjects=subjects, admin_ids=admin_ids)
    )
    main_router.include_router(build_attendance_router(session=session))

    return main_router
