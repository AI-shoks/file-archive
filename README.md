# file-archive

Личный органайзер учебных материалов. Загрузка файлов с ручной меткой
предмета и хранением по папкам.

Границы и архитектурные решения — в [CLAUDE.md](CLAUDE.md).
Порядок работ — в [ROADMAP.md](ROADMAP.md).

## Запуск локально

```bash
python -m venv venv
venv\Scripts\activate            # Windows; на *nix: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Тесты:

```bash
python -m pytest
```

## Переменные окружения

| Переменная           | Назначение                                              | Дефолт                            |
|----------------------|---------------------------------------------------------|-----------------------------------|
| `FILE_ARCHIVE_ROOT`  | Корневой каталог хранилища                               | `C:/Users/artem/file-archive-data`|
| `SEED_SUBJECTS`      | CSV-список папок-предметов, создаваемых при старте       | пусто (сидирование не выполняется)|

## Деплой (Render)

Конфигурация — [render.yaml](render.yaml). Старт:
`uvicorn main:app --host 0.0.0.0 --port $PORT`.

**Хранилище на демо-деплое эфемерное by design.** Диск Render очищается
при каждом редеплое и засыпании инстанса, поэтому загруженные файлы не
сохраняются между деплоями, а папки-предметы пересоздаются при старте из
`SEED_SUBJECTS`. Для постоянного хранения достаточно подключить Render
Persistent Disk и указать `FILE_ARCHIVE_ROOT` на его mount path — замена
тривиальна и не требует изменений кода.
