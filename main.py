import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import storage
from storage import ArchiveFileNotFoundError, FileTooLargeError, SubjectNotFoundError

logger = logging.getLogger("file_archive")

# --- Защита записи (Слой 2) -------------------------------------------------
# Ключ хранится ТОЛЬКО на сервере (env). Во фронтенд (публичный static/app.js)
# его зашивать нельзя — он виден всем; поэтому UI спрашивает ключ у юзера и
# шлёт заголовком X-API-Key. Здесь — серверная проверка + rate-limit.
#
# Режим fail-closed: если UPLOAD_API_KEY не задан, загрузка ВЫКЛЮЧЕНА (503),
# а не открыта. Осознанный выбор «secure by default»: забытый на проде ключ
# не должен молча оставлять запись публичной (см. CLAUDE.md).
UPLOAD_API_KEY = os.environ.get("UPLOAD_API_KEY", "").strip()

# Rate-limit: не больше N загрузок с одного IP за окно. In-memory, на один
# процесс (Render free = 1 воркер); сбрасывается при рестарте — для демо ок.
UPLOAD_RATE_LIMIT = int(os.environ.get("UPLOAD_RATE_LIMIT", "20"))
UPLOAD_RATE_WINDOW_SECONDS = 60

# IP -> времена недавних загрузок. Доступ из пула потоков (sync-зависимости
# FastAPI исполняются в threadpool), поэтому под локом.
_upload_hits: dict[str, deque[float]] = defaultdict(deque)
_upload_hits_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """IP клиента с учётом прокси Render. За балансировщиком request.client
    содержит адрес прокси, реальный клиент — первый в X-Forwarded-For.
    Заголовок подделываем — поэтому это defense-in-depth, не аутентификация."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_upload_rate_limit(request: Request) -> None:
    """Зависимость: ограничивает частоту загрузок с одного IP. Считаются ВСЕ
    попытки (в т.ч. с неверным ключом) — чтобы заодно тормозить перебор ключа.
    Стоит ПЕРЕД проверкой ключа в списке dependencies эндпоинта."""
    ip = _client_ip(request)
    now = time.monotonic()
    with _upload_hits_lock:
        hits = _upload_hits[ip]
        while hits and now - hits[0] > UPLOAD_RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= UPLOAD_RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Слишком много загрузок, попробуйте позже")
        hits.append(now)


def require_upload_key(x_api_key: str | None = Header(default=None)) -> None:
    """Зависимость: проверяет X-API-Key для записи.

    - Ключ не сконфигурирован (env пуст) -> 503: запись намеренно выключена
      (fail-closed), это не вина клиента.
    - Ключ задан, но в запросе неверный/отсутствует -> 401.
    Сравнение через secrets.compare_digest — постоянное время, без утечки
    длины/префикса по таймингу."""
    if not UPLOAD_API_KEY:
        raise HTTPException(status_code=503, detail="Загрузка не настроена (UPLOAD_API_KEY не задан)")
    if x_api_key is None or not secrets.compare_digest(x_api_key, UPLOAD_API_KEY):
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий ключ загрузки")


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

    # Видимый сигнал режима записи при старте (важно для прода).
    if UPLOAD_API_KEY:
        logger.info("upload protected by API key (rate limit %d/%ds)",
                    UPLOAD_RATE_LIMIT, UPLOAD_RATE_WINDOW_SECONDS)
    else:
        logger.warning("UPLOAD_API_KEY не задан — загрузка ЗАКРЫТА (fail-closed), "
                       "POST /upload/file вернёт 503")
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


@app.post(
    "/upload/file",
    # Порядок важен: rate-limit ВЫШЕ проверки ключа, чтобы перебор ключа
    # тоже упирался в лимит.
    dependencies=[Depends(enforce_upload_rate_limit), Depends(require_upload_key)],
)
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


# Слой 2: статический фронтенд (vanilla, без сборки) отдаётся самим FastAPI.
# Монтируется ПОСЛЕДНИМ: Starlette матчит роуты в порядке регистрации, и
# конкретные API-роуты выше перехватывают /health, /subjects, /files/...,
# /search, /upload/file раньше этого catch-all. html=True отдаёт index.html
# на "/". Каталог создаём при импорте — на эфемерном диске его может не быть.
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
