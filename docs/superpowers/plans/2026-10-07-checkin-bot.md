# Бот отметки посещения пар — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот в беседе группы, который по команде админа открывает текущую пару, принимает отметки студентов одной кнопкой и пишет «+» в Google-таблицу посещаемости, закрывая пару по расписанию.

**Architecture:** Чистые сервисы без знания о Telegram (`schedule`, `students`, `subjects`, `sheets`, `state`) и один координатор `session`, который держит состояние активной пары, буфер отметок и таймеры закрытия. Хендлеры — тонкие адаптеры: превращают callback в вызов сессии и ответ в текст. Google-таблица спрятана за протоколом `SubjectSheet`, поэтому сессия тестируется на фейке без сети.

**Tech Stack:** Python 3.13, aiogram 3.24, gspread (service account), uv, pytest + pytest-asyncio, Docker.

**Spec:** `docs/superpowers/specs/2026-10-07-checkin-bot-design.md`

## Global Constraints

- Python `>=3.13`, aiogram `==3.24.0` — версия уже зафиксирована в `pyproject.toml`, не менять.
- Зависимости добавлять только через `uv add`, `uv.lock` коммитится вместе с изменениями.
- Автор коммитов — `duckinzzz <yurchenko.ps@ya.ru>`; трейлер `Co-Authored-By` не добавлять никогда.
- Таймзона по умолчанию `Europe/Moscow`; все datetime, которые сравниваются, — aware.
- Литерал отметки в таблице — ровно `+`.
- Токены, id таблицы и ключ сервисного аккаунта — только в `.env`; `credentials.json` в git не попадает.
- Логирование: `core.log.logger`, формат из шаблона.
- Тесты не ходят в сеть и не поднимают Telegram-бота.
- Сообщения пользователю — на русском.

## Отличия от спеки

Спека согласована, но при детализации вылезли четыре места, где буквальное следование ей хуже. Каждое — уточнение, а не смена поведения; перечислены, чтобы ревьюер сверил:

1. **Идентификатор сессии вместо `message_id` в callback_data.** `callback_data` собирается до отправки сообщения, когда `message_id` ещё неизвестен; плюс после рестарта сообщение не переотправляется. Поэтому в кнопке едет короткий токен (`uuid4().hex[:12]`), он же хранится в `state.json`.
2. **`SubjectSheet.marked_rows(column) -> set[int]` вместо `is_marked(row, column) -> bool`.** Уже отмеченные строки читаются один раз при открытии пары (один вызов `col_values`), а не по вызову на каждое нажатие. Поведение то же, запросов меньше.
3. **Добавлены модули `services/state.py`, `utils/names.py`, `utils/retry.py`, `core/log.py`.** Спека описывала эти обязанности, но не выделяла файлы. `core/log.py` отделён, чтобы тесты не тянули `core.app` (который создаёт `Bot`).
4. **Валидацию JSON-справочников делает загрузчик, а не `core/config.py`.** `load_settings` проверяет, что файлы существуют; разбор JSON с внятной ошибкой — в `StudentDirectory.load` / `Subjects.load`, которые вызываются на старте бота. Намерение спеки (падать быстро и понятно) сохранено.

Также из шаблона удаляется `handlers/echo.py`: он отвечает на любое сообщение в беседе, что для боевого бота недопустимо.

## Review Focus

Пять классов входа, которые спека подразумевает, но не проговаривает; тест на каждый добавлен в задачу-владельца кода:

1. **Битый или неполный `state.json`** (`{}`, обрезанный файл, дата строкой не по формату) — бот обязан стартовать с чистым состоянием, а не падать на старте. Тест в Task 9.
2. **Вкладка без студентов** (только шапка или вообще пустая) — `ensure_date_column` не должен писать дату в колонку A (там ФИО), `student_rows()` возвращает `{}`. Тест в Task 8.
3. **Дата в шапке без года** (`07.10`) — столбец должен находиться, а не создаваться второй раз. Тест в Task 8.
4. **Ровно момент окончания пары** — пара уже считается закончившейся: старт новой не проходит, отметка не принимается. Тесты в Task 5 и Task 11.
5. **Повторный запуск того же предмета в тот же день** — второй столбец с сегодняшней датой не создаётся. Тест в Task 8.

---

### Task 1: Конфигурация и логирование

**Files:**
- Modify: `core/config.py` (полная замена содержимого)
- Create: `core/log.py`
- Modify: `core/app.py`
- Modify: `.env.example`
- Test: `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `core.config.BOT_TOKEN: str` — как в шаблоне.
  - `core.config.ConfigError(ValueError)`.
  - `core.config.parse_pair_end_times(raw: str) -> list[datetime.time]`.
  - `core.config.parse_admin_ids(raw: str) -> frozenset[int]`.
  - `core.config.Settings` (frozen dataclass) с полями `admin_ids: frozenset[int]`, `chat_id: int`, `pair_end_times: tuple[time, ...]`, `spreadsheet_id: str`, `credentials_path: Path`, `tz: ZoneInfo`, `students_path: Path`, `subjects_path: Path`, `state_path: Path`.
  - `core.config.load_settings(env: Mapping[str, str] | None = None) -> Settings`.
  - `core.log.logger`.

- [ ] **Step 1: Настроить pytest**

Добавить в `pyproject.toml` dev-зависимости и конфиг:

```bash
uv add --dev pytest pytest-asyncio
```

В конец `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`asyncio_mode = "auto"` — чтобы `async def test_...` не требовал декоратора.

- [ ] **Step 2: Написать `tests/conftest.py` и падающие тесты конфига**

Создать пустой `tests/__init__.py` — без него pytest не поставит корень репозитория в `sys.path` и импорты вида `from tests.fakes import ...` не заработают.

`tests/conftest.py` (обязательно до импорта `core.config`, который падает без токена):

```python
import os

os.environ.setdefault("BOT_TOKEN", "123456789:AAFakeTokenForTestsOnly1234567890")
```

`tests/test_config.py`:

```python
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.config import ConfigError, load_settings, parse_admin_ids, parse_pair_end_times


def _env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    env = {
        "ADMIN_IDS": "111,222",
        "CHAT_ID": "-1001234567890",
        "PAIR_END_TIMES": "10:05,11:40,13:15",
        "SPREADSHEET_ID": "sheet-id",
        "GOOGLE_CREDENTIALS_PATH": str(credentials),
    }
    env.update(overrides)
    return env


def test_parse_pair_end_times_reads_hh_mm():
    assert parse_pair_end_times("10:05, 11:40,13:15") == [time(10, 5), time(11, 40), time(13, 15)]


@pytest.mark.parametrize("raw", ["", "  ", "10:05,чепуха", "13:15,10:05"])
def test_parse_pair_end_times_rejects_bad_input(raw: str):
    with pytest.raises(ConfigError):
        parse_pair_end_times(raw)


def test_parse_admin_ids_skips_spaces():
    assert parse_admin_ids(" 111 , 222 ") == frozenset({111, 222})


def test_parse_admin_ids_rejects_garbage():
    with pytest.raises(ConfigError):
        parse_admin_ids("111,abc")


def test_load_settings_uses_defaults(tmp_path: Path):
    settings = load_settings(_env(tmp_path))
    assert settings.admin_ids == frozenset({111, 222})
    assert settings.chat_id == -1001234567890
    assert settings.pair_end_times == (time(10, 5), time(11, 40), time(13, 15))
    assert settings.spreadsheet_id == "sheet-id"
    assert settings.tz == ZoneInfo("Europe/Moscow")
    assert settings.students_path == Path("data/students.json")
    assert settings.subjects_path == Path("data/subjects.json")
    assert settings.state_path == Path("data/state.json")


def test_load_settings_honours_tz_and_paths(tmp_path: Path):
    settings = load_settings(
        _env(tmp_path, TZ="Asia/Yekaterinburg", STUDENTS_PATH=str(tmp_path / "s.json"))
    )
    assert settings.tz == ZoneInfo("Asia/Yekaterinburg")
    assert settings.students_path == tmp_path / "s.json"


@pytest.mark.parametrize("missing", ["ADMIN_IDS", "CHAT_ID", "PAIR_END_TIMES", "SPREADSHEET_ID", "GOOGLE_CREDENTIALS_PATH"])
def test_load_settings_requires_variable(tmp_path: Path, missing: str):
    env = _env(tmp_path)
    env.pop(missing)
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_load_settings_rejects_missing_credentials_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="GOOGLE_CREDENTIALS_PATH"):
        load_settings(_env(tmp_path, GOOGLE_CREDENTIALS_PATH=str(tmp_path / "nope.json")))


def test_load_settings_rejects_unknown_tz(tmp_path: Path):
    with pytest.raises(ConfigError, match="TZ"):
        load_settings(_env(tmp_path, TZ="Mars/Olympus"))


def test_load_settings_rejects_non_numeric_chat_id(tmp_path: Path):
    with pytest.raises(ConfigError, match="CHAT_ID"):
        load_settings(_env(tmp_path, CHAT_ID="group-chat"))
```

- [ ] **Step 3: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_settings'`.

- [ ] **Step 4: Написать `core/config.py`**

```python
import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found")


class ConfigError(ValueError):
    """Некорректная конфигурация окружения."""


def parse_pair_end_times(raw: str) -> list[time]:
    times: list[time] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            hour, minute = chunk.split(":")
            times.append(time(int(hour), int(minute)))
        except ValueError as exc:
            raise ConfigError(f"PAIR_END_TIMES: не удалось разобрать {chunk!r}") from exc
    if not times:
        raise ConfigError("PAIR_END_TIMES: список пуст")
    if times != sorted(times):
        raise ConfigError("PAIR_END_TIMES: времена должны идти по возрастанию")
    return times


def parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"ADMIN_IDS: {chunk!r} не похоже на id") from exc
    if not ids:
        raise ConfigError("ADMIN_IDS: список пуст")
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    admin_ids: frozenset[int]
    chat_id: int
    pair_end_times: tuple[time, ...]
    spreadsheet_id: str
    credentials_path: Path
    tz: ZoneInfo
    students_path: Path
    subjects_path: Path
    state_path: Path


def _required(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise ConfigError(f"{name}: переменная не задана")
    return value


def _required_int(env: Mapping[str, str], name: str) -> int:
    raw = _required(env, name)
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}: {raw!r} не число") from exc


def _optional_path(env: Mapping[str, str], name: str, default: str) -> Path:
    value = (env.get(name) or "").strip()
    return Path(value or default)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    tz_name = (env.get("TZ") or "").strip() or "Europe/Moscow"
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # ZoneInfoNotFoundError и производные
        raise ConfigError(f"TZ: неизвестная таймзона {tz_name!r}") from exc

    credentials_path = Path(_required(env, "GOOGLE_CREDENTIALS_PATH"))
    if not credentials_path.is_file():
        raise ConfigError(f"GOOGLE_CREDENTIALS_PATH: файл не найден: {credentials_path}")

    return Settings(
        admin_ids=parse_admin_ids(_required(env, "ADMIN_IDS")),
        chat_id=_required_int(env, "CHAT_ID"),
        pair_end_times=tuple(parse_pair_end_times(_required(env, "PAIR_END_TIMES"))),
        spreadsheet_id=_required(env, "SPREADSHEET_ID"),
        credentials_path=credentials_path,
        tz=tz,
        students_path=_optional_path(env, "STUDENTS_PATH", "data/students.json"),
        subjects_path=_optional_path(env, "SUBJECTS_PATH", "data/subjects.json"),
        state_path=_optional_path(env, "STATE_PATH", "data/state.json"),
    )
```

- [ ] **Step 5: Вынести логгер в `core/log.py` и переписать `core/app.py`**

`core/log.py`:

```python
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("bot_core")
```

`core/app.py` целиком:

```python
from aiogram import Bot, Dispatcher

from core.config import BOT_TOKEN
from core.log import logger

logger.info(f"Bot starting | token ends with ...{BOT_TOKEN[-6:]}")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
```

- [ ] **Step 6: Обновить `.env.example`**

```
BOT_TOKEN=  # tgbot token from @BotFather
ADMIN_IDS=  # tg id админов через запятую: 111,222
CHAT_ID=  # id беседы группы, например -1001234567890
PAIR_END_TIMES=  # времена окончания пар по порядку: 10:05,11:40,13:15,14:50
SPREADSHEET_ID=  # id Google-таблицы посещаемости
GOOGLE_CREDENTIALS_PATH=credentials.json  # путь к JSON-ключу сервисного аккаунта
TZ=Europe/Moscow
STUDENTS_PATH=data/students.json
SUBJECTS_PATH=data/subjects.json
STATE_PATH=data/state.json
```

- [ ] **Step 7: Прогнать тесты**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, 17 passed.

- [ ] **Step 8: Коммит**

```bash
git add pyproject.toml uv.lock core/config.py core/log.py core/app.py .env.example tests/
git commit -m "feat: конфигурация бота и отдельный логгер"
```

---

### Task 2: Нормализация ФИО

**Files:**
- Create: `utils/names.py`
- Test: `tests/test_names.py`

**Interfaces:**
- Consumes: ничего.
- Produces: `utils.names.normalize_name(value: str) -> str` — ключ сверки ФИО из справочника с ФИО в таблице.

- [ ] **Step 1: Написать падающий тест**

`tests/test_names.py`:

```python
import pytest

from utils.names import normalize_name


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Иванов Иван Иванович", "  Иванов   Иван  Иванович "),
        ("Пётр Семёнов", "Петр Семенов"),
        ("ПЁТР СЕМЁНОВ", "петр семенов"),
        ("Иванов\tИван\nИванович", "Иванов Иван Иванович"),
    ],
)
def test_normalize_name_matches_variants(left: str, right: str):
    assert normalize_name(left) == normalize_name(right)


def test_normalize_name_keeps_different_people_apart():
    assert normalize_name("Иванов Иван") != normalize_name("Иванов Иван Иванович")


def test_normalize_name_of_blank_is_empty():
    assert normalize_name("   ") == ""
```

- [ ] **Step 2: Запустить тест — должен упасть**

Run: `uv run pytest tests/test_names.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.names'`.

- [ ] **Step 3: Написать `utils/names.py`**

```python
def normalize_name(value: str) -> str:
    """Ключ сверки ФИО: регистр, ё и любые пробелы не важны."""
    lowered = value.replace("ё", "е").replace("Ё", "Е").lower()
    return " ".join(lowered.split())
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_names.py -v`
Expected: PASS, 6 passed.

- [ ] **Step 5: Коммит**

```bash
git add utils/names.py tests/test_names.py
git commit -m "feat: нормализация ФИО для сверки с таблицей"
```

---

### Task 3: Справочник студентов

**Files:**
- Create: `services/__init__.py`, `services/students.py`
- Test: `tests/test_students.py`

**Interfaces:**
- Consumes: `utils.names.normalize_name`, `core.config.ConfigError`.
- Produces:
  - `services.students.StudentDirectory.load(path: Path) -> StudentDirectory` — кидает `ConfigError` на отсутствующий файл, битый JSON, не-объект, нечисловой ключ, пустое ФИО.
  - `StudentDirectory.name_of(tg_id: int) -> str | None`.
  - `StudentDirectory.all_names() -> list[str]` — ФИО в порядке сортировки по алфавиту (для отчёта).

- [ ] **Step 1: Написать падающий тест**

`tests/test_students.py`:

```python
import json
from pathlib import Path

import pytest

from core.config import ConfigError
from services.students import StudentDirectory


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "students.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_and_lookup(tmp_path: Path):
    directory = StudentDirectory.load(_write(tmp_path, {"111": "Иванов Иван Иванович"}))
    assert directory.name_of(111) == "Иванов Иван Иванович"
    assert directory.name_of(999) is None


def test_all_names_sorted(tmp_path: Path):
    directory = StudentDirectory.load(_write(tmp_path, {"2": "Петров Пётр", "1": "Иванов Иван"}))
    assert directory.all_names() == ["Иванов Иван", "Петров Пётр"]


def test_names_are_stripped(tmp_path: Path):
    directory = StudentDirectory.load(_write(tmp_path, {"1": "  Иванов Иван  "}))
    assert directory.name_of(1) == "Иванов Иван"


def test_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="не найден"):
        StudentDirectory.load(tmp_path / "nope.json")


def test_broken_json(tmp_path: Path):
    path = tmp_path / "students.json"
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON"):
        StudentDirectory.load(path)


def test_not_an_object(tmp_path: Path):
    with pytest.raises(ConfigError, match="объект"):
        StudentDirectory.load(_write(tmp_path, ["111"]))


def test_non_numeric_key(tmp_path: Path):
    with pytest.raises(ConfigError, match="ключ"):
        StudentDirectory.load(_write(tmp_path, {"student": "Иванов Иван"}))


@pytest.mark.parametrize("value", ["", "   ", 42])
def test_bad_name(tmp_path: Path, value: object):
    with pytest.raises(ConfigError, match="ФИО"):
        StudentDirectory.load(_write(tmp_path, {"1": value}))
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_students.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services'`.

- [ ] **Step 3: Написать `services/students.py`**

Создать пустой `services/__init__.py`, затем:

```python
import json
from pathlib import Path

from core.config import ConfigError


class StudentDirectory:
    """Справочник группы: tg_id → ФИО."""

    def __init__(self, by_id: dict[int, str]) -> None:
        self._by_id = dict(by_id)

    @classmethod
    def load(cls, path: Path) -> "StudentDirectory":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Справочник студентов не найден: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Справочник студентов: некорректный JSON в {path}") from exc

        if not isinstance(raw, dict):
            raise ConfigError(
                f"Справочник студентов: ожидался объект вида {{\"tg_id\": \"ФИО\"}}, {path}"
            )

        by_id: dict[int, str] = {}
        for key, value in raw.items():
            try:
                tg_id = int(key)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"Справочник студентов: ключ {key!r} не число") from exc
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"Справочник студентов: у {tg_id} пустое ФИО")
            by_id[tg_id] = value.strip()

        return cls(by_id)

    def name_of(self, tg_id: int) -> str | None:
        return self._by_id.get(tg_id)

    def all_names(self) -> list[str]:
        return sorted(self._by_id.values())
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_students.py -v`
Expected: PASS, 10 passed.

- [ ] **Step 5: Коммит**

```bash
git add services/__init__.py services/students.py tests/test_students.py
git commit -m "feat: справочник студентов tg_id → ФИО"
```

---

### Task 4: Справочник предметов

**Files:**
- Create: `services/subjects.py`
- Test: `tests/test_subjects.py`

**Interfaces:**
- Consumes: `core.config.ConfigError`.
- Produces:
  - `services.subjects.Subjects.load(path: Path) -> Subjects`.
  - `Subjects.titles() -> tuple[str, ...]` — порядок из файла, стабилен для индексов в `callback_data`.
  - `Subjects.title_at(index: int) -> str | None`.
  - `Subjects.worksheet_of(title: str) -> str | None` — имя вкладки.

- [ ] **Step 1: Написать падающий тест**

`tests/test_subjects.py`:

```python
import json
from pathlib import Path

import pytest

from core.config import ConfigError
from services.subjects import Subjects


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "subjects.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_titles_keep_file_order(tmp_path: Path):
    subjects = Subjects.load(_write(tmp_path, {"Матан": "Матан", "Физика": "Физика 1 сем"}))
    assert subjects.titles() == ("Матан", "Физика")


def test_title_at(tmp_path: Path):
    subjects = Subjects.load(_write(tmp_path, {"Матан": "Матан"}))
    assert subjects.title_at(0) == "Матан"
    assert subjects.title_at(5) is None


def test_worksheet_of(tmp_path: Path):
    subjects = Subjects.load(_write(tmp_path, {"Матан": "Матан 1 сем"}))
    assert subjects.worksheet_of("Матан") == "Матан 1 сем"
    assert subjects.worksheet_of("Неизвестный") is None


def test_missing_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="не найден"):
        Subjects.load(tmp_path / "nope.json")


def test_broken_json(tmp_path: Path):
    path = tmp_path / "subjects.json"
    path.write_text("{не json", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON"):
        Subjects.load(path)


def test_empty_object(tmp_path: Path):
    with pytest.raises(ConfigError, match="пуст"):
        Subjects.load(_write(tmp_path, {}))


def test_blank_worksheet(tmp_path: Path):
    with pytest.raises(ConfigError, match="вкладк"):
        Subjects.load(_write(tmp_path, {"Матан": "  "}))


def test_duplicate_worksheets_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="повтор"):
        Subjects.load(_write(tmp_path, {"Матан": "Лист", "Физика": "Лист"}))
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_subjects.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.subjects'`.

- [ ] **Step 3: Написать `services/subjects.py`**

```python
import json
from pathlib import Path

from core.config import ConfigError


class Subjects:
    """Справочник предметов: название для кнопки → имя вкладки в таблице."""

    def __init__(self, by_title: dict[str, str]) -> None:
        self._by_title = dict(by_title)
        self._titles = tuple(by_title)

    @classmethod
    def load(cls, path: Path) -> "Subjects":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"Справочник предметов не найден: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Справочник предметов: некорректный JSON в {path}") from exc

        if not isinstance(raw, dict) or not raw:
            raise ConfigError(
                f"Справочник предметов пуст или не объект вида {{\"Предмет\": \"Вкладка\"}}: {path}"
            )

        by_title: dict[str, str] = {}
        used_worksheets: dict[str, str] = {}
        for title, worksheet in raw.items():
            if not isinstance(title, str) or not title.strip():
                raise ConfigError(f"Справочник предметов: пустое название предмета в {path}")
            if not isinstance(worksheet, str) or not worksheet.strip():
                raise ConfigError(f"Справочник предметов: у {title!r} не указана вкладка")
            worksheet = worksheet.strip()
            if worksheet in used_worksheets:
                raise ConfigError(
                    f"Справочник предметов: вкладка {worksheet!r} повторяется "
                    f"у {used_worksheets[worksheet]!r} и {title!r}"
                )
            used_worksheets[worksheet] = title
            by_title[title.strip()] = worksheet

        return cls(by_title)

    def titles(self) -> tuple[str, ...]:
        return self._titles

    def title_at(self, index: int) -> str | None:
        if 0 <= index < len(self._titles):
            return self._titles[index]
        return None

    def worksheet_of(self, title: str) -> str | None:
        return self._by_title.get(title)
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_subjects.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 5: Коммит**

```bash
git add services/subjects.py tests/test_subjects.py
git commit -m "feat: справочник предметов предмет → вкладка"
```

---

### Task 5: Расписание пар

**Files:**
- Create: `services/schedule.py`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `services.schedule.CurrentPair` — frozen dataclass с полями `number: int` (1-based) и `end_at: datetime`.
  - `services.schedule.current_pair(now: datetime, pair_end_times: Sequence[time]) -> CurrentPair | None` — ближайшее время окончания, которое **строго больше** `now`; `None`, если все прошли. Кидает `ValueError`, если `now` без таймзоны.

- [ ] **Step 1: Написать падающий тест**

`tests/test_schedule.py`:

```python
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from services.schedule import current_pair

MSK = ZoneInfo("Europe/Moscow")
ENDS = [time(10, 5), time(11, 40), time(13, 15)]


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 7, hour, minute, second, tzinfo=MSK)


def test_before_first_pair():
    pair = current_pair(_at(9, 0), ENDS)
    assert pair is not None
    assert pair.number == 1
    assert pair.end_at == _at(10, 5)


def test_between_pairs_picks_next():
    pair = current_pair(_at(11, 0), ENDS)
    assert pair is not None
    assert pair.number == 2
    assert pair.end_at == _at(11, 40)


def test_exactly_at_end_time_pair_is_over():
    pair = current_pair(_at(10, 5), ENDS)
    assert pair is not None
    assert pair.number == 2
    assert pair.end_at == _at(11, 40)


def test_after_last_pair():
    assert current_pair(_at(15, 0), ENDS) is None


def test_exactly_at_last_end_time():
    assert current_pair(_at(13, 15), ENDS) is None


def test_single_pair_list():
    pair = current_pair(_at(9, 0), [time(10, 5)])
    assert pair is not None
    assert pair.number == 1


def test_naive_datetime_rejected():
    with pytest.raises(ValueError, match="таймзон"):
        current_pair(datetime(2026, 10, 7, 9, 0), ENDS)
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.schedule'`.

- [ ] **Step 3: Написать `services/schedule.py`**

```python
from dataclasses import dataclass
from datetime import datetime, time
from typing import Sequence


@dataclass(frozen=True)
class CurrentPair:
    number: int
    end_at: datetime


def current_pair(now: datetime, pair_end_times: Sequence[time]) -> CurrentPair | None:
    """Ближайший конец пары, который ещё не наступил.

    Ровно в момент окончания пара уже считается закончившейся, поэтому
    сравнение строгое. `None` — все пары на сегодня прошли.
    """
    if now.tzinfo is None:
        raise ValueError("now должен быть с таймзоной")

    for index, end in enumerate(pair_end_times, start=1):
        candidate = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
        if candidate > now:
            return CurrentPair(number=index, end_at=candidate)
    return None
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_schedule.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Коммит**

```bash
git add services/schedule.py tests/test_schedule.py
git commit -m "feat: определение текущей пары по расписанию концов"
```

---

### Task 6: Повтор вызовов с backoff

**Files:**
- Create: `utils/retry.py`
- Test: `tests/test_retry.py`

**Interfaces:**
- Consumes: ничего (класс исключения передаётся параметром, чтобы `utils` не зависел от `services`).
- Produces: `utils.retry.call_with_retry(func, *args, attempts: int = 3, base_delay: float = 1.0, retry_on: tuple[type[BaseException], ...]) -> T` — синхронный `func` выполняется в `asyncio.to_thread` (gspread синхронный, нельзя блокировать лог).

- [ ] **Step 1: Написать падающий тест**

`tests/test_retry.py`:

```python
import time as time_module

import pytest

from utils.retry import call_with_retry


class Transient(Exception):
    pass


class Permanent(Exception):
    pass


async def test_returns_result_without_retries():
    def func(value: int) -> int:
        return value * 2

    assert await call_with_retry(func, 21, retry_on=(Transient,)) == 42


async def test_retries_transient_then_succeeds():
    attempts = []

    def func() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise Transient("429")
        return "ok"

    assert await call_with_retry(func, attempts=3, base_delay=0, retry_on=(Transient,)) == "ok"
    assert len(attempts) == 3


async def test_gives_up_after_attempts():
    def func() -> None:
        raise Transient("429")

    with pytest.raises(Transient):
        await call_with_retry(func, attempts=3, base_delay=0, retry_on=(Transient,))


async def test_permanent_error_is_not_retried():
    attempts = []

    def func() -> None:
        attempts.append(1)
        raise Permanent("нет вкладки")

    with pytest.raises(Permanent):
        await call_with_retry(func, attempts=3, base_delay=0, retry_on=(Transient,))
    assert len(attempts) == 1


async def test_delay_grows_exponentially():
    delays = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    def func() -> None:
        raise Transient("429")

    with pytest.raises(Transient):
        await call_with_retry(
            func, attempts=3, base_delay=1.0, retry_on=(Transient,), sleep=fake_sleep
        )
    assert delays == [1.0, 2.0]
```

`time_module` импортирован намеренно: убедиться, что тесты не спят по-настоящему.

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_retry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.retry'`.

- [ ] **Step 3: Написать `utils/retry.py`**

```python
import asyncio
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


async def call_with_retry(
    func: Callable[..., T],
    *args: Any,
    attempts: int = 3,
    base_delay: float = 1.0,
    retry_on: tuple[type[BaseException], ...],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Вызвать синхронную func в отдельном потоке, повторяя на retry_on.

    Задержка между попытками растёт вдвое: base_delay, 2*base_delay, ...
    """
    for attempt in range(attempts):
        try:
            return await asyncio.to_thread(func, *args)
        except retry_on:
            if attempt == attempts - 1:
                raise
            await sleep(base_delay * (2**attempt))
    raise AssertionError("недостижимо: цикл заканчивается return или raise")
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_retry.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 5: Коммит**

```bash
git add utils/retry.py tests/test_retry.py
git commit -m "feat: повтор вызовов с экспоненциальным backoff"
```

---

### Task 7: Протокол таблицы, фейк и чтение вкладки

**Files:**
- Create: `services/sheets.py`
- Create: `tests/fakes.py`
- Test: `tests/test_sheets.py`

**Interfaces:**
- Consumes: `utils.names.normalize_name`.
- Produces:
  - `services.sheets.MARK = "+"`.
  - `services.sheets.SheetError(RuntimeError)` — постоянная ошибка (нет доступа, нет вкладки).
  - `services.sheets.SheetTransientError(SheetError)` — временная (429, 5xx).
  - `services.sheets.SubjectSheet` — Protocol: `student_rows() -> dict[str, int]`, `ensure_date_column(day: date) -> int`, `marked_rows(column: int) -> set[int]`, `write_marks(marks: Sequence[tuple[int, int]]) -> None`.
  - `services.sheets.GspreadSubjectSheet` — реализация поверх листа gspread: `GspreadSubjectSheet(worksheet)`; класс-метод `open(spreadsheet_id: str, worksheet: str, credentials_path: Path) -> GspreadSubjectSheet`.
  - `tests/fakes.FakeSubjectSheet` — реализация протокола в памяти.
  - `tests/fakes.FakeWorksheet` — подделка листа gspread для тестов `GspreadSubjectSheet`.

- [ ] **Step 1: Добавить gspread**

```bash
uv add gspread
```

- [ ] **Step 2: Написать `tests/fakes.py`**

```python
from datetime import date
from typing import Sequence

from services.sheets import MARK


class FakeWorksheet:
    """Минимальная подделка gspread.worksheet.Worksheet."""

    def __init__(self, rows: list[list[str]] | None = None) -> None:
        self.rows: list[list[str]] = [list(row) for row in (rows or [])]
        self.updates: list[tuple[int, int, str]] = []
        self.batch_updates: list[list[dict]] = []

    def _ensure_cell(self, row: int, column: int) -> None:
        while len(self.rows) < row:
            self.rows.append([])
        while len(self.rows[row - 1]) < column:
            self.rows[row - 1].append("")

    def get_all_values(self) -> list[list[str]]:
        width = max((len(row) for row in self.rows), default=0)
        return [list(row) + [""] * (width - len(row)) for row in self.rows]

    def col_values(self, column: int) -> list[str]:
        values = []
        for row in self.rows:
            values.append(row[column - 1] if len(row) >= column else "")
        return values

    def update_cell(self, row: int, column: int, value: str) -> None:
        self._ensure_cell(row, column)
        self.rows[row - 1][column - 1] = value
        self.updates.append((row, column, value))

    def batch_update(self, data: list[dict], **kwargs: object) -> None:
        self.batch_updates.append(data)
        for item in data:
            row, column = item["range"]  # кортеж (row, column) в тестах
            self._ensure_cell(row, column)
            self.rows[row - 1][column - 1] = item["values"][0][0]


class FakeSubjectSheet:
    """Реализация протокола SubjectSheet в памяти.

    Колонка A — ФИО, даты начинаются с колонки B.
    """

    def __init__(
        self,
        students: Sequence[str] = (),
        dates: Sequence[date] = (),
        cells: dict[tuple[int, int], str] | None = None,
    ) -> None:
        self.students = list(students)
        self.dates = list(dates)
        self.cells = dict(cells or {})
        self.written: list[tuple[int, int]] = []
        self.fail_next_writes = 0

    def student_rows(self) -> dict[str, int]:
        from utils.names import normalize_name

        return {normalize_name(name): row for row, name in enumerate(self.students, start=2)}

    def ensure_date_column(self, day: date) -> int:
        if day in self.dates:
            return self.dates.index(day) + 2
        self.dates.append(day)
        return len(self.dates) + 1

    def marked_rows(self, column: int) -> set[int]:
        return {
            row
            for (row, col), value in self.cells.items()
            if col == column and value.strip() == MARK
        }

    def write_marks(self, marks: Sequence[tuple[int, int]]) -> None:
        if self.fail_next_writes > 0:
            self.fail_next_writes -= 1
            from services.sheets import SheetTransientError

            raise SheetTransientError("429")
        self.written.extend(marks)
        for row, column in marks:
            self.cells[(row, column)] = MARK
```

- [ ] **Step 3: Написать падающие тесты**

`tests/test_sheets.py`:

```python
from datetime import date

import pytest

from services.sheets import MARK, GspreadSubjectSheet, SheetError
from tests.fakes import FakeWorksheet

TODAY = date(2026, 10, 7)


def _sheet(rows: list[list[str]]) -> GspreadSubjectSheet:
    return GspreadSubjectSheet(FakeWorksheet(rows))


def test_student_rows_maps_normalized_names():
    sheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""], ["Петров Пётр", ""]])
    assert sheet.student_rows() == {"иванов иван": 2, "петров петр": 3}


def test_student_rows_skips_blank_rows():
    sheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""], ["", ""]])
    assert sheet.student_rows() == {"иванов иван": 2}


def test_student_rows_on_empty_sheet():
    assert _sheet([]).student_rows() == {}


def test_ensure_date_column_finds_existing():
    sheet = _sheet([["ФИО", "07.10.2026", "09.10.2026"], ["Иванов Иван", "", ""]])
    assert sheet.ensure_date_column(TODAY) == 2


def test_ensure_date_column_finds_date_without_year():
    sheet = _sheet([["ФИО", "07.10"], ["Иванов Иван", ""]])
    assert sheet.ensure_date_column(TODAY) == 2


def test_ensure_date_column_does_not_duplicate_same_day():
    sheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])
    assert sheet.ensure_date_column(TODAY) == 2
    assert sheet.ensure_date_column(TODAY) == 2


def test_ensure_date_column_appends_after_last_filled():
    sheet = _sheet([["ФИО", "01.10.2026", "03.10.2026"], ["Иванов Иван", "", ""]])
    assert sheet.ensure_date_column(TODAY) == 4


def test_ensure_date_column_never_writes_into_column_a():
    worksheet = FakeWorksheet([])
    sheet = GspreadSubjectSheet(worksheet)
    assert sheet.ensure_date_column(TODAY) == 2
    assert worksheet.updates == [(1, 2, "07.10.2026")]


def test_marked_rows_reads_plus_only():
    sheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", "+"], ["Петров Пётр", "н"]])
    assert sheet.marked_rows(2) == {2}


def test_marked_rows_ignores_other_columns():
    sheet = _sheet([["ФИО", "07.10.2026", "09.10.2026"], ["Иванов Иван", "+", "+"]])
    assert sheet.marked_rows(3) == {2}


def test_mark_literal_is_plus():
    assert MARK == "+"
```

- [ ] **Step 4: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_sheets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.sheets'`.

- [ ] **Step 5: Написать `services/sheets.py` (чтение + константы)**

```python
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Protocol, Sequence

import gspread
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

from utils.names import normalize_name

MARK = "+"

_DATE_FORMATS = ("%d.%m.%Y", "%d.%m")


class SheetError(RuntimeError):
    """Постоянная ошибка: нет доступа, нет вкладки, нет таблицы."""


class SheetTransientError(SheetError):
    """Временная ошибка Google API: 429, 5xx, сеть."""


class SubjectSheet(Protocol):
    def student_rows(self) -> dict[str, int]:
        """Нормализованное ФИО → номер строки (1-based)."""

    def ensure_date_column(self, day: date) -> int:
        """Номер столбца с датой; создаёт столбец, если его нет."""

    def marked_rows(self, column: int) -> set[int]:
        """Номера строк, где в этом столбце уже стоит «+»."""

    def write_marks(self, marks: Sequence[tuple[int, int]]) -> None:
        """Проставить «+» во все (row, column) одной пачкой."""


def _parse_header_date(cell: str, today: date) -> date | None:
    value = cell.strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        year = parsed.year if "%Y" in fmt else today.year
        return date(year, parsed.month, parsed.day)
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _translate(exc: APIError) -> SheetError:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429 or (isinstance(status, int) and 500 <= status < 600):
        return SheetTransientError(str(exc))
    return SheetError(str(exc))


class GspreadSubjectSheet:
    """Вкладка одного предмета в Google-таблице."""

    def __init__(self, worksheet: "gspread.Worksheet") -> None:
        self._ws = worksheet
        self._cache: list[list[str]] | None = None

    @classmethod
    def open(
        cls, spreadsheet_id: str, worksheet: str, credentials_path: Path
    ) -> "GspreadSubjectSheet":
        try:
            client = gspread.service_account(filename=str(credentials_path))
        except Exception as exc:
            raise SheetError(f"Не удалось прочитать ключ сервисного аккаунта: {exc}") from exc

        try:
            spreadsheet = client.open_by_key(spreadsheet_id)
        except SpreadsheetNotFound as exc:
            raise SheetError(
                f"Таблица {spreadsheet_id} не найдена. Проверь, что она расшарена "
                f"на email сервисного аккаунта из {credentials_path}"
            ) from exc
        except APIError as exc:
            raise _translate(exc) from exc

        try:
            worksheet_object = spreadsheet.worksheet(worksheet)
        except WorksheetNotFound as exc:
            raise SheetError(f"В таблице нет вкладки {worksheet!r}") from exc
        except APIError as exc:
            raise _translate(exc) from exc

        return cls(worksheet_object)

    def _values(self) -> list[list[str]]:
        if self._cache is None:
            try:
                self._cache = self._ws.get_all_values()
            except APIError as exc:
                raise _translate(exc) from exc
        return self._cache

    def student_rows(self) -> dict[str, int]:
        rows: dict[str, int] = {}
        for index, record in enumerate(self._values(), start=1):
            if index == 1 or not record:
                continue
            name = record[0].strip()
            if name:
                rows[normalize_name(name)] = index
        return rows

    def ensure_date_column(self, day: date) -> int:
        header = self._values()[0] if self._values() else []
        for index, cell in enumerate(header, start=1):
            if _parse_header_date(cell, day) == day:
                return index

        # Колонка A занята ФИО, поэтому дата никогда не пишется в неё.
        column = max(len(header), 1) + 1
        try:
            self._ws.update_cell(1, column, day.strftime("%d.%m.%Y"))
        except APIError as exc:
            raise _translate(exc) from exc
        self._cache = None
        return column

    def marked_rows(self, column: int) -> set[int]:
        try:
            values = self._ws.col_values(column)
        except APIError as exc:
            raise _translate(exc) from exc
        return {
            index
            for index, value in enumerate(values, start=1)
            if index > 1 and value.strip() == MARK
        }
```

- [ ] **Step 6: Запустить тесты**

Run: `uv run pytest tests/test_sheets.py -v`
Expected: PASS, 11 passed.

- [ ] **Step 7: Коммит**

```bash
git add services/sheets.py tests/fakes.py tests/test_sheets.py pyproject.toml uv.lock
git commit -m "feat: чтение вкладки предмета и определение столбца даты"
```

---

### Task 8: Запись отметок в таблицу

**Files:**
- Modify: `services/sheets.py` (дописать метод и открытый конструктор для тестов)
- Test: `tests/test_sheets_write.py`

**Interfaces:**
- Consumes: `GspreadSubjectSheet`, `FakeWorksheet` из Task 7.
- Produces: `GspreadSubjectSheet.write_marks(marks: Sequence[tuple[int, int]]) -> None` — один `batch_update` на пачку, пустой список ничего не делает.

- [ ] **Step 1: Написать падающий тест**

`tests/test_sheets_write.py`:

```python
from datetime import date

import pytest

from services.sheets import MARK, GspreadSubjectSheet, SheetTransientError
from tests.fakes import FakeWorksheet

TODAY = date(2026, 10, 7)


def _sheet(rows: list[list[str]]) -> tuple[GspreadSubjectSheet, FakeWorksheet]:
    worksheet = FakeWorksheet(rows)
    return GspreadSubjectSheet(worksheet), worksheet


def test_write_marks_uses_single_batch_call():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])
    sheet.write_marks([(2, 2), (3, 2)])
    assert len(worksheet.batch_updates) == 1
    assert len(worksheet.batch_updates[0]) == 2


def test_write_marks_puts_plus_in_cells():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])
    sheet.write_marks([(2, 2)])
    assert worksheet.rows[1][1] == MARK


def test_write_marks_with_empty_list_makes_no_call():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"]])
    sheet.write_marks([])
    assert worksheet.batch_updates == []


def test_write_marks_builds_a1_ranges():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])
    sheet.write_marks([(2, 2)])
    assert worksheet.batch_updates[0][0]["range"] == "B2"


def test_write_marks_wraps_transient_error():
    sheet, worksheet = _sheet([["ФИО", "07.10.2026"], ["Иванов Иван", ""]])

    def boom(*args: object, **kwargs: object) -> None:
        raise SheetTransientError("429")

    worksheet.batch_update = boom  # type: ignore[method-assign]
    with pytest.raises(SheetTransientError):
        sheet.write_marks([(2, 2)])
```

Тест `test_write_marks_builds_a1_ranges` требует, чтобы `FakeWorksheet.batch_update` понимал и строковый A1-диапазон, и кортеж. Обновить `batch_update` в `tests/fakes.py`:

```python
    def batch_update(self, data: list[dict], **kwargs: object) -> None:
        self.batch_updates.append(data)
        for item in data:
            target = item["range"]
            if isinstance(target, str):
                column = ord(target[0]) - ord("A") + 1
                row = int(target[1:])
            else:
                row, column = target
            self._ensure_cell(row, column)
            self.rows[row - 1][column - 1] = item["values"][0][0]
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_sheets_write.py -v`
Expected: FAIL — `AttributeError: 'GspreadSubjectSheet' object has no attribute 'write_marks'`.

- [ ] **Step 3: Дописать `write_marks` в `services/sheets.py`**

Добавить `rowcol_to_a1` в импорты из gspread:

```python
from gspread.utils import rowcol_to_a1
```

И метод в `GspreadSubjectSheet` (после `marked_rows`):

```python
    def write_marks(self, marks: Sequence[tuple[int, int]]) -> None:
        if not marks:
            return
        data = [
            {"range": rowcol_to_a1(row, column), "values": [[MARK]]}
            for row, column in marks
        ]
        try:
            self._ws.batch_update(data, value_input_option="USER_ENTERED")
        except APIError as exc:
            raise _translate(exc) from exc
```

Один `batch_update` на всю пачку: лимит Google — порядка 60 запросов на запись в минуту, пачка считается за один запрос.

- [ ] **Step 4: Запустить тесты (и весь файл Task 7 заодно)**

Run: `uv run pytest tests/test_sheets.py tests/test_sheets_write.py -v`
Expected: PASS, 16 passed.

- [ ] **Step 5: Коммит**

```bash
git add services/sheets.py tests/fakes.py tests/test_sheets_write.py
git commit -m "feat: батч-запись отметок в Google-таблицу"
```

---

### Task 9: Хранилище состояния пары

**Files:**
- Create: `services/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `core.log.logger`.
- Produces:
  - `services.state.StoredSession` — frozen dataclass: `token: str`, `subject: str`, `worksheet: str`, `message_id: int`, `day: date`, `pair_number: int`, `end_at: datetime`, `marked_rows: dict[int, int]` (tg_id → строка), `pending: tuple[tuple[int, int], ...]`.
  - `StoredSession.to_json() -> dict[str, object]` и `StoredSession.from_json(raw: object) -> StoredSession` (кидает `ValueError` на неподходящий объект).
  - `services.state.StateStore(path: Path)`: `load() -> StoredSession | None` (битый файл → лог + `None`), `save(state) -> None` (атомарно), `clear() -> None`.

- [ ] **Step 1: Написать падающий тест**

`tests/test_state.py`:

```python
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from services.state import StateStore, StoredSession

MSK = ZoneInfo("Europe/Moscow")


def _state() -> StoredSession:
    return StoredSession(
        token="abc123",
        subject="Матан",
        worksheet="Матан",
        message_id=42,
        day=date(2026, 10, 7),
        pair_number=3,
        end_at=datetime(2026, 10, 7, 13, 15, tzinfo=MSK),
        marked_rows={111: 2, 222: 5},
        pending=((2, 4),),
    )


def test_round_trip(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.save(_state())
    assert store.load() == _state()


def test_load_without_file(tmp_path: Path):
    assert StateStore(tmp_path / "state.json").load() is None


def test_save_is_atomic_and_leaves_no_tmp(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.save(_state())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]


def test_save_creates_parent_directory(tmp_path: Path):
    store = StateStore(tmp_path / "nested" / "state.json")
    store.save(_state())
    assert (tmp_path / "nested" / "state.json").is_file()


def test_clear_removes_file(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.save(_state())
    store.clear()
    assert store.load() is None


def test_clear_without_file_is_noop(tmp_path: Path):
    StateStore(tmp_path / "state.json").clear()


@pytest.mark.parametrize(
    "payload",
    [
        "{не json",
        "{}",
        "[]",
        '{"token": "a", "subject": "Матан"}',
        '{"token": "a", "subject": "Матан", "worksheet": "М", "message_id": 1, '
        '"day": "07.10.2026", "pair_number": 1, "end_at": "2026-10-07T13:15:00+03:00", '
        '"marked_rows": {}, "pending": []}',
    ],
)
def test_broken_state_is_ignored(tmp_path: Path, payload: str):
    path = tmp_path / "state.json"
    path.write_text(payload, encoding="utf-8")
    assert StateStore(path).load() is None


def test_json_keeps_cyrillic_and_aware_datetime(tmp_path: Path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.save(_state())
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["subject"] == "Матан"
    assert raw["marked_rows"] == {"111": 2, "222": 5}
    assert raw["end_at"].endswith("+03:00")


def test_from_json_rejects_bad_end_at():
    with pytest.raises(ValueError):
        StoredSession.from_json(
            {
                "token": "a",
                "subject": "Матан",
                "worksheet": "Матан",
                "message_id": 1,
                "day": "2026-10-07",
                "pair_number": 1,
                "end_at": "вчера",
                "marked_rows": {},
                "pending": [],
            }
        )
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.state'`.

- [ ] **Step 3: Написать `services/state.py`**

```python
import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from core.log import logger


@dataclass(frozen=True)
class StoredSession:
    """Активная пара в том виде, в каком она переживает рестарт."""

    token: str
    subject: str
    worksheet: str
    message_id: int
    day: date
    pair_number: int
    end_at: datetime
    marked_rows: dict[int, int]
    pending: tuple[tuple[int, int], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "subject": self.subject,
            "worksheet": self.worksheet,
            "message_id": self.message_id,
            "day": self.day.isoformat(),
            "pair_number": self.pair_number,
            "end_at": self.end_at.isoformat(),
            "marked_rows": {str(tg_id): row for tg_id, row in self.marked_rows.items()},
            "pending": [[row, column] for row, column in self.pending],
        }

    @classmethod
    def from_json(cls, raw: object) -> "StoredSession":
        if not isinstance(raw, dict):
            raise ValueError("состояние не объект")

        marked = raw["marked_rows"]
        pending = raw["pending"]
        if not isinstance(marked, dict) or not isinstance(pending, list):
            raise ValueError("marked_rows или pending не той формы")

        end_at = datetime.fromisoformat(str(raw["end_at"]))
        if end_at.tzinfo is None:
            raise ValueError("end_at без таймзоны")

        return cls(
            token=str(raw["token"]),
            subject=str(raw["subject"]),
            worksheet=str(raw["worksheet"]),
            message_id=int(raw["message_id"]),
            day=date.fromisoformat(str(raw["day"])),
            pair_number=int(raw["pair_number"]),
            end_at=end_at,
            marked_rows={int(tg_id): int(row) for tg_id, row in marked.items()},
            pending=tuple((int(row), int(column)) for row, column in pending),
        )


class StateStore:
    """Файл состояния на volume: активная пара и буфер отметок."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> StoredSession | None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Файл состояния %s не читается (%s), стартую с чистого листа", self._path, exc)
            return None

        try:
            return StoredSession.from_json(raw)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Файл состояния %s повреждён (%s), стартую с чистого листа", self._path, exc)
            return None

    def save(self, state: StoredSession) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        tmp.write_text(json.dumps(state.to_json(), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_state.py -v`
Expected: PASS, 13 passed.

- [ ] **Step 5: Коммит**

```bash
git add services/state.py tests/test_state.py
git commit -m "feat: файл состояния активной пары"
```

---

### Task 10: Сессия — запуск и закрытие пары

**Files:**
- Create: `keyboards/__init__.py` (перезапись), `keyboards/attendance.py`
- Create: `services/session.py`
- Test: `tests/test_session_start.py`

**Interfaces:**
- Consumes: `Settings`, `StudentDirectory`, `Subjects`, `SubjectSheet`, `FakeSubjectSheet`, `StateStore`, `CurrentPair`/`current_pair`, `call_with_retry`.
- Produces:
  - `keyboards.attendance.checkin_kb(token: str) -> InlineKeyboardMarkup` — одна кнопка «Отметиться» с `callback_data=f"att:{token}"`.
  - `services.session.StartResult` — enum: `STARTED`, `DAY_OVER`, `UNKNOWN_SUBJECT`, `SHEET_ERROR`.
  - `services.session.CheckinResult` — enum: `MARKED`, `ALREADY`, `NO_SESSION`, `NOT_IN_GROUP`, `NOT_IN_SHEET`.
  - `services.session.format_pair_message(subject: str, pair: CurrentPair) -> str`.
  - `services.session.CheckinSession` — конструктор `CheckinSession(*, bot, chat_id, pair_end_times, directory, subjects, open_sheet, store, clock, report=None, flush_delay=2.0, flush_size=20, retry_base_delay=1.0, sleep=asyncio.sleep)`, методы `start(subject_title) -> StartResult`, `handle_checkin(tg_id, token) -> CheckinResult`, `close() -> None`, `restore() -> None`, свойства `close_task: asyncio.Task | None`, `chat_id: int`, `active_subject: str | None`, `marked_count: int`.

- [ ] **Step 1: Написать падающий тест**

Для тестов нужен фейковый бот-объект. Добавить в `tests/fakes.py`:

```python
class FakeBot:
    """Подделка aiogram.Bot: запоминает отправленные и отредактированные сообщения."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self.fail_send = False

    async def send_message(self, chat_id: int, text: str, **kwargs: object):
        if self.fail_send:
            raise RuntimeError("telegram недоступен")
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})
        return SimpleNamespace(message_id=100 + len(self.sent))

    async def edit_message_text(self, text: str, chat_id: int, message_id: int, **kwargs: object):
        self.edited.append({"chat_id": chat_id, "message_id": message_id, "text": text})
        return SimpleNamespace(message_id=message_id)


class TestSleeper:
    """Замена asyncio.sleep для тестов: короткие паузы пропускает, длинную держит.

    flush_delay в тестах нулевой — он должен срабатывать сразу. Пауза до конца
    пары измеряется часами; её держим до явного release(), иначе таймер закрытия
    сработает посреди теста и пара исчезнет из-под проверок.
    """

    def __init__(self, threshold: float = 1.0) -> None:
        self.threshold = threshold
        self.delays: list[float] = []
        self._released = asyncio.Event()

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        if delay <= self.threshold:
            await asyncio.sleep(0)
            return
        await self._released.wait()

    def release(self) -> None:
        self._released.set()
```

`SimpleNamespace` импортировать из `types` в начале `tests/fakes.py`, `asyncio` — там же.

`tests/test_session_start.py`:

```python
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from services.schedule import current_pair
from services.session import CheckinSession, StartResult, format_pair_message
from services.state import StateStore
from services.students import StudentDirectory
from services.subjects import Subjects
from tests.fakes import FakeBot, FakeSubjectSheet, TestSleeper

MSK = ZoneInfo("Europe/Moscow")
ENDS = [time(10, 5), time(11, 40), time(13, 15)]
STUDENTS = ["Иванов Иван", "Петров Пётр"]


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def build(
    tmp_path: Path,
    *,
    now: datetime = datetime(2026, 10, 7, 12, 30, tzinfo=MSK),
    sheet: FakeSubjectSheet | None = None,
    sleeper: TestSleeper | None = None,
) -> tuple[CheckinSession, FakeBot, FakeSubjectSheet, StateStore]:
    bot = FakeBot()
    active_sheet = sheet or FakeSubjectSheet(students=STUDENTS)
    store = StateStore(tmp_path / "state.json")
    session = CheckinSession(
        bot=bot,  # type: ignore[arg-type]
        chat_id=-100,
        pair_end_times=tuple(ENDS),
        directory=StudentDirectory({111: "Иванов Иван", 222: "Петров Пётр"}),
        subjects=Subjects({"Матан": "Матан"}),
        open_sheet=lambda worksheet: active_sheet,
        store=store,
        clock=Clock(now),
        flush_delay=0,
        retry_base_delay=0,
        sleep=sleeper or TestSleeper(),
    )
    return session, bot, active_sheet, store


def test_format_pair_message():
    pair = current_pair(datetime(2026, 10, 7, 12, 30, tzinfo=MSK), ENDS)
    assert pair is not None
    text = format_pair_message("Матан", pair)
    assert "Матан" in text
    assert "3 пара" in text
    assert "13:15" in text


async def test_start_posts_message_with_button(tmp_path: Path):
    session, bot, sheet, store = build(tmp_path)
    assert await session.start("Матан") is StartResult.STARTED
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == -100
    markup = bot.sent[0]["kwargs"]["reply_markup"]
    assert markup.inline_keyboard[0][0].text == "Отметиться"
    assert store.load() is not None


async def test_start_creates_today_column(tmp_path: Path):
    session, _, sheet, _ = build(tmp_path)
    await session.start("Матан")
    assert sheet.dates == [date(2026, 10, 7)]


async def test_start_unknown_subject(tmp_path: Path):
    session, bot, _, store = build(tmp_path)
    assert await session.start("Философия") is StartResult.UNKNOWN_SUBJECT
    assert bot.sent == []
    assert store.load() is None


async def test_start_after_last_pair(tmp_path: Path):
    session, bot, _, _ = build(tmp_path, now=datetime(2026, 10, 7, 15, 0, tzinfo=MSK))
    assert await session.start("Матан") is StartResult.DAY_OVER
    assert bot.sent == []


async def test_start_exactly_at_end_time_is_day_over(tmp_path: Path):
    session, bot, _, _ = build(tmp_path, now=datetime(2026, 10, 7, 13, 15, tzinfo=MSK))
    assert await session.start("Матан") is StartResult.DAY_OVER
    assert bot.sent == []


async def test_start_reports_sheet_error(tmp_path: Path):
    from services.sheets import SheetError

    session, bot, _, store = build(tmp_path)
    session._open_sheet = lambda worksheet: _broken_sheet()
    assert await session.start("Матан") is StartResult.SHEET_ERROR
    assert bot.sent == []
    assert store.load() is None


def _broken_sheet() -> FakeSubjectSheet:
    sheet = FakeSubjectSheet(students=STUDENTS)

    def boom(day: date) -> int:
        raise SheetError("нет вкладки")

    sheet.ensure_date_column = boom  # type: ignore[method-assign]
    return sheet


async def test_close_edits_message_and_clears_state(tmp_path: Path):
    session, bot, _, store = build(tmp_path)
    await session.start("Матан")
    await session.close()
    assert bot.edited[-1]["text"].startswith("Матан — пара закрыта")
    assert store.load() is None
    assert session.close_task is None


async def test_close_without_active_session_is_noop(tmp_path: Path):
    session, bot, _, _ = build(tmp_path)
    await session.close()
    assert bot.edited == []


async def test_close_survives_edit_failure(tmp_path: Path):
    session, bot, _, store = build(tmp_path)
    await session.start("Матан")

    async def boom(**kwargs: object) -> None:
        raise RuntimeError("message is not modified")

    bot.edit_message_text = boom  # type: ignore[method-assign]
    await session.close()
    assert store.load() is None


async def test_starting_new_pair_closes_previous(tmp_path: Path):
    session, bot, _, _ = build(tmp_path)
    await session.start("Матан")
    await session.start("Матан")
    assert len(bot.sent) == 2
    assert len(bot.edited) == 1
    assert bot.edited[0]["message_id"] == 101


async def test_close_task_armed(tmp_path: Path):
    session, _, _, _ = build(tmp_path)
    await session.start("Матан")
    assert session.close_task is not None
    await session.close()


async def test_close_timer_closes_pair(tmp_path: Path):
    sleeper = TestSleeper()
    session, bot, _, store = build(tmp_path, sleeper=sleeper)
    await session.start("Матан")
    assert store.load() is not None

    sleeper.release()
    await session.close_task

    assert store.load() is None
    assert bot.edited[-1]["text"].startswith("Матан — пара закрыта")
```

`test_close_timer_closes_pair` заодно проверяет, что таймер закрытия действительно дожидается `end_at`: `TestSleeper` получает паузу в 45 минут и не отпускает её, пока тест не вызовет `release()`. Если кто-то перепутает знак в `_close_at`, задержка станет нулевой и тест упадёт на `assert store.load() is not None` — пара закроется раньше времени. До этой строки в тесте нет ни одного `await` после `start`, поэтому таймер не успевает выполниться.

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_session_start.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.session'`.

- [ ] **Step 3: Написать `keyboards/attendance.py` и обновить `keyboards/__init__.py`**

`keyboards/attendance.py`:

```python
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CHECKIN_CALLBACK_PREFIX = "att:"


def checkin_kb(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отметиться", callback_data=f"{CHECKIN_CALLBACK_PREFIX}{token}")],
        ]
    )
```

`keyboards/__init__.py` (старый `main_kb` больше не нужен, `keyboards/base.py` удаляется):

```python
from .attendance import CHECKIN_CALLBACK_PREFIX, checkin_kb

__all__ = ["CHECKIN_CALLBACK_PREFIX", "checkin_kb"]
```

```bash
git rm keyboards/base.py
```

- [ ] **Step 4: Написать `services/session.py`**

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from typing import Awaitable, Callable, Sequence
from uuid import uuid4

from aiogram import Bot

from core.log import logger
from keyboards import checkin_kb
from services.schedule import CurrentPair, current_pair
from services.sheets import SheetError, SheetTransientError, SubjectSheet
from services.state import StateStore, StoredSession
from services.students import StudentDirectory
from services.subjects import Subjects
from utils.names import normalize_name
from utils.retry import call_with_retry


class StartResult(Enum):
    STARTED = "started"
    DAY_OVER = "day_over"
    UNKNOWN_SUBJECT = "unknown_subject"
    SHEET_ERROR = "sheet_error"


class CheckinResult(Enum):
    MARKED = "marked"
    ALREADY = "already"
    NO_SESSION = "no_session"
    NOT_IN_GROUP = "not_in_group"
    NOT_IN_SHEET = "not_in_sheet"


def format_pair_message(subject: str, pair: CurrentPair) -> str:
    return (
        f"📚 Сейчас идёт: {subject} ({pair.number} пара, до {pair.end_at:%H:%M})\n"
        "Отметься, если присутствуешь."
    )


def _closed_message(active: "_Active") -> str:
    total = len(active.rows)
    marked = len(set(active.marked_rows.values()) | active.sheet_marked_rows)
    return f"{active.subject} — пара закрыта, отметились {marked} из {total}"


@dataclass
class _Active:
    token: str
    subject: str
    worksheet: str
    sheet: SubjectSheet
    day: date
    pair_number: int
    end_at: datetime
    message_id: int
    column: int
    rows: dict[str, int]
    sheet_marked_rows: set[int]
    marked_rows: dict[int, int] = field(default_factory=dict)
    pending: list[tuple[int, int]] = field(default_factory=list)

    def to_stored(self) -> StoredSession:
        return StoredSession(
            token=self.token,
            subject=self.subject,
            worksheet=self.worksheet,
            message_id=self.message_id,
            day=self.day,
            pair_number=self.pair_number,
            end_at=self.end_at,
            marked_rows=dict(self.marked_rows),
            pending=tuple(self.pending),
        )


class CheckinSession:
    """Активная пара: сообщение в беседе, буфер отметок, таймеры."""

    def __init__(
        self,
        *,
        bot: Bot,
        chat_id: int,
        pair_end_times: Sequence[time],
        directory: StudentDirectory,
        subjects: Subjects,
        open_sheet: Callable[[str], SubjectSheet],
        store: StateStore,
        clock: Callable[[], datetime],
        report: Callable[[str], Awaitable[None]] | None = None,
        flush_delay: float = 2.0,
        flush_size: int = 20,
        retry_base_delay: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._pair_end_times = tuple(pair_end_times)
        self._directory = directory
        self._subjects = subjects
        self._open_sheet = open_sheet
        self._store = store
        self._clock = clock
        self._report_hook = report
        self._flush_delay = flush_delay
        self._flush_size = flush_size
        self._retry_base_delay = retry_base_delay
        self._sleep = sleep
        self._active: _Active | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def chat_id(self) -> int:
        return self._chat_id

    @property
    def close_task(self) -> "asyncio.Task[None] | None":
        return self._close_task

    @property
    def active_subject(self) -> str | None:
        return self._active.subject if self._active else None

    @property
    def marked_count(self) -> int:
        if self._active is None:
            return 0
        return len(set(self._active.marked_rows.values()) | self._active.sheet_marked_rows)

    async def start(self, subject_title: str) -> StartResult:
        worksheet = self._subjects.worksheet_of(subject_title)
        if worksheet is None:
            logger.warning("Неизвестный предмет: %r", subject_title)
            return StartResult.UNKNOWN_SUBJECT

        pair = current_pair(self._clock(), self._pair_end_times)
        if pair is None:
            return StartResult.DAY_OVER

        async with self._lock:
            previous = self._detach_active()
            if previous is not None:
                await self._finish(previous)

            try:
                sheet = self._open_sheet(worksheet)
                column = await asyncio.to_thread(sheet.ensure_date_column, pair.end_at.date())
                rows = await asyncio.to_thread(sheet.student_rows)
                already = await asyncio.to_thread(sheet.marked_rows, column)
            except SheetError as exc:
                logger.exception("Не удалось подготовить вкладку %r", worksheet)
                await self._report(f"⚠️ Не смог открыть вкладку «{worksheet}»: {exc}")
                return StartResult.SHEET_ERROR

            token = uuid4().hex[:12]
            message = await self._bot.send_message(
                self._chat_id,
                format_pair_message(subject_title, pair),
                reply_markup=checkin_kb(token),
            )

            self._active = _Active(
                token=token,
                subject=subject_title,
                worksheet=worksheet,
                sheet=sheet,
                day=pair.end_at.date(),
                pair_number=pair.number,
                end_at=pair.end_at,
                message_id=message.message_id,
                column=column,
                rows=rows,
                sheet_marked_rows=already,
            )
            self._store.save(self._active.to_stored())
            self._arm_close(pair.end_at)

        logger.info(
            "Пара %s (%s, до %s) открыта, студентов в листе: %d",
            subject_title,
            pair.number,
            pair.end_at,
            len(rows),
        )
        return StartResult.STARTED

    async def close(self) -> None:
        async with self._lock:
            active = self._detach_active()
            if active is None:
                return
            await self._finish(active)
        logger.info("Пара %s закрыта", active.subject)

    def _detach_active(self) -> "_Active | None":
        """Снять активную пару и погасить её таймеры. Вызывать под self._lock."""
        active = self._active
        if active is None:
            return None
        self._active = None

        self._cancel_flush()
        task = self._close_task
        self._close_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        return active

    async def _finish(self, active: _Active) -> None:
        """Дописать буфер, объявить итог в беседе, отчитаться админу. Вызывать под self._lock."""
        await self._flush(active)
        await self._announce_closed(active)
        await self._report_summary(active)
        self._store.clear()

    async def restore(self) -> None:
        stored = self._store.load()
        if stored is None:
            return

        try:
            sheet = self._open_sheet(stored.worksheet)
            column = await asyncio.to_thread(sheet.ensure_date_column, stored.day)
            rows = await asyncio.to_thread(sheet.student_rows)
            already = await asyncio.to_thread(sheet.marked_rows, column)
        except SheetError as exc:
            logger.exception("Не удалось восстановить пару %r", stored.subject)
            await self._report(f"⚠️ Не смог восстановить пару «{stored.subject}»: {exc}")
            self._store.clear()
            return

        self._active = _Active(
            token=stored.token,
            subject=stored.subject,
            worksheet=stored.worksheet,
            sheet=sheet,
            day=stored.day,
            pair_number=stored.pair_number,
            end_at=stored.end_at,
            message_id=stored.message_id,
            column=column,
            rows=rows,
            sheet_marked_rows=already,
            marked_rows=dict(stored.marked_rows),
            pending=list(stored.pending),
        )
        logger.info("Восстановил пару %s до %s", stored.subject, stored.end_at)

        if stored.end_at <= self._clock():
            await self.close()
        else:
            self._arm_close(stored.end_at)

    def _arm_close(self, end_at: datetime) -> None:
        self._close_task = asyncio.create_task(self._close_at(end_at))

    async def _close_at(self, end_at: datetime) -> None:
        delay = max((end_at - self._clock()).total_seconds(), 0.0)
        await self._sleep(delay)
        await self.close()

    async def _announce_closed(self, active: _Active) -> None:
        try:
            await self._bot.edit_message_text(
                _closed_message(active),
                chat_id=self._chat_id,
                message_id=active.message_id,
            )
        except Exception:
            logger.exception("Не удалось отредактировать сообщение о закрытии пары %s", active.subject)

    async def _report(self, text: str) -> None:
        """Сообщение админам в ЛС; вызывается только из хендлеров сессии."""
        if self._report_hook is None:
            logger.info("Отчёт админам: %s", text)
            return
        await self._report_hook(text)
```

Дальше в этом же файле — остальные методы `CheckinSession`: `_arm_close`, `_close_at`, `_announce_closed`, `_report`, `_report_summary`, `_flush`, `_schedule_flush`, `_cancel_flush`, `_flush_later`. `handle_checkin` допишет Task 11.

`_report_summary` — отчёт админу после закрытия пары. В отчёт попадают только те студенты справочника, чьи ФИО нашлись в листе:

```python
    async def _report_summary(self, active: _Active) -> None:
        marked_rows = set(active.marked_rows.values()) | active.sheet_marked_rows
        present = [
            name
            for name in self._directory.all_names()
            if (row := active.rows.get(normalize_name(name))) is not None and row in marked_rows
        ]
        missing = [
            name
            for name in self._directory.all_names()
            if (row := active.rows.get(normalize_name(name))) is not None and row not in marked_rows
        ]
        lines = [
            f"📊 {active.subject} ({active.pair_number} пара), {active.day:%d.%m.%Y}",
            f"Отметились {len(present)} из {len(present) + len(missing)}",
        ]
        lines += [f"• {name}" for name in present]
        if missing:
            lines.append("Не отметились:")
            lines += [f"• {name}" for name in missing]
        await self._report("\n".join(lines))
```

Буфер отметок: `_flush` пишет пачку одним вызовом, при временной ошибке возвращает отметки в буфер, чтобы их подхватила следующая попытка:

```python
    async def _flush(self, active: _Active) -> None:
        if not active.pending:
            return
        batch = active.pending
        active.pending = []
        try:
            await call_with_retry(
                active.sheet.write_marks,
                batch,
                retry_on=(SheetTransientError,),
                base_delay=self._retry_base_delay,
            )
        except SheetError as exc:
            logger.exception("Не удалось записать отметки (%s)", active.subject)
            active.pending = batch + active.pending
            await self._report(f"⚠️ Отметки по «{active.subject}» не записались: {exc}")

    def _cancel_flush(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            self._flush_task = None

    def _schedule_flush(self) -> None:
        self._cancel_flush()
        self._flush_task = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        # Только под локом: иначе таймер и handle_checkin полезут в pending разом.
        current = asyncio.current_task()
        try:
            await self._sleep(self._flush_delay)
            async with self._lock:
                active = self._active
                if active is not None:
                    await self._flush(active)
        finally:
            if self._flush_task is current:
                self._flush_task = None
```

`handle_checkin` добавит Task 11; в Task 10 он ещё не нужен, но `CheckinResult` уже объявлен.

- [ ] **Step 5: Запустить тесты**

Run: `uv run pytest tests/test_session_start.py -v`
Expected: PASS, 13 passed.

- [ ] **Step 6: Коммит**

```bash
git add keyboards/ services/session.py tests/fakes.py tests/test_session_start.py
git commit -m "feat: сессия пары — запуск, буфер и закрытие"
```

---

### Task 11: Сессия — отметки и идемпотентность

**Files:**
- Modify: `services/session.py`
- Test: `tests/test_session_checkin.py`

**Interfaces:**
- Consumes: `CheckinSession` из Task 10.
- Produces: `CheckinSession.handle_checkin(tg_id: int, token: str) -> CheckinResult`; буфер сбрасывается по таймеру `flush_delay` или при накоплении `flush_size` отметок; `CheckinSession.flush_now() -> None` — принудительный сброс (им же пользуется таймер).

- [ ] **Step 1: Написать падающий тест**

`tests/test_session_checkin.py`:

```python
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from services.session import CheckinResult
from tests.fakes import FakeSubjectSheet
from tests.test_session_start import ENDS, MSK, build

IVAN = 111
PETR = 222
STRANGER = 999

NOW = datetime(2026, 10, 7, 12, 30, tzinfo=MSK)


async def _started(tmp_path: Path, sheet: FakeSubjectSheet | None = None):
    session, bot, active_sheet, store = build(tmp_path, now=NOW, sheet=sheet)
    await session.start("Матан")
    token = session._active.token
    return session, bot, active_sheet, store, token


async def test_marks_and_writes_to_sheet(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.MARKED
    await session.flush_now()
    assert sheet.written == [(2, 2)]


async def test_second_press_is_idempotent(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.ALREADY
    await session.flush_now()
    assert sheet.written == [(2, 2)]


async def test_mark_already_present_in_sheet(tmp_path: Path):
    sheet = FakeSubjectSheet(students=["Иванов Иван", "Петров Пётр"], cells={(2, 2): "+"})
    session, _, _, _, token = await _started(tmp_path, sheet=sheet)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.ALREADY


async def test_unknown_student(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    assert await session.handle_checkin(STRANGER, token) is CheckinResult.NOT_IN_GROUP
    await session.flush_now()
    assert sheet.written == []


async def test_student_missing_from_sheet(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path, sheet=FakeSubjectSheet(students=["Петров Пётр"]))
    assert await session.handle_checkin(IVAN, token) is CheckinResult.NOT_IN_SHEET
    await session.flush_now()
    assert sheet.written == []


async def test_wrong_token(tmp_path: Path):
    session, _, _, _, _ = await _started(tmp_path)
    assert await session.handle_checkin(IVAN, "чужой") is CheckinResult.NO_SESSION


async def test_without_active_pair(tmp_path: Path):
    session, _, _, _, token = await _started(tmp_path)
    await session.close()
    assert await session.handle_checkin(IVAN, token) is CheckinResult.NO_SESSION


async def test_after_end_time(tmp_path: Path):
    session, _, _, _, token = await _started(tmp_path)
    session._clock.moment = datetime(2026, 10, 7, 13, 16, tzinfo=MSK)
    assert await session.handle_checkin(IVAN, token) is CheckinResult.NO_SESSION


async def test_buffer_flushes_after_delay(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    assert sheet.written == []
    await asyncio.wait_for(_drain(session), timeout=1)
    assert sheet.written == [(2, 2)]


async def _drain(session) -> None:
    while session._flush_task is not None:
        await asyncio.sleep(0)


async def test_transient_failure_keeps_marks_for_retry(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    sheet.fail_next_writes = 3  # три попытки call_with_retry израсходованы
    await session.handle_checkin(IVAN, token)
    await session.flush_now()
    assert sheet.written == []
    assert session._active.pending == [(2, 2)]

async def test_close_flushes_pending_marks(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    await session.close()
    assert sheet.written == [(2, 2)]


async def test_close_sends_summary_to_admins(tmp_path: Path):
    reports: list[str] = []

    async def report(text: str) -> None:
        reports.append(text)

    session, _, _, _, token = await _started(tmp_path)
    session._report_hook = report
    await session.handle_checkin(IVAN, token)
    await session.close()
    assert len(reports) == 1
    assert "Иванов Иван" in reports[0]
    assert "Петров Пётр" in reports[0]
    assert "Не отметились" in reports[0]


async def test_state_updated_on_each_mark(tmp_path: Path):
    session, _, _, store, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    stored = store.load()
    assert stored is not None
    assert stored.marked_rows == {IVAN: 2}


async def test_flush_size_forces_write(tmp_path: Path):
    session, _, sheet, _, token = await _started(tmp_path)
    session._flush_size = 2
    await session.handle_checkin(IVAN, token)
    await session.handle_checkin(PETR, token)
    await asyncio.wait_for(_drain(session), timeout=1)
    assert sorted(sheet.written) == [(2, 2), (3, 2)]


async def test_restore_keeps_marks_after_restart(tmp_path: Path):
    session, _, sheet, store, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    await session.flush_now()

    revived, bot2, sheet2, store2 = build(tmp_path, now=NOW, sheet=sheet)
    revived._report_hook = session._report_hook
    await revived.restore()
    assert revived.active_subject == "Матан"
    assert await revived.handle_checkin(IVAN, token) is CheckinResult.ALREADY
    await revived.close()


async def test_restore_of_finished_pair_closes_it(tmp_path: Path):
    session, _, sheet, store, token = await _started(tmp_path)
    await session.handle_checkin(IVAN, token)
    await session._flush(session._active)

    later = NOW + timedelta(hours=2)
    revived, bot2, _, store2 = build(tmp_path, now=later, sheet=sheet)
    await revived.restore()
    assert store2.load() is None
    assert bot2.edited[-1]["text"].startswith("Матан — пара закрыта")
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_session_checkin.py -v`
Expected: FAIL — `AttributeError: 'CheckinSession' object has no attribute 'handle_checkin'`.

- [ ] **Step 3: Реализовать `handle_checkin`, `flush_now` и сброс по размеру**

Добавить в `services/session.py`:

```python
    async def handle_checkin(self, tg_id: int, token: str) -> CheckinResult:
        async with self._lock:
            active = self._active
            if active is None or active.token != token or self._clock() >= active.end_at:
                return CheckinResult.NO_SESSION

            name = self._directory.name_of(tg_id)
            if name is None:
                return CheckinResult.NOT_IN_GROUP

            row = active.rows.get(normalize_name(name))
            if row is None:
                logger.warning("Студент %s (id %s) не найден в листе %r", name, tg_id, active.worksheet)
                await self._report(
                    f"⚠️ {name} (id {tg_id}) жмёт «Отметиться», но его нет в листе "
                    f"«{active.worksheet}». Отметка не поставлена."
                )
                return CheckinResult.NOT_IN_SHEET

            already = row in active.sheet_marked_rows or row in set(active.marked_rows.values())
            if already:
                return CheckinResult.ALREADY

            active.marked_rows[tg_id] = row
            active.pending.append((row, active.column))
            self._store.save(active.to_stored())

            if len(active.pending) >= self._flush_size:
                self._cancel_flush()
                await self._flush(active)
            else:
                self._schedule_flush()

            return CheckinResult.MARKED

    async def flush_now(self) -> None:
        async with self._lock:
            active = self._active
            if active is None:
                return
            self._cancel_flush()
            await self._flush(active)
```

`_flush_later` уже написан в Task 10 — в нём уже есть и лок, и защита `finally` от затирания ссылки на свежую задачу. Здесь его трогать не нужно, только `handle_checkin` и `flush_now` ниже. Перед сбросом по размеру буфера таймер отменяется, иначе он проснётся уже после записи.

`_report` из Task 10 уже умеет звать хук. Поле `_report_hook` — из конструктора.

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_session_checkin.py -v`
Expected: PASS, 16 passed.

- [ ] **Step 5: Прогнать весь набор**

Run: `uv run pytest -v`
Expected: PASS, все тесты.

- [ ] **Step 6: Коммит**

```bash
git add services/session.py tests/test_session_checkin.py
git commit -m "feat: отметки, буфер и отчёт по паре"
```

---

### Task 12: Хендлеры, сборка графа и запуск

**Files:**
- Delete: `handlers/echo.py`, `handlers/base.py`
- Create: `handlers/admin.py`, `handlers/attendance.py`, `keyboards/admin.py`
- Modify: `handlers/__init__.py`, `keyboards/__init__.py`, `core/bootstrap.py`, `run.py`
- Test: `tests/test_handlers.py`

**Interfaces:**
- Consumes: `CheckinSession`, `StartResult`, `CheckinResult`, `Subjects`, `Settings`.
- Produces:
  - `keyboards.admin.subjects_kb(titles: Sequence[str]) -> InlineKeyboardMarkup` — по кнопке на предмет, `callback_data=f"subject:{index}"` (индекс, а не название: у `callback_data` лимит 64 байта, кириллица ест по два); `SUBJECT_CALLBACK_PREFIX = "subject:"`.
  - `handlers.admin.build_admin_router(*, session, subjects, admin_ids) -> Router` — `/start` в ЛС + обработка `subject:<index>`; `START_REPLIES: dict[StartResult, str]`, `start_should_alert(result) -> bool`.
  - `handlers.attendance.build_attendance_router(*, session) -> Router` — обработка `att:<token>` с отсечением нажатий не из `session.chat_id`; `CHECKIN_REPLIES: dict[CheckinResult, str]`.
  - `handlers.get_main_router(session, subjects, admin_ids) -> Router`.
  - `core.bootstrap.build_session(settings, bot) -> CheckinSession`.

- [ ] **Step 1: Написать падающий тест**

`tests/test_handlers.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from handlers import get_main_router
from handlers.attendance import CHECKIN_REPLIES, build_attendance_router
from handlers.admin import START_REPLIES, build_admin_router
from keyboards.admin import subjects_kb
from services.session import CheckinResult, StartResult
from services.subjects import Subjects

ADMIN = 111

SUBJECTS = Subjects({"Матан": "Матан", "Физика": "Физика"})


def _router(*, start=StartResult.STARTED, checkin=CheckinResult.MARKED):
    session = SimpleNamespace(
        start=AsyncMock(return_value=start),
        handle_checkin=AsyncMock(return_value=checkin),
    )
    return session


def test_get_main_router_registers_two_routers():
    router = get_main_router(_router(), SUBJECTS, frozenset({ADMIN}))
    assert len(router.sub_routers) == 2


def test_subjects_kb_uses_index_in_callback():
    markup = subjects_kb(SUBJECTS.titles())
    assert markup.inline_keyboard[0][0].text == "Матан"
    assert markup.inline_keyboard[0][0].callback_data == "subject:0"
    assert markup.inline_keyboard[1][0].callback_data == "subject:1"


def test_all_results_have_text():
    for result in StartResult:
        assert START_REPLIES[result]
    for result in CheckinResult:
        assert CHECKIN_REPLIES[result]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (StartResult.DAY_OVER, True),
        (StartResult.SHEET_ERROR, True),
        (StartResult.UNKNOWN_SUBJECT, True),
        (StartResult.STARTED, False),
    ],
)
def test_start_reply_alert_flag(result, expected):
    from handlers.admin import start_should_alert

    assert start_should_alert(result) is expected


def test_admin_router_is_built():
    assert build_admin_router(
        session=_router(), subjects=SUBJECTS, admin_ids=frozenset({ADMIN})
    ) is not None


def test_attendance_router_is_built():
    assert build_attendance_router(session=_router()) is not None
```

Строка `assert [button.text for button in markup.inline_keyboard[0]] == []` лишняя и неверна — удалить её; проверки ниже покрывают то же самое.

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'handlers.admin'`.

- [ ] **Step 3: Написать `keyboards/admin.py`**

```python
from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

SUBJECT_CALLBACK_PREFIX = "subject:"


def subjects_kb(titles: Sequence[str]) -> InlineKeyboardMarkup:
    # Индекс, а не название: в callback_data умещается 64 байта, кириллица — по два на символ.
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=title, callback_data=f"{SUBJECT_CALLBACK_PREFIX}{index}")]
            for index, title in enumerate(titles)
        ]
    )
```

`keyboards/__init__.py`:

```python
from .admin import SUBJECT_CALLBACK_PREFIX, subjects_kb
from .attendance import CHECKIN_CALLBACK_PREFIX, checkin_kb

__all__ = [
    "CHECKIN_CALLBACK_PREFIX",
    "SUBJECT_CALLBACK_PREFIX",
    "checkin_kb",
    "subjects_kb",
]
```

- [ ] **Step 4: Написать `handlers/admin.py`**

```python
from aiogram import F, Router, types
from aiogram.enums import ChatType
from aiogram.filters import CommandStart

from core.log import logger
from keyboards import subjects_kb
from services.session import CheckinSession, StartResult
from services.subjects import Subjects

START_REPLIES: dict[StartResult, str] = {
    StartResult.STARTED: "Пара открыта, сообщение ушло в беседу.",
    StartResult.DAY_OVER: "Пары на сегодня закончились.",
    StartResult.UNKNOWN_SUBJECT: "Такого предмета нет в справочнике.",
    StartResult.SHEET_ERROR: "Не смог открыть вкладку в таблице, подробности выше.",
}


def start_should_alert(result: StartResult) -> bool:
    return result is not StartResult.STARTED


def build_admin_router(
    *, session: CheckinSession, subjects: Subjects, admin_ids: frozenset[int]
) -> Router:
    router = Router(name="admin")

    @router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
    async def cmd_start(message: types.Message) -> None:
        user = message.from_user
        if user is None or user.id not in admin_ids:
            logger.warning("Посторонний стартует бота: %s", user.id if user else "unknown")
            return
        await message.answer("Выбери предмет текущей пары:", reply_markup=subjects_kb(subjects.titles()))

    @router.callback_query(F.data.startswith("subject:"))
    async def process_subject(callback: types.CallbackQuery) -> None:
        user = callback.from_user
        if user.id not in admin_ids:
            await callback.answer("Нет доступа", show_alert=True)
            return

        raw_index = (callback.data or "").split(":", 1)[1]
        title = subjects.title_at(int(raw_index)) if raw_index.isdigit() else None
        if title is None:
            await callback.answer("Предмет не найден", show_alert=True)
            return

        result = await session.start(title)
        await callback.answer(START_REPLIES[result], show_alert=start_should_alert(result))

    return router
```

- [ ] **Step 5: Написать `handlers/attendance.py`**

```python
from aiogram import F, Router, types

from services.session import CheckinResult, CheckinSession

CHECKIN_REPLIES: dict[CheckinResult, str] = {
    CheckinResult.MARKED: "Отмечен ✅",
    CheckinResult.ALREADY: "Ты уже отмечен",
    CheckinResult.NO_SESSION: "Эта пара уже закончилась",
    CheckinResult.NOT_IN_GROUP: "Тебя нет в списке группы",
    CheckinResult.NOT_IN_SHEET: "Не нашёл тебя в таблице, написал админу",
}


def build_attendance_router(*, session: CheckinSession) -> Router:
    router = Router(name="attendance")

    @router.callback_query(F.data.startswith("att:"))
    async def process_checkin(callback: types.CallbackQuery) -> None:
        # Нажатия из чужих чатов игнорируем: кнопка живёт только в беседе группы.
        if callback.message is None or callback.message.chat.id != session.chat_id:
            await callback.answer()
            return

        token = (callback.data or "").split(":", 1)[1]
        result = await session.handle_checkin(callback.from_user.id, token)
        await callback.answer(CHECKIN_REPLIES[result], show_alert=result is CheckinResult.NOT_IN_SHEET)

    return router
```

`CheckinResult.MARKED` отвечает без `show_alert` — всплывающее уведомление в Telegram и так видно.

- [ ] **Step 6: Переписать `handlers/__init__.py`, удалить старые хендлеры**

```bash
git rm handlers/echo.py handlers/base.py
```

`handlers/__init__.py`:

```python
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
```

- [ ] **Step 7: Написать `core/bootstrap.py`**

`build_context` собирает весь граф объектов и отдаёт его наружу: роутеру нужны и сессия, и справочник предметов, и id админов.

```python
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
```

- [ ] **Step 8: Переписать `run.py`**

`run.py` целиком:

```python
import asyncio

from aiogram.types import BotCommand

from core.app import bot, dp, logger
from core.bootstrap import build_context
from core.config import load_settings
from handlers import get_main_router


async def main() -> None:
    settings = load_settings()
    context = build_context(settings, bot)

    dp.include_router(get_main_router(context.session, context.subjects, context.admin_ids))
    await bot.set_my_commands(
        [BotCommand(command="start", description="Выбрать предмет текущей пары")]
    )

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot started")

    await context.session.restore()
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
```


- [ ] **Step 9: Запустить тесты**

Run: `uv run pytest -v`
Expected: PASS, все тесты.

- [ ] **Step 10: Коммит**

```bash
git add handlers/ keyboards/ core/bootstrap.py run.py tests/test_handlers.py
git commit -m "feat: хендлеры админа и отметок, сборка приложения"
```

---

### Task 13: Примеры справочников, Docker и README

**Files:**
- Create: `data/students.json`, `data/subjects.json`
- Modify: `.gitignore`, `docker-compose.yml`, `.dockerignore`, `README.md`
- Test: `tests/test_data_files.py`

**Interfaces:**
- Consumes: `StudentDirectory.load`, `Subjects.load`.
- Produces: файлы-примеры, читаемые загрузчиками; volume для `credentials.json` и `data/`.

- [ ] **Step 1: Написать падающий тест**

`tests/test_data_files.py`:

```python
from pathlib import Path

from services.students import StudentDirectory
from services.subjects import Subjects

ROOT = Path(__file__).resolve().parent.parent


def test_students_example_is_loadable():
    directory = StudentDirectory.load(ROOT / "data" / "students.json")
    assert directory.all_names()


def test_subjects_example_is_loadable():
    subjects = Subjects.load(ROOT / "data" / "subjects.json")
    assert subjects.titles()
    assert subjects.worksheet_of(subjects.titles()[0])
```

- [ ] **Step 2: Запустить тесты — должны упасть**

Run: `uv run pytest tests/test_data_files.py -v`
Expected: FAIL — `ConfigError: Справочник студентов не найден`.

- [ ] **Step 3: Создать справочники-заготовки**

`data/students.json` (заменить на реальный маппинг):

```json
{
  "111111111": "Иванов Иван Иванович",
  "222222222": "Петров Пётр Петрович"
}
```

`data/subjects.json` (название кнопки → имя вкладки в таблице):

```json
{
  "Матан": "Матан",
  "Физика": "Физика"
}
```

- [ ] **Step 4: Запустить тесты**

Run: `uv run pytest tests/test_data_files.py -v`
Expected: PASS, 2 passed.

- [ ] **Step 5: Закрыть секреты и состояние в `.gitignore`**

Дописать в `.gitignore`:

```
credentials.json
data/state.json
```

- [ ] **Step 6: Пробросить volume в docker-compose**

`docker-compose.yml`, сервис `bot` — добавить:

```yaml
    volumes:
      - ./credentials.json:/app/credentials.json:ro
      - ./data:/app/data
```

В `docker-compose.DEV.yml` volume `.:/app` уже покрывает оба пути, менять не нужно. В `.dockerignore` добавить `credentials.json` и `data/state.json`, чтобы ключ и рантайм-состояние не попадали в образ.

- [ ] **Step 7: Дописать README**

```markdown
# checkinzzz_bot

Бот отметки посещения пар. Живёт в беседе группы: админ запускает текущую пару
из личных сообщений, студенты жмут «Отметиться», плюсы уезжают в Google-таблицу.
Пара закрывается сама по времени окончания.

## Настройка

1. Создать `.env` по `.env.example`.
2. Google Cloud: включить **Google Sheets API** и **Google Drive API**, создать
   сервисный аккаунт, скачать JSON-ключ в `credentials.json` в корне проекта.
3. Расшарить таблицу посещаемости на `client_email` сервисного аккаунта с
   правами **Editor**. Если этого не сделать, бот напишет
   «Таблица не найдена» — это самая частая ошибка настройки.
4. В таблице завести вкладку на каждый предмет; в колонке A — ФИО студентов,
   первая строка — шапка с датами. Столбец на сегодняшний день бот создаст сам.
5. Заполнить `data/students.json` (`tg_id`: ФИО) и `data/subjects.json`
   (название кнопки: имя вкладки). ФИО должны совпадать с колонкой A таблицы;
   регистр, лишние пробелы и «ё» бот прощает.
6. Админ пишет боту в личку `/start` и выбирает предмет.

## Запуск

- Локально

```bash
uv sync
uv run --env-file .env run.py
```

- Docker (hot reload):

```bash
docker compose -f docker-compose.DEV.yml up --build
```

- Docker (prod):

```bash
docker compose up --build -d
```

## Тесты

```bash
uv run pytest
```
```

- [ ] **Step 8: Прогнать весь набор и проверить запуск**

Run: `uv run pytest -v`
Expected: PASS, все тесты.

Run: `uv run python -c "from core.config import load_settings; print('import ok')"`
Expected: `import ok` (конфиг без env не читается, но модуль импортируется).

- [ ] **Step 9: Коммит**

```bash
git add data/ .gitignore .dockerignore docker-compose.yml README.md tests/test_data_files.py
git commit -m "chore: справочники-заготовки, volume для ключа и README"
```

---

## Что остаётся заказчику

Перед первым боевым запуском нужны данные, которых нет в репозитории:

- `PAIR_END_TIMES` — времена окончания пар;
- `ADMIN_IDS` — id админов, `CHAT_ID` — id беседы;
- `SPREADSHEET_ID` — id таблицы посещаемости;
- `credentials.json` — ключ сервисного аккаунта, расшаренная таблица;
- `data/students.json` — реальный маппинг tg_id → ФИО;
- сверка ФИО в колонке A таблицы со справочником (иначе бот напишет админу, что не нашёл студента).

Ручная проверка после этого: тестовая таблица + тестовый токен, прогон
«админ запустил пару → студент отметился → наступил конец пары → плюс в таблице,
итог в беседе, отчёт админу».
