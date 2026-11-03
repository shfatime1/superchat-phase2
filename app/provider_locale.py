"""Localized provider explanations; all factual values remain provider supplied."""

LABELS = {
    "en": {"fetched": "Fetched at", "retailer": "Retailer", "price_date": "Catalog price date", "unknown": "unknown",
           "stale": "older than 24 hours; recheck price", "cached": "cached", "official": "CinemaPlus official public listing",
           "tmdb": "TMDB metadata; CinemaPlus screening unverified", "schedule": "Official schedule", "duration": "Duration",
           "minutes": "minutes", "locations": "CinemaPlus locations", "hall": "Hall unspecified", "listed": "listed price",
           "seats": "Seat availability unknown", "empty": "No matching provider results. This does not establish availability.",
           "rating": "TMDB rating"},
    "az": {"fetched": "Alınma vaxtı", "retailer": "Satıcı", "price_date": "Kataloq qiymətinin tarixi", "unknown": "məlum deyil",
           "stale": "24 saatdan köhnədir; qiyməti yenidən yoxlayın", "cached": "keşlənmiş", "official": "CinemaPlus rəsmi film siyahısı",
           "tmdb": "TMDB məlumatı; CinemaPlus nümayişi təsdiqlənməyib", "schedule": "Rəsmi cədvəl", "duration": "Müddət",
           "minutes": "dəqiqə", "locations": "CinemaPlus məkanları", "hall": "Zal göstərilməyib", "listed": "göstərilən qiymət",
           "seats": "Yerlərin mövcudluğu məlum deyil", "empty": "Uyğun nəticə tapılmadı. Bu, mövcudluğu təsdiqləmir.", "rating": "TMDB reytinqi"},
    "ru": {"fetched": "Получено", "retailer": "Продавец", "price_date": "Дата цены в каталоге", "unknown": "неизвестно",
           "stale": "старше 24 часов; уточните цену", "cached": "кешированные", "official": "Официальная афиша CinemaPlus",
           "tmdb": "Данные TMDB; показ в CinemaPlus не подтверждён", "schedule": "Официальное расписание", "duration": "Длительность",
           "minutes": "минут", "locations": "Кинотеатры CinemaPlus", "hall": "Зал не указан", "listed": "указанная цена",
           "seats": "Наличие мест неизвестно", "empty": "Подходящих результатов нет. Это не подтверждает наличие.", "rating": "Рейтинг TMDB"},
}
ERRORS = {
    "currency_filter_mismatch": ("Bu kataloq üçün yerli valyutada büdcə göstərin. Valyuta çevrilməsi edilmir.", "Укажите бюджет в валюте каталога. Конвертация валют не выполняется."),
    "currency_required": ("Büdcə üçün valyuta göstərin, məsələn USD.", "Укажите валюту бюджета, например USD."),
    "query_required": ("Məhsul adını və ya kateqoriyasını göstərin.", "Укажите название или категорию товара."),
    "unsupported_filter": ("Provayder bu filtri təsdiqləyə bilmir.", "Провайдер не может подтвердить этот фильтр."),
    "invalid_response": ("Provayder etibarlı məlumat qaytarmadı. Yenidən cəhd edin.", "Провайдер вернул некорректные данные. Попробуйте снова."),
    "upstream_degraded": ("Provayder axtarışı tamamlaya bilmədi. Yenidən cəhd edin.", "Провайдер не смог завершить поиск. Попробуйте снова."),
    "rate_limited": ("Provayderin sorğu limitinə çatılıb. Bir az sonra yenidən cəhd edin.", "Достигнут лимит запросов провайдера. Повторите позже."),
    "seat_availability_unavailable": ("Boş yerləri və son qiyməti CinemaPlus-un rəsmi saytında yoxlayın.", "Проверьте места и окончательную цену на официальном сайте CinemaPlus."),
    "unsupported_operation": ("Bu provayder alış, rezervasiya və ya stok yoxlaması etmir. Rəsmi sayta keçin.", "Провайдер не выполняет покупки, бронирования или проверку наличия. Перейдите на официальный сайт."),
    "authorization_required": ("Bu məlumat üçün provayderin icazəsi tələb olunur.", "Для этих данных требуется разрешение провайдера."),
    "missing_credentials": ("Provayder üçün API açarı konfiqurasiya edilməyib.", "API-ключ провайдера не настроен."),
}


def localize_outcomes(outcomes, language):
    if language == "en":
        return
    slot = 0 if language == "az" else 1
    notices = {
        "flights": ("Aviasales-in keşlənmiş qiymətləridir. Qiymət, baqaj və yerləri rəsmi saytda yoxlayın; rezervasiya təsdiqlənmir.",
                    "Цены из кеша Aviasales. Уточните цену, багаж и места на официальном сайте; бронирование не подтверждено."),
        "shopping": ("BuyWhere kataloq təklifləri Birmarket deyil. Qiymətlər köhnə ola bilər; tarixi və satıcıda son qiyməti yoxlayın. Stok və Azərbaycana çatdırılma təsdiqlənməyib. Keçidlər komissiya gətirə bilər.",
                     "Предложения каталога BuyWhere, а не Birmarket. Цены могут быть устаревшими; проверьте дату и цену у продавца. Наличие и доставка в Азербайджан не подтверждены. Ссылки могут приносить комиссию."),
        "cinema": ("CinemaPlus-un yayımladığı film və seans məlumatlarıdır. Yerlər və son qiymətlər üçün rəsmi sayta keçin.",
                   "Опубликованные фильмы и сеансы CinemaPlus. Места и окончательные цены уточняйте на официальном сайте."),
    }
    for outcome in outcomes:
        source = outcome.data.get("provider")
        if not source:
            continue
        error = outcome.data.get("provider_error")
        if error:
            message = ERRORS.get(error["code"], ("Məlumat mənbəyi əlçatan deyil. Yenidən cəhd edin.", "Источник данных недоступен. Попробуйте снова."))[slot]
            source["notice"] = error["message"] = message
        elif source["provider"] == "TMDB":
            source["notice"] = ("TMDB yalnız film məlumatıdır; CinemaPlus nümayişi və seansları təsdiqlənmir.", "TMDB предоставляет только данные о фильмах; показы и сеансы CinemaPlus не подтверждены.")[slot]
        elif outcome.domain == "shopping" and source["provider"] != "BuyWhere":
            source["notice"] = ("Provayderin məhsul məlumatlarıdır. Son qiyməti, stok və çatdırılmanı satıcıda yoxlayın.", "Данные товаров от провайдера. Уточните цену, наличие и доставку у продавца.")[slot]
        else:
            source["notice"] = notices[outcome.domain][slot]
