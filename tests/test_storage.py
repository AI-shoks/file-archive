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
