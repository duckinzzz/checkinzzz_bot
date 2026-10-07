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
