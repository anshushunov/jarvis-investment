from datetime import date, datetime
from decimal import Decimal
from typing import Callable
from xml.etree import ElementTree

import httpx

from app.config import get_settings

# ЦБ отдаёт XML в windows-1251 и с десятичной запятой. httpx угадывает
# кодировку по заголовку, но полагаться на это не стоит: разбираем байты сами.
ENCODING = "windows-1251"
# Курс к рублю хранится с восемью знаками: у валют с номиналом в сто и тысячу
# (иена, донг) четырёх знаков не хватает — 0.0027 вместо 0.00274523 даёт
# ошибку в проценты.
RATE_EXP = Decimal("0.00000001")


def _http_get(url: str, params: dict[str, str], timeout: float) -> bytes:
    response = httpx.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.content


class CbrClient:
    """Курсы валют Банка России из XML_daily.

    Выбран XML_daily, а не SOAP-сервис DailyInfoWebServ из спеки: тот же набор
    данных отдаётся обычным GET без конверта SOAP, а курсы на дату — ровно то
    единственное, что от ЦБ нужно этой фазе.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 15.0,
        fetch: Callable[[str, dict[str, str], float], bytes] = _http_get,
    ) -> None:
        self.base_url = (base_url or get_settings().cbr_base_url).rstrip("/")
        self.timeout = timeout
        # Внедряемая загрузка: тесты разбирают записанный ответ, не выходя в сеть.
        self._fetch = fetch

    def rates(self, on_date: date) -> tuple[date, dict[str, Decimal]]:
        """Курсы, действующие на `on_date`, и дата, на которую они установлены.

        Эти две даты не совпадают в выходные и праздники: ЦБ не публикует курс
        на каждый календарный день, и на запрос воскресенья отвечает курсом
        пятницы, сообщая это атрибутом Date. Записывать такой курс под
        запрошенной датой значит выдумать публикацию, которой не было; поэтому
        дата возвращается наружу и хранение идёт под ней.
        """
        body = self._fetch(
            f"{self.base_url}/scripts/XML_daily.asp",
            {"date_req": on_date.strftime("%d/%m/%Y")},
            self.timeout,
        )
        root = ElementTree.fromstring(body.decode(ENCODING))
        effective = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date()

        rates: dict[str, Decimal] = {}
        for valute in root.findall("Valute"):
            code = (valute.findtext("CharCode") or "").upper()
            nominal = valute.findtext("Nominal")
            value = valute.findtext("Value")
            if not code or not nominal or not value:
                continue
            rate = Decimal(value.replace(",", ".")) / Decimal(nominal)
            rates[code] = rate.quantize(RATE_EXP)
        return effective, rates
