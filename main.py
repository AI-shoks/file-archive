import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

import storage
from storage import ArchiveFileNotFoundError, FileTooLargeError, SubjectNotFoundError

logger = logging.getLogger("file_archive")


def _configure_logging() -> None:
    """Настраивает логгер file_archive независимо от uvicorn.

    `logging.basicConfig()` при импорте ненадёжен: под uvicorn корневой
    логгер уже может быть с хендлерами (тогда basicConfig — no-op) либо,
    наоборот, не сконфигурирован так, как мы ждём. Поэтому вешаем
    собственный StreamHandler прямо на логгер file_archive и фиксируем
    уровень — наблюдаемость не зависит от настроек сервера. propagate=False
    исключает дубль строк, если root тоже с хендлерами. Идемпотентно:
    повторный импорт не плодит хендлеры.
    """
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_configure_logging()


def parse_subjects(seed: str) -> list[str]:
    """Разбирает CSV-список предметов из env SEED_SUBJECTS.

    Пустые элементы и пробелы по краям отбрасываются. Это та логика,
    что чуть не сорвала деплой (см. ROADMAP), поэтому вынесена в чистую
    функцию и покрыта тестами отдельно от lifespan."""
    return [s.strip() for s in seed.split(",") if s.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # На эфемерном деплое диск пуст после редеплоя — сидируем папки-предметы
    # из env-списка (CSV). Локально SEED_SUBJECTS обычно не задан, и сидирование
    # не выполняется.
    subjects = parse_subjects(os.environ.get("SEED_SUBJECTS", ""))
    if subjects:
        created = storage.seed_subjects(subjects)
        logger.info("seeded %d subjects", len(created))
    else:
        logger.info("no SEED_SUBJECTS provided, skipping seeding")
    yield


app = FastAPI(title="File Archive", lifespan=lifespan)


class HealthResp(BaseModel):
    status: str


class SubjectsResp(BaseModel):
    subjects: list[str]


class FilesResp(BaseModel):
    subject: str
    files: list[str]


class SearchResult(BaseModel):
    subject: str
    filename: str


class SearchResp(BaseModel):
    query: str
    results: list[SearchResult]


class UploadResp(BaseModel):
    subject: str
    filename: str


@app.get("/health")
def health() -> HealthResp:
    return HealthResp(status="ok")


@app.get("/subjects")
def list_subjects() -> SubjectsResp:
    return SubjectsResp(subjects=storage.list_subjects())


@app.get("/files/{subject}")
def list_files(subject: str) -> FilesResp:
    try:
        files = storage.list_files(subject)
    except SubjectNotFoundError:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимый предмет")

    return FilesResp(subject=subject, files=files)


@app.get("/files/{subject}/{filename}")
def download_file(subject: str, filename: str) -> FileResponse:
    try:
        path = storage.get_file_path(subject, filename)
    except SubjectNotFoundError:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    except ArchiveFileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл не найден")
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимый предмет или имя файла")

    # filename=path.name — клиент получит исходное имя файла, абсолютный
    # путь сервера в ответ не попадает.
    return FileResponse(path, filename=path.name)


@app.get("/search")
def search(q: str) -> SearchResp:
    try:
        results = storage.search_files(q)
    except ValueError:
        raise HTTPException(status_code=400, detail="Пустой поисковый запрос")

    return SearchResp(query=q, results=[SearchResult(**r) for r in results])


@app.post("/upload/file")
async def upload_file(
    subject: str = Form(...),
    file: UploadFile = File(...),
) -> UploadResp:
    content = await file.read()
    try:
        # Запись на диск синхронна (storage.save_file -> write_bytes); чтобы
        # не блокировать event loop большой записью, уводим её в пул потоков.
        saved_path = await run_in_threadpool(
            storage.save_file, subject, file.filename or "", content
        )
    except SubjectNotFoundError:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    except FileTooLargeError:
        raise HTTPException(status_code=413, detail="Файл слишком большой")
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимый предмет или имя файла")

    saved_name = Path(saved_path).name
    logger.info("uploaded %r to subject %r", saved_name, subject)
    return UploadResp(subject=subject, filename=saved_name)
