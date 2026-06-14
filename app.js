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
    label: "Survival win",
    short: "Survival win",
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
  { key: "mechanic", label: "Genre", tags: ["Shooter", "Action", "Brawler", "Racing", "Puzzle", "Platformer", "RPG", "Tactics", "Stealth", "Soulslike", "Loot", "Adventure"] },
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
    ratingCount: { min: "", max: "" },
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
  activeFilters: document.querySelector("#activeFilters"),
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
  // ratingCount has no column header of its own — it's rendered as a second
  // range control inside the Rating popover. Config is used by the range
  // helpers (extents / active-state) and the URL sync.
  ratingCount: { type: "range", label: "Reviews", step: 50, min: 0 },
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
  price: { type: "range", label: "Price", step: 50, min: 0 }
};

function getRangeExtents(key) {
  // Keep 0 in scope: price 0 = a legitimately free game, and the floor must be
  // 0 so those games stay inside the Price range (no other column has a real 0).
  const values = games.map((g) => Number(g[key])).filter((v) => !isNaN(v) && v >= 0);
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

// --- Shareable URL: reflect all active filters/sort/view in the query string so
// a link reproduces the same view for someone else. Range params encode as
// "min-max" (either side may be empty); sets as comma lists. Defaults are omitted
// to keep the URL clean. history.replaceState avoids polluting back-history.
const RANGE_PARAMS = [["year", "year"], ["rating", "rating"], ["ratingCount", "reviews"], ["playersMax", "players"], ["hours", "hours"], ["price", "price"]];

function syncURL() {
  const p = new URLSearchParams();
  const f = state.filters;
  if (f.title) p.set("q", f.title);
  for (const [key, param] of RANGE_PARAMS) {
    const r = f[key];
    if (r.min !== "" || r.max !== "") p.set(param, `${r.min}-${r.max}`);
  }
  if (f.genres.size) p.set("genres", [...f.genres].join(","));
  if (f.endingType.size) p.set("ending", [...f.endingType].join(","));
  if (f.oneCopy.size) p.set("copies", [...f.oneCopy].join(","));
  if (!(state.sortKey === "year" && state.sortDirection === "desc")) p.set("sort", `${state.sortKey}:${state.sortDirection}`);
  if (state.viewMode !== "active") p.set("view", state.viewMode);
  const qs = p.toString();
  history.replaceState(null, "", qs ? `${location.pathname}?${qs}` : location.pathname);
}

// Sanitize a range bound parsed from the URL: a negative value would invert the
// filter (e.g. max=-100 hides every row), so drop it to "" (no constraint).
// Mirrors the live-input guard in bindFilterControls.
function clampRangeBound(raw) {
  if (raw === "") return "";
  return parseFloat(raw) < 0 ? "" : raw;
}

function applyFiltersFromURL() {
  const p = new URLSearchParams(location.search);
  if (![...p.keys()].length) return;
  const f = state.filters;
  if (p.has("q")) f.title = p.get("q");
  for (const [key, param] of RANGE_PARAMS) {
    if (p.has(param)) {
      const raw = p.get(param);
      const idx = raw.indexOf("-");
      if (idx === -1) {
        f[key] = { min: clampRangeBound(raw), max: "" };
      } else if (raw.indexOf("-", idx + 1) !== -1) {
        // More than one '-' (e.g. "50--100") would mis-split into a negative
        // bound; treat the whole range as malformed and ignore it.
        continue;
      } else {
        f[key] = { min: clampRangeBound(raw.slice(0, idx)), max: clampRangeBound(raw.slice(idx + 1)) };
      }
    }
  }
  if (p.has("genres")) f.genres = new Set(p.get("genres").split(",").filter((t) => TAG_TO_AXIS[t]));
  if (p.has("ending")) f.endingType = new Set(p.get("ending").split(",").filter(Boolean));
  if (p.has("copies")) f.oneCopy = new Set(p.get("copies").split(",").filter(Boolean));
  if (p.has("sort")) {
    const [k, d] = p.get("sort").split(":");
    const SORT_KEYS = ["year", "rating", "playersMax", "hours", "price", "genres", "endingType", "oneCopy", "title", "verdict"];
    if (SORT_KEYS.includes(k)) state.sortKey = k;
    if (d === "asc" || d === "desc") state.sortDirection = d;
  }
  if (p.has("view") && ["active", "all", "played"].includes(p.get("view"))) state.viewMode = p.get("view");
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
  // The Rating column sorts by the Wilson lower-bound score (Steam %positive
  // discounted for review count), not the raw %. See WHY-4 in CLAUDE.md.
  if (key === "rating") return wilsonScore(game);
  // Verdict sorts by finish strength: a clear (hard) finish first, a fuzzy
  // (soft) finish — marked with a leading 🟠 in the verdict — second.
  if (key === "verdict") return (game.verdict || "").trimStart().startsWith("🟠") ? 1 : 0;
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
    const haystack = [game.title, game.verdict, game.genres.join(" ")].join(" ").toLowerCase();
    if (!haystack.includes(text)) return false;
  }

  for (const key of ["year", "rating", "ratingCount", "playersMax", "hours", "price"]) {
    const filter = state.filters[key];
    if (filter.min === "" && filter.max === "") continue;
    const value = Number(game[key]);
    // An ACTIVE range can't admit an unknown value (e.g. a fresh add with no
    // ratingCount yet): NaN comparisons are always false, which would wrongly
    // let it slip past a "min reviews" filter. Exclude it instead.
    if (isNaN(value)) return false;
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
  syncURL();
  document.body.dataset.theme = state.theme;
  document.body.dataset.viewMode = state.viewMode;
  const themeLabel = els.themeButton.querySelector(".btn-label");
  if (themeLabel) themeLabel.textContent = state.theme === "dark" ? " Light" : " Dark";

  els.viewMode.querySelectorAll(".view-mode-btn").forEach((btn) => {
    const isActive = btn.dataset.view === state.viewMode;
    btn.classList.toggle("is-active", isActive);
    btn.setAttribute("aria-selected", String(isActive));
  });

  const visibleGames = getVisibleGames();
  const playedCount = games.filter(isPlayed).length;

  els.body.innerHTML = visibleGames.map(renderRow).join("");
  els.empty.hidden = visibleGames.length > 0;
  els.caption.textContent = `Showing ${visibleGames.length} of ${games.length}. Played: ${playedCount}.`;
  renderSortIcons();
  renderActiveFilterButtons();
}

// Patch the table after a single Played toggle WITHOUT rebuilding every row.
// Toggles the row's styling in place; drops it if it no longer belongs to the
// current view (To play / Played); refreshes caption + empty state from the
// live DOM. A one-row change should cost one row, not an 851-row re-render.
function refreshAfterPlayedToggle(game, tr) {
  savePrefs();
  const nowPlayed = isPlayed(game);
  if (tr) {
    tr.classList.toggle("is-played", nowPlayed);
    const inView =
      state.viewMode === "all" ||
      (state.viewMode === "active" && !nowPlayed) ||
      (state.viewMode === "played" && nowPlayed);
    if (!inView) tr.remove();
  }
  const visibleCount = els.body.querySelectorAll("tr").length;
  const playedCount = games.filter(isPlayed).length;
  els.empty.hidden = visibleCount > 0;
  els.caption.textContent = `Showing ${visibleCount} of ${games.length}. Played: ${playedCount}.`;
}

// --- Resilient header images -------------------------------------------------
// Steam header art has no single durable URL: the hash-less path
// /steam/apps/<id>/header.jpg works for established apps but 404s for the very
// newest; the hashed store_item_assets/<hash>/header.jpg works for new apps but
// goes stale when a dev re-uploads art (the hash in the path changes -> 404).
// On top of that, a single CDN host can be regionally unreachable while the
// asset is fine elsewhere. So the <img> is given an ordered failover list and a
// delegated 'error' handler walks it host-by-host, ending on an inline SVG that
// can never itself fail. The cron + write-guard keep the STORED url durable;
// this is the client-side safety net for drift + regional flakiness.
const IMG_PLACEHOLDER =
  "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%20460%20215'%3E%3Crect%20width='460'%20height='215'%20fill='%231b1f29'/%3E%3Ctext%20x='230'%20y='112'%20fill='%235b6577'%20font-family='sans-serif'%20font-size='22'%20text-anchor='middle'%3Eno%20image%3C/text%3E%3C/svg%3E";
const imgResolved = new Map(); // appId -> first src that successfully loaded this session

function steamAppId(storeUrl) {
  const m = /\/app\/(\d+)/.exec(storeUrl || "");
  return m ? m[1] : "";
}

// Ordered failover URLs for one app, derived from the appid + the form of the
// url that just failed. Host families don't cross: shared.* serves the hashed
// store_item_assets path, cdn.* serves the hash-less path (each on all three CDN
// vendors). Terminates on the inline placeholder.
function buildImgCandidates(appId, failedSrc) {
  const list = [failedSrc];
  if (appId) {
    const hashed = /\/store_item_assets\/steam\/apps\/\d+\/([0-9a-f]{8,})\/header\.jpg/.exec(failedSrc || "");
    if (hashed) {
      const path = `/store_item_assets/steam/apps/${appId}/${hashed[1]}/header.jpg`;
      ["shared.akamai", "shared.fastly", "shared.cloudflare"].forEach((h) =>
        list.push(`https://${h}.steamstatic.com${path}`)
      );
    }
    // Hash-less variants double as the cure for a drifted hash on an established
    // app, and as the host-swap for a regionally blocked CDN host.
    ["cdn.cloudflare", "cdn.akamai", "cdn.fastly"].forEach((h) =>
      list.push(`https://${h}.steamstatic.com/steam/apps/${appId}/header.jpg`)
    );
  }
  list.push(IMG_PLACEHOLDER);
  return [...new Set(list)];
}

// Delegated, capture-phase (error does NOT bubble) handler on the tbody. Walks
// the candidate list via a data-attr index so it survives the innerHTML rebuilds
// render() does, and can never infinite-loop (index advances, skips dupes, and
// the last candidate is a no-network data URI).
function onImgError(event) {
  const img = event.target;
  if (!(img instanceof HTMLImageElement) || !img.classList.contains("thumb")) return;
  if (img.dataset.imgDone) return;
  const cands = buildImgCandidates(img.dataset.app, img.getAttribute("src"));
  let idx = Number(img.dataset.imgIdx || 0);
  let next;
  do {
    idx += 1;
    next = cands[idx];
  } while (next && next === img.getAttribute("src"));
  if (!next) {
    img.dataset.imgDone = "1";
    return;
  }
  img.dataset.imgIdx = String(idx);
  if (idx >= cands.length - 1) img.dataset.imgDone = "1"; // reached the placeholder
  img.src = next;
}

// Remember the first url that actually loaded for an app, so re-renders
// (filter/sort/played-toggle rebuild the whole tbody) reuse it instead of
// re-walking the failover chain. Never memoize the inline placeholder.
function onImgLoad(event) {
  const img = event.target;
  if (!(img instanceof HTMLImageElement) || !img.classList.contains("thumb")) return;
  const appId = img.dataset.app;
  if (!appId || imgResolved.has(appId)) return;
  const src = img.getAttribute("src");
  if (src && src.slice(0, 5) !== "data:") imgResolved.set(appId, src);
}

function renderRow(game) {
  const played = isPlayed(game);
  const oneCopy = ONE_COPY[game.oneCopy] || ONE_COPY.none;
  const priceDisplay = `<a class="price-link" href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">${game.price}&nbsp;₴</a>`;
  const appId = steamAppId(game.storeUrl);
  const imgSrc = (appId && imgResolved.get(appId)) || game.imageUrl;

  return `
    <tr class="${played ? "is-played" : ""}">
      <td class="image-cell">
        <a href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">
          <img class="thumb" src="${escapeHtml(imgSrc)}" alt="${escapeHtml(game.title)}" loading="lazy" decoding="async" width="100" height="47"${appId ? ` data-app="${appId}"` : ""}>
        </a>
      </td>
      <td class="title-cell">
        <a class="game-link" href="${escapeHtml(game.storeUrl)}" target="_blank" rel="noreferrer">${escapeHtml(game.title)}</a>
      </td>
      <td class="number-cell">${game.year}</td>
      <td><div class="tag-list">${game.genres.map((genre) => `<span class="tag${TIER_VALUES.has(genre) ? " tier" : ""}">${escapeHtml(genre)}</span>`).join("")}</div></td>
      <td>${renderEndingType(game.endingType)}</td>
      <td class="number-cell rating" title="Wilson score — Steam %positive adjusted for how many reviews back it (95% confidence lower bound); the column sorts by this. Sub-line: review count · raw Steam %.">${renderRatingCell(game)}</td>
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

// Wilson lower bound of the positive fraction at 95% confidence, scaled to
// 0-100. This is what the Rating column sorts by: it discounts a high %positive
// that rests on few reviews (a 100%-of-10 indie scores well below a 96%-of-40k
// AAA), while a well-reviewed game stays near its raw %. Returns 0 when the
// review count is missing/zero so such rows sort to the bottom. See WHY-4.
function wilsonScore(game) {
  const n = Number(game.ratingCount);
  const pct = Number(game.rating);
  if (!(n > 0) || isNaN(pct)) return 0;
  const z = 1.96;
  const p = pct / 100;
  const denom = 1 + (z * z) / n;
  const centre = p + (z * z) / (2 * n);
  const margin = z * Math.sqrt((p * (1 - p) + (z * z) / (4 * n)) / n);
  return ((centre - margin) / denom) * 100;
}

// Compact review-count label: 640, 1.2K, 25K, 1.5M (3 zeros collapse to K/M so
// it fits under the score). Returns "—" when there's no count.
function formatReviewCount(value) {
  const n = Number(value);
  if (!(n > 0)) return "—";
  if (n < 1000) return String(n);
  if (n < 1000000) {
    const k = n / 1000;
    const r = k < 10 ? Math.round(k * 10) / 10 : Math.round(k);
    // r === 1000 only for n in [999500, 999999]; fall through so it reads "1M".
    if (r < 1000) return (Number.isInteger(r) ? String(r) : r.toFixed(1)) + "K";
  }
  const m = n / 1000000;
  const r = m < 10 ? Math.round(m * 10) / 10 : Math.round(m);
  return (Number.isInteger(r) ? String(r) : r.toFixed(1)) + "M";
}

// Rating cell: the Wilson score big, with a sub-caption of "<reviews> · <Steam %>"
// — the raw inputs the score is computed from. If a row has no review count yet
// (a fresh add the cron hasn't reached), fall back to showing the raw % big and
// "—" below; it still sorts to the bottom via wilsonScore() === 0.
function renderRatingCell(game) {
  const count = Number(game.ratingCount);
  const pct = Number(game.rating);
  const hasData = count > 0 && !isNaN(pct);
  const big = hasData ? Math.round(wilsonScore(game)) : (isNaN(pct) ? "—" : pct);
  const sub = hasData ? `${formatReviewCount(count)} · ${pct}%` : "—";
  return `<span class="wilson-score">${big}</span><span class="rating-sub">${sub}</span>`;
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

// === YouTube fast-open (Approach F: preconnect + warm-on-first-interaction +
// pointer pre-buffer + reveal/unmute on click) ================================
//
// Goal: minimize wall-clock from the user's click on a YouTube icon to the
// video actually PLAYING. We attack every step that the old code paid ON the
// click: DNS/TLS to YouTube (now preconnected in <head>), fetching+parsing the
// player JS (now loaded on first interaction), and buffering the specific video
// (now started MUTED on pointerenter/pointerdown, BEFORE the modal is shown).
// On the actual click we only reveal the modal and unmute — the gesture that
// authorizes sound — so playback is typically already running by then.
//
// Mechanism uses the YouTube IFrame Player API so we can (a) pre-buffer a video
// muted without showing it, (b) flip mute off on the click gesture, and (c) get
// a precise PLAYING signal for instrumentation. A single persistent player is
// reused for all 800+ rows — we never create per-row iframes.

const YT_EMBED_HOST = "https://www.youtube-nocookie.com";

// Cold fallback used only when the IFrame Player API never loads (blocked /
// offline / very slow). Replaces the #videoFrame element with a plain autoplay
// iframe by the same id so `.video-modal iframe` CSS still applies. autoplay=1
// with a real user gesture (the click) gets sound; no API means no muted
// pre-buffer, but preconnect still removed the DNS/TLS cost from the click.
function fallbackIframe(videoId) {
  const host = document.querySelector("#videoFrame");
  if (!host) return;
  let frame = host;
  if (frame.tagName !== "IFRAME") {
    frame = document.createElement("iframe");
    frame.id = "videoFrame";
    frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    frame.allowFullscreen = true;
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    frame.title = "Gameplay video";
    host.replaceWith(frame);
    els.videoFrame = frame; // keep the cached ref live for closeVideo()
  }
  frame.src = `${YT_EMBED_HOST}/embed/${videoId}?autoplay=1&rel=0&modestbranding=1&playsinline=1`;
}

// Instrumentation: set to true to log "click->play Xms" to the console.
// Guarded so it ships off; flip to true (or set window.YT_PERF=true before load)
// to measure. Times from the click gesture to the first PLAYING state.
const YT_PERF = false;
// Debug / benchmark via URL params — no rebuild, no branch-switch needed:
//   ?ytperf=1   -> log + on-screen TOAST of "click->play Nms (new|legacy)"
//   ?yt=legacy  -> disable the preconnect-prewarm fast path (always cold-load),
//                  so you can A/B it against the new path by just changing the URL.
const YT_PARAMS = (typeof location !== "undefined") ? new URLSearchParams(location.search) : new URLSearchParams();
const YT_PERF_PARAM = YT_PARAMS.has("ytperf");
const YT_LEGACY = YT_PARAMS.get("yt") === "legacy";
function ytPerfOn() { return YT_PERF || YT_PERF_PARAM || (typeof window !== "undefined" && window.YT_PERF); }
function ytPerfReport(ms) {
  const tag = YT_LEGACY ? "legacy" : "new";
  console.log(`[yt] click->play ${ms}ms (${tag})`);
  if (typeof showToast === "function") showToast(`click→play ${ms}ms (${tag})`);
}
let ytClickAt = 0; // performance.now() captured at the click gesture

const ytState = {
  apiRequested: false, // IFrame API <script> injected?
  player: null,        // YT.Player instance once ready
  ready: false,        // player fired onReady?
  prebufferedId: null, // videoId we've cued/buffered muted (modal still hidden)
  pendingPlayId: null, // videoId to reveal+play as soon as the player is ready
  revealed: false,     // is the modal actually OPEN (user clicked), not just prebuffering?
  usedFallback: false, // a plain <iframe> took over (API never arrived by click)
  trigger: null        // the icon that opened the modal, to restore focus on close
};

// Load the IFrame Player API exactly once. Called on the FIRST user interaction
// (pointerdown/touchstart/keydown anywhere) so it never blocks first paint, yet
// is almost always ready by the time a YouTube icon is actually clicked.
function warmYouTube() {
  if (ytState.apiRequested) return;
  ytState.apiRequested = true;
  // If another script already pulled the API in, just build the player.
  if (window.YT && window.YT.Player) { createYtPlayer(); return; }
  const prev = window.onYouTubeIframeAPIReady;
  window.onYouTubeIframeAPIReady = () => {
    if (typeof prev === "function") { try { prev(); } catch (_) {} }
    createYtPlayer();
  };
  const s = document.createElement("script");
  s.src = "https://www.youtube.com/iframe_api";
  s.async = true;
  document.head.appendChild(s);
}

function createYtPlayer() {
  if (ytState.player || ytState.usedFallback) return;
  // Adopt the existing #videoFrame iframe as a YT.Player. Start with no video
  // (autoplay off) and muted — nothing is shown until the modal opens.
  ytState.player = new YT.Player("videoFrame", {
    host: YT_EMBED_HOST,
    playerVars: {
      autoplay: 0,
      rel: 0,
      modestbranding: 1,
      playsinline: 1,
      enablejsapi: 1,
      // REQUIRED for enablejsapi: without it the API posts commands to the wrong
      // origin (it guessed https:// on an http:// page) — postMessage is rejected,
      // commands (play/unMute/seek) never reach the player, and the iframe stays
      // white. Pin it to OUR page origin so every postMessage matches.
      origin: (typeof location !== "undefined" ? location.origin : undefined)
    },
    events: {
      onReady: onYtReady,
      onError: onYtError,
      onStateChange: onYtStateChange
    }
  });
}

function onYtReady() {
  ytState.ready = true;
  try { ytState.player.mute(); } catch (_) {}
  // The API replaced the #videoFrame div with its own iframe — re-cache the live
  // element so closeVideo()/fallback never touch the detached placeholder.
  try { els.videoFrame = ytState.player.getIframe(); } catch (_) {}
  // If the user already clicked an icon while the API was still loading, honor
  // that now: reveal + play with sound (the original click was the gesture).
  if (ytState.pendingPlayId) {
    playRevealed(ytState.pendingPlayId);
  } else if (ytState.prebufferedId) {
    // A hover/pointerdown asked us to pre-buffer before we were ready; do it now
    // (muted, modal stays hidden).
    prebufferVideo(ytState.prebufferedId);
  }
}

function onYtStateChange(e) {
  if (!ytPerfOn()) return;
  // YT.PlayerState.PLAYING === 1
  if (e && e.data === 1 && ytClickAt) {
    ytPerfReport(Math.round(performance.now() - ytClickAt));
    ytClickAt = 0; // log once per open
  }
}

// YouTube playback error (e.data: 2 bad id, 5 HTML5 transient, 100 removed,
// 101/150 embedding-off). Many are transient — the "An error occurred, try
// again" that clears on a second open. Retry the current video ONCE; the
// _erroredId guard prevents a loop. Only while the modal is actually open.
function onYtError(e) {
  if (!ytState.revealed) return;
  const code = e && e.data;
  const id = ytState.prebufferedId;
  if (!id) return;
  // Codes 100 (removed), 101/150 (embedding disabled) are PERMANENT — retrying
  // loops uselessly. Only 5 (HTML5 transient) and 2 (bad param) are retryable.
  if (code !== 5 && code !== 2) {
    if (typeof showToast === "function") showToast("This video is unavailable — try opening it on YouTube.");
    return;
  }
  if (ytState._erroredId === id) return; // already retried this one
  ytState._erroredId = id;
  try { ytState.player.loadVideoById(id); } catch (_) { return; } // don't swallow the load failure
  try { ytState.player.unMute(); ytState.player.setVolume(100); } catch (_) {}
}

// Pre-buffer a video MUTED with the modal still hidden. Satisfies autoplay
// policy (muted autoplay is always allowed) so frames start downloading/decoding
// before the user commits. Idempotent per id. Cancels any earlier pre-buffer so
// we never have more than one video in flight — no request storm across rows.
function prebufferVideo(videoId) {
  if (!videoId) return;
  if (YT_LEGACY) return; // A/B: legacy mode never prewarms — the click loads cold
  // Respect Save-Data / metered connections: skip speculative muted buffering.
  if (navigator.connection && navigator.connection.saveData) return;
  // Don't prewarm WHILE the table is scrolling: as the page moves under a
  // stationary cursor, pointerover fires on every row passing beneath it. Each
  // would kick a loadVideoById — a request/decode storm that stutters the
  // scroll. The scroll handler clears this flag ~250ms after motion stops.
  if (ytState.scrolling) return;
  warmYouTube();
  if (!ytState.ready || !ytState.player) {
    // Remember the latest hover target; onYtReady will pick it up.
    ytState.prebufferedId = videoId;
    return;
  }
  if (ytState.prebufferedId === videoId && !ytState.revealed) return; // already buffering this one
  if (ytState.revealed) return; // a video is on screen; don't yank it for a hover
  ytState.prebufferedId = videoId;
  try {
    ytState.player.mute();
    // The iframe must have real (non-zero) dimensions or the browser will stall
    // a hidden video. So we put the modal into a "prebuffer" state: rendered and
    // laid out (iframe has size) but fully transparent + non-interactive + no
    // backdrop — the user sees and hears nothing. CSS keys off [data-prebuffer].
    if (els.videoModal.hidden) {
      els.videoModal.hidden = false;
      els.videoModal.dataset.prebuffer = "1";
      els.videoModal.setAttribute("aria-hidden", "true"); // invisible buffer: hide from assistive tech
    }
    // loadVideoById starts buffering AND playing (muted) immediately, which is
    // what pre-warms the decode pipeline; while data-prebuffer is set the user
    // sees nothing and hears nothing until they click.
    ytState.player.loadVideoById(videoId);
  } catch (_) {
    ytState.prebufferedId = null;
    if (els.videoModal.dataset.prebuffer) {
      els.videoModal.hidden = true;
      delete els.videoModal.dataset.prebuffer;
    }
  }
}

// Tear down a hover pre-buffer that was never clicked: stop the muted video and
// dismiss the transparent prebuffer modal. No-op once the video is revealed (a
// real open owns the player now) so a stray pointerout can't kill a playing
// video the user just clicked into.
function cancelPrebuffer() {
  if (ytState.revealed) return;
  if (!ytState.prebufferedId && !els.videoModal.dataset.prebuffer) return;
  ytState.prebufferedId = null;
  if (els.videoModal.dataset.prebuffer) {
    els.videoModal.hidden = true;
    delete els.videoModal.dataset.prebuffer;
    els.videoModal.removeAttribute("aria-hidden");
  }
  if (ytState.player && ytState.ready) {
    try { ytState.player.stopVideo(); ytState.player.mute(); } catch (_) {}
  }
}

// Reveal the modal and play WITH SOUND. Called from the click handler (the user
// gesture that authorizes unmuted audio). If we pre-buffered this exact id, the
// video is already running muted — we just unmute + reveal (near-instant). If
// not (cold click, or a different id), we load it now.
function playRevealed(videoId) {
  ytState.pendingPlayId = null;
  ytState._erroredId = null; // fresh open of any video gets a fresh retry budget
  ytState.revealed = true;
  els.videoModal.hidden = false;
  delete els.videoModal.dataset.prebuffer; // exit prebuffer → fully visible
  els.videoModal.removeAttribute("aria-hidden");
  document.body.style.overflow = "hidden";
  try {
    if (ytState.prebufferedId === videoId) {
      // Hot path: already buffered muted. Unmute (gesture allows it) + ensure
      // it's playing. No new network round-trip for the embed/player. Set volume
      // BEFORE unmuting so audio doesn't briefly play at the wrong level.
      ytState.player.setVolume(100);
      ytState.player.unMute();
      ytState.player.playVideo();
      // NB: no seekTo(0) — seeking a still-buffering prewarmed video throws
      // YouTube error 5 ("An error occurred, try again", clears on 2nd open).
      // A short hover only advances a couple seconds; not worth the breakage.
      // The video was likely ALREADY playing (muted) so onStateChange may not
      // re-fire PLAYING — log the (tiny) click->reveal time here so the metric
      // still captures the hot path. Guarded behind the perf flag.
      if (ytPerfOn() && ytClickAt && ytState.player.getPlayerState &&
          ytState.player.getPlayerState() === 1) {
        ytPerfReport(Math.round(performance.now() - ytClickAt));
        ytClickAt = 0;
      }
    } else {
      ytState.player.loadVideoById(videoId);
      ytState.player.setVolume(100);
      ytState.player.unMute();
    }
  } catch (_) {
    // Defensive fallback: drive a plain iframe directly (no API). Still off the
    // cold-DNS path thanks to preconnect.
    fallbackIframe(videoId);
  }
  ytState.prebufferedId = videoId; // the visible video is now this one
}

function openVideo(videoId) {
  if (ytPerfOn()) ytClickAt = performance.now();
  // Instant facade: paint the YouTube thumbnail behind the (still-spinning)
  // player so the modal is never an empty black box on a cold click. i.ytimg.com
  // is preconnected, so this is a single already-warm image fetch; the opaque
  // iframe paints over it the moment the first video frame is ready.
  const frameEl = els.videoModal.querySelector(".video-modal-frame");
  if (frameEl) frameEl.style.backgroundImage = `url("https://i.ytimg.com/vi/${videoId}/hqdefault.jpg")`;
  warmYouTube();
  if (ytState.ready && ytState.player) {
    playRevealed(videoId);
    return;
  }
  // API not ready at click (rare — it loads on the first interaction anywhere).
  // Don't wait for it: build a plain autoplay iframe SYNCHRONOUSLY inside this
  // click gesture so iOS/Safari grant sound (a delayed src set loses the gesture
  // and would force muted playback). Mark usedFallback so a late
  // onYouTubeIframeAPIReady doesn't also build a YT.Player over this iframe.
  ytState.usedFallback = true;
  ytState.revealed = true;
  els.videoModal.hidden = false;
  delete els.videoModal.dataset.prebuffer; // a click means: reveal it
  els.videoModal.removeAttribute("aria-hidden");
  document.body.style.overflow = "hidden";
  fallbackIframe(videoId);
}

function closeVideo() {
  els.videoModal.hidden = true;
  const frameEl = els.videoModal.querySelector(".video-modal-frame");
  if (frameEl) frameEl.style.backgroundImage = ""; // drop the thumbnail facade
  delete els.videoModal.dataset.prebuffer;
  els.videoModal.removeAttribute("aria-hidden");
  document.body.style.overflow = "";
  ytState.revealed = false;
  ytState.pendingPlayId = null;
  ytState.prebufferedId = null;
  ytState._erroredId = null;
  // STOP playback so no audio leaks after close. Stop the API player if present;
  // and if a plain fallback iframe took over, blank its src to tear it down.
  if (ytState.player && ytState.ready) {
    try { ytState.player.stopVideo(); ytState.player.mute(); } catch (_) {}
  }
  if (ytState.usedFallback) {
    // Tear down the raw fallback iframe AND restore a clean <div id="videoFrame">
    // so the API player can adopt it on the next open — don't stay stuck on the
    // fallback (losing prewarm) for the rest of the session.
    const frame = els.videoFrame || document.querySelector("#videoFrame");
    if (frame) {
      try { frame.src = ""; } catch (_) {}
      const div = document.createElement("div");
      div.id = "videoFrame";
      frame.replaceWith(div);
      els.videoFrame = div;
    }
    ytState.usedFallback = false;
  }
  // Return focus to the icon that opened the modal (keyboard a11y).
  if (ytState.trigger) {
    try { ytState.trigger.focus({ preventScroll: true }); } catch (_) {}
    ytState.trigger = null;
  }
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
  document.querySelectorAll("[data-sort]").forEach((sorter) => {
    const key = sorter.dataset.sort;
    const th = sorter.closest("th");
    if (th) th.classList.toggle("is-active-sort", key === state.sortKey);
  });
}

function renderActiveFilterButtons() {
  document.querySelectorAll("[data-filter]").forEach((control) => {
    const isActive = filterIsActive(control.dataset.filter);
    control.classList.toggle("has-active-filter", isActive);
  });
  renderActiveFilterChips();
}

// Build a removable chip per active filter dimension/value, mirroring the
// header-highlight state above. Each chip carries enough data-* to clear EXACTLY
// its own slice on click (a single genre tag / set value, or one whole range /
// text field) — see clearFilterChip. Returns nothing when no filter is active so
// the bar collapses entirely (rendered hidden).
function activeFilterChips() {
  const f = state.filters;
  const chips = [];

  if (f.title.trim()) {
    chips.push({ key: "title", value: "", label: `Search: ${f.title.trim()}` });
  }

  // Ranges: one chip per range field, label showing only the bound(s) that
  // actually constrain (min only → "≥ x", max only → "≤ y", both → "x–y").
  // rating + ratingCount are independent chips even though they share a popover.
  for (const key of ["year", "rating", "ratingCount", "playersMax", "hours", "price"]) {
    if (!rangeFilterActive(key)) continue;
    const value = state.filters[key];
    const { min: dataMin, max: dataMax } = getRangeExtents(key);
    const minActive = value.min !== "" && Number(value.min) > dataMin;
    const maxActive = value.max !== "" && Number(value.max) < dataMax;
    const name = filterConfig[key].label;
    let label;
    if (minActive && maxActive) label = `${name} ${value.min}–${value.max}`;
    else if (minActive) label = `${name} ≥ ${value.min}`;
    else label = `${name} ≤ ${value.max}`;
    chips.push({ key, value: "", label });
  }

  // Faceted genres: one chip per selected tag (clearing removes just that tag).
  for (const tag of f.genres) {
    chips.push({ key: "genres", value: tag, label: `Genre: ${tag}` });
  }

  // Multi-select sets: one chip per selected value, using the column's display
  // label for the value where it has one (e.g. ending-type short names).
  for (const setKey of ["endingType", "oneCopy"]) {
    const config = filterConfig[setKey];
    for (const value of f[setKey]) {
      const label = config.labelFor ? config.labelFor(value) : value;
      chips.push({ key: setKey, value, label });
    }
  }

  return chips;
}

function renderActiveFilterChips() {
  if (!els.activeFilters) return;
  const chips = activeFilterChips();
  els.activeFilters.hidden = chips.length === 0;
  els.activeFilters.innerHTML = chips
    .map((chip) => `
      <button class="filter-chip" type="button" data-chip-key="${escapeHtml(chip.key)}" data-chip-value="${escapeHtml(chip.value)}">
        <span class="filter-chip-label">${escapeHtml(chip.label)}</span>
        <span class="filter-chip-x" aria-hidden="true">×</span>
        <span class="visually-hidden">Remove filter</span>
      </button>`)
    .join("");
}

// Clear exactly the slice a chip represents, then re-render everything (table +
// headers + chips + URL). For single-value set chips (genres/ending/copies) this
// removes only that value and keeps the rest; for text/range chips it falls back
// to clearFilter, which clears that whole dimension. Note: clearFilter("rating")
// would ALSO wipe ratingCount (they share a popover), so the rating chip resets
// only its own bounds here to leave a separate Reviews chip intact.
function clearFilterChip(key, value) {
  const slot = state.filters[key];
  if (slot instanceof Set) {
    slot.delete(value);
  } else if (key === "rating") {
    slot.min = "";
    slot.max = "";
  } else {
    clearFilter(key);
  }
  render();
}

function rangeFilterActive(key) {
  const value = state.filters[key];
  const { min: dataMin, max: dataMax } = getRangeExtents(key);
  const minActive = value.min !== "" && Number(value.min) > dataMin;
  const maxActive = value.max !== "" && Number(value.max) < dataMax;
  return minActive || maxActive;
}

function filterIsActive(key) {
  const value = state.filters[key];
  if (value instanceof Set) return value.size > 0;
  // The Rating header trigger also covers the Reviews (ratingCount) control that
  // shares its popover, so it lights up if either bound is set.
  if (key === "rating") return rangeFilterActive("rating") || rangeFilterActive("ratingCount");
  const config = filterConfig[key];
  if (config && config.type === "range") return rangeFilterActive(key);
  if (typeof value === "object") return value.min !== "" || value.max !== "";
  return Boolean(value);
}

// Tracks the filter trigger that opened the popover, so Escape can return focus
// there (keyboard a11y). Set in openFilter, read by the Escape handler.
let lastFilterTrigger = null;

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
  capFilterHeight();
  lastFilterTrigger = button.querySelector(".filter-button");
  // Move focus into the popover so keyboard users land on the first control
  // (text/range input or first checkbox). preventScroll avoids a page jump.
  els.popover.querySelector("input, button")?.focus({ preventScroll: true });
}

// Keep the popover within the viewport: it grows with content, but if there's a
// scrollable option list, cap ITS height to the space from its top down to the
// screen bottom MINUS room for the Clear button below it (reserve) — so the
// popover grows yet the button stays on screen and the list scrolls when capped.
// Range/text filters (no list) cap the popover itself. MUST be re-run whenever
// the popover markup is rebuilt (the genres popover re-renders on every toggle,
// which would otherwise drop this inline max-height and let it spill off-screen).
function capFilterHeight() {
  const vGap = 12;
  // Reset any inline clamp left by a previous range/text popover so only the
  // active branch's computation applies (otherwise a set/list filter inherits
  // the old max-height and clips its option list + Clear button).
  els.popover.style.maxHeight = "";
  els.popover.style.overflowY = "";
  const list = els.popover.querySelector(".checkbox-list");
  if (list) {
    const footer = els.popover.querySelector(".popover-footer");
    const reserve = (footer ? footer.offsetHeight + 10 : 0) + 14; // footer + its margin-top + popover bottom padding
    const avail = window.innerHeight - list.getBoundingClientRect().top - reserve - vGap;
    list.style.maxHeight = `${Math.max(120, avail)}px`;
  } else {
    const top = els.popover.getBoundingClientRect().top;
    els.popover.style.maxHeight = `${Math.max(160, window.innerHeight - top - vGap)}px`;
    els.popover.style.overflowY = "auto";
  }
}

// The min/max input pair for one range field. Extracted so the Rating popover
// can stack two of them (Steam % + Reviews). Each input carries its OWN field
// key in data-range-min/max, so bindFilterControls routes edits to the right
// filter even when several ranges share one popover.
function rangeInputs(key) {
  const config = filterConfig[key];
  const filter = state.filters[key];
  const { min: dataMin, max: dataMax } = getRangeExtents(key);
  const step = config.step || 1;
  const inputMin = config.min !== undefined ? config.min : 0;
  const minValue = filter.min !== "" ? filter.min : String(dataMin);
  const maxValue = filter.max !== "" ? filter.max : String(dataMax);
  return `
    <div class="range-grid">
      <input class="filter-input" type="number" inputmode="numeric" data-range-min="${escapeHtml(key)}" value="${escapeHtml(minValue)}" placeholder="${dataMin}" min="${inputMin}" step="${step}">
      <input class="filter-input" type="number" inputmode="numeric" data-range-max="${escapeHtml(key)}" value="${escapeHtml(maxValue)}" placeholder="${dataMax}" min="${inputMin}" step="${step}">
    </div>
  `;
}

// Footer row shared by every popover: Clear (secondary) + Done (primary).
// Filters apply live on input, so Done only closes the popover.
function filterFooter(key) {
  return `
    <div class="popover-footer">
      <button class="button" type="button" data-clear-filter="${escapeHtml(key)}">Clear</button>
      <button class="button primary" type="button" data-close-filter>Done</button>
    </div>
  `;
}

function renderFilterMarkup(key, config) {
  if (config.type === "text") {
    return `
      <div class="popover-title">${escapeHtml(config.label)}</div>
      <input class="filter-input" data-text-filter="${escapeHtml(key)}" value="${escapeHtml(state.filters[key])}" placeholder="${escapeHtml(config.placeholder)}">
      ${filterFooter(key)}
    `;
  }

  // The Rating popover is special: TWO range controls — Steam % (the raw
  // `rating`) and minimum Reviews (`ratingCount`) — so you can ask for "highly
  // rated AND well-reviewed". The column itself still SORTS by the Wilson score.
  if (key === "rating") {
    return `
      <div class="popover-title">Rating — Steam % (min / max)</div>
      ${rangeInputs("rating")}
      <div class="popover-subhead">Reviews (min / max)</div>
      ${rangeInputs("ratingCount")}
      ${filterFooter("rating")}
    `;
  }

  if (config.type === "range") {
    return `
      <div class="popover-title">${escapeHtml(config.label)}: min / max</div>
      ${rangeInputs(key)}
      ${filterFooter(key)}
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
      ${filterFooter("genres")}
    `;
  }

  // Simple single-list set filter (endingType, oneCopy) with optional subtitle.
  const options = config.options();
  const renderOptionRow = (value) => {
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
      ${options.map(renderOptionRow).join("")}
    </div>
    ${filterFooter(key)}
  `;
}

let textFilterTimer = 0;

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
        if (input.dataset.rangeMin) state.filters[input.dataset.rangeMin].min = input.value;
        if (input.dataset.rangeMax) state.filters[input.dataset.rangeMax].max = input.value;
      }
      if (input.dataset.setFilter) {
        if (input.checked) state.filters[key].add(input.value);
        else state.filters[key].delete(input.value);
      }
      // Free-text typing fires per keystroke; coalesce the (full-table) render so
      // a fast typist doesn't trigger 851-row rebuilds mid-word. Range/checkbox
      // changes are discrete, so they render immediately.
      if (config.type === "text") {
        clearTimeout(textFilterTimer);
        textFilterTimer = setTimeout(render, 200);
        return;
      }
      render();
      // The faceted Genres popover shows live counts that depend on the
      // current selection, so re-render it in place after each toggle.
      if (key === "genres" && input.dataset.setFilter) {
        const toggledValue = input.value;
        els.popover.innerHTML = renderFilterMarkup(key, config);
        bindFilterControls(key, config);
        capFilterHeight();
        // The rebuild dropped the focused checkbox; restore focus to it so
        // keyboard users can keep toggling without losing their place.
        els.popover.querySelector(`input[data-set-filter="genres"][value="${CSS.escape(toggledValue)}"]`)?.focus({ preventScroll: true });
      }
    });
  });

  const clearButton = els.popover.querySelector("[data-clear-filter]");
  clearButton?.addEventListener("click", () => {
    clearFilter(key);
    closeFilter();
    render();
  });

  // Done just dismisses the popover — filters already applied live on input.
  const closeButton = els.popover.querySelector("[data-close-filter]");
  closeButton?.addEventListener("click", () => {
    closeFilter();
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
  // The Rating popover's Clear also resets the Reviews (ratingCount) control
  // that shares it.
  if (key === "rating") {
    state.filters.ratingCount.min = "";
    state.filters.ratingCount.max = "";
  }
}

function clearAllFilters() {
  Object.keys(state.filters).forEach(clearFilter);
  closeFilter();
  render();
}

function toggleSort(key) {
  if (!key) return;
  closeFilter();
  if (state.sortKey === key) {
    // Same column toggles direction. (Direction is not visualized but changes
    // which end of the list shows up first.)
    state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
  } else {
    // New column: pick a sensible default direction per data type so the user
    // rarely needs a second click. Numeric / rank-like columns start descending
    // (newest/highest first); textual columns ascending. Verdict is ascending so
    // a clear (hard) finish shows before a fuzzy (soft 🟠) one.
    state.sortKey = key;
    const numericDefaultDesc = new Set(["year", "rating", "playersMax", "hours", "price", "endingType", "oneCopy"]);
    state.sortDirection = numericDefaultDesc.has(key) ? "desc" : "asc";
  }
  render();
}

function initEvents() {
  document.querySelectorAll(".th-control[data-filter]").forEach((control) => {
    const sortBtn = control.querySelector(".th-sort[data-sort]");
    control.addEventListener("click", (event) => {
      if (event.target.closest(".th-sort")) {
        toggleSort(sortBtn?.dataset.sort);
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

  // Sort-only headers (no filter popover) — e.g. Verdict.
  document.querySelectorAll(".th-sort-only[data-sort]").forEach((btn) => {
    btn.addEventListener("click", () => toggleSort(btn.dataset.sort));
  });

  // Active-filter chips: one delegated handler — clicking a chip clears just its
  // own dimension/value (the chip list is rebuilt on every render).
  els.activeFilters?.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-chip-key]");
    if (!chip) return;
    clearFilterChip(chip.dataset.chipKey, chip.dataset.chipValue);
  });

  // A drag-select inside a number input can release the mouse OUTSIDE the
  // popover, firing a "click" whose target is outside — which would wrongly
  // close the popover mid-selection. So remember where the press STARTED: only
  // a click whose press origin AND release target are both genuinely outside
  // closes the popover.
  let pressStartedInside = false;
  document.addEventListener("mousedown", (event) => {
    pressStartedInside =
      !els.popover.hidden &&
      (els.popover.contains(event.target) || !!event.target.closest("[data-filter]"));
  });

  document.addEventListener("click", (event) => {
    const startedInside = pressStartedInside;
    pressStartedInside = false;
    if (els.popover.hidden) return;
    if (startedInside) return;
    if (els.popover.contains(event.target) || event.target.closest("[data-filter]")) return;
    closeFilter();
  });

  // Resilient header images: ONE delegated handler each for load/error, in the
  // CAPTURE phase (resource load/error events do not bubble, so a tbody-level
  // listener only sees child <img> events on the way down). Bound once here and
  // never removed — it survives every render() innerHTML rebuild of the rows.
  els.body.addEventListener("error", onImgError, { capture: true });
  els.body.addEventListener("load", onImgLoad, { capture: true });

  // --- YouTube pre-warming on the table -------------------------------------
  // Load the IFrame Player API as early as possible so it's READY before the
  // first click — otherwise the first click hits the no-API fallback (slower,
  // and no timing). Idle so it never blocks first paint; first interaction is a
  // backstop if idle is delayed.
  const warmOnce = () => warmYouTube();
  if (typeof requestIdleCallback === "function") requestIdleCallback(warmOnce, { timeout: 2500 });
  else setTimeout(warmOnce, 1200);
  ["pointerover", "pointerdown", "keydown"].forEach((ev) =>
    window.addEventListener(ev, warmOnce, { once: true, passive: true })
  );

  // Desktop pre-buffer (muted, modal stays hidden). Two triggers:
  //   • hovering anywhere on a game ROW -> prewarm that row's video after a short
  //     dwell. The cursor enters the row LONG before the tiny icon, so this is
  //     the big head start. The dwell avoids thrashing while scanning past rows.
  //   • hovering the icon itself -> prewarm immediately (no dwell).
  // Only ONE video is ever in flight (prebufferVideo swaps), so sweeping the
  // table can't storm YouTube.
  // While the table scrolls, a stationary cursor still receives pointerover for
  // every row sliding under it — that would storm prebufferVideo. Flag scrolling
  // so prewarm pauses, and clear it ~250ms after motion settles.
  let ytScrollTimer = 0;
  const scroller = els.body.closest(".table-wrap");
  if (scroller) {
    scroller.addEventListener("scroll", () => {
      ytState.scrolling = true;
      clearTimeout(ytScrollTimer);
      ytScrollTimer = setTimeout(() => { ytState.scrolling = false; }, 250);
    }, { passive: true });
  }

  let ytRowDwell = 0;
  els.body.addEventListener("pointerover", (event) => {
    if (event.pointerType === "touch") return;
    const icon = event.target.closest("[data-video-id]");
    if (icon) { clearTimeout(ytRowDwell); prebufferVideo(icon.dataset.videoId); return; }
    const row = event.target.closest("tr");
    const btn = row && row.querySelector("[data-video-id]");
    if (!btn) return;
    clearTimeout(ytRowDwell);
    const id = btn.dataset.videoId;
    ytRowDwell = setTimeout(() => prebufferVideo(id), 120);
  }, { passive: true });

  // Leaving the table entirely tears down an un-clicked silent pre-buffer (stop
  // the muted video, hide the transparent modal, free bandwidth). Row-to-row
  // moves DON'T cancel — the next row's pointerover just swaps the prewarm.
  els.body.addEventListener("pointerleave", () => {
    clearTimeout(ytRowDwell);
    cancelPrebuffer();
  });

  // pointerdown = earliest signal on touch (no hover) and just before the click.
  els.body.addEventListener("pointerdown", (event) => {
    const ytButton = event.target.closest("[data-video-id]");
    if (ytButton) prebufferVideo(ytButton.dataset.videoId);
  }, { passive: true });

  els.body.addEventListener("click", (event) => {
    const ytButton = event.target.closest("[data-video-id]");
    if (ytButton) {
      event.preventDefault();
      ytState.trigger = ytButton; // restore focus here on close (keyboard a11y)
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
    const toggledRow = button.closest("tr");
    setTimeout(() => refreshAfterPlayedToggle(game, toggledRow), next ? 760 : 220);
    showToast(next ? "Marked as played" : "Unmarked");
  });

  els.videoModal.addEventListener("click", (event) => {
    if (event.target.closest("[data-close]")) closeVideo();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (ytState.revealed) { // only close a genuinely-open modal, never a silent prebuffer
      closeVideo();
      return;
    }
    if (ytState.prebufferedId) { cancelPrebuffer(); return; } // clear a stuck silent prebuffer
    if (!els.popover.hidden) {
      closeFilter();
      lastFilterTrigger?.focus();
    }
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

  initStickyOffsets();
}

// Mobile: the title block scrolls away as ordinary flow content (no display
// toggling — that changed the document height and made the page jump). Only the
// controls bar + filter strip are sticky. We just need the filter strip to stick
// flush below the controls bar, so keep --controls-h in sync with the controls
// bar height. No scroll listener, no layout mutation = nothing to jerk.
function initStickyOffsets() {
  const controls = document.querySelector(".top-actions");
  const sync = () => {
    if (controls) {
      document.documentElement.style.setProperty("--controls-h", controls.offsetHeight + "px");
    }
  };
  window.addEventListener("resize", sync);
  sync();
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.remove("visible"), 1400);
}

loadPrefs();
applyFiltersFromURL();
initEvents();
render();
