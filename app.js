const STORAGE_KEY = "pc-coop-table-v3";

// Labels mirror what's shown in the table chips — filter labels are kept
// identical so users see one term, not two. Subtitle is a one-sentence
// definition rendered in light gray under the filter checkbox. Pulled from
// .claude/skills/shared/taxonomy.json so the skills and the UI agree.
const ONE_COPY = {
  "friend-pass": {
    label: "Friend Pass",
    rank: 3,
    tone: "good",
    subtitle: "Friend Pass / asymmetric — one owner can invite a non-owner."
  },
  "remote-play": {
    label: "Remote Play",
    rank: 2,
    tone: "warn",
    subtitle: "Local co-op only, played remotely via Steam Remote Play Together. One copy required."
  },
  none: {
    label: "Two copies",
    rank: 1,
    tone: "muted",
    subtitle: "Each player needs their own copy. Standard online multiplayer."
  }
};

const ENDING_TYPE = {
  story: {
    label: "Story",
    short: "Story",
    tone: "info",
    rank: 5,
    subtitle: "Narrative campaign with cutscenes and a defined finale."
  },
  levels: {
    label: "Levels",
    short: "Levels",
    tone: "muted",
    rank: 4,
    subtitle: "Discrete level / mission set with a defined last one. No procedural generation."
  },
  "arcade-goal": {
    label: "Goal",
    short: "Goal",
    tone: "good",
    rank: 3,
    subtitle: "Single-session win in 5–60 min. Restart to retry. No persistent meta-progress."
  },
  roguelite: {
    label: "Roguelite",
    short: "Roguelite",
    tone: "warn",
    rank: 2,
    subtitle: "Procedural runs with persistent meta-progress between attempts. Final boss = real ending."
  },
  "survival-goal": {
    label: "Survival",
    short: "Survival",
    tone: "bad",
    rank: 1,
    subtitle: "Open-ended survival with an explicit named win-condition (final boss / structure / rocket)."
  }
};

const TIER_VALUES = new Set(["AAA", "AA", "Indie"]);

// Faceted-filter axes for the Genres column. Mirrors the `axes` structure in
// .claude/skills/shared/taxonomy.json. Within an axis the filter is OR (pick
// First-person + Third-person → games matching either). Across axes it's AND
// (Tier=AAA AND View=Side-view → must be both). "FPS" is a legacy perspective
// tag still present in un-migrated data; it lives under the View axis until the
// taxonomy migration replaces it with First-person.
const GENRE_AXES = [
  { key: "tier", label: "Tier", tags: ["AAA", "AA", "Indie"] },
  { key: "perspective", label: "View", tags: ["First-person", "Third-person", "Isometric", "Side-view", "FPS"] },
  { key: "mechanic", label: "Genre", tags: ["Shooter", "Action", "Puzzle", "Platformer", "RPG", "Tactics", "Stealth", "Soulslike", "Loot", "Adventure"] },
  { key: "setting", label: "Setting", tags: ["Fantasy", "Sci-fi", "Horror", "Military"] },
  { key: "structure", label: "Structure", tags: ["Open World", "Survival"] }
];
const TAG_TO_AXIS = (() => {
  const map = {};
  for (const axis of GENRE_AXES) {
    for (const tag of axis.tags) map[tag] = axis.key;
  }
  return map;
})();
const OTHER_AXIS = "_other";

// 'FIT_RANK' has been removed as the 'Попадание' column is deleted

const state = {
  sortKey: "year",
  sortDirection: "desc",
  // "active" = unplayed only (default), "all" = everything, "played" = played only
  viewMode: "active",
  theme: "dark",
  // Maps gameId -> true (marked played) | false (explicitly unmarked).
  // Storage uses the older "hiddenOverrides" key — same shape, same semantics
  // (true == "this game is done"), just renamed for clarity.
  playedOverrides: {},
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
  viewMode: document.querySelector("#viewModeControl"),
  themeButton: document.querySelector("#themeButton"),
  resetFilters: document.querySelector("#resetFiltersButton"),
  videoModal: document.querySelector("#videoModal"),
  videoFrame: document.querySelector("#videoFrame")
};

const games = window.GAMES.map((game) => ({
  hidden: false,
  hiddenReason: "",
  ...game
}));

const filterConfig = {
  title: { type: "text", label: "Game", placeholder: "Title or verdict" },
  year: { type: "range", label: "Year", step: 1, min: 0 },
  rating: { type: "range", label: "Rating", step: 5, min: 0 },
  playersMax: { type: "range", label: "Players", step: 1, min: 0 },
  hours: { type: "range", label: "Hours", step: 1, min: 0 },
  genres: { type: "set", label: "Genres", options: () => uniqueSorted(games.flatMap((game) => game.genres)) },
  endingType: {
    type: "set",
    label: "Ending",
    options: () => Object.keys(ENDING_TYPE),
    labelFor: (value) => ENDING_TYPE[value]?.short || value,
    subtitleFor: (value) => ENDING_TYPE[value]?.subtitle || ""
  },
  oneCopy: {
    type: "set",
    label: "Copies",
    options: () => Object.keys(ONE_COPY),
    labelFor: (value) => ONE_COPY[value]?.label || value,
    subtitleFor: (value) => ONE_COPY[value]?.subtitle || ""
  },
  price: { type: "range", label: "Price", step: 50, min: 49 }
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
    // Forward-compat: viewMode supersedes the older showHidden boolean.
    if (typeof prefs.viewMode === "string") {
      state.viewMode = prefs.viewMode;
    } else if (prefs.showHidden) {
      state.viewMode = "all";
    }
    // Same: playedOverrides supersedes the older hiddenOverrides (same shape).
    state.playedOverrides = prefs.playedOverrides || prefs.hiddenOverrides || {};
  } catch {
    state.theme = "dark";
  }
}

function savePrefs() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    theme: state.theme,
    viewMode: state.viewMode,
    playedOverrides: state.playedOverrides
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

function isPlayed(game) {
  if (Object.prototype.hasOwnProperty.call(state.playedOverrides, game.id)) {
    return state.playedOverrides[game.id];
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

// Group a Set of selected genre tags by their axis. Returns { axisKey: [tags] }.
function groupSelectedGenresByAxis(selectedSet) {
  const byAxis = {};
  for (const tag of selectedSet) {
    const axis = TAG_TO_AXIS[tag] || OTHER_AXIS;
    (byAxis[axis] ||= []).push(tag);
  }
  return byAxis;
}

// Faceted genre match: OR within an axis, AND across axes.
// `genresByAxis` is the precomputed grouping (so callers can override one axis
// when computing per-option counts). When omitted, uses the live filter state.
function gameMatchesGenres(game, genresByAxis) {
  const byAxis = genresByAxis || groupSelectedGenresByAxis(state.filters.genres);
  const gameTags = new Set(game.genres);
  for (const axis of Object.keys(byAxis)) {
    const tags = byAxis[axis];
    if (tags.length === 0) continue;
    // OR within axis: game must have at least one of the selected tags
    if (!tags.some((t) => gameTags.has(t))) return false; // AND across axes
  }
  return true;
}

function gameMatchesFilters(game, opts) {
  const skipGenres = opts && opts.skipGenres;
  const genresOverride = opts && opts.genresByAxis;

  const played = isPlayed(game);
  if (state.viewMode === "active" && played) return false;
  if (state.viewMode === "played" && !played) return false;
  // "all" — no filtering by played state

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

  if (!skipGenres) {
    if (genresOverride) {
      // Count-probe path: always apply the provided axis grouping.
      if (!gameMatchesGenres(game, genresOverride)) return false;
    } else if (state.filters.genres.size > 0) {
      if (!gameMatchesGenres(game)) return false;
    }
  }
  if (state.filters.endingType.size > 0 && !state.filters.endingType.has(game.endingType)) return false;
  if (state.filters.oneCopy.size > 0 && !state.filters.oneCopy.has(game.oneCopy)) return false;

  return true;
}

// For the faceted Genres popover: how many games would match if `tag` (in
// `axisKey`) were the constraint for its axis, holding all OTHER axes' current
// selections + every non-genre filter fixed. Drives the live counts and the
// auto-disable of zero-count options. Same-axis siblings are ignored (OR
// semantics — adding another option in the same axis only widens).
function countForGenreOption(axisKey, tag) {
  const byAxis = groupSelectedGenresByAxis(state.filters.genres);
  // Replace this axis's selection with just `tag` for the count probe.
  const probe = { ...byAxis, [axisKey]: [tag] };
  let n = 0;
  for (const game of games) {
    if (gameMatchesFilters(game, { genresByAxis: probe })) n++;
  }
  return n;
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
  document.body.dataset.viewMode = state.viewMode;
  els.themeButton.lastChild.textContent = state.theme === "dark" ? " Light" : " Dark";

  els.viewMode.querySelectorAll(".view-mode-btn").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.view === state.viewMode);
  });

  const visibleGames = getVisibleGames();
  const playedCount = games.filter(isPlayed).length;

  els.body.innerHTML = visibleGames.map(renderRow).join("");
  els.empty.hidden = visibleGames.length > 0;
  els.caption.textContent = `Showing ${visibleGames.length} of ${games.length}. Played: ${playedCount}.`;
  renderSortIcons();
  renderActiveFilterButtons();
}

function renderRow(game) {
  const played = isPlayed(game);
  const oneCopy = ONE_COPY[game.oneCopy] || ONE_COPY.none;
  const priceDisplay = game.price > 0
    ? `<a class="price-link" href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">${game.price}&nbsp;₴</a>`
    : `<span class="detail">—</span>`;

  return `
    <tr class="${played ? "is-played" : ""}">
      <td class="image-cell">
        <a href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">
          <img src="${escapeHtml(game.imageUrl)}" alt="${escapeHtml(game.title)}" loading="lazy">
        </a>
      </td>
      <td class="title-cell">
        <a class="game-link" href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">${escapeHtml(game.title)}</a>
      </td>
      <td class="number-cell">${game.year}</td>
      <td><div class="tag-list">${game.genres.map((genre) => `<span class="tag${TIER_VALUES.has(genre) ? " tier" : ""}">${escapeHtml(genre)}</span>`).join("")}</div></td>
      <td>${renderEndingType(game.endingType)}</td>
      <td class="number-cell rating">${game.rating}</td>
      <td class="number-cell">${game.playersMax}</td>
      <td class="number-cell">${trimNumber(game.hours)}&nbsp;h</td>
      <td><span class="badge ${oneCopy.tone}">${escapeHtml(oneCopy.label)}</span></td>
      <td class="number-cell price-cell">${priceDisplay}</td>
      <td class="verdict-cell">${escapeHtml(game.verdict)}</td>
      <td>${renderYoutubeButton(game)}</td>
      <td class="action-cell">
        <button class="icon-action played-toggle" type="button" data-played-id="${escapeHtml(game.id)}" data-played="${played}" aria-label="${played ? "Unmark" : "Mark as played"} ${escapeHtml(game.title)}" aria-pressed="${played}">
          ${checkIcon()}
        </button>
      </td>
    </tr>
  `;
}

function trimNumber(value) {
  return Math.round(value);
}

function extractYoutubeId(url) {
  if (typeof url !== "string") return null;
  const match = url.match(/(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|v\/|shorts\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  return match ? match[1] : null;
}

function renderYoutubeButton(game) {
  const videoId = extractYoutubeId(game.youtubeUrl);
  const icon = `
    <svg class="yt-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path class="yt-icon-body" d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.378.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.12 2.136c1.873.505 9.378.505 9.378.505s7.505 0 9.378-.505a3.015 3.015 0 0 0 2.12-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814z"></path>
      <path class="yt-icon-play" d="M9.75 15.568V8.432L15.818 12z"></path>
    </svg>`;
  const aria = `aria-label="Gameplay — ${escapeHtml(game.title)}"`;
  if (videoId) {
    return `<button class="youtube-link" type="button" data-video-id="${videoId}" data-video-title="${escapeHtml(game.title)}" ${aria}>${icon}</button>`;
  }
  return `<a class="youtube-link" href="${escapeHtml(game.youtubeUrl)}" target="_blank" rel="noreferrer" ${aria}>${icon}</a>`;
}

function openVideo(videoId) {
  els.videoFrame.src = `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0&modestbranding=1`;
  els.videoModal.hidden = false;
  document.body.style.overflow = "hidden";
}

function closeVideo() {
  els.videoFrame.src = "";
  els.videoModal.hidden = true;
  document.body.style.overflow = "";
}

function renderEndingType(value) {
  const meta = ENDING_TYPE[value];
  if (!meta) return `<span class="detail">—</span>`;
  return `<span class="badge ending ${meta.tone}" data-ending="${escapeHtml(value)}">${escapeHtml(meta.short)}</span>`;
}

function checkIcon() {
  // YouTube-like "satisfying" toggle. Layers:
  //   1. .particle-burst — 8 radial particles that fly out on activation
  //   2. <circle> — fills green on activation (transition)
  //   3. Two tick paths — drawn one after another (pen-like motion: short
  //      stroke down-right, then longer stroke up-right with a brief pause
  //      between them). Each animates via stroke-dashoffset.
  // Animation timing is in CSS keyframes; total duration ~700ms.
  const particles = Array.from({ length: 8 }, (_, i) =>
    `<span class="particle" style="--angle:${i * 45}deg"></span>`
  ).join("");
  return `<span class="particle-burst" aria-hidden="true">${particles}</span>
  <svg class="check-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
    <circle class="check-icon-ring" cx="12" cy="12" r="9"></circle>
    <path class="check-icon-tick check-icon-tick-down" d="M7.2 12.6 L10.8 16.2" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"></path>
    <path class="check-icon-tick check-icon-tick-up" d="M10.8 16.2 L17 9" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"></path>
  </svg>`;
}

function renderSortIcons() {
  // Direction arrows were removed (they clipped the labels in narrow columns
  // and the user explicitly said direction doesn't matter to them visually).
  // Active sort column is marked with .is-active-sort on the <th> itself,
  // so the underline spans the full column width — not just the inner chip.
  document.querySelectorAll(".th-control[data-filter]").forEach((control) => {
    const key = control.querySelector("[data-sort]")?.dataset.sort;
    const th = control.closest("th");
    if (th) th.classList.toggle("is-active-sort", key === state.sortKey);
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
      <button class="button full" type="button" data-clear-filter="${escapeHtml(key)}">Clear</button>
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
      <div class="popover-title">${escapeHtml(config.label)}: min / max</div>
      <div class="range-grid">
        <input class="filter-input" type="number" inputmode="numeric" data-range-min="${escapeHtml(key)}" value="${escapeHtml(minValue)}" placeholder="${dataMin}" min="${inputMin}" step="${step}">
        <input class="filter-input" type="number" inputmode="numeric" data-range-max="${escapeHtml(key)}" value="${escapeHtml(maxValue)}" placeholder="${dataMax}" min="${inputMin}" step="${step}">
      </div>
      <button class="button full" type="button" data-clear-filter="${escapeHtml(key)}">Clear</button>
    `;
  }

  const selected = state.filters[key];

  // Genres is a faceted filter: render one labeled section per axis
  // (Tier / View / Genre / Setting / Structure). Each option shows a live
  // count and disables itself when picking it would yield zero results given
  // the other axes' current selections. OR within a section, AND across.
  if (key === "genres") {
    const present = new Set(config.options());
    const sectionsHtml = GENRE_AXES
      .map((axis) => {
        const tagsInData = axis.tags.filter((t) => present.has(t));
        if (tagsInData.length === 0) return "";
        const rows = tagsInData
          .map((value) => {
            const count = countForGenreOption(axis.key, value);
            const isChecked = selected.has(value);
            const isDisabled = count === 0 && !isChecked;
            return `
              <label class="check-row faceted${isDisabled ? " disabled" : ""}">
                <input type="checkbox" data-set-filter="genres" value="${escapeHtml(value)}" ${isChecked ? "checked" : ""} ${isDisabled ? "disabled" : ""}>
                <span class="check-label">${escapeHtml(value)}</span>
                <span class="check-count">${count}</span>
              </label>
            `;
          })
          .join("");
        return `
          <div class="facet-section">
            <div class="facet-heading">${escapeHtml(axis.label)}</div>
            ${rows}
          </div>
        `;
      })
      .filter(Boolean)
      .join('<hr class="filter-divider">');
    return `
      <div class="popover-title">${escapeHtml(config.label)}</div>
      <div class="checkbox-list faceted">
        ${sectionsHtml}
      </div>
      <button class="button full" type="button" data-clear-filter="genres">Clear</button>
    `;
  }

  // Simple single-list set filter (endingType, oneCopy) with optional subtitle.
  const options = config.options();
  const renderRow = (value) => {
    const labelText = config.labelFor ? config.labelFor(value) : value;
    const subtitleText = config.subtitleFor ? config.subtitleFor(value) : "";
    const subtitleHtml = subtitleText
      ? `<div class="filter-subtitle">${escapeHtml(subtitleText)}</div>`
      : "";
    return `
      <label class="check-row${subtitleText ? " with-subtitle" : ""}">
        <input type="checkbox" data-set-filter="${escapeHtml(key)}" value="${escapeHtml(value)}" ${selected.has(value) ? "checked" : ""}>
        <div class="check-row-text">
          <span>${escapeHtml(labelText)}</span>
          ${subtitleHtml}
        </div>
      </label>
    `;
  };
  return `
    <div class="popover-title">${escapeHtml(config.label)}</div>
    <div class="checkbox-list">
      ${options.map(renderRow).join("")}
    </div>
    <button class="button full" type="button" data-clear-filter="${escapeHtml(key)}">Clear</button>
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
      // The faceted Genres popover shows live counts that depend on the
      // current selection, so re-render it in place after each toggle.
      if (key === "genres" && input.dataset.setFilter) {
        els.popover.innerHTML = renderFilterMarkup(key, config);
        bindFilterControls(key, config);
      }
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
          // Same column toggles direction. (Direction is not visualized but
          // changes which end of the list shows up first.)
          state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
        } else {
          // New column: pick a sensible default direction per data type so
          // the user rarely needs a second click. Numeric / rank-like columns
          // start descending (newest/highest first); textual columns ascending.
          state.sortKey = key;
          const numericDefaultDesc = new Set(["year", "rating", "playersMax", "hours", "price", "endingType", "oneCopy"]);
          state.sortDirection = numericDefaultDesc.has(key) ? "desc" : "asc";
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
    const ytButton = event.target.closest("[data-video-id]");
    if (ytButton) {
      event.preventDefault();
      openVideo(ytButton.dataset.videoId);
      return;
    }
    const button = event.target.closest("[data-played-id]");
    if (!button) return;
    const game = games.find((item) => item.id === button.dataset.playedId);
    if (!game) return;
    const next = !isPlayed(game);
    state.playedOverrides[game.id] = next;
    // Trigger the satisfying animation on the existing element BEFORE the
    // row's eventual re-render. data-played flips immediately so the CSS
    // transitions (green fill, tick draw-in) run while the row is still in
    // place. The full animation is ~720ms — re-render is delayed so the user
    // sees the whole sequence even when the row is about to be filtered out
    // of the active view.
    button.dataset.played = String(next);
    if (next) button.classList.add("is-toggling");
    setTimeout(() => {
      savePrefs();
      render();
    }, next ? 760 : 220);
    showToast(next ? "Marked as played" : "Unmarked");
  });

  els.videoModal.addEventListener("click", (event) => {
    if (event.target.closest("[data-close]")) closeVideo();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !els.videoModal.hidden) closeVideo();
  });

  els.viewMode.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-view]");
    if (!btn) return;
    state.viewMode = btn.dataset.view;
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
