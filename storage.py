from pathlib import Path

ROOT_DIR = Path("C:/Users/artem/file-archive-data")

# Известное ограничение Слоя 1: проверка идёт по уже прочитанным в память
# байтам (await file.read() в main.py), то есть от самого факта буферизации
# огромного файла в RAM эта проверка не защищает — только не даёт его
# сохранить на диск. Полная защита от OOM требует лимита на уровне
# ASGI-сервера/Render или потокового чтения, что вне скоупа Слоя 1.
MAX_FILE_SIZE_BYTES = 40_000 * 1024


class SubjectNotFoundError(Exception):
    pass


def save_file(subject: str, filename: str, content: bytes) -> Path:
    subject_dir = ROOT_DIR / subject
    resolved_root = ROOT_DIR.resolve()
    resolved_subject_dir = subject_dir.resolve()
    if not resolved_subject_dir.is_relative_to(resolved_root):
        raise ValueError(f"Недопустимый предмет: {subject}")

    if not subject_dir.is_dir():
        raise SubjectNotFoundError(subject)

    # Path(filename).name отрезает любые "../" и каталоги из присланного
    # имени файла — иначе клиент мог бы указать имя вроде "../../evil.txt"
    # и записать файл вне папки предмета.
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("Имя файла пустое")

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"Файл слишком большой (максимум {MAX_FILE_SIZE_BYTES // 1024} КБ)")

    dest = subject_dir / safe_name
    dest.write_bytes(content)
    return dest
