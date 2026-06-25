"use strict";

// Vanilla-фронтенд поверх готового API Слоя 1. Никакой сборки: один файл,
// fetch к эндпоинтам /subjects, /files/{subject}, /files/{subject}/{file},
// /search, /upload/file. Состояние минимальное — выбранный предмет.

const el = (id) => document.getElementById(id);

const subjectsList = el("subjects-list");
const filesList = el("files-list");
const filesTitle = el("files-title");
const uploadForm = el("upload-form");
const uploadFile = el("upload-file");
const uploadKey = el("upload-key");
const searchForm = el("search-form");
const searchInput = el("search-input");
const searchPanel = el("search-panel");
const searchList = el("search-list");
const message = el("message");

let selectedSubject = null;

// Один общий помощник: показывает ошибку пользователю и пишет в консоль.
function showMessage(text, isError = true) {
  message.textContent = text;
  message.hidden = false;
  message.classList.toggle("error", isError);
}

function clearMessage() {
  message.hidden = true;
  message.textContent = "";
}

// API детально знает про коды (404/400/413/422). Здесь достаточно текста.
async function api(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = `Ошибка ${resp.status}`;
    try {
      const body = await resp.json();
      if (body && body.detail) detail = body.detail;
    } catch {
      // тело не JSON (например, 422 со списком) — оставляем код
    }
    throw new Error(detail);
  }
  return resp;
}

function fileHref(subject, filename) {
  return `/files/${encodeURIComponent(subject)}/${encodeURIComponent(filename)}`;
}

// Ссылка-«скачать» с явным текстом имени файла.
function downloadLink(subject, filename) {
  const a = document.createElement("a");
  a.href = fileHref(subject, filename);
  a.textContent = filename;
  a.setAttribute("download", "");
  return a;
}

async function loadSubjects() {
  try {
    const resp = await api("/subjects");
    const { subjects } = await resp.json();
    subjectsList.replaceChildren();
    if (subjects.length === 0) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "Нет предметов";
      subjectsList.append(li);
      return;
    }
    for (const subject of subjects) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.className = "link";
      btn.textContent = subject;
      btn.addEventListener("click", () => selectSubject(subject));
      li.append(btn);
      subjectsList.append(li);
    }
  } catch (e) {
    showMessage(`Не удалось загрузить предметы: ${e.message}`);
  }
}

async function selectSubject(subject) {
  selectedSubject = subject;
  clearMessage();
  searchPanel.hidden = true;
  filesTitle.textContent = `Файлы — ${subject}`;
  uploadForm.hidden = false;
  await loadFiles(subject);
}

async function loadFiles(subject) {
  try {
    const resp = await api(`/files/${encodeURIComponent(subject)}`);
    const { files } = await resp.json();
    filesList.replaceChildren();
    if (files.length === 0) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "Файлов пока нет";
      filesList.append(li);
      return;
    }
    for (const filename of files) {
      const li = document.createElement("li");
      li.append(downloadLink(subject, filename));
      filesList.append(li);
    }
  } catch (e) {
    showMessage(`Не удалось загрузить файлы: ${e.message}`);
  }
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedSubject) return;
  const file = uploadFile.files[0];
  if (!file) return;

  const form = new FormData();
  form.append("subject", selectedSubject);
  form.append("file", file);

  // Ключ хранится ТОЛЬКО введённым пользователем (и в localStorage его
  // браузера), в коде страницы его нет. Шлём заголовком, если указан.
  const key = uploadKey.value.trim();
  const headers = key ? { "X-API-Key": key } : undefined;
  localStorage.setItem("uploadKey", key);

  try {
    const resp = await api("/upload/file", { method: "POST", body: form, headers });
    const { filename } = await resp.json();
    // Сервер мог переименовать (report(1).docx) — показываем фактическое имя.
    showMessage(`Загружено: ${filename}`, false);
    uploadFile.value = "";  // сбрасываем только файл, ключ оставляем
    await loadFiles(selectedSubject);
  } catch (e) {
    showMessage(`Загрузка не удалась: ${e.message}`);
  }
});

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const q = searchInput.value.trim();
  if (!q) return;

  try {
    const resp = await api(`/search?q=${encodeURIComponent(q)}`);
    const { results } = await resp.json();
    clearMessage();
    searchPanel.hidden = false;
    searchList.replaceChildren();
    if (results.length === 0) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "Ничего не найдено";
      searchList.append(li);
      return;
    }
    for (const { subject, filename } of results) {
      const li = document.createElement("li");
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = subject;
      li.append(tag, downloadLink(subject, filename));
      searchList.append(li);
    }
  } catch (e) {
    showMessage(`Поиск не удался: ${e.message}`);
  }
});

// Подставляем ранее введённый ключ из localStorage (удобство, не секрет —
// это браузер самого пользователя).
uploadKey.value = localStorage.getItem("uploadKey") || "";

loadSubjects();
