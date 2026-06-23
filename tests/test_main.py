import functools

import pytest
from fastapi.testclient import TestClient

import storage
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """Подменяет storage-функции на версии с root_dir=tmp_path,
    чтобы main.py не трогал реальный ROOT_DIR."""
    monkeypatch.setattr(storage, "save_file", functools.partial(storage.save_file, root_dir=tmp_path))
    monkeypatch.setattr(storage, "list_subjects", functools.partial(storage.list_subjects, root_dir=tmp_path))
    return tmp_path


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_subjects_endpoint(isolate_storage):
    (isolate_storage / "Статистика").mkdir()
    (isolate_storage / "Математика").mkdir()

    response = client.get("/subjects")

    assert response.status_code == 200
    assert response.json() == {"subjects": ["Математика", "Статистика"]}


def test_upload_file_success(isolate_storage):
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()

    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"test content")},
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "Статистика", "filename": "report.docx"}
    assert (subject_dir / "report.docx").read_bytes() == b"test content"


def test_upload_file_subject_not_found():
    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"data")},
    )

    assert response.status_code == 404


def test_upload_file_invalid_subject():
    response = client.post(
        "/upload/file",
        data={"subject": "../x"},
        files={"file": ("report.docx", b"data")},
    )

    assert response.status_code == 400


def test_upload_file_too_large(isolate_storage):
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()
    content = b"x" * (storage.MAX_FILE_SIZE_BYTES + 1)

    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", content)},
    )

    assert response.status_code == 413


def test_upload_file_response_has_no_absolute_path(isolate_storage):
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()

    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"data")},
    )

    assert str(isolate_storage) not in response.text
