/* SuperChat: no external libraries, no HTML injection, no client-side credentials. */
"use strict";
const $ = id => document.getElementById(id);
const input = $("message-input"), messages = $("messages"), scrollArea = $("scroll-area");
let conversations = [], activeId = null, storageKey = null, busy = false, ready = false;
const names = {flights: "Flights", shopping: "Shopping", cinema: "Cinema"};
const money = value => Number(value).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = String(text);
  return element;
}
function button(text, action, className = "small-button") {
  const element = node("button", className, text);
  element.type = "button";
  element.disabled = busy;
  element.addEventListener("click", action);
  return element;
}
function current() { return conversations.find(chat => chat.id === activeId); }
function save() {
  if (!storageKey) return;
  try {
    localStorage.setItem(storageKey, JSON.stringify(conversations));
    sessionStorage.setItem(storageKey + ".active", activeId || "");
  } catch { showNotice("Browser storage is full or unavailable. This chat works, but new messages may not survive a refresh."); }
}
function showNotice(text) { $("notice").textContent = text; $("notice").hidden = !text; }
function clearError() { $("error").replaceChildren(); $("error").hidden = true; }
function showError(text, retry) {
  const target = $("error");
  target.replaceChildren(node("span", "", text));
  if (retry) target.append(button("Retry safely", retry));
  target.hidden = false;
}
function setBusy(value) {
  busy = value;
  $("loading").hidden = !value;
  input.disabled = value || !!current()?.archived || !ready;
  $("send-button").disabled = value || !input.value.trim() || !!current()?.archived || !ready;
  document.querySelectorAll(".suggestion,.mixed-prompt,.new-chat,.conversation-button").forEach(element => { element.disabled = value || !ready; });
  document.querySelectorAll(".card-actions button,.card-actions input,.result-heading button,.cart-line button").forEach(element => {
    element.disabled = value || !ready || !!current()?.archived || element.dataset.unavailable === "true";
  });
  $("clear-history").disabled = value;
  document.querySelectorAll("#error button").forEach(element => { element.disabled = value; });
  $("chat-form").setAttribute("aria-busy", String(value));
}
function closeSidebar() {
  $("sidebar").classList.remove("open"); $("scrim").hidden = true;
  $("menu-button").setAttribute("aria-expanded", "false");
}
function newConversation() {
  if (busy || !ready) return;
  const existing = conversations.find(chat => !chat.turns.length && !chat.archived);
  if (existing) activeId = existing.id;
  else {
    const chat = {id: crypto.randomUUID(), sessionId: null, title: "New conversation", turns: [], updated: Date.now(), pending: null, archived: false};
    conversations.unshift(chat); activeId = chat.id;
  }
  save(); render(); closeSidebar(); input.focus();
}
function renderSidebar() {
  const list = $("conversation-list"); list.replaceChildren();
  const saved = conversations.filter(chat => chat.turns.length);
  $("empty-history").hidden = !!saved.length;
  list.hidden = !saved.length;
  saved.forEach(chat => {
    const item = button("", () => selectConversation(chat.id), "conversation-button" + (chat.id === activeId ? " active" : ""));
    item.append(node("span", "conversation-symbol", "◌"), node("span", "", chat.title));
    item.title = chat.title;
    if (chat.id === activeId) item.setAttribute("aria-current", "page");
    list.append(item);
  });
}
async function selectConversation(id) {
  if (busy) return;
  activeId = id; clearError(); showNotice(""); save(); render(); closeSidebar();
  await restoreSession();
}
function displayDate(date) {
  if (!date) return "";
  const parsed = new Date(date + "T12:00:00");
  return Number.isNaN(parsed.valueOf()) ? date : parsed.toLocaleDateString("en-GB", {day: "numeric", month: "short"});
}
function quantityAction(parent, label, max, prompt) {
  const actions = node("div", "card-actions");
  const quantity = node("input", "quantity-input");
  quantity.type = "number"; quantity.min = "1"; quantity.step = "1"; quantity.value = "1";
  quantity.max = String(Math.max(1, max)); quantity.setAttribute("aria-label", "Quantity for " + label);
  const action = button(label, () => {
    if (!quantity.checkValidity() || !Number.isInteger(Number(quantity.value))) { quantity.reportValidity(); return; }
    send(prompt(Number(quantity.value)));
  }, "small-button primary");
  action.disabled = busy || max < 1; quantity.disabled = busy || max < 1;
  action.dataset.unavailable = quantity.dataset.unavailable = String(max < 1);
  actions.append(quantity, action); parent.append(actions);
}
function makeCard(id, price) {
  const card = node("article", "result-card"), top = node("div", "card-top");
  top.append(node("span", "record-id", id));
  if (price !== undefined) {
    const amount = node("span", "price", money(price)); amount.append(node("small", "", "AZN")); top.append(amount);
  }
  card.append(top); return card;
}
function flightCard(f) {
  const card = makeCard(f.id, f.price_azn);
  card.append(node("h3", "", `${f.origin.city} → ${f.destination.city}`),
    node("div", "card-subtitle", `${f.airline} · ${f.flight_number}`),
    node("div", "card-meta", `${displayDate(f.departure_local.slice(0,10))} · ${f.departure_local.slice(11,16)} → ${f.arrival_local.slice(11,16)}\n${f.duration_min} min · ${f.stops ? f.stops + " stop(s)" : "Direct"} · ${f.baggage_kg} kg baggage\n${f.seats_available} seats left · ${f.cabin}`));
  card.querySelector(".card-meta").style.whiteSpace = "pre-line";
  quantityAction(card, "Mock reserve", f.seats_available, q => `Reserve flight ${f.id} for ${q} passengers.`);
  const actions = card.querySelector(".card-actions");
  actions.append(button("Details", () => send(`Show details for flight ${f.id}.`)));
  return card;
}
function productCard(p) {
  const card = makeCard(p.id, p.price_azn);
  card.append(node("h3", "", p.name.en), node("div", "card-subtitle", `${p.brand} · ${p.color}`),
    node("div", "card-meta", `${p.rating} / 5 rating · ${p.stock ? p.stock + " in stock" : "Out of stock"}`),
    node("div", "card-meta", p.description));
  quantityAction(card, "Add to cart", p.stock, q => `Add ${q} ${p.id} to my cart.`);
  return card;
}
function movieCard(m) {
  const card = makeCard(m.id);
  card.append(node("h3", "", m.title));
  const genres = node("div"); m.genre.forEach(genre => genres.append(node("span", "movie-genre", genre))); card.append(genres);
  card.append(node("div", "card-meta", `${m.rating} / 10 · ${m.duration_min} min · ${m.language} · ${m.age_rating}`), node("div", "card-meta", m.synopsis));
  const actions = node("div", "card-actions"); actions.append(button("Showtimes", () => send(`Show details and showtimes for movie ${m.id}.`))); card.append(actions);
  return card;
}
function comparison(rows, domain) {
  const wrapper = node("div", "comparison-wrap"), table = node("table"), head = node("tr");
  const headers = domain === "flights" ? ["Flight", "Price (AZN)", "Stops", "Duration", "Baggage", "Seats"] : domain === "shopping" ? ["Product", "Price (AZN)", "Rating", "Stock", "Colour"] : ["Film", "Rating", "Language", "Duration"];
  headers.forEach(text => head.append(node("th", "", text))); const thead = node("thead"); thead.append(head); table.append(thead);
  const body = node("tbody");
  rows.forEach(row => {
    const values = domain === "flights" ? [row.id, money(row.price_azn), row.stops, row.duration_min + " min", row.baggage_kg + " kg", row.seats_available] : domain === "shopping" ? [row.name.en, money(row.price_azn), row.rating, row.stock, row.color] : [row.title, row.rating, row.language, row.duration_min + " min"];
    const tr = node("tr"); values.forEach(value => tr.append(node("td", "", value))); body.append(tr);
  }); table.append(body); wrapper.append(table); return wrapper;
}
const issueText = {
  flight_search: "Please provide the missing flight search details.", flight_reserve: "Choose a flight and specify the passenger count.", cinema_reserve: "Choose a showtime and specify the ticket count.",
  cart_item: "Which product and how many units?", choose_item: "Which option do you mean? Give its ID or position in the list.", compare_items: "Choose at least two options to compare.",
  invalid_selection: "That position is not in the displayed list.", unknown_id: "That ID is not in the official catalogue.", insufficient_stock: "That quantity exceeds stock, including items in your cart.",
  insufficient_seats: "There are not enough seats for that quantity.", cart_quantity: "You cannot remove more units than are in the cart.", invalid_range: "Please check the minimum and maximum.", invalid_time: "Use a valid local time, such as 19:30.",
  invalid_sort: "That sort order is not supported.", selection_mismatch: "That option does not match your stated constraints. Please clarify.", date: "Which exact date do you mean?", one_way_only: "Please search each direction separately.", data_unavailable: "The data source is unavailable. Please try again.", unsupported_operation: "That operation is not supported in this domain."
};
function renderResult(result) {
  if (result.data?.provider) return renderProviderResult(result);
  const section = node("section", "result-section"), heading = node("div", "result-heading", names[result.domain] || result.domain);
  section.append(heading);
  const data = result.data || {};
  if (result.status === "no_results") section.append(node("p", "result-issue", result.domain === "shopping" ? "No matching products found." : "No matching records in the official dataset. Try another date or filter."));
  if (result.status === "error" || result.status === "clarification") {
    let explanation = issueText[result.code] || ({unsupported_filter: "The provider cannot verify that filter.", currency_filter_mismatch: "AZN budgets cannot filter another currency. Please update the currency or budget."}[result.code]) || "Please clarify the request.";
    if (result.missing?.length) explanation += " Missing: " + result.missing.map(field => field.replaceAll("_", " ")).join(", ") + ".";
    if (data.available !== undefined) explanation += ` Available: ${data.available}.`;
    section.append(node("div", "result-issue", explanation));
  }
  if (data.reservation) {
    const r = data.reservation, box = node("div", "confirmation");
    box.append(node("strong", "", "✓ Mock reservation recorded"), node("p", "", `${r.quantity} × ${r.record_id} · ${money(r.total_azn)} AZN`), node("code", "", r.confirmation_id), node("p", "", "Demonstration only. No payment or real-world booking.")); section.append(box);
  }
  const rows = data.flights || data.products || data.movies || [];
  if (result.operation === "compare" && rows.length) section.append(comparison(rows, result.domain));
  if (rows.length) {
    const grid = node("div", "result-grid"), selected = new Set();
    let compareButton;
    if (rows.length > 1 && result.operation !== "compare") {
      compareButton = button("Compare selected", () => send(`Compare ${names[result.domain].toLowerCase()} ${[...selected].join(" and ")}.`));
      compareButton.disabled = true; compareButton.dataset.unavailable = "true"; heading.append(compareButton);
    }
    rows.forEach(row => {
      const card = result.domain === "flights" ? flightCard(row) : result.domain === "shopping" ? productCard(row) : movieCard(row);
      if (compareButton) {
        const label = node("label", "card-meta"), checkbox = node("input"); checkbox.type = "checkbox";
        checkbox.setAttribute("aria-label", "Select " + row.id + " for comparison");
        checkbox.addEventListener("change", () => { checkbox.checked ? selected.add(row.id) : selected.delete(row.id); compareButton.dataset.unavailable = String(selected.size < 2); compareButton.disabled = busy || !!current()?.archived || selected.size < 2; });
        label.append(checkbox, document.createTextNode(" Compare")); card.append(label);
      }
      grid.append(card);
    }); section.append(grid);
  }
  if (data.showtimes?.length) {
    const list = node("div", "showtime-list");
    const movieNames = Object.fromEntries((data.movies || []).map(row => [row.id, row.title]));
    const cinemaNames = Object.fromEntries((data.cinemas || []).map(row => [row.id, row.name]));
    data.showtimes.forEach(s => {
      const row = node("article", "showtime-card"), info = node("div");
      info.append(node("h4", "", `${movieNames[s.movie_id] || s.movie_id} · ${displayDate(s.date)} · ${s.time.slice(0,5)}`),
        node("div", "card-meta", `${cinemaNames[s.cinema_id] || s.cinema_id} · ${s.hall} · ${s.id}`),
        node("div", s.seats_available ? "card-subtitle" : "sold-out", `${money(s.price_azn)} AZN · ${s.seats_available ? s.seats_available + " seats left" : "Sold out"}`));
      row.append(info); quantityAction(row, "Mock tickets", s.seats_available, q => `Reserve ${q} tickets for showtime ${s.id}.`); list.append(row);
    }); section.append(list);
  }
  if (data.cart) {
    const cart = node("div", "cart-lines");
    if (!data.cart.lines.length) cart.append(node("p", "card-meta", "Your cart is empty."));
    data.cart.lines.forEach(line => {
      const row = node("div", "cart-line"), info = node("div");
      info.append(node("strong", "", line.product.name.en), node("div", "card-meta", `${line.quantity} × ${money(line.unit_price_azn)} AZN · ${line.product.id}`));
      row.append(info, node("span", "", money(line.subtotal_azn) + " AZN"), button("Remove 1", () => send(`Remove 1 ${line.product.id} from my cart.`))); cart.append(row);
    }); const total = node("div", "cart-total"); total.append(node("span", "", "Total"), node("span", "", money(data.cart.total_azn) + " AZN")); cart.append(total); section.append(cart);
  }
  return section;
}
function providerLink(label, href, merchantLink = false) {
  try {
    const url = new URL(href);
    const allowed = ["aviasales.com", "birmarket.az", "cinemastercard.az", "themoviedb.org", "ebay.com", "buywhere.ai"];
    const publicMerchant = merchantLink && url.hostname.includes(".") && !/^\d+(?:\.\d+){3}$/.test(url.hostname) && !url.hostname.includes(":") && !/\.(?:local|internal|localhost)$/.test(url.hostname) && (!url.port || url.port === "443");
    if (url.protocol !== "https:" || url.username || url.password || !(publicMerchant || allowed.some(host => url.hostname === host || url.hostname.endsWith("." + host)))) return node("span", "", label);
    const link = node("a", "small-button", label);
    link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
    return link;
  } catch { return node("span", "", label); }
}
function providerImage(href, label) {
  try {
    const url = new URL(href);
    if (url.protocol !== "https:" || url.username || url.password || !["image.tmdb.org", "i.ebayimg.com", "cinemastercard.az", "m.media-amazon.com", "images-na.ssl-images-amazon.com", "cdn.shopify.com", "c1.neweggimages.com", "i5.walmartimages.com", "target.scene7.com"].includes(url.hostname)) return null;
    const img = node("img", "provider-image"); img.src = url.href; img.alt = label;
    img.loading = "lazy"; img.referrerPolicy = "no-referrer";
    img.addEventListener("error", () => { img.hidden = true; });
    return img;
  } catch { return null; }
}
function renderProviderResult(result) {
  const data = result.data, source = data.provider;
  const section = node("section", "result-section");
  section.append(node("div", "result-heading", `${source.provider} · ${source.status}`),
    node("p", "card-meta", source.notice));
  if (source.fetched_at) section.append(node("p", "card-meta", `Fetched ${source.fetched_at}${source.local_cache_hit ? " · local cache" : ""}`));
  if (data.partial) section.append(node("p", "card-meta", "Limited provider results; filters and comparisons apply to returned options."));
  if (data.provider_error && (data.provider_error.message !== source.notice || data.provider_error.retry_after)) section.append(node("p", "result-issue", data.provider_error.message +
    (data.provider_error.retry_after ? ` Retry after ${data.provider_error.retry_after} seconds.` : "")));
  if (result.status === "no_results") section.append(node("p", "result-issue", "No matching provider results. This does not establish availability."));
  const rows = data.flights || data.products || data.movies || [], grid = node("div", "result-grid"), selected = new Set();
  if (rows.length > 1 && result.operation !== "compare") {
    const compare = button("Compare selected", () => send(`Compare ${names[result.domain].toLowerCase()} ${[...selected].join(" and ")}.`));
    compare.disabled = true; compare.dataset.unavailable = "true"; section.append(compare);
    grid.compareButton = compare;
  }
  rows.forEach(row => {
    const card = node("article", "result-card");
    card.append(node("div", "record-id", row.id));
    const picture = providerImage(row.poster_url || row.image_url, row.title || "Provider image");
    if (picture) card.append(picture);
    if (result.domain === "flights") {
      card.append(node("h3", "", `${row.origin} → ${row.destination}`),
        node("p", "card-subtitle", `${row.airline || "Airline unknown"} ${row.flight_number || ""}`),
        node("p", "card-meta", `Departure: ${row.departure_at}`));
      if (row.return_at) card.append(node("p", "card-meta", `Return: ${row.return_at}`));
      if (row.origin_airport || row.destination_airport) card.append(node("p", "card-meta", `Airports: ${row.origin_airport || "unknown"} → ${row.destination_airport || "unknown"}`));
      card.append(node("p", "card-meta", `Stops: ${row.stops ?? "unknown"} · Duration: ${row.duration_min === null ? "unknown" : row.duration_min + " min"}`),
        node("p", "card-meta", "Seats, baggage and cabin: unknown"));
      if (row.booking_url) card.append(providerLink("Recheck on Aviasales", row.booking_url));
    } else if (result.domain === "shopping") {
      const availability = row.in_stock === true ? "Provider reports estimated availability" : row.in_stock === false ? "Provider reports out of stock" : "Stock: unverified";
      card.append(node("h3", "", row.title), node("p", "card-meta", availability + " · Delivery to Azerbaijan unverified"));
      if (row.brand || row.color) card.append(node("p", "card-meta", [row.brand, row.color].filter(Boolean).join(" · ")));
      if (row.category) card.append(node("p", "card-meta", row.category));
      if (row.condition) card.append(node("p", "card-meta", row.condition));
      if (row.description) card.append(node("p", "card-meta", row.description));
      if (row.merchant) card.append(node("p", "card-meta", "Retailer: " + row.merchant));
      if (source.provider === "BuyWhere") card.append(node("p", "card-meta", "Catalog price date: " + (row.price_as_of || "unknown") + (row.price_stale ? " · Older than 24 hours; recheck price" : "")));
      if (row.product_url) card.append(providerLink(source.provider === "BuyWhere" ? "View retailer offer" : "View on " + source.provider, row.product_url, source.provider === "BuyWhere"));
    } else {
      const official = !!row.movie_url;
      const description = official ? (row.confirmed_cinemaplus_screening ? "Published CinemaPlus showtimes below" : "Listed on the official CinemaPlus site · Select for dated showtimes") : "TMDB metadata · CinemaPlus screening unverified";
      card.append(node("h3", "", row.title), node("p", "card-meta", description),
        node("p", "card-meta", row.synopsis || ""));
      if (row.rating !== null) card.append(node("p", "card-meta", `${row.rating}/10 TMDB rating`));
      if (row.duration_min !== null) card.append(node("p", "card-meta", `${row.duration_min} min`));
      if (row.genre?.length) card.append(node("p", "card-meta", row.genre.join(", ")));
      if (row.age_rating) card.append(node("p", "card-meta", row.age_rating));
      if (row.screening_languages?.length) card.append(node("p", "card-meta", "Listed languages: " + row.screening_languages.join(", ")));
      card.append(providerLink(official ? "Movie on CinemaPlus" : "Movie metadata on TMDB", row.movie_url || row.metadata_url));
      if (official && row.showtimes_url) card.append(providerLink("Official showtimes", row.showtimes_url));
    }
    if (row.price) card.append(node("p", "price", `${money(row.price.amount)} ${row.price.currency}${result.domain === "flights" ? " · cached" : ""}`));
    const actions = node("div", "card-actions");
    actions.append(button("Details", () => send(`Show details for ${result.domain === "cinema" ? "movie" : result.domain === "flights" ? "flight" : "product"} ${row.id}.`)));
    card.append(actions);
    if (grid.compareButton) {
      const label = node("label", "card-meta"), check = node("input"); check.type = "checkbox";
      check.setAttribute("aria-label", "Select " + row.id + " for comparison");
      check.addEventListener("change", () => {
        check.checked ? selected.add(row.id) : selected.delete(row.id);
        grid.compareButton.disabled = selected.size < 2; grid.compareButton.dataset.unavailable = String(selected.size < 2);
      });
      label.append(check, document.createTextNode(" Compare")); card.append(label);
    }
    grid.append(card);
  });
  section.append(grid, providerLink("Open provider website", result.domain === "flights" ? "https://www.aviasales.com/" : source.source_url));
  if (data.cinemas?.length) {
    const places = node("div", "provider-locations"); places.append(node("h4", "", "CinemaPlus locations"));
    data.cinemas.forEach(c => places.append(providerLink(c.name, c.source_url)));
    section.append(places);
  }
  if (data.showtimes?.length) {
    const list = node("div", "showtime-list");
    data.showtimes.slice(0, 20).forEach(s => {
      const row = node("article", "showtime-card"), info = node("div");
      info.append(node("h4", "", `${s.movie_title} · ${s.date} ${s.time}`),
        node("p", "card-meta", `${s.cinema_name} · ${s.hall || "Hall unspecified"}${s.language ? " · " + s.language : ""}`),
        node("p", "card-meta", s.price ? `${money(s.price.amount)} ${s.price.currency} listed price · Seats unknown` : "Price and seats unverified"));
      row.append(info, providerLink("Official schedule", s.showtimes_url)); list.append(row);
    });
    if (data.showtimes.length > 20) list.append(node("p", "card-meta", `Showing 20 of ${data.showtimes.length} published sessions. Open the official schedule for more.`));
    section.append(list);
  }
  if (result.domain === "cinema" && source.provider === "TMDB") section.append(providerLink("CinemaPlus listings and tickets", "https://cinemastercard.az/"));
  return section;
}
function renderTurn(turn) {
  const block = node("article", "turn " + turn.role);
  if (turn.role === "user") { block.append(node("div", "user-bubble", turn.content)); return block; }
  const heading = node("div", "assistant-heading");
  heading.append(node("span", "assistant-avatar", "✦"), node("span", "", "SuperChat"));
  if (turn.routing?.source === "local") heading.append(node("span", "mode-badge", "Local assistant"));
  block.append(heading);
  if (!turn.results?.length || (turn.routing?.language && !["en", "English"].includes(turn.routing.language))) block.append(node("div", "assistant-text", turn.content));
  else block.append(node("div", "assistant-text", turn.results.some(r => r.data?.provider_error) ? "Here’s the current provider status." : turn.results.some(r => r.status === "clarification" || r.status === "error") ? "Let’s check a couple of details." : turn.results.some(r => r.code === "reserved") ? "Your mock reservation is ready." : "Here’s what I found for you."));
  (turn.results || []).forEach(result => block.append(renderResult(result)));
  if (turn.results?.length) {
    const details = node("details", "card-meta"); details.append(node("summary", "", "Read full response"), node("div", "assistant-text", turn.content)); block.append(details);
  }
  return block;
}
function render() {
  const chat = current(); renderSidebar(); messages.replaceChildren();
  $("welcome").hidden = !!chat?.turns.length;
  (chat?.turns || []).forEach(turn => messages.append(renderTurn(turn)));
  if (chat?.archived) {
    showNotice("You can still read this conversation. Start a new conversation to continue with fresh server context.");
    $("notice").append(document.createTextNode(" "), button("Start a new conversation", () => { clearError(); showNotice(""); newConversation(); }));
  }
  else if (chat?.pending && !busy && $("error").hidden) showError("This message has not been confirmed. Retry with the same request ID to avoid duplicate operations.", () => send(null, true));
  setBusy(busy); scrollBottom();
}
function scrollBottom() { requestAnimationFrame(() => { scrollArea.scrollTop = scrollArea.scrollHeight; }); }
async function api(path, options = {}) {
  const response = await fetch(path, {credentials: "same-origin", ...options});
  if (!response.ok) { const error = new Error("HTTP " + response.status); error.status = response.status; throw error; }
  return response.json();
}
async function restoreSession() {
  const chat = current();
  if (!chat?.sessionId || chat.archived || chat.pending) return;
  const targetId = chat.id;
  try {
    const state = await api("/api/session/" + encodeURIComponent(chat.sessionId));
    chat.turns = state.history; save(); if (activeId === targetId) render();
  } catch (error) {
    if (error.status === 404) { chat.archived = true; save(); if (activeId === targetId) render(); }
    else if (activeId === targetId) showNotice("Saved messages are available. The server could not refresh this conversation yet.");
  }
}
async function send(text, retry = false) {
  if (busy || !ready || current()?.archived) return;
  if (!current()) newConversation();
  const chat = current();
  if (chat.pending && !retry) { showError("Resolve the unconfirmed message first to avoid repeating an operation.", () => send(null, true)); return; }
  if (!retry) {
    text = (text ?? input.value).trim(); if (!text || text.length > 8000) return;
    chat.pending = {message: text, session_id: chat.sessionId, request_id: crypto.randomUUID()};
    chat.turns.push({role: "user", content: text});
    if (chat.title === "New conversation") chat.title = text.slice(0, 52);
    chat.updated = Date.now(); input.value = ""; input.style.height = "auto";
  }
  clearError(); showNotice(""); save(); setBusy(true); render(); scrollBottom();
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 25000);
  try {
    const answer = await api("/api/chat", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(chat.pending), signal: controller.signal});
    chat.sessionId = answer.session_id; chat.turns = answer.state.history; chat.pending = null; clearError(); save();
    $("connection").classList.toggle("degraded", answer.routing.source === "local");
    $("connection").replaceChildren(node("span"), document.createTextNode(answer.routing.source === "local" ? "Local assistant" : "Connected to Gemini"));
  } catch (error) {
    if (error.status === 404) { chat.archived = true; chat.pending = null; save(); }
    else if ([409, 422].includes(error.status)) {
      chat.pending = null; save(); showError("This request could not be accepted. Check the message and try again.");
    } else showError([502,503,504].includes(error.status) ? "The assistant is temporarily unavailable. Your conversation is saved. Retry safely in a moment." : "The connection was interrupted before we received confirmation. Your message is saved; retry safely.", () => send(null, true));
  } finally {
    clearTimeout(timer); setBusy(false); render();
    if (!chat.archived) input.focus();
  }
}
$("chat-form").addEventListener("submit", event => { event.preventDefault(); send(); });
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 130) + "px"; setBusy(busy); });
input.addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); send(); } });
document.querySelectorAll("[data-prompt]").forEach(element => element.addEventListener("click", () => send(element.dataset.prompt)));
$("new-chat").addEventListener("click", () => { clearError(); showNotice(""); newConversation(); });
$("menu-button").addEventListener("click", () => { const open = $("sidebar").classList.toggle("open"); $("scrim").hidden = !open; $("menu-button").setAttribute("aria-expanded", String(open)); });
$("scrim").addEventListener("click", closeSidebar);
$("info-button").addEventListener("click", () => $("info-dialog").showModal());
$("close-info").addEventListener("click", () => $("info-dialog").close());
document.addEventListener("keydown", event => { if (event.key === "Escape") closeSidebar(); });
$("clear-history").addEventListener("click", () => {
  if (busy || !confirm("Clear saved conversations from this browser?")) return;
  conversations = []; activeId = null; clearError(); showNotice(""); save(); newConversation();
});
async function init() {
  setBusy(false);
  try {
    const client = await api("/api/client"); storageKey = "superchat.v1." + client.namespace;
    document.querySelector(".reference-date").textContent = `Reference date · ${client.reference_date} · Asia/Baku`;
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "[]");
      conversations = Array.isArray(saved) ? saved.filter(chat => chat.id && Array.isArray(chat.turns)) : [];
      activeId = sessionStorage.getItem(storageKey + ".active") || conversations[0]?.id;
    } catch { conversations = []; }
    ready = true;
    if (client.routing_mode === "offline") { $("connection").replaceChildren(node("span"), document.createTextNode("Local assistant")); $("connection").classList.add("degraded"); }
    if (!current()) newConversation(); else render();
    await restoreSession(); input.focus();
  } catch { showError("SuperChat could not connect to the backend. Check that it is running, then reload this page.", () => location.reload()); }
}
init();
