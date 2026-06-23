from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

import storage
from storage import FileTooLargeError, SubjectNotFoundError

app = FastAPI(title="File Archive")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
