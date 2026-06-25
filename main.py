import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import storage
from storage import ArchiveFileNotFoundError, FileTooLargeError, SubjectNotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # На эфемерном деплое диск пуст после редеплоя — сидируем папки-предметы
    # из env-списка (CSV). Локально SEED_SUBJECTS обычно не задан, и сидирование
    # не выполняется.
    seed = os.environ.get("SEED_SUBJECTS", "")
    subjects = [s.strip() for s in seed.split(",") if s.strip()]
    if subjects:
        storage.seed_subjects(subjects)
    yield


app = FastAPI(title="File Archive", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/subjects")
def list_subjects() -> dict[str, list[str]]:
    return {"subjects": storage.list_subjects()}


@app.get("/files/{subject}")
def list_files(subject: str) -> dict[str, object]:
    try:
        files = storage.list_files(subject)
    except SubjectNotFoundError:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимый предмет")

    return {"subject": subject, "files": files}


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


@app.post("/upload/file")
async def upload_file(
    subject: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, str]:
    content = await file.read()
    try:
        saved_path = storage.save_file(subject, file.filename or "", content)
    except SubjectNotFoundError:
        raise HTTPException(status_code=404, detail="Предмет не найден")
    except FileTooLargeError:
        raise HTTPException(status_code=413, detail="Файл слишком большой")
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимый предмет или имя файла")

    return {"subject": subject, "filename": Path(saved_path).name}
