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


class ArchiveFileNotFoundError(Exception):
    pass


def _validate_subject(subject: str, *, context: str = "Недопустимый предмет") -> None:
    """Единственная форма проверки subject (см. CLAUDE.md): subject обязан
    быть ОДНИМ именем папки, а не путём. `subject != Path(subject).name`
    отсекает "../x", "a/b", абсолютные пути — после неё subject физически
    не может выйти за ROOT_DIR. context позволяет менять текст ошибки
    (например, для SEED_SUBJECTS), не размножая саму проверку."""
    if not subject or subject != Path(subject).name:
        raise ValueError(f"{context}: {subject}")


def _safe_filename(filename: str) -> str:
    """Извлекает безопасное имя файла, отрезая любой путь/"../"
    (Path(...).name). Пустой результат -> ValueError. Иначе клиент мог бы
    указать имя вроде "../../evil.txt" и записать/прочитать файл вне папки
    предмета."""
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("Имя файла пустое")
    return safe_name


def _write_unique(subject_dir: Path, safe_name: str, content: bytes) -> Path:
    """Атомарно пишет content под именем, не затирающим существующий файл.

    Перебирает имена safe_name, "stem(1).suffix", "stem(2).suffix", ... и
    для каждого пытается СОЗДАТЬ файл эксклюзивно: open(..., "xb") =
    O_CREAT|O_EXCL. Если имя уже занято — open бросает FileExistsError, и
    мы переходим к следующему кандидату; иначе записываем и возвращаем путь.

    Почему не "проверить exists(), потом write_bytes()": между проверкой и
    записью есть окно (TOCTOU). save_file уводится в пул потоков
    (run_in_threadpool, main.py), поэтому две параллельные заливки одного
    имени реально конкурируют — оба увидели бы имя свободным и одна затёрла
    бы другую (тихая потеря данных). Эксклюзивное создание делает «занять
    имя» и «начать запись» одной атомарной операцией: ровно один поток
    создаёт файл, остальные получают FileExistsError и берут следующее имя.
    """
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    n = 0
    while True:
        name = safe_name if n == 0 else f"{stem}({n}){suffix}"
        candidate = subject_dir / name
        try:
            with open(candidate, "xb") as f:
                f.write(content)
            return candidate
        except FileExistsError:
            n += 1


def save_file(subject: str, filename: str, content: bytes, root_dir: Path = ROOT_DIR) -> Path:
    _validate_subject(subject)

    subject_dir = root_dir / subject

    if not subject_dir.is_dir():
        raise SubjectNotFoundError(subject)

    safe_name = _safe_filename(filename)

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(f"Файл слишком большой (максимум {MAX_FILE_SIZE_BYTES // 1024} КБ)")

    return _write_unique(subject_dir, safe_name, content)


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
    _validate_subject(subject)

    subject_dir = root_dir / subject
    if not subject_dir.is_dir():
        raise SubjectNotFoundError(subject)

    return sorted(p.name for p in subject_dir.iterdir() if p.is_file())


def get_file_path(subject: str, filename: str, root_dir: Path = ROOT_DIR) -> Path:
    """Возвращает путь к существующему файлу предмета для скачивания.

    Проверки — те же, что при загрузке: валидный subject (одно имя папки),
    существующая папка предмета, безопасное имя файла (Path(...).name
    отрезает любой путь/../). Нет папки -> SubjectNotFoundError,
    нет файла -> ArchiveFileNotFoundError.
    """
    _validate_subject(subject)

    subject_dir = root_dir / subject
    if not subject_dir.is_dir():
        raise SubjectNotFoundError(subject)

    safe_name = _safe_filename(filename)

    dest = subject_dir / safe_name
    if not dest.is_file():
        raise ArchiveFileNotFoundError(safe_name)

    return dest


def search_files(query: str, root_dir: Path = ROOT_DIR) -> list[dict[str, str]]:
    """Ищет файлы по подстроке в имени по всем предметам.

    Регистронезависимо. Возвращает список {"subject":..., "filename":...},
    отсортированный по (предмет, файл). Пустой запрос -> ValueError.
    Подкаталоги внутри предметов игнорируются.
    """
    needle = query.strip().lower()
    if not needle:
        raise ValueError("Пустой поисковый запрос")

    if not root_dir.is_dir():
        return []

    results: list[dict[str, str]] = []
    for subject_dir in root_dir.iterdir():
        if not subject_dir.is_dir():
            continue
        for entry in subject_dir.iterdir():
            if entry.is_file() and needle in entry.name.lower():
                results.append({"subject": subject_dir.name, "filename": entry.name})

    results.sort(key=lambda r: (r["subject"], r["filename"]))
    return results


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
        # та же проверка, что и в save_file, с уточнённым текстом ошибки.
        _validate_subject(subject, context="Недопустимый предмет в SEED_SUBJECTS")
        path = root_dir / subject
        path.mkdir(exist_ok=True)
        created.append(path)
    return created
