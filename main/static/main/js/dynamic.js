/* ЛЗ 9: обработка пользовательских событий и динамические блоки.
 * 1) setInterval     -> fetch -> JSON (живой счётчик мест)
 * 2) change          -> fetch POST + CSRF -> JSON (статус записи без перезагрузки)
 * 3) input           -> подсказка по ссылке на GitHub (проверка на сервере остаётся)
 * Пользовательский текст всегда выводим через textContent, а не innerHTML (защита от XSS).
 */
(function () {
  "use strict";

  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // ---------- 1. Живой счётчик мест на странице записи ----------
  const live = document.getElementById("seats-live");
  if (live) {
    const takenEl = document.getElementById("seats-taken");
    const maxEl = document.getElementById("seats-max");
    const submit = document.getElementById("book-submit");

    async function refreshSeats() {
      if (document.hidden) return;                 // вкладка скрыта — не нагружаем сервер
      try {
        const r = await fetch(live.dataset.url);
        if (!r.ok) return;
        const d = await r.json();
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
      const r = await fetch(select.dataset.url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ status: select.value }),
      });
      const data = await r.json();
      if (!r.ok || !data.ok) throw new Error(data.error || "HTTP " + r.status);
      const badge = select.closest("tr").querySelector(".js-status-badge");
      badge.textContent = data.label;                       // textContent, не innerHTML
      badge.className = "badge-status js-status-badge st-" + data.status;
      select.dataset.current = data.status;
      flash(select, "flash-ok");
    } catch (err) {
      select.value = previous;                              // откатываем выбор
      flash(select, "flash-err");
    } finally {
      select.disabled = false;
    }
  });

  function flash(el, cls) {
    el.classList.add(cls);
    setTimeout(() => el.classList.remove(cls), 1200);
  }

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
})();
