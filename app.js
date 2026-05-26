const STORAGE_KEY = "pc-coop-table-v3";

const ONE_COPY = {
  "friend-pass": { label: "Friend Pass", rank: 3, tone: "good" },
  "remote-play": { label: "Remote Play", rank: 2, tone: "warn" },
  none: { label: "Нужно 2 копии", rank: 1, tone: "muted" }
};

const ENDING_TYPE = {
  story: { label: "Сюжет", short: "Сюжет", tone: "info", rank: 5 },
  levels: { label: "Уровни", short: "Уровни", tone: "muted", rank: 4 },
  "arcade-goal": { label: "Цель / эскейп", short: "Цель", tone: "good", rank: 3 },
  roguelite: { label: "Roguelite", short: "Roguelite", tone: "warn", rank: 2 },
  "survival-goal": { label: "Survival + финал", short: "Survival", tone: "bad", rank: 1 }
};

const TIER_VALUES = new Set(["AAA", "AA", "Indie"]);

// 'FIT_RANK' has been removed as the 'Попадание' column is deleted

const state = {
  sortKey: "rating",
  sortDirection: "desc",
  showHidden: false,
  theme: "dark",
  hiddenOverrides: {},
  filters: {
    title: "",
    year: { min: "", max: "" },
    rating: { min: "", max: "" },
    playersMax: { min: "", max: "" },
    hours: { min: "", max: "" },
    price: { min: "", max: "" },
    genres: new Set(),
    endingType: new Set(),
    oneCopy: new Set()
  }
};

const els = {
  body: document.querySelector("#gamesBody"),
  caption: document.querySelector("#tableCaption"),
  empty: document.querySelector("#emptyState"),
  popover: document.querySelector("#filterPopover"),
  toast: document.querySelector("#toast"),
  showHidden: document.querySelector("#showHiddenToggle"),
  themeButton: document.querySelector("#themeButton"),
  resetFilters: document.querySelector("#resetFiltersButton")
};

const games = window.GAMES.map((game) => ({
  hidden: false,
  hiddenReason: "",
  ...game
}));

const filterConfig = {
  title: { type: "text", label: "Игра", placeholder: "Название или вердикт" },
  year: { type: "range", label: "Год", step: 1, min: 0 },
  rating: { type: "range", label: "Рейтинг", step: 5, min: 0 },
  playersMax: { type: "range", label: "Игроки", step: 1, min: 0 },
  hours: { type: "range", label: "Часы", step: 1, min: 0 },
  genres: { type: "set", label: "Жанры", options: () => uniqueSorted(games.flatMap((game) => game.genres)) },
  endingType: {
    type: "set",
    label: "Тип игры",
    options: () => Object.keys(ENDING_TYPE),
    labelFor: (value) => ENDING_TYPE[value]?.label || value
  },
  oneCopy: {
    type: "set",
    label: "Второму",
    options: () => Object.keys(ONE_COPY),
    labelFor: (value) => ONE_COPY[value].label
  },
  price: { type: "range", label: "Цена", step: 50, min: 49 }
};

function getRangeExtents(key) {
  const values = games.map((g) => Number(g[key])).filter((v) => !isNaN(v) && v > 0);
  if (!values.length) return { min: 0, max: 0 };
  return { min: Math.min(...values), max: Math.max(...values) };
}

function loadPrefs() {
  try {
    const prefs = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    state.theme = prefs.theme || "dark";
    state.showHidden = Boolean(prefs.showHidden);
    state.hiddenOverrides = prefs.hiddenOverrides || {};
  } catch {
    state.theme = "dark";
  }
}

function savePrefs() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    theme: state.theme,
    showHidden: state.showHidden,
    hiddenOverrides: state.hiddenOverrides
  }));
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function isHidden(game) {
  if (Object.prototype.hasOwnProperty.call(state.hiddenOverrides, game.id)) {
    return state.hiddenOverrides[game.id];
  }
  return Boolean(game.hidden);
}

function getSortValue(game, key) {
  if (key === "genres") return game.genres.join(", ");
  if (key === "oneCopy") return ONE_COPY[game.oneCopy]?.rank || 0;
  if (key === "endingType") return ENDING_TYPE[game.endingType]?.rank || 0;
  if (key === "price") return game.price || 0;
  return game[key];
}

function compareValues(a, b) {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a ?? "").localeCompare(String(b ?? ""), "ru", { numeric: true });
}

function gameMatchesFilters(game) {
  if (!state.showHidden && isHidden(game)) return false;

  const text = state.filters.title.trim().toLowerCase();
  if (text) {
    const haystack = [game.title, game.verdict, game.genres.join(" "), game.ratingLabel].join(" ").toLowerCase();
    if (!haystack.includes(text)) return false;
  }

  for (const key of ["year", "rating", "playersMax", "hours", "price"]) {
    const filter = state.filters[key];
    const value = Number(game[key]);
    if (filter.min !== "" && value < Number(filter.min)) return false;
    if (filter.max !== "" && value > Number(filter.max)) return false;
  }

  if (state.filters.genres.size > 0 && !game.genres.some((genre) => state.filters.genres.has(genre))) return false;
  if (state.filters.endingType.size > 0 && !state.filters.endingType.has(game.endingType)) return false;
  if (state.filters.oneCopy.size > 0 && !state.filters.oneCopy.has(game.oneCopy)) return false;

  return true;
}

function getVisibleGames() {
  return games
    .filter(gameMatchesFilters)
    .sort((a, b) => {
      const result = compareValues(getSortValue(a, state.sortKey), getSortValue(b, state.sortKey));
      const direction = state.sortDirection === "asc" ? 1 : -1;
      return result * direction || a.title.localeCompare(b.title, "ru");
    });
}

function render() {
  document.body.dataset.theme = state.theme;
  els.showHidden.checked = state.showHidden;
  els.themeButton.lastChild.textContent = state.theme === "dark" ? " Светлая" : " Тёмная";

  const visibleGames = getVisibleGames();
  const hiddenCount = games.filter(isHidden).length;

  els.body.innerHTML = visibleGames.map(renderRow).join("");
  els.empty.hidden = visibleGames.length > 0;
  els.caption.textContent = `Показано ${visibleGames.length} из ${games.length}. Скрыто: ${hiddenCount}.`;
  renderSortIcons();
  renderActiveFilterButtons();
}

function renderRow(game) {
  const hidden = isHidden(game);
  const oneCopy = ONE_COPY[game.oneCopy] || ONE_COPY.none;
  const hiddenLabel = hidden ? `<span class="hidden-note">${escapeHtml(game.hiddenReason || "Скрыто")}</span>` : "";
  const priceDisplay = game.price > 0
    ? `<a class="price-link" href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">${game.price}&nbsp;₴</a>`
    : `<span class="detail">—</span>`;

  return `
    <tr class="${hidden ? "is-hidden" : ""}">
      <td class="image-cell">
        <a href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">
          <img src="${escapeHtml(game.imageUrl)}" alt="${escapeHtml(game.title)}" loading="lazy">
        </a>
      </td>
      <td class="title-cell">
        <a class="game-link" href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">${escapeHtml(game.title)}</a>
        ${hiddenLabel}
      </td>
      <td class="number-cell">${game.year}</td>
      <td><div class="tag-list">${game.genres.map((genre) => `<span class="tag${TIER_VALUES.has(genre) ? " tier" : ""}">${escapeHtml(genre)}</span>`).join("")}</div></td>
      <td>${renderEndingType(game.endingType)}</td>
      <td class="number-cell rating">${game.rating}</td>
      <td class="number-cell">${game.playersMax}</td>
      <td class="number-cell">${trimNumber(game.hours)}&nbsp;ч</td>
      <td><span class="badge ${oneCopy.tone}">${escapeHtml(oneCopy.label)}</span></td>
      <td class="number-cell price-cell">${priceDisplay}</td>
      <td class="verdict-cell">${escapeHtml(game.verdict)}</td>
      <td><a class="youtube-link" href="${escapeHtml(game.youtubeUrl)}" target="_blank" rel="noreferrer">Gameplay</a></td>
      <td class="action-cell">
        <button class="icon-action" type="button" data-hide-id="${escapeHtml(game.id)}" aria-label="${hidden ? "Вернуть" : "Скрыть"} ${escapeHtml(game.title)}">
          ${hidden ? restoreIcon() : hideIcon()}
        </button>
      </td>
    </tr>
  `;
}

function trimNumber(value) {
  return Number.isInteger(value) ? value : value.toFixed(1);
}

function renderEndingType(value) {
  const meta = ENDING_TYPE[value];
  if (!meta) return `<span class="detail">—</span>`;
  return `<span class="badge ending ${meta.tone}" data-ending="${escapeHtml(value)}">${escapeHtml(meta.short)}</span>`;
}

// 'fitTone' has been removed as the 'Попадание' column is deleted

function hideIcon() {
  return '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 3l18 18"></path><path d="M10.6 10.6A2 2 0 0 0 13.4 13.4"></path><path d="M9.9 4.2A10.7 10.7 0 0 1 12 4c5 0 9 5 10 8a15.9 15.9 0 0 1-3.1 4.7"></path><path d="M6.1 6.1A15.2 15.2 0 0 0 2 12c1 3 5 8 10 8a10.8 10.8 0 0 0 4.1-.8"></path></svg>';
}

function restoreIcon() {
  return '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
}

function renderSortIcons() {
  document.querySelectorAll("[data-sort-icon]").forEach((icon) => {
    const key = icon.dataset.sortIcon;
    icon.textContent = key === state.sortKey ? (state.sortDirection === "asc" ? "↑" : "↓") : "";
  });
}

function renderActiveFilterButtons() {
  document.querySelectorAll("[data-filter]").forEach((control) => {
    const isActive = filterIsActive(control.dataset.filter);
    control.classList.toggle("has-active-filter", isActive);
  });
}

function filterIsActive(key) {
  const value = state.filters[key];
  if (value instanceof Set) return value.size > 0;
  const config = filterConfig[key];
  if (config && config.type === "range") {
    const { min: dataMin, max: dataMax } = getRangeExtents(key);
    const minActive = value.min !== "" && Number(value.min) > dataMin;
    const maxActive = value.max !== "" && Number(value.max) < dataMax;
    return minActive || maxActive;
  }
  if (typeof value === "object") return value.min !== "" || value.max !== "";
  return Boolean(value);
}

function openFilter(key, button) {
  const config = filterConfig[key];
  if (!config) return;

  els.popover.innerHTML = renderFilterMarkup(key, config);
  els.popover.hidden = false;

  const rect = button.getBoundingClientRect();
  const width = Math.min(320, window.innerWidth - 24);
  els.popover.style.width = `${width}px`;
  els.popover.style.left = `${Math.min(window.innerWidth - width - 12, Math.max(12, rect.right - width))}px`;
  els.popover.style.top = `${rect.bottom + 8}px`;
  bindFilterControls(key, config);
}

function renderFilterMarkup(key, config) {
  if (config.type === "text") {
    return `
      <div class="popover-title">${escapeHtml(config.label)}</div>
      <input class="filter-input" data-text-filter="${escapeHtml(key)}" value="${escapeHtml(state.filters[key])}" placeholder="${escapeHtml(config.placeholder)}">
      <button class="button full" type="button" data-clear-filter="${escapeHtml(key)}">Очистить</button>
    `;
  }

  if (config.type === "range") {
    const filter = state.filters[key];
    const { min: dataMin, max: dataMax } = getRangeExtents(key);
    const step = config.step || 1;
    const inputMin = config.min !== undefined ? config.min : 0;
    const minValue = filter.min !== "" ? filter.min : String(dataMin);
    const maxValue = filter.max !== "" ? filter.max : String(dataMax);
    return `
      <div class="popover-title">${escapeHtml(config.label)}: от / до</div>
      <div class="range-grid">
        <input class="filter-input" type="number" inputmode="numeric" data-range-min="${escapeHtml(key)}" value="${escapeHtml(minValue)}" placeholder="${dataMin}" min="${inputMin}" step="${step}">
        <input class="filter-input" type="number" inputmode="numeric" data-range-max="${escapeHtml(key)}" value="${escapeHtml(maxValue)}" placeholder="${dataMax}" min="${inputMin}" step="${step}">
      </div>
      <button class="button full" type="button" data-clear-filter="${escapeHtml(key)}">Очистить</button>
    `;
  }

  const options = config.options();
  const selected = state.filters[key];
  return `
    <div class="popover-title">${escapeHtml(config.label)}</div>
    <div class="checkbox-list">
      ${options.map((value) => `
        <label class="check-row">
          <input type="checkbox" data-set-filter="${escapeHtml(key)}" value="${escapeHtml(value)}" ${selected.has(value) ? "checked" : ""}>
          <span>${escapeHtml(config.labelFor ? config.labelFor(value) : value)}</span>
        </label>
      `).join("")}
    </div>
    <button class="button full" type="button" data-clear-filter="${escapeHtml(key)}">Очистить</button>
  `;
}

function bindFilterControls(key, config) {
  els.popover.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", () => {
      if (config.type === "text") {
        state.filters[key] = input.value;
      }
      if (input.dataset.rangeMin || input.dataset.rangeMax) {
        if (input.value !== "" && parseFloat(input.value) < 0) {
          input.value = "0";
        }
        if (input.dataset.rangeMin) state.filters[key].min = input.value;
        if (input.dataset.rangeMax) state.filters[key].max = input.value;
      }
      if (input.dataset.setFilter) {
        if (input.checked) state.filters[key].add(input.value);
        else state.filters[key].delete(input.value);
      }
      render();
    });
  });

  const clearButton = els.popover.querySelector("[data-clear-filter]");
  clearButton?.addEventListener("click", () => {
    clearFilter(key);
    closeFilter();
    render();
  });
}

function closeFilter() {
  els.popover.hidden = true;
  els.popover.innerHTML = "";
}

function clearFilter(key) {
  const value = state.filters[key];
  if (value instanceof Set) value.clear();
  else if (typeof value === "object") {
    value.min = "";
    value.max = "";
  } else {
    state.filters[key] = "";
  }
}

function clearAllFilters() {
  Object.keys(state.filters).forEach(clearFilter);
  closeFilter();
  render();
}

function initEvents() {
  document.querySelectorAll(".th-control[data-filter]").forEach((control) => {
    const sortBtn = control.querySelector(".th-sort[data-sort]");
    control.addEventListener("click", (event) => {
      if (event.target.closest(".th-sort")) {
        closeFilter();
        const key = sortBtn?.dataset.sort;
        if (!key) return;
        if (state.sortKey === key) {
          state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
        } else {
          state.sortKey = key;
          state.sortDirection = "asc";
        }
        render();
        return;
      }
      if (!els.popover.hidden && els.popover.dataset.key === control.dataset.filter) {
        closeFilter();
        return;
      }
      els.popover.dataset.key = control.dataset.filter;
      openFilter(control.dataset.filter, control);
    });
  });

  document.addEventListener("click", (event) => {
    if (els.popover.hidden) return;
    if (els.popover.contains(event.target) || event.target.closest("[data-filter]")) return;
    closeFilter();
  });

  els.body.addEventListener("click", (event) => {
    const button = event.target.closest("[data-hide-id]");
    if (!button) return;
    const game = games.find((item) => item.id === button.dataset.hideId);
    if (!game) return;
    state.hiddenOverrides[game.id] = !isHidden(game);
    savePrefs();
    render();
    showToast(state.hiddenOverrides[game.id] ? "Игра скрыта" : "Игра возвращена");
  });

  els.showHidden.addEventListener("change", () => {
    state.showHidden = els.showHidden.checked;
    savePrefs();
    render();
  });

  els.themeButton.addEventListener("click", () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    savePrefs();
    render();
  });

  els.resetFilters.addEventListener("click", clearAllFilters);
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.remove("visible"), 1400);
}

loadPrefs();
initEvents();
render();
