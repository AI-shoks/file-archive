import os
from pathlib import Path

# Путь к хранилищу берётся из env (на деплое его задаёт платформа),
# с откатом на локальный путь для разработки.
ROOT_DIR = Path(os.environ.get("FILE_ARCHIVE_ROOT", "C:/Users/artem/file-archive-data"))

# Известное ограничение Слоя 1: проверка идёт по уже прочитанным в память
# байтам (await file.read() в main.py), то есть от самого факта буферизации
# огромного файла в RAM эта проверка не защищает — только не даёт его
# сохранить на диск. Полная защита от OOM требует лимита на уровне
# ASGI-сервера/Render или потокового чтения, что вне скоупа Слоя 1.
MAX_FILE_SIZE_BYTES = 40_000 * 1024


class SubjectNotFoundError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


def save_file(subject: str, filename: str, content: bytes, root_dir: Path = ROOT_DIR) -> Path:
    if not subject or subject != Path(subject).name:
        raise ValueError(f"Недопустимый предмет: {subject}")

    subject_dir = root_dir / subject

    if not subject_dir.is_dir():
        raise SubjectNotFoundError(subject)

    # Path(filename).name отрезает любые "../" и каталоги из присланного
    # имени файла — иначе клиент мог бы указать имя вроде "../../evil.txt"
    # и записать файл вне папки предмета.
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("Имя файла пустое")

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(f"Файл слишком большой (максимум {MAX_FILE_SIZE_BYTES // 1024} КБ)")

    dest = subject_dir / safe_name
    dest.write_bytes(content)
    return dest


def list_subjects(root_dir: Path = ROOT_DIR) -> list[str]:
    """Возвращает отсортированные имена папок-предметов в root_dir.

    Если каталога ещё нет — пустой список (на эфемерном деплое до старта
    сидирования такое возможно).
    """
    if not root_dir.is_dir():
        return []
    return sorted(p.name for p in root_dir.iterdir() if p.is_dir())


def list_files(subject: str, root_dir: Path = ROOT_DIR) -> list[str]:
    """Возвращает отсортированные имена файлов в папке предмета.

    Валидация subject — та же, что в save_file (одно имя папки, не путь).
    Нет папки предмета -> SubjectNotFoundError. Подкаталоги игнорируются.
    """
    if not subject or subject != Path(subject).name:
        raise ValueError(f"Недопустимый предмет: {subject}")

    subject_dir = root_dir / subject
    if not subject_dir.is_dir():
        raise SubjectNotFoundError(subject)

    return sorted(p.name for p in subject_dir.iterdir() if p.is_file())


def seed_subjects(subjects: list[str], root_dir: Path = ROOT_DIR) -> list[Path]:
    """Создаёт ROOT_DIR и перечисленные папки-предметы при старте.

    Нужно для эфемерного деплоя (Render): после редеплоя диск пуст,
    а вручную папки создать негде. Это ОТДЕЛЬНАЯ boot-time операция —
    save_file по-прежнему НЕ создаёт папки сам, скоуп не меняется.
    Список предметов приходит снаружи (env SEED_SUBJECTS), не из кода.
    """
    root_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for subject in subjects:
        # та же проверка, что и в save_file: subject обязан быть одним
        # именем папки, а не путём.
        if not subject or subject != Path(subject).name:
            raise ValueError(f"Недопустимый предмет в SEED_SUBJECTS: {subject}")
        path = root_dir / subject
        path.mkdir(exist_ok=True)
        created.append(path)
    return created
