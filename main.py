from fastapi import FastAPI

app = FastAPI(title="File Archive")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
