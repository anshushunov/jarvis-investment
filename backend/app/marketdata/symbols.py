"""Куда идти за ценой бумаги и под каким именем её там спрашивать.

Правило здесь одно на проект: и ежедневное обновление котировок
(app/marketdata/service.py), и разовая загрузка истории
(app/marketdata/history.py) спрашивают его, а не решают сами. Два правила о
том, где котируется бумага, разъедутся так же, как разъехались два правила о
знаке ADJUSTMENT — и стоить это будет неверной оценки капитала.
"""

from sqlalchemy import func, or_

from app.models import Instrument
from app.money import BASE_CURRENCY

# Площадку задаёт эмитент, а не валюта расчётов сама по себе. Восемь облигаций
# российских эмитентов номинированы в юанях (РУСАЛ, Полюс, Роснефть, ЭН+ и
# другие) и торгуются на MOEX; прежнее правило «на MOEX ходим только за
# рублёвыми» уводило их к брокеру, и биржевой цены у них не было вовсе.
MOEX_ISIN_PREFIX = "RU"

# Но и одного ISIN мало: расписки и редомицилированные компании торгуются на
# MOEX с иностранным ISIN — HeadHunter (US42207L1061), РусАгро (US7496552057),
# X5 (US98387E2054), Russia 2028 (XS0088543193). Замер живой базы 12.08.2026:
# правило по одному ISIN уводило с биржи десять таких бумаг, три из них лежат в
# портфеле. Рублёвые расчёты — признак того, что бумага торгуется в России, и
# он дополняет ISIN, а не заменяет его: у юаневой облигации расчёты не
# рублёвые, у гонконгской бумаги — не рублёвые тоже, и второй признак их не
# путает.

# Гонконгская биржа нумерует бумаги четырьмя знаками: 700 — это 0700.HK.
HK_SYMBOL_WIDTH = 4

# Бумаги, у которых справочник брокера положил в тикер сам ISIN, а настоящий
# символ известен. Сопоставление задано поимённо, потому что вывести его не из
# чего: тикер сменился (Block был SQ, стал XYZ) либо бумага живёт в двух
# валютных линейках (гонконгский фонд iShares: 3010.HK за гонконгские доллары,
# 83010.HK за юани). Проверено на живых ответах Yahoo 12.08.2026; валюта в
# ответе совпала с валютой инструмента у всех пяти.
YAHOO_SYMBOL_BY_ISIN = {
    "US8522341036": "XYZ",       # Block, бывший SQ
    "US87918A1051": "TDOC",      # Teladoc Health
    "US91332U1016": "U",         # Unity Software
    "HK0000051877": "3010.HK",   # iShares Core MSCI Asia ex Japan, гонконгская линейка
    "HK0000310034": "83010.HK",  # он же, юаневая линейка
    "US0567521085": "BIDU",      # Baidu, американские расписки
    "US92766K1060": "SPCE",      # Virgin Galactic, обратный сплит 1:20 в 2024
}

# Бумаги, которых у Yahoo нет и не будет: делистинг без правопреемника на
# бирже. Перечислены явно, чтобы прогон не тратил на них запрос и чтобы
# следующая сессия не искала «почему не нашлось».
YAHOO_UNAVAILABLE = {
    "US87238U2033",  # ТКС Холдинг после редомициляции
    # Bed Bath & Beyond. Тикер BBBY у Yahoo отвечает и даже совпадает по
    # названию и валюте — но принадлежит другому юрлицу: после банкротства
    # 2023 года его занял бывший Overstock. За 20.01.2021 он отдаёт 60,93 —
    # цену Overstock, тогда как сама BBBY стоила около 21. Защита по валюте
    # такую подмену не ловит, поэтому бумага объявлена ненаходимой явно.
    "US0758961009",
}


def priced_at_moex(instrument: Instrument) -> bool:
    """Идём ли за ценой этой бумаги на MOEX."""
    isin = (instrument.isin or "").upper()
    currency = (instrument.currency or BASE_CURRENCY).upper()
    return bool(instrument.secid) and (
        isin.startswith(MOEX_ISIN_PREFIX) or currency == BASE_CURRENCY
    )


def moex_filter(isin_column, currency_column) -> object:
    """То же правило для выборки из базы: ISIN российского эмитента либо
    рублёвые расчёты."""
    return or_(
        func.upper(func.coalesce(isin_column, "")).startswith(MOEX_ISIN_PREFIX),
        func.upper(func.coalesce(currency_column, BASE_CURRENCY)) == BASE_CURRENCY,
    )


def yahoo_symbol(instrument: Instrument) -> str | None:
    """Символ Yahoo или None, если спрашивать нечего.

    None означает «символа нет», а не «ошибка»: бумага останется неоценённой на
    своих датах, и это будет видно в покрытии снимка. Угадывать хуже, чем не
    знать: неверный символ даёт правдоподобную цену чужой бумаги.
    """
    isin = instrument.isin or ""
    if isin in YAHOO_UNAVAILABLE:
        return None
    known = YAHOO_SYMBOL_BY_ISIN.get(isin)
    if known:
        return known
    if priced_at_moex(instrument):
        return None

    ticker = (instrument.ticker or "").strip().upper()
    if not ticker or ticker == isin.upper():
        return None
    if ticker.isdigit():
        return f"{ticker.zfill(HK_SYMBOL_WIDTH)}.HK"
    return ticker
