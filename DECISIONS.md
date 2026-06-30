# Design Decisions

Why the archive is built the way it is — the security and concurrency choices
that aren't obvious from the code. The [README](README.md) covers what it does
and how to run it; this file covers *why*, so each decision can be defended
rather than just pointed at.

## 1. Filename collisions resolved by atomic exclusive-create, not check-then-write

When an upload's name already exists, the existing file is never overwritten.
`_write_unique` tries `name`, then `name(1).ext`, `name(2).ext`, … and for each
candidate attempts to *create* it exclusively with `open(path, "xb")`
(`O_CREAT | O_EXCL`); the first name that doesn't already exist wins, and the
actual stored name is returned to the client.

The rejected alternative — check `exists()`, then `write_bytes()` — has a
time-of-check/time-of-use (TOCTOU) gap between the check and the write. That gap
is real here, not theoretical: uploads are offloaded to a thread pool
(see decision 4), so two concurrent uploads of the same name can interleave,
both see the name as free, and one clobbers the other. Exclusive create fuses
"claim the name" and "start writing" into one atomic operation — exactly one
writer wins a given name, the rest get `FileExistsError` and move to the next
candidate. Silent overwrite is data loss without warning, so it is designed out.

## 2. `subject` is validated as a single name; `filename` is reduced to one

- **subject** — `if not subject or subject != Path(subject).name: raise`.
  Subject folders are created ahead of time, so a subject must *be* one folder
  name, not a path. That check rejects `"../x"`, `"a/b"`, and absolute paths,
  after which subject physically cannot escape the storage root.
  `is_relative_to()` / `.resolve()` on top of it would be dead code.
- **filename** — `Path(filename).name` *extracts* the safe leaf, discarding any
  path or `../` a client sent; an empty result raises.

The distinction is deliberate: for `subject`, `.name` is used as a *check*
("the input already is a bare name"); for `filename`, `.name` is used to
*derive* a safe name from possibly-hostile input. Both validations live in one
helper each (`_validate_subject`, `_safe_filename`) so the rule isn't duplicated
across `save_file` / `list_files` / `get_file_path` / `seed_subjects`.

## 3. Custom exceptions subclass `Exception`, and `except` order is specific-first

`SubjectNotFoundError` / `ArchiveFileNotFoundError` → 404,
`FileTooLargeError` → 413, plain `ValueError` → 400.

The custom exceptions deliberately do **not** inherit from `ValueError`: if they
did, the `except ValueError` arm would catch them first and the 404/413 mappings
would be unreachable. For the same reason the handlers list the specific
`except` arms above the broad `except ValueError` — Python takes the first
matching arm, so a broad arm placed first would swallow the specific ones and
collapse every error into a 400.

## 4. Disk writes run in a thread pool, off the event loop

The upload endpoint is `async`, but the synchronous disk write (`save_file`) is
dispatched via `run_in_threadpool`. A direct synchronous `write_bytes` inside an
`async def` blocks the entire event loop for the duration of the write,
stalling every other in-flight request. The storage layer keeps its simple
synchronous API; offloading is the transport layer's concern, so the two stay
decoupled.

## 5. Write access is fail-closed

`POST /upload/file` requires `UPLOAD_API_KEY` via an `X-API-Key` header,
compared with `secrets.compare_digest` (constant time, no length/prefix timing
leak). The status codes are split by fault:

- key **not configured** → `503` — writes are *off*, not open. A key forgotten
  on a deploy must never silently leave the archive publicly writable.
  Secure-by-default is the invariant; it is not to be flipped to fail-open
  without an explicit decision.
- key configured but **wrong/missing** in the request → `401` — the client's
  fault.

A per-IP rate limit sits *above* the key check in the dependency list, so
brute-force attempts are throttled before they reach it; it is defense-in-depth
(the `X-Forwarded-For` IP is spoofable), not authentication. The key is never
embedded in the public `static/` frontend — the UI asks the user for it and
keeps it in their `localStorage`.

## 6. Responses never include an absolute filesystem path

Endpoints return only `{"subject", "filename"}`, and downloads set
`FileResponse(..., filename=path.name)`; the absolute stored path never appears
in a response. An absolute path leaks the OS, the system username, and the
filesystem layout — passive reconnaissance for an attacker. Subject and filename
were supplied by the client, so echoing them back reveals nothing new about the
server.
