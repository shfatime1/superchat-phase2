"""AZ/EN/RU request normalization. Facts, IDs and quoted titles are never translated."""
import re
import unicodedata

ALIASES = {"english": "en", "azerbaijani": "az", "russian": "ru", "русский": "ru", "azərbaycan": "az"}


def language_code(value):
    value = (value or "").casefold()
    code = ALIASES.get(value, value.split("-")[0])
    return code if code in {"az", "en", "ru"} else None


def requested_language(message):
    text = message.casefold().strip(" .!?")
    choices = {"az": r"azərbaycanca|azerbaycanca|azerbaijani|azərbaycan dilində|az dilində",
               "ru": r"по-русски|на русском|русский|russian|rusca|rus dilində",
               "en": r"in english|english|ingiliscə|ingilisce|ingilis dilində|ingilis dilinde|на английском"}
    for language, expression in choices.items():
        if re.fullmatch(r"(?:please\s+)?(?:" + expression + r")(?:\s+please)?", text) or (
            re.search(r"\b(answer|respond|reply|speak|отвечай|ответь|говори|cavab|danış|yaz)\b", text)
            and re.search(expression, text)):
            return language
    return None


def language_only(message):
    text = message.casefold().strip(" .!?")
    patterns = [r"(?:please\s+)?(?:(?:answer|respond|reply|speak)(?:\s+to me)?\s+)?(?:in\s+)?(?:english|russian|azerbaijani)(?:\s+please)?",
                r"(?:пожалуйста\s+)?(?:(?:отвечай|ответь|говори)\s+)?(?:по-русски|(?:на\s+)?(?:русском|английском|азербайджанском))(?:\s+языке)?",
                r"(?:(?:mənə|mene)\s+)?(?:azərbaycanca|azerbaycanca|rusca|ingiliscə|ingilisce|(?:azərbaycan|azerbaycan|rus|ingilis)\s+dilind[əe])(?:\s+(?:cavab ver|danış|yaz))?"]
    return bool(requested_language(message) and any(re.fullmatch(pattern, text) for pattern in patterns))


def detect_language(message, previous=None):
    if requested_language(message):
        return requested_language(message)
    text = message.casefold()
    if re.search(r"\b(?:mene|lazimdi|lazimdir|qulaqciq\w*|qulaqcig\w*)\b", text):
        return "az"
    # Grammar signals beat borrowed product names and city names.
    az = len(re.findall(r"\b(?:göstər|goster|ucuz|ucuş\w*|uçuş\w*|sabah|bu gün|bugün|bu gun|dan|daha|notebooklar|noutbuk\w*|qulaqlıq\w*|qulaqliq\w*|filmlər|filmler|seans\w*|birinci|ikinci|müqayisə|muqayise|zəhmət|zehmet)\b", text))
    ru = len(re.findall(r"\b(?:покажи\w*|найди|рейс\w*|авиабилет\w*|ноутбук\w*|дешевле|дороже|сегодня|завтра|фильм\w*|сеанс\w*|перв\w*|втор\w*|сравни\w*|только|до|из|наушник\w*)\b", text))
    en = len(re.findall(r"\b(?:show|find|under|above|below|flights?|movies?|playing|please|compare|details|cheapest|cheaper|first|second|third|back|tomorrow|today|tonight|direct)\b", text))
    if az and az >= ru and az >= en:
        return "az"
    if ru and ru >= en:
        return "ru"
    if en:
        return "en"
    if re.search(r"[əƏğĞıİşŞçÇ]", message):
        return "az"
    if re.search(r"[а-яё]", text):
        return "ru"
    return language_code(previous) or "en"


# Long phrases are replaced before individual words. This is the conservative
# outage grammar; Gemini still receives the original multilingual request.
PHRASES = {
    r"(?:mənə|mene)\s+(.+?)\s+(?:lazımdır|lazimdi|lazimdir|lazımdı)": r"i need \1",
    r"qulaqcıq(?:lar)?|qulaqciq(?:lar)?|qulaqcig(?:lar)?": "headphones",
    r"elmi fantastika|elmi-fantastik|fantastika|научная фантастика|фантастик[аи]": "sci-fi",
    r"komediya|комеди[яию]": "comedy",
    r"reytinq|рейтинг(?:ом)?": "rating",
    r"rəng|reng|цвет(?:а)?": "color",
    r"marka|бренд(?:а)?": "brand",
    r"səbət|sebet|корзин[ауы]": "cart",
    r"çıxar|cixar|удали": "remove",
    r"hava necədir|hava necedir|погод[ауы]": "weather",
    r"nəsə yaxşı|nese yaxsi|что-нибудь хорошее": "something good",
    r"daha çox məhsul|daha cox mehsul|növbəti səhifə|novbeti sehife|ещё товары|еще товары|следующая страница": "more products",
    r"qiyməti artan|qiymeti artan|əvvəl ucuz|evvel ucuz|от дешевых к дорогим|сначала дешевые": "cheapest first",
    r"qiyməti azalan|qiymeti azalan|сначала дорогие": "most expensive first",
    r"birinci(?:si|ni)?|ilk(?:ini)?|перв(?:ый|ую|ое|ого)": "first one",
    r"ikinci(?:si|ni)?|втор(?:ой|ую|ое|ого)": "second one",
    r"üçüncü(?:sü|nü)?|ucun cu|трет(?:ий|ью|ье)": "third one",
    r"daha ucuz(?:unu)?|подешевле|самый дешевый": "the cheaper one",
    r"yalnız birbaşa|yalniz birbasa|только прямые": "only direct",
    r"bu axşam|bu aksam|сегодня вечером": "tonight",
    r"bu gün|bu gun|bugün|сегодня": "today",
    r"sabah|завтра": "tomorrow",
    r"bazar ertəsi|bazar ertesi|понедельник(?:а|у)?": "monday",
    r"çərşənbə axşamı|cersenbe axsami|вторник(?:а|у)?": "tuesday",
    r"çərşənbə|cersenbe|сред(?:а|у)": "wednesday",
    r"cümə axşamı|cume axsami|четверг(?:а|у)?": "thursday",
    r"cümə|cume|пятниц(?:а|у|ы)": "friday",
    r"şənbə|senbe|суббот(?:а|у|ы)": "saturday",
    r"bazar|воскресенье": "sunday",
    r"gələn|gelen|следующ(?:ий|ую|ее)": "next",
    r"simsiz qulaqlıq(?:lar)?|simsiz qulaqliq(?:lar)?|беспроводные наушники": "wireless headphones",
    r"qulaqlıqlar|qulaqlıq|qulaqliqlar|qulaqliq|наушник(?:и|ов)?": "headphones",
    r"notebook(?:lar|s)?|noutbuk(?:lar)?|ноутбук(?:и|а|ов)?|laptoplar": "laptops",
    r"telefon(?:lar)?|смартфон(?:ы|ов)?|телефон(?:ы|ов)?": "smartphones",
    r"bel çantası|bel cantasi|рюкзак(?:и|ов)?": "backpack",
    r"alış-veriş|alis-veris|покупки": "shopping",
    r"məhsullar|mehsullar|məhsul|товар(?:ы|ов)?": "products",
    r"təyyarə biletləri|teyyare biletleri|uçuşlar|uçuş|ucuslar|ucus|авиабилет(?:ы|ов)?|рейс(?:ы|ов)?": "flights",
    r"filmlər|filmler|film(?:lər|ler)?|фильм(?:ы|ов)?": "movies",
    r"seanslar|seans|сеанс(?:ы|ов)?|расписание": "showtimes",
    r"kinoteatr(?:lar)?|кинотеатр(?:ы|ов)?|кино|kino": "cinema",
    r"hamısını|hamisini|bütün|butun|все|всех": "all",
    r"göstər|goster|покажи(?:те)?": "show me",
    r"tap|найди(?:те)?": "find",
    r"istəyirəm|isteyirem|хочу": "i need",
    r"istənilən marka|istenilen marka|любой бренд": "any brand",
    r"zəhmət olmasa|zehmet olmasa|пожалуйста": "please",
    r"müqayisə et|muqayise et|сравни(?:ть|те)?": "compare",
    r"ətraflı|etrafli|подробнее|детали": "details",
    r"qayıt|qayit|вернись к|назад к": "back to",
    r"yalnız|yalniz|только": "only",
    r"birbaşa|birbasa|прямые|прямой": "direct",
    r"yerlər|yerler|yer|места|мест": "seats",
    r"mövcuddur|movcuddur|доступно|наличие": "available",
    r"baqaj|багаж": "baggage",
    r"sərnişin|sernisin|пассажир(?:а|ов|ы)?": "passengers",
    r"səbətə əlavə et|sebete elave et|добавь в корзину": "add to my cart",
    r"rezerv et|забронируй": "reserve",
    r"etmə|etme|не надо|не бронируй|не добавляй": "do not",
    r"не|никогда": "not",
    r"iki|два|две": "two", r"üç|uc|три": "three",
    r"əgər|eger|если": "if",
    r"olmadan|без": "without",
    r"və|ve|и|также": "and",
    r"qara|черный|чёрный": "black",
    r"ağ|ag|белый": "white",
    r"rus dilində|на русском": "in Russian",
    r"ingilis dilində|на английском": "in English",
    r"azərbaycan dilində|на азербайджанском": "in Azerbaijani",
    r"dollar(?:dan|a)?|доллар(?:ов|а|ы)?": "USD",
    r"manat(?:dan|a)?|манат(?:ов|а|ы)?": "AZN",
    r"avro|евро": "EUR",
    r"qiyməti|qiymeti|цена|ценой": "price",
    r"aşağı|asagi|дешевле|менее|до": "under",
    r"yuxarı|yuxari|дороже|более|от": "above",
    r"ən azı|en azi|не менее": "at least",
    r"bakıdan|bakidan|баку": "baku",
    r"istanbula|istanbulu|istanbuldan|стамбул(?:а)?": "istanbul",
    r"bakı|baki": "baku",
    r"dubay(?:a|dan)?|дуба(?:й|я)": "dubai",
    r"moskva(?:ya|dan)?|москв(?:а|ы|у)": "moscow",
    r"из": "from", r"в": "to",
    r"yanvar|января": "january", r"fevral|февраля": "february",
    r"mart|марта": "march", r"aprel|апреля": "april", r"may|мая": "may",
    r"iyun|июня": "june", r"iyul|июля": "july", r"avqust|августа": "august",
    r"sentyabr|сентября": "september", r"oktyabr|октября": "october",
    r"noyabr|ноября": "november", r"dekabr|декабря": "december",
}


def normalize_text(message):
    text = unicodedata.normalize("NFC", message)
    protected = []
    def protect(match):
        protected.append(match[0]); return f" zzprotected{len(protected)-1}zz "
    text = re.sub(r'"[^"\n]+"|“[^”\n]+”|\b(?:bw-[\w-]+|cp-[\w-]+|av-[a-f0-9]{16}|tmdb-\d+|ebay-v1\|\d+\|\d+)\b', protect, text, flags=re.I)
    text = text.casefold().replace("i\u0307", "i")
    # Azerbaijani's case endings express from/to without separate prepositions.
    for city, english in ((r"bakı|baki|baku", "baku"), (r"istanbul", "istanbul"), (r"dubay|dubai", "dubai"), (r"moskva", "moscow")):
        text = re.sub(r"\b(?:" + city + r")[ '-]?(?:dan|dən|den)\b", "from " + english, text)
        text = re.sub(r"\b(?:" + city + r")[ '-]?(?:ya|yə|ye|a|ə)\b", "to " + english, text)
    text = re.sub(r"\b(?:dollar)(?:dan|a)?\b", "USD", text)
    text = re.sub(r"(?<=\d),(\d{1,2})(?!\d)", r".\1", text)
    text = re.sub(r"\bне менее\b", "at least", text)
    text = re.sub(r"\bне более\b", "under", text)
    # '500$ dan ucuz' -> 'under 500$'; retain the original numeric value.
    text = re.sub(r"((?:[$€₼]\s*)?\d+(?:[.,]\d+)?\s*(?:[$€₼]|usd|eur|azn)?)\s*-?\s*(?:dan|dən|den)?\s*(?:ucuz|aşağı|asagi)\b", r"under \1", text, flags=re.I)
    for pattern, value in PHRASES.items():
        text = re.sub(r"(?<!\w)(?:" + pattern + r")(?!\w)", value, text, flags=re.I)
    text = re.sub(r"\b(?:mənə|mene|мне)\b", "", text)
    text = re.sub(r"\b(?:lazimdi|lazimdir|lazımdır|lazımdı)\b", "", text)
    text = re.sub(r"\b(?:is\s+)?(?:price|priced|costs?)\s+(?=under|below|above|over)", "", text)
    text = re.sub(r"\s+show me[.!?]*$", "", text)
    text = text.casefold()
    for index, value in enumerate(protected):
        text = text.replace(f"zzprotected{index}zz", value)
    return re.sub(r"\s+", " ", text).strip()
