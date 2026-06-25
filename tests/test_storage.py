import pytest

import storage
from storage import ArchiveFileNotFoundError, FileTooLargeError, SubjectNotFoundError


def test_save_file_success(tmp_path):
    """Успешная загрузка: файл записан на диск, содержимое совпадает."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    content = b"test content"

    dest = storage.save_file("Статистика", "report.docx", content, root_dir=tmp_path)

    assert dest.exists()
    assert dest.read_bytes() == content


def test_save_file_at_size_limit_succeeds(tmp_path):
    """Файл РОВНО на лимите (== MAX) сохраняется (ловит '>' vs '>=')."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    content = b"x" * storage.MAX_FILE_SIZE_BYTES

    dest = storage.save_file("Статистика", "report.docx", content, root_dir=tmp_path)

    assert dest.exists()
    assert dest.read_bytes() == content


def test_save_file_duplicate_name_is_renamed(tmp_path):
    """Вторая загрузка того же имени не затирает первую, а сохраняется
    как report(1).docx; третья — report(2).docx."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()

    first = storage.save_file("Статистика", "report.docx", b"v1", root_dir=tmp_path)
    second = storage.save_file("Статистика", "report.docx", b"v2", root_dir=tmp_path)
    third = storage.save_file("Статистика", "report.docx", b"v3", root_dir=tmp_path)

    assert first.name == "report.docx"
    assert second.name == "report(1).docx"
    assert third.name == "report(2).docx"
    # первый файл цел, данные не потеряны
    assert first.read_bytes() == b"v1"
    assert second.read_bytes() == b"v2"
    assert third.read_bytes() == b"v3"


def test_save_file_fills_base_name_when_free(tmp_path):
    """Есть report(1).docx, но базового report.docx нет: загрузка report.docx
    занимает свободное базовое имя, а не плодит report(2).docx."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    (subject_dir / "report(1).docx").write_bytes(b"old")

    dest = storage.save_file("Статистика", "report.docx", b"v1", root_dir=tmp_path)

    assert dest.name == "report.docx"
    assert dest.read_bytes() == b"v1"
    assert (subject_dir / "report(1).docx").read_bytes() == b"old"


def test_save_file_skips_occupied_index(tmp_path):
    """Базовое имя занято, report(1).docx тоже занят: следующая загрузка
    перепрыгивает на первый свободный индекс (report(2).docx)."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    (subject_dir / "report.docx").write_bytes(b"a")
    (subject_dir / "report(1).docx").write_bytes(b"b")

    dest = storage.save_file("Статистика", "report.docx", b"c", root_dir=tmp_path)

    assert dest.name == "report(2).docx"
    assert dest.read_bytes() == b"c"
    # ранее существующие файлы не тронуты
    assert (subject_dir / "report.docx").read_bytes() == b"a"
    assert (subject_dir / "report(1).docx").read_bytes() == b"b"


def test_save_file_invalid_subject(tmp_path):
    """Subject-путь (../x) отклоняется на первой проверке. Папка не нужна."""
    with pytest.raises(ValueError):
        storage.save_file("../x", "report.docx", b"data", root_dir=tmp_path)


def test_save_file_empty_subject(tmp_path):
    """Пустой subject падает на первой проверке (not subject). Папка не нужна."""
    with pytest.raises(ValueError):
        storage.save_file("", "report.docx", b"data", root_dir=tmp_path)


def test_save_file_subject_not_found(tmp_path):
    """Папки-предмета нет -> SubjectNotFoundError. Папку НЕ создаём."""
    with pytest.raises(SubjectNotFoundError):
        storage.save_file("Статистика", "report.docx", b"data", root_dir=tmp_path)


def test_save_file_empty_filename(tmp_path):
    """Пустое имя файла -> ValueError. Проверка после is_dir(), папка нужна."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    with pytest.raises(ValueError):
        storage.save_file("Статистика", "", b"data", root_dir=tmp_path)


def test_save_file_too_large(tmp_path):
    """Файл больше лимита -> FileTooLargeError. Проверка после is_dir(), папка нужна."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    content = b"x" * (storage.MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(FileTooLargeError):
        storage.save_file("Статистика", "report.docx", content, root_dir=tmp_path)


def test_list_subjects_empty_when_no_root(tmp_path):
    """Каталога нет -> пустой список, без ошибки."""
    assert storage.list_subjects(root_dir=tmp_path / "missing") == []


def test_list_subjects_returns_sorted_dirs(tmp_path):
    """Возвращаются только папки, отсортированные; файлы игнорируются."""
    (tmp_path / "Математика").mkdir()
    (tmp_path / "Статистика").mkdir()
    (tmp_path / "не_папка.txt").write_text("x", encoding="utf-8")

    assert storage.list_subjects(root_dir=tmp_path) == ["Математика", "Статистика"]


def test_list_files_returns_sorted_files(tmp_path):
    """Только файлы, отсортированы; подкаталоги игнорируются."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    (subject_dir / "b.docx").write_text("x", encoding="utf-8")
    (subject_dir / "a.pdf").write_text("x", encoding="utf-8")
    (subject_dir / "вложенная").mkdir()

    assert storage.list_files("Статистика", root_dir=tmp_path) == ["a.pdf", "b.docx"]


def test_list_files_empty_subject_dir(tmp_path):
    """Папка предмета есть, но пустая -> пустой список."""
    (tmp_path / "Статистика").mkdir()
    assert storage.list_files("Статистика", root_dir=tmp_path) == []


def test_list_files_subject_not_found(tmp_path):
    """Папки предмета нет -> SubjectNotFoundError."""
    with pytest.raises(SubjectNotFoundError):
        storage.list_files("Статистика", root_dir=tmp_path)


def test_list_files_invalid_subject(tmp_path):
    """Subject-путь отклоняется так же, как в save_file."""
    with pytest.raises(ValueError):
        storage.list_files("../x", root_dir=tmp_path)


def test_get_file_path_success(tmp_path):
    """Существующий файл -> возвращается его путь."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    (subject_dir / "report.docx").write_bytes(b"data")

    path = storage.get_file_path("Статистика", "report.docx", root_dir=tmp_path)
    assert path == subject_dir / "report.docx"
    assert path.read_bytes() == b"data"


def test_get_file_path_subject_not_found(tmp_path):
    with pytest.raises(SubjectNotFoundError):
        storage.get_file_path("Статистика", "report.docx", root_dir=tmp_path)


def test_get_file_path_file_not_found(tmp_path):
    (tmp_path / "Статистика").mkdir()
    with pytest.raises(ArchiveFileNotFoundError):
        storage.get_file_path("Статистика", "missing.docx", root_dir=tmp_path)


def test_get_file_path_invalid_subject(tmp_path):
    with pytest.raises(ValueError):
        storage.get_file_path("../x", "report.docx", root_dir=tmp_path)


def test_get_file_path_traversal_filename_is_neutralized(tmp_path):
    """'../' в имени файла отрезается -> ищется внутри папки предмета
    и не находится (а не читается чужой файл)."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    (tmp_path / "secret.txt").write_bytes(b"secret")  # вне папки предмета

    with pytest.raises(ArchiveFileNotFoundError):
        storage.get_file_path("Статистика", "../secret.txt", root_dir=tmp_path)


def test_search_files_matches_across_subjects(tmp_path):
    """Регистронезависимый поиск подстроки по всем предметам, отсортировано."""
    stat = tmp_path / "Статистика"
    stat.mkdir()
    (stat / "Лекция1.pdf").write_text("x", encoding="utf-8")
    (stat / "домашка.docx").write_text("x", encoding="utf-8")
    math = tmp_path / "Математика"
    math.mkdir()
    (math / "лекция_вводная.pdf").write_text("x", encoding="utf-8")

    results = storage.search_files("лекция", root_dir=tmp_path)

    assert results == [
        {"subject": "Математика", "filename": "лекция_вводная.pdf"},
        {"subject": "Статистика", "filename": "Лекция1.pdf"},
    ]


def test_search_files_no_match(tmp_path):
    (tmp_path / "Статистика").mkdir()
    (tmp_path / "Статистика" / "report.pdf").write_text("x", encoding="utf-8")
    assert storage.search_files("отсутствует", root_dir=tmp_path) == []


def test_search_files_empty_query(tmp_path):
    with pytest.raises(ValueError):
        storage.search_files("   ", root_dir=tmp_path)


def test_search_files_missing_root(tmp_path):
    assert storage.search_files("x", root_dir=tmp_path / "missing") == []


def test_seed_subjects_creates_root_and_folders(tmp_path):
    """seed_subjects создаёт ROOT_DIR (если нет) и папки из списка."""
    root = tmp_path / "data"  # ещё не существует
    created = storage.seed_subjects(["Статистика", "Математика"], root_dir=root)

    assert (root / "Статистика").is_dir()
    assert (root / "Математика").is_dir()
    assert [p.name for p in created] == ["Статистика", "Математика"]


def test_seed_subjects_idempotent(tmp_path):
    """Повторный вызов не падает на уже существующих папках."""
    storage.seed_subjects(["Статистика"], root_dir=tmp_path)
    storage.seed_subjects(["Статистика"], root_dir=tmp_path)  # не должно бросить
    assert (tmp_path / "Статистика").is_dir()


def test_seed_subjects_rejects_path(tmp_path):
    """Недопустимое имя предмета (путь) отклоняется так же, как в save_file."""
    with pytest.raises(ValueError):
        storage.seed_subjects(["../x"], root_dir=tmp_path)


def test_seed_then_save_file_works(tmp_path):
    """После сидирования save_file пишет в созданную папку без 404."""
    storage.seed_subjects(["Статистика"], root_dir=tmp_path)
    dest = storage.save_file("Статистика", "report.docx", b"data", root_dir=tmp_path)
    assert dest.exists()
