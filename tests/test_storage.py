import pytest

import storage
from storage import SubjectNotFoundError, FileTooLargeError


def test_save_file_success(tmp_path):
    """Успешная загрузка: файл записан на диск, содержимое совпадает."""
    subject_dir = tmp_path / "Статистика"
    subject_dir.mkdir()
    content = b"test content"

    dest = storage.save_file("Статистика", "report.docx", content, root_dir=tmp_path)

    assert dest.exists()
    assert dest.read_bytes() == content


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
