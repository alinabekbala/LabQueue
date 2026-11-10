/* ЛЗ 9 + ЛЗ 11: клиентская интерактивность и обмен данными с сервером (fetch / AJAX).
 *
 * 0) request()        -> общий слой: заголовки, CSRF, обработка ошибок сети и HTTP
 * 1) setInterval      -> fetch GET  -> JSON  (живой счётчик мест)                     [ЛЗ 9]
 * 2) change           -> fetch POST -> JSON  (смена статуса записи)                    [ЛЗ 9, ЛЗ 11]
 * 3) input            -> подсказка по ссылке на GitHub (проверка на сервере остаётся)  [ЛЗ 9]
 * 4) списки           -> fetch GET  -> HTML-фрагмент (поиск, фильтры, сортировка, страницы) [ЛЗ 11]
 * 5) удаление записи  -> окно подтверждения + fetch POST -> JSON                       [ЛЗ 11]
 * 6) проверка записи  -> fetch GET  -> JSON  (нет ли уже такой записи на слоте)        [ЛЗ 11]
 * Текст пользователя всегда выводим через textContent, а не innerHTML (защита от XSS).
 * HTML-фрагменты приходят из шаблонов Django, где пользовательский текст уже экранирован.
 */
(function () {
  "use strict";

  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // ---------- 0. Общий слой обмена с сервером ----------
  class ApiError extends Error {
    constructor(message, status) { super(message); this.name = "ApiError"; this.status = status; }
  }

  /** fetch с единой обработкой: заголовки, CSRF для POST, ошибки сети и HTTP, истёкшая сессия. */
  async function request(url, { method = "GET", json, signal } = {}) {
    const headers = { "X-Requested-With": "XMLHttpRequest" };   // так сервер узнаёт, что это AJAX
    const options = { method, headers, signal, credentials: "same-origin" };
    if (method !== "GET") headers["X-CSRFToken"] = csrf;          // защита от CSRF
    if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(json);
    }
    let response;
    try {
      response = await fetch(url, options);
    } catch (err) {
      if (err.name === "AbortError") throw err;                   // запрос отменили мы сами
      throw new ApiError("Нет связи с сервером", 0);
    }
    if (response.redirected && response.url.includes("/login/")) {
      window.location.href = response.url;                        // сессия закончилась
      throw new ApiError("Нужно войти заново", 401);
    }
    if (!response.ok) {
      let message = "Ошибка сервера (" + response.status + ")";
      try {
        const data = await response.json();
        if (data.error) message = data.error;
      } catch (e) { /* ответ не JSON: оставляем общий текст */ }
      throw new ApiError(message, response.status);
    }
    return response;
  }

  /** Всплывающее уведомление (замена flash-сообщению, когда страница не перезагружается). */
  const toastBox = document.getElementById("toast-box");
  function toast(text, kind) {
    if (!toastBox) return;
    const el = document.createElement("div");
    el.className = "app-toast " + (kind || "ok");
    el.textContent = text;
    toastBox.appendChild(el);
    setTimeout(() => el.classList.add("hide"), 2800);
    setTimeout(() => el.remove(), 3400);
  }

  /** Кружок с числом в меню (компонент nav_badge из ЛЗ 9) обновляем из JSON-ответа. */
  function setBadge(count) {
    const box = document.getElementById("nav-badge");
    if (!box || typeof count !== "number") return;
    box.replaceChildren();
    if (count > 0) {
      const el = document.createElement("span");
      el.className = "nav-count";
      el.title = box.dataset.title || "";
      el.textContent = count;
      box.appendChild(el);
    }
  }

  function flash(el, cls) {
    el.classList.add(cls);
    setTimeout(() => el.classList.remove(cls), 1200);
  }

  // ---------- 1. Живой счётчик мест на странице записи ----------
  const live = document.getElementById("seats-live");
  if (live) {
    const takenEl = document.getElementById("seats-taken");
    const maxEl = document.getElementById("seats-max");
    const submit = document.getElementById("book-submit");

    async function refreshSeats() {
      if (document.hidden) return;                 // вкладка скрыта — не нагружаем сервер
      try {
        const d = await (await request(live.dataset.url)).json();
        takenEl.textContent = d.taken;
        maxEl.textContent = d.max;
        if (submit) {
          submit.disabled = d.is_full;
          submit.textContent = d.is_full ? "Мест больше нет" : "Подтвердить запись";
        }
      } catch (err) { /* сеть недоступна: оставляем прошлые значения */ }
    }
    setInterval(refreshSeats, 10000);
  }

  // ---------- 2. Смена статуса записи без перезагрузки (преподаватель) ----------
  document.addEventListener("change", async (e) => {
    const select = e.target.closest ? e.target.closest(".js-status-select") : null;
    if (!select) return;
    const previous = select.dataset.current;
    select.disabled = true;
    try {
      const data = await (await request(select.dataset.url, {
        method: "POST", json: { status: select.value },
      })).json();
      const badge = select.closest("tr").querySelector(".js-status-badge");
      badge.textContent = data.label;                       // textContent, не innerHTML
      badge.className = "badge-status js-status-badge st-" + data.status;
      select.dataset.current = data.status;
      setBadge(data.waiting);                               // число в меню тоже меняется
      flash(select, "flash-ok");
      toast("Статус изменён: " + data.label, "ok");
    } catch (err) {
      select.value = previous;                              // откатываем выбор
      flash(select, "flash-err");
      toast(err.message || "Не удалось изменить статус", "err");
    } finally {
      select.disabled = false;
    }
  });

  // ---------- 3. Подсказка по ссылке на репозиторий ----------
  const gh = document.getElementById("id_github_url");
  if (gh) {
    const hint = document.createElement("div");
    hint.className = "live-hint";
    gh.insertAdjacentElement("afterend", hint);
    const ok = /^https?:\/\/(www\.)?(github\.com|gitlab\.com)\/[^\s/]+\/[^\s/]+/i;
    gh.addEventListener("input", () => {
      const v = gh.value.trim();
      if (!v) { hint.textContent = ""; hint.className = "live-hint"; return; }
      const good = ok.test(v);
      hint.textContent = good ? "Ссылка похожа на репозиторий" : "Нужна ссылка на github.com или gitlab.com";
      hint.className = "live-hint " + (good ? "ok" : "bad");
    });
  }

  // ---------- 4. Списки без перезагрузки: поиск, фильтры, сортировка, страницы ----------
  // Форма с атрибутом data-ajax-list и блок #list-body есть на страницах слотов и записей.
  // Сервер на AJAX-запрос отдаёт HTML-фрагмент с тремя частями: счётчик, ошибки, список.
  let reloadList = null;
  const listForm = document.querySelector("form[data-ajax-list]");
  if (listForm && document.getElementById("list-body")) {
    const PARTS = ["list-summary", "list-errors", "list-body"];
    let controller = null;                // для отмены устаревшего запроса
    let timer = null;                     // для задержки (debounce) при вводе текста
    let lastUrl = location.pathname + location.search;

    /** Адрес из текущих значений формы, как при обычной отправке GET-формы. */
    const formUrl = () => location.pathname + "?" + new URLSearchParams(new FormData(listForm)).toString();

    /** Поля формы повторяют адрес (нужно при кнопке «Назад» и при клике по заголовку колонки). */
    function syncForm(url) {
      const params = new URL(url, location.href).searchParams;
      for (const el of listForm.elements) {
        if (!el.name || el.type === "submit" || el.type === "button") continue;
        if (el.type === "checkbox") el.checked = params.has(el.name);
        else if ((params.get(el.name) || "") !== el.value) el.value = params.get(el.name) || "";
      }
    }

    function clearError() {
      const old = document.getElementById("list-error");
      if (old) old.remove();
    }

    function showError(message, retry) {
      clearError();
      const box = document.createElement("div");
      box.id = "list-error";
      box.className = "alert alert-danger d-flex align-items-center gap-3";
      box.setAttribute("role", "alert");
      const text = document.createElement("span");
      text.textContent = message;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-sm btn-outline-ink ms-auto";
      button.textContent = "Повторить";
      button.addEventListener("click", retry);
      box.append(text, button);
      document.getElementById("list-body").before(box);
    }

    async function loadList(url, { push = true, force = false, scroll = false } = {}) {
      if (!force && url === lastUrl) return;                  // ничего не изменилось
      if (controller) controller.abort();                     // предыдущий запрос уже не нужен
      const mine = controller = new AbortController();
      const body = document.getElementById("list-body");
      const summary = document.getElementById("list-summary");
      const previousSummary = summary ? summary.textContent : "";
      body.classList.add("is-loading");                       // состояние «загрузка»
      body.setAttribute("aria-busy", "true");
      if (summary) summary.textContent = "Загрузка…";
      clearError();
      try {
        const response = await request(url, { signal: mine.signal });
        const doc = new DOMParser().parseFromString(await response.text(), "text/html");
        for (const id of PARTS) {                             // заменяем только изменившиеся части
          const fresh = doc.getElementById(id);
          const old = document.getElementById(id);
          if (fresh && old) old.replaceChildren(...fresh.childNodes);
        }
        lastUrl = url;
        if (push) history.pushState(null, "", url);           // адрес меняется: ссылку можно скопировать
        syncForm(url);
        if (scroll) document.getElementById("list-body").scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (err) {
        if (err.name === "AbortError") return;                // запрос заменён более новым
        if (summary) summary.textContent = previousSummary;
        showError(err.message || "Не удалось загрузить список", () => loadList(url, { push, force: true }));
      } finally {
        if (controller === mine) {
          const current = document.getElementById("list-body");
          current.classList.remove("is-loading");
          current.removeAttribute("aria-busy");
        }
      }
    }
    reloadList = () => loadList(location.pathname + location.search, { push: false, force: true });

    // Кнопка «Найти»: обычная отправка формы заменяется на fetch.
    listForm.addEventListener("submit", (e) => {
      e.preventDefault();
      clearTimeout(timer);
      loadList(formUrl(), { force: true });
    });

    // Ввод в текстовое поле: ждём 300 мс после последней буквы; выбор в списке, дата, флажок: сразу.
    listForm.addEventListener("input", (e) => {
      const typing = e.target.matches('input[type="text"], input[type="search"], input[type="number"]');
      clearTimeout(timer);
      if (typing) timer = setTimeout(() => loadList(formUrl()), 300);
      else loadList(formUrl());
    });

    // Номера страниц и заголовки колонок: перехватываем клик, адрес берём из ссылки.
    document.addEventListener("click", (e) => {
      const link = e.target.closest ? e.target.closest("#list-body a[href^='?']") : null;
      if (!link || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      const u = new URL(link.getAttribute("href"), location.href);
      loadList(u.pathname + u.search, { scroll: true });
    });

    // Кнопки «Назад» и «Вперёд» в браузере.
    window.addEventListener("popstate", () => loadList(location.pathname + location.search, { push: false, force: true }));
  }

  // ---------- 5. Удаление записи без перезагрузки ----------
  const confirmModal = document.getElementById("confirm-delete");
  if (confirmModal && window.bootstrap) {
    const modal = window.bootstrap.Modal.getOrCreateInstance(confirmModal);
    const yes = document.getElementById("confirm-delete-yes");
    let target = null;

    document.addEventListener("click", (e) => {
      const button = e.target.closest ? e.target.closest(".js-delete") : null;
      if (!button) return;
      e.preventDefault();                                      // без JS сработает ссылка на страницу подтверждения
      target = button;
      document.getElementById("confirm-delete-text").textContent =
        "Студент " + button.dataset.name + ", лаба №" + button.dataset.lab + ".";
      modal.show();
    });

    yes.addEventListener("click", async () => {
      if (!target) return;
      yes.disabled = true;                                     // защита от двойного нажатия
      try {
        const data = await (await request(target.dataset.url, { method: "POST" })).json();
        modal.hide();
        setBadge(data.waiting);
        toast(data.message, "ok");
        if (reloadList) reloadList(); else window.location.reload();
      } catch (err) {
        modal.hide();
        toast(err.message || "Не удалось удалить запись", "err");
      } finally {
        yes.disabled = false;
        target = null;
      }
    });
  }

  // ---------- 6. Проверка «на лету» при записи на слот ----------
  const bookingHint = document.getElementById("booking-hint");
  const nameInput = document.getElementById("id_student_name");
  const labInput = document.getElementById("id_lab_number");
  if (bookingHint && nameInput && labInput) {
    let timer = null;
    let controller = null;
    const show = (text, cls) => { bookingHint.textContent = text; bookingHint.className = "live-hint " + cls; };

    async function check() {
      const name = nameInput.value.trim();
      const lab = labInput.value.trim();
      if (name.split(/\s+/).length < 2 || !lab) { show("", ""); return; }
      if (controller) controller.abort();
      controller = new AbortController();
      const query = new URLSearchParams({ student_name: name, lab_number: lab });
      try {
        const d = await (await request(bookingHint.dataset.url + "?" + query, { signal: controller.signal })).json();
        if (d.checked) show(d.message, d.ok ? "ok" : "bad"); else show("", "");
      } catch (err) {
        if (err.name !== "AbortError") show("", "");          // подсказка не обязательна: форма проверит сама
      }
    }
    const later = () => { clearTimeout(timer); timer = setTimeout(check, 400); };
    nameInput.addEventListener("input", later);
    labInput.addEventListener("input", later);
    if (nameInput.value && labInput.value) check();           // значения могли подставиться из сессии
  }
})();
