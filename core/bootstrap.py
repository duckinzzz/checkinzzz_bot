from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot

from core.config import Settings
from core.log import logger
from services.session import CheckinSession
from services.sheets import GspreadSubjectSheet, SubjectSheet
from services.state import StateStore
from services.students import StudentDirectory
from services.subjects import Subjects


@dataclass(frozen=True)
class AppContext:
    session: CheckinSession
    subjects: Subjects
    admin_ids: frozenset[int]


def build_context(settings: Settings, bot: Bot) -> AppContext:
    directory = StudentDirectory.load(settings.students_path)
    subjects = Subjects.load(settings.subjects_path)
    store = StateStore(settings.state_path)

    def open_sheet(worksheet: str) -> SubjectSheet:
        return GspreadSubjectSheet.open(
            settings.spreadsheet_id, worksheet, settings.credentials_path
        )

    async def report(text: str) -> None:
        for admin_id in sorted(settings.admin_ids):
            try:
                await bot.send_message(admin_id, text)
            except Exception:
                logger.exception("Не смог отправить отчёт админу %s", admin_id)

    logger.info(
        "Справочники загружены: %d студентов, %d предметов",
        len(directory.all_names()),
        len(subjects.titles()),
    )

    session = CheckinSession(
        bot=bot,
        chat_id=settings.chat_id,
        pair_end_times=settings.pair_end_times,
        directory=directory,
        subjects=subjects,
        open_sheet=open_sheet,
        store=store,
        clock=lambda: datetime.now(settings.tz),
        report=report,
    )
    return AppContext(session=session, subjects=subjects, admin_ids=settings.admin_ids)
