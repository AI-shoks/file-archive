import functools

import pytest
from fastapi.testclient import TestClient

import main
import storage
from main import app, parse_subjects

client = TestClient(app)

TEST_UPLOAD_KEY = "test-upload-key"


@pytest.mark.parametrize(
    "seed, expected",
    [
        ("", []),
        ("   ", []),
        (",,", []),
        ("Статистика", ["Статистика"]),
        (" Статистика , Математика ", ["Статистика", "Математика"]),
        ("Статистика,,Математика,", ["Статистика", "Математика"]),
    ],
)
def test_parse_subjects(seed, expected):
    """CSV-разбор SEED_SUBJECTS: пустые элементы и пробелы отбрасываются.
    Именно этот код чуть не сорвал деплой, поэтому покрыт отдельно."""
    assert parse_subjects(seed) == expected


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """Подменяет storage-функции на версии с root_dir=tmp_path,
    чтобы main.py не трогал реальный ROOT_DIR."""
    monkeypatch.setattr(storage, "save_file", functools.partial(storage.save_file, root_dir=tmp_path))
    monkeypatch.setattr(storage, "list_subjects", functools.partial(storage.list_subjects, root_dir=tmp_path))
    monkeypatch.setattr(storage, "list_files", functools.partial(storage.list_files, root_dir=tmp_path))
    monkeypatch.setattr(storage, "get_file_path", functools.partial(storage.get_file_path, root_dir=tmp_path))
    monkeypatch.setattr(storage, "search_files", functools.partial(storage.search_files, root_dir=tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def upload_auth(monkeypatch):
    """По умолчанию для тестов запись СКОНФИГУРИРОВАНА (ключ задан) и клиент
    шлёт верный X-API-Key — чтобы существующие upload-тесты проверяли свою
    логику, а не упирались в 503/401. Также чистит rate-limit между тестами,
    иначе счётчик по IP 'testclient' тёк бы из теста в тест."""
    monkeypatch.setattr(main, "UPLOAD_API_KEY", TEST_UPLOAD_KEY)
    main._upload_hits.clear()
    client.headers["x-api-key"] = TEST_UPLOAD_KEY
    yield
    client.headers.pop("x-api-key", None)
    main._upload_hits.clear()


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_html_is_served():
    """Корень '/' отдаёт статический index.html фронтенда (Слой 2)."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "file-archive" in response.text


def test_static_asset_is_served():
    """Статический ассет (app.js) доступен по своему пути.

    MIME-тип .js зависит от реестра ОС (mimetypes), поэтому проверяем не
    content-type, а что отдано именно тело нашего скрипта."""
    response = client.get("/app.js")
    assert response.status_code == 200
    assert "loadSubjects" in response.text


def test_api_routes_win_over_static_mount():
    """API-роут не перехватывается catch-all монтированием static.
    /health должен остаться JSON-эндпоинтом, а не отдачей файла."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_subjects_endpoint(isolate_storage):
    (isolate_storage / "Статистика").mkdir()
    (isolate_storage / "Математика").mkdir()

    response = client.get("/subjects")

    assert response.status_code == 200
    assert response.json() == {"subjects": ["Математика", "Статистика"]}


def test_list_files_endpoint(isolate_storage):
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()
    (subject_dir / "b.docx").write_text("x", encoding="utf-8")
    (subject_dir / "a.pdf").write_text("x", encoding="utf-8")

    response = client.get("/files/Статистика")

    assert response.status_code == 200
    assert response.json() == {"subject": "Статистика", "files": ["a.pdf", "b.docx"]}


def test_list_files_endpoint_subject_not_found(isolate_storage):
    response = client.get("/files/НетТакого")
    assert response.status_code == 404


def test_download_file_success(isolate_storage):
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()
    (subject_dir / "report.docx").write_bytes(b"file body")

    response = client.get("/files/Статистика/report.docx")

    assert response.status_code == 200
    assert response.content == b"file body"
    assert "report.docx" in response.headers.get("content-disposition", "")


def test_download_file_subject_not_found(isolate_storage):
    response = client.get("/files/НетТакого/report.docx")
    assert response.status_code == 404


def test_download_file_not_found(isolate_storage):
    (isolate_storage / "Статистика").mkdir()
    response = client.get("/files/Статистика/missing.docx")
    assert response.status_code == 404


def test_search_endpoint(isolate_storage):
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()
    (subject_dir / "Лекция1.pdf").write_text("x", encoding="utf-8")
    (subject_dir / "report.docx").write_text("x", encoding="utf-8")

    response = client.get("/search", params={"q": "лекция"})

    assert response.status_code == 200
    assert response.json() == {
        "query": "лекция",
        "results": [{"subject": "Статистика", "filename": "Лекция1.pdf"}],
    }


def test_search_endpoint_empty_query(isolate_storage):
    response = client.get("/search", params={"q": "  "})
    assert response.status_code == 400


def test_search_endpoint_missing_query_param(isolate_storage):
    response = client.get("/search")
    assert response.status_code == 422  # обязательный параметр q отсутствует


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


def test_upload_file_at_size_limit_succeeds(isolate_storage):
    """Файл ровно на лимите проходит через эндпоинт (граница == MAX)."""
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()
    content = b"x" * storage.MAX_FILE_SIZE_BYTES

    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", content)},
    )

    assert response.status_code == 200
    assert (subject_dir / "report.docx").read_bytes() == content


def test_upload_file_duplicate_name_is_renamed(isolate_storage):
    """Повторная загрузка того же имени возвращает report(1).docx,
    оба файла лежат на диске (нет тихой перезаписи)."""
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()

    first = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"v1")},
    )
    second = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"v2")},
    )

    assert first.json()["filename"] == "report.docx"
    assert second.json()["filename"] == "report(1).docx"
    assert (subject_dir / "report.docx").read_bytes() == b"v1"
    assert (subject_dir / "report(1).docx").read_bytes() == b"v2"


def test_upload_file_empty_filename_is_rejected(isolate_storage):
    """Пустое имя файла отвергается на уровне эндпоинта.

    Замечание: multipart-часть с filename="" не доходит до save_file —
    FastAPI/`File(...)` отбраковывает её раньше как невалидный ввод (422).
    Ветка ValueError->400 для пустого имени в storage остаётся защитной.
    Главное для QA: пустое имя НЕ приводит к записи файла и НЕ даёт 2xx."""
    (isolate_storage / "Статистика").mkdir()

    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("", b"data")},
    )

    assert response.status_code == 422
    assert list((isolate_storage / "Статистика").iterdir()) == []


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


# --- Защита записи (Слой 2) -------------------------------------------------


def test_upload_missing_key_is_unauthorized(isolate_storage):
    """Ключ сконфигурирован, но клиент его не прислал -> 401, файл не записан."""
    (isolate_storage / "Статистика").mkdir()
    local = TestClient(app)  # без дефолтного X-API-Key

    response = local.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"data")},
    )

    assert response.status_code == 401
    assert list((isolate_storage / "Статистика").iterdir()) == []


def test_upload_wrong_key_is_unauthorized(isolate_storage):
    """Неверный ключ -> 401."""
    (isolate_storage / "Статистика").mkdir()

    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"data")},
        headers={"x-api-key": "wrong-key"},
    )

    assert response.status_code == 401


def test_upload_correct_key_succeeds(isolate_storage):
    """Верный ключ -> 200, файл записан (явный позитивный кейс auth)."""
    subject_dir = isolate_storage / "Статистика"
    subject_dir.mkdir()

    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"data")},
        headers={"x-api-key": TEST_UPLOAD_KEY},
    )

    assert response.status_code == 200
    assert (subject_dir / "report.docx").read_bytes() == b"data"


def test_upload_disabled_when_key_unconfigured(isolate_storage, monkeypatch):
    """Fail-closed: ключ не задан в env -> запись выключена (503), не открыта."""
    monkeypatch.setattr(main, "UPLOAD_API_KEY", "")
    (isolate_storage / "Статистика").mkdir()

    response = client.post(
        "/upload/file",
        data={"subject": "Статистика"},
        files={"file": ("report.docx", b"data")},
    )

    assert response.status_code == 503
    assert list((isolate_storage / "Статистика").iterdir()) == []


def test_upload_rate_limited(isolate_storage, monkeypatch):
    """Сверх лимита загрузок с одного IP -> 429 (rate-limit поверх auth)."""
    monkeypatch.setattr(main, "UPLOAD_RATE_LIMIT", 2)
    main._upload_hits.clear()
    (isolate_storage / "Статистика").mkdir()

    codes = []
    for i in range(3):
        r = client.post(
            "/upload/file",
            data={"subject": "Статистика"},
            files={"file": (f"r{i}.docx", b"data")},
        )
        codes.append(r.status_code)

    assert codes == [200, 200, 429]
