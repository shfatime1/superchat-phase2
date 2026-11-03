/* Interface preferences only. No API calls, routing changes or chat-storage writes. */
"use strict";
window.SuperChatUI = (() => {
  const key = "superchat.ui.preferences";
  const dictionary = Object.fromEntries([
    ["New chat", "Yeni söhbət", "Новый чат"], ["New conversation", "Yeni söhbət", "Новый чат"],
    ["YOUR ASSISTANTS", "KÖMƏKÇİLƏRİNİZ", "ВАШИ ПОМОЩНИКИ"], ["RECENT CHATS", "SON SÖHBƏTLƏR", "НЕДАВНИЕ ЧАТЫ"],
    ["Flights", "Uçuşlar", "Авиабилеты"], ["Shopping", "Alış-veriş", "Покупки"], ["Cinema", "Kino", "Кино"],
    ["Your conversations will appear here.", "Söhbətləriniz burada görünəcək.", "Здесь появятся ваши чаты."],
    ["One chat. Three worlds.", "Bir söhbət. Üç dünya.", "Один чат. Три мира."],
    ["ONE CHAT. THREE WORLDS.", "BİR SÖHBƏT. ÜÇ DÜNYA.", "ОДИН ЧАТ. ТРИ МИРА."],
    ["What’s on your mind?", "Ağlınızda nə var?", "Что у вас на уме?"],
    ["A little closer to your next destination.", "Növbəti səyahətinizə bir addım daha yaxın.", "На шаг ближе к вашему следующему путешествию."],
    ["Find something that fits your everyday.", "Gündəlik həyatınıza uyğun məhsulu tapın.", "Найдите то, что нужно каждый день."],
    ["Your next great film night starts here.", "Növbəti kino axşamınız buradan başlayır.", "Ваш следующий киновечер начинается здесь."],
    ["Have more than one plan? Ask for both.", "Bir neçə planınız var? Birlikdə soruşun.", "Несколько планов? Спросите обо всём сразу."],
    ["Where would you like to go?", "Hara getmək istərdiniz?", "Куда хотите отправиться?"],
    ["What would you like to find?", "Nə tapmaq istərdiniz?", "Что хотите найти?"],
    ["What would you like to watch?", "Nə izləmək istərdiniz?", "Что хотите посмотреть?"],
    ["Light mode", "İşıqlı rejim", "Светлая тема"], ["Dark mode", "Qaranlıq rejim", "Тёмная тема"],
    ["Interface language", "İnterfeys dili", "Язык интерфейса"], ["Enter to send", "Göndərmək üçün Enter", "Enter — отправить"],
    ["Message SuperChat", "SuperChat-a mesaj yazın", "Сообщение SuperChat"], ["Send message", "Mesajı göndər", "Отправить сообщение"],
    ["Putting your plan together", "Planınız hazırlanır", "Готовим ваш план"], ["Ready to help", "Köməyə hazırdır", "Готов помочь"],
    ["Local assistant", "Lokal köməkçi", "Локальный помощник"], ["Connected to Gemini", "Gemini-yə qoşulub", "Подключено к Gemini"],
    ["Clear saved conversations", "Saxlanmış söhbətləri sil", "Удалить сохранённые чаты"],
    ["Clear saved conversations from this browser?", "Bu brauzerdə saxlanmış söhbətlər silinsin?", "Удалить сохранённые чаты из этого браузера?"],
    ["Close sidebar", "Yan paneli bağla", "Закрыть боковую панель"], ["Open sidebar", "Yan paneli aç", "Открыть боковую панель"],
    ["Conversation navigation", "Söhbət naviqasiyası", "Навигация по чатам"], ["Saved conversations", "Saxlanmış söhbətlər", "Сохранённые чаты"],
    ["Conversation", "Söhbət", "Переписка"], ["Assistants", "Köməkçilər", "Помощники"], ["About SuperChat", "SuperChat haqqında", "О SuperChat"],
    ["Close information", "Məlumatı bağla", "Закрыть информацию"], ["MEET SUPERCHAT", "SUPERCHAT İLƏ TANIŞ OLUN", "ЗНАКОМЬТЕСЬ: SUPERCHAT"],
    ["Three possibilities. One conversation.", "Üç imkan. Bir söhbət.", "Три возможности. Один чат."],
    ["Search flights, discover products, or plan a film night. Each conversation remembers your plans.", "Uçuş və məhsul axtarın, kino axşamı planlaşdırın. Hər söhbət planlarınızı yadda saxlayır.", "Ищите авиабилеты и товары, планируйте киновечер. Каждый чат помнит ваши планы."],
    ["Aviasales fares are cached. CinemaPlus supplies official listings and schedules. BuyWhere supplies product offers with price dates; links may earn BuyWhere a commission. eBay and TMDB are optional. Birmarket reuse permission is unconfirmed. Seats, purchases and reservations are unavailable.", "Aviasales qiymətləri keşlənib. CinemaPlus rəsmi film siyahısı və seansları təqdim edir. BuyWhere qiymət tarixləri ilə məhsul təklifləri təqdim edir; keçidlərdən komissiya qazana bilər. eBay və TMDB əlavə mənbələrdir. Birmarket məlumatlarının təkrar istifadəsinə icazə təsdiqlənməyib. Yerlər, alış və rezervasiya əlçatan deyil.", "Цены Aviasales кешированы. CinemaPlus предоставляет официальную афишу и расписание. BuyWhere предоставляет товары с датами цен и может получать комиссию по ссылкам. eBay и TMDB — дополнительные источники. Разрешение на повторное использование Birmarket не подтверждено. Места, покупки и бронирования недоступны."],
    ["When Gemini is unavailable, a limited local assistant handles clear English requests.", "Gemini əlçatan olmayanda məhdud lokal köməkçi aydın ingiliscə sorğuları emal edir.", "Когда Gemini недоступен, ограниченный локальный помощник обрабатывает понятные запросы на английском."],
    ["Saved chats stay in this browser. Server context resets when the backend restarts.", "Saxlanmış söhbətlər bu brauzerdə qalır. Server yenidən başlayanda kontekst sıfırlanır.", "Сохранённые чаты остаются в браузере. При перезапуске сервера контекст сбрасывается."],
    ["This product uses the TMDB API but is not endorsed or certified by TMDB.", "Bu məhsul TMDB API-dən istifadə edir, lakin TMDB tərəfindən təsdiqlənməyib və sertifikatlaşdırılmayıb.", "Продукт использует API TMDB, но не одобрен и не сертифицирован TMDB."],
    ["Provider data · Cached flight prices · Verify availability with the provider.", "Provayder məlumatları · Keşlənmiş uçuş qiymətləri · Mövcudluğu provayderdə yoxlayın.", "Данные провайдеров · Кешированные цены авиабилетов · Уточняйте наличие у провайдера."],
    ["Details", "Ətraflı", "Подробнее"], ["Compare", "Müqayisə", "Сравнить"], [" Compare", " Müqayisə", " Сравнить"],
    ["Compare selected", "Seçilənləri müqayisə et", "Сравнить выбранное"], ["Read full response", "Tam cavabı oxu", "Прочитать полный ответ"],
    ["Retry safely", "Yenidən cəhd et", "Повторить безопасно"], ["Start a new conversation", "Yeni söhbət başlat", "Начать новый чат"],
    ["Here’s what I found for you.", "Sizin üçün tapdıqlarım.", "Вот что удалось найти."],
    ["Here’s the current provider status.", "Provayderin cari vəziyyəti.", "Текущий статус провайдера."],
    ["Let’s check a couple of details.", "Bir neçə detalı dəqiqləşdirək.", "Давайте уточним несколько деталей."],
    ["Your mock reservation is ready.", "Sınaq rezervasiyanız hazırdır.", "Тестовое бронирование готово."],
    ["Open provider website", "Provayderin saytını aç", "Открыть сайт провайдера"],
    ["View retailer offer", "Satıcının təklifinə bax", "Посмотреть предложение продавца"],
    ["Recheck on Aviasales", "Aviasales-də yoxla", "Уточнить на Aviasales"],
    ["Official showtimes", "Rəsmi seanslar", "Официальные сеансы"], ["Official schedule", "Rəsmi cədvəl", "Официальное расписание"],
    ["Movie on CinemaPlus", "CinemaPlus-da film", "Фильм на CinemaPlus"], ["Movie metadata on TMDB", "TMDB-də film məlumatı", "Информация о фильме на TMDB"],
    ["CinemaPlus locations", "CinemaPlus məkanları", "Кинотеатры CinemaPlus"], ["CinemaPlus listings and tickets", "CinemaPlus filmləri və biletlər", "Афиша и билеты CinemaPlus"],
    ["Limited provider results; filters and comparisons apply to returned options.", "Nəticələr məhduddur; filtrlər və müqayisələr göstərilən təkliflərə aiddir.", "Результаты ограничены; фильтры и сравнения применяются к показанным вариантам."],
    ["No matching provider results. This does not establish availability.", "Uyğun nəticə tapılmadı. Bu, mövcudluğu təsdiqləmir.", "Подходящих результатов нет. Это не подтверждает наличие."],
    ["No matching products found.", "Uyğun məhsul tapılmadı.", "Подходящих товаров не найдено."],
    ["Seats, baggage and cabin: unknown", "Yerlər, baqaj və kabin: məlum deyil", "Места, багаж и класс: неизвестны"],
    ["Stock: unverified · Delivery to Azerbaijan unverified", "Stok təsdiqlənməyib · Azərbaycana çatdırılma təsdiqlənməyib", "Наличие не подтверждено · Доставка в Азербайджан не подтверждена"],
    ["Provider reports estimated availability · Delivery to Azerbaijan unverified", "Provayder təxmini mövcudluq bildirir · Azərbaycana çatdırılma təsdiqlənməyib", "Провайдер сообщает о предполагаемом наличии · Доставка в Азербайджан не подтверждена"],
    ["Provider reports out of stock · Delivery to Azerbaijan unverified", "Provayder stokda olmadığını bildirir · Azərbaycana çatdırılma təsdiqlənməyib", "По данным провайдера товара нет в наличии · Доставка в Азербайджан не подтверждена"],
    ["Published CinemaPlus showtimes below", "Yayımlanmış CinemaPlus seansları aşağıdadır", "Ниже опубликованные сеансы CinemaPlus"],
    ["Listed on the official CinemaPlus site · Select for dated showtimes", "Rəsmi CinemaPlus saytında yer alır · Tarixli seanslar üçün seçin", "На официальном сайте CinemaPlus · Выберите для сеансов по датам"],
    ["TMDB metadata · CinemaPlus screening unverified", "TMDB məlumatı · CinemaPlus nümayişi təsdiqlənməyib", "Данные TMDB · Показ в CinemaPlus не подтверждён"],
    ["Price and seats unverified", "Qiymət və yerlər təsdiqlənməyib", "Цена и места не подтверждены"],
    ["Showtimes", "Seanslar", "Сеансы"], ["Add to cart", "Səbətə əlavə et", "В корзину"], ["Mock reserve", "Sınaq rezervasiyası", "Тестовое бронирование"],
    ["Mock tickets", "Sınaq biletləri", "Тестовые билеты"], ["Your cart is empty.", "Səbətiniz boşdur.", "Ваша корзина пуста."],
    ["Remove 1", "1 ədəd sil", "Удалить 1"], ["Total", "Cəmi", "Итого"], ["Flight", "Uçuş", "Рейс"], ["Product", "Məhsul", "Товар"],
    ["Film", "Film", "Фильм"], ["Price (AZN)", "Qiymət (AZN)", "Цена (AZN)"], ["Stops", "Dayanmalar", "Пересадки"],
    ["Duration", "Müddət", "Длительность"], ["Baggage", "Baqaj", "Багаж"], ["Seats", "Yerlər", "Места"], ["Rating", "Reytinq", "Рейтинг"],
    ["Stock", "Stok", "Наличие"], ["Colour", "Rəng", "Цвет"], ["Language", "Dil", "Язык"],
    ["Saved messages are available. The server could not refresh this conversation yet.", "Saxlanmış mesajlar mövcuddur. Server söhbəti hələ yeniləyə bilmədi.", "Сохранённые сообщения доступны. Сервер пока не смог обновить чат."],
    ["You can still read this conversation. Start a new conversation to continue with fresh server context.", "Bu söhbəti oxuya bilərsiniz. Davam etmək üçün yeni söhbət başladın.", "Вы можете прочитать этот чат. Чтобы продолжить, начните новый."],
    ["This message has not been confirmed. Retry with the same request ID to avoid duplicate operations.", "Mesaj təsdiqlənməyib. Əməliyyat təkrarlanmasın deyə yenidən cəhd edin.", "Сообщение не подтверждено. Повторите с тем же ID запроса, чтобы избежать дублирования."],
    ["Resolve the unconfirmed message first to avoid repeating an operation.", "Əməliyyat təkrarlanmasın deyə əvvəlcə təsdiqlənməmiş mesajı həll edin.", "Сначала разрешите неподтверждённый запрос, чтобы не повторить операцию."],
    ["SuperChat could not connect to the backend. Check that it is running, then reload this page.", "SuperChat serverə qoşula bilmədi. Serveri yoxlayın və səhifəni yeniləyin.", "SuperChat не смог подключиться к серверу. Проверьте сервер и обновите страницу."],
    ["This request could not be accepted. Check the message and try again.", "Sorğu qəbul edilmədi. Mesajı yoxlayıb yenidən cəhd edin.", "Запрос не принят. Проверьте сообщение и повторите."],
    ["The assistant is temporarily unavailable. Your conversation is saved. Retry safely in a moment.", "Köməkçi müvəqqəti əlçatan deyil. Söhbətiniz saxlanıb. Bir az sonra yenidən cəhd edin.", "Помощник временно недоступен. Чат сохранён. Повторите немного позже."],
    ["The connection was interrupted before we received confirmation. Your message is saved; retry safely.", "Təsdiq alınmadan bağlantı kəsildi. Mesajınız saxlanıb; yenidən cəhd edə bilərsiniz.", "Соединение прервалось до подтверждения. Сообщение сохранено; можно безопасно повторить."],
    ["Browser storage is full or unavailable. This chat works, but new messages may not survive a refresh.", "Brauzer yaddaşı doludur və ya əlçatan deyil. Yeni mesajlar səhifə yenilənəndə itə bilər.", "Хранилище браузера заполнено или недоступно. Новые сообщения могут не сохраниться после обновления."],
  ].map(([en, az, ru]) => [en, {en, az, ru}]));
  let preferences = {theme: "dark", language: "en", assistant: "flights"};
  try { const saved = JSON.parse(localStorage.getItem(key) || "null");
    if (saved && typeof saved === "object") preferences = {
      theme: ["dark", "light"].includes(saved.theme) ? saved.theme : "dark",
      language: ["az", "en", "ru"].includes(saved.language) ? saved.language : "en",
      assistant: ["flights", "shopping", "cinema"].includes(saved.assistant) ? saved.assistant : "flights"};
  } catch { /* Preferences are optional, including in private browsing. */ }
  const prompts = {flights: ["Flights", "Where would you like to go?", "A little closer to your next destination."],
    shopping: ["Shopping", "What would you like to find?", "Find something that fits your everyday."],
    cinema: ["Cinema", "What would you like to watch?", "Your next great film night starts here."]};
  const prefixes = [
    ["Departure: ", "Gediş: ", "Вылет: "], ["Return: ", "Qayıdış: ", "Обратно: "],
    ["Retailer: ", "Satıcı: ", "Продавец: "], ["Catalog price date: ", "Kataloq qiymətinin tarixi: ", "Дата цены в каталоге: "],
    ["Fetched ", "Alınma vaxtı: ", "Получено: "], ["Reference date · ", "İstinad tarixi · ", "Опорная дата · "],
    ["View on ", "Burada bax: ", "Посмотреть на "], ["Listed languages: ", "Göstərilən dillər: ", "Указанные языки: "]
  ];
  function translate(text) {
    if (dictionary[text]) return dictionary[text][preferences.language];
    const prefix = prefixes.find(([en]) => text.startsWith(en));
    if (prefix) return prefix[{en: 0, az: 1, ru: 2}[preferences.language]] + text.slice(prefix[0].length);
    return text;
  }
  function setText(element, text) {
    if (dictionary[text] || prefixes.some(([en]) => text.startsWith(en))) element.dataset.uiText = text;
    else delete element.dataset.uiText;
    element.textContent = translate(text);
  }
  function persist() { try { localStorage.setItem(key, JSON.stringify(preferences)); } catch {} }
  function apply() {
    document.documentElement.lang = preferences.language;
    document.documentElement.dataset.theme = preferences.theme;
    document.querySelector('meta[name="theme-color"]').content = preferences.theme === "dark" ? "#1d1f1e" : "#f9fbf9";
    document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = translate(el.dataset.i18n); });
    document.querySelectorAll("[data-ui-text]").forEach(el => { el.textContent = translate(el.dataset.uiText); });
    document.querySelectorAll("[data-i18n-aria]").forEach(el => el.setAttribute("aria-label", translate(el.dataset.i18nAria)));
    const nextTheme = preferences.theme === "dark" ? "Light mode" : "Dark mode";
    document.querySelectorAll("[data-theme-label]").forEach(el => { el.textContent = translate(nextTheme); });
    const toggle = document.getElementById("theme-toggle");
    toggle.textContent = preferences.theme === "dark" ? "☼" : "☾";
    toggle.title = translate(nextTheme); toggle.setAttribute("aria-label", translate(nextTheme));
    toggle.setAttribute("aria-pressed", String(preferences.theme === "dark"));
    document.querySelector(".theme-icon").textContent = toggle.textContent;
    document.getElementById("page-language").value = preferences.language;
    document.querySelectorAll("[data-assistant]").forEach(el => {
      const active = el.dataset.assistant === preferences.assistant;
      el.classList.toggle("active", active); el.setAttribute("aria-pressed", String(active));
    });
    const [name, placeholder, description] = prompts[preferences.assistant];
    const domain = document.getElementById("composer-domain"); domain.dataset.i18n = name; domain.textContent = translate(name);
    domain.parentElement.dataset.domain = preferences.assistant;
    document.getElementById("message-input").placeholder = translate(placeholder);
    const welcome = document.getElementById("welcome-description"); welcome.dataset.i18n = description; welcome.textContent = translate(description);
  }
  // Keep existing example prompts unchanged; update only their visible labels/icons.
  document.querySelectorAll(".suggestion").forEach((el, index) => {
    const domain = ["flights", "shopping", "cinema"][index];
    el.querySelector("strong").dataset.i18n = prompts[domain][0];
    const icon = document.querySelector(`[data-assistant="${domain}"] svg`).cloneNode(true);
    el.querySelector(".tile-icon").replaceChildren(icon);
  });
  document.querySelectorAll("#scrim,#sidebar,#conversation-list,#messages").forEach(el => { el.dataset.i18nAria = el.getAttribute("aria-label"); });
  function setTheme(theme) { if (["light", "dark"].includes(theme)) { preferences.theme = theme; persist(); apply(); } }
  function setLanguage(language) { if (["az", "en", "ru"].includes(language)) { preferences.language = language; persist(); apply(); } }
  document.getElementById("page-language").addEventListener("change", event => setLanguage(event.target.value));
  ["theme-toggle", "theme-toggle-sidebar"].forEach(id => document.getElementById(id).addEventListener("click", () => setTheme(preferences.theme === "dark" ? "light" : "dark")));
  document.querySelectorAll("[data-assistant]").forEach(el => el.addEventListener("click", () => {
    preferences.assistant = el.dataset.assistant; persist(); apply();
    document.getElementById("sidebar").classList.remove("open"); document.getElementById("scrim").hidden = true;
    document.getElementById("menu-button").setAttribute("aria-expanded", "false"); document.getElementById("message-input").focus();
  }));
  apply();
  return {translate, setText, setTheme, setLanguage, get language() { return preferences.language; }};
})();
