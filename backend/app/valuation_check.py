"""Сверка нашей оценки капитала с итогом брокера.

Запускается вручную: `cd backend && uv run python -m app.valuation_check`.
Читающий инструмент — ходит в API брокера за итогами по счетам и ничего не
меняет ни у брокера, ни в базе.

Зачем отдельный модуль, а не тест: сверять есть смысл только на настоящих
данных владельца, а они в тесты не попадают и попадать не должны.
"""

import logging
from decimal import Decimal

import httpx

from app.analytics.service import portfolio_overview
from app.config import get_settings
from app.connectors.tbank.client import OPERATIONS_SERVICE, TBankClient
from app.connectors.tbank.quotation import to_money
from app.db import SessionLocal
from app.models import Account
from app.money import money

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Расхождение, ниже которого сверка считается сошедшейся. Копейки набегают
# из-за разного порядка округления и разной секунды котировки; проценты — нет.
TOLERANCE_RATIO = Decimal("0.005")

# Один относительный допуск на крупном счёте слишком щедр: полпроцента от пяти
# миллионов — это двадцать пять тысяч рублей, которые прошли бы как «ок».
# Поэтому расхождение обязано укладываться в оба допуска сразу.
TOLERANCE_ABSOLUTE = money("15000")


def main() -> None:
    token = get_settings().tbank_token
    if not token:
        logger.warning("TBANK_TOKEN не задан — сверять не с чем")
        return

    client = TBankClient(token)
    with SessionLocal() as session:
        overview = portfolio_overview(session)
        accounts = {
            account.id: account
            for account in session.query(Account).filter(Account.broker == "tbank")
        }

        total_ours = money("0")
        total_theirs = money("0")
        # Перебираем все счета брокера, а не только те, что попали в
        # by_account: счёт, синхронизация которого отвалилась целиком, не имеет
        # ни позиций, ни денег — и в прежней версии не появлялся в сверке
        # вовсе. Ровно тот случай, ради которого сверку и смотрят.
        for account in sorted(accounts.values(), key=lambda item: item.name):
            ours = overview.by_account.get(account.id, money("0"))
            try:
                payload = client._post(
                    OPERATIONS_SERVICE, "GetPortfolio", {"accountId": account.external_id}
                )
            except httpx.HTTPError as exc:
                # Перебор теперь идёт по всем счетам брокера, включая никогда
                # не синхронизировавшиеся и закрытые (см. правку выше) —
                # запрос по такому счёту вполне может ответить 4xx или
                # оборваться по сети. Без перехвата один такой счёт обрывал бы
                # весь скрипт и прятал состояние всех остальных, а сверку
                # смотрят именно тогда, когда что-то уже сломалось. Итог по
                # счёту при этом не подставляется нулём — его просто нет, и
                # ниже он не участвует в "Итого сопоставимых счетов".
                logger.info(
                    "%-28s наш %14s   брокер: ошибка запроса (%s)",
                    account.name, f"{ours:,.2f}", exc,
                )
                continue
            raw_total = payload.get("totalAmountPortfolio")
            if not raw_total:
                # Счёт особого типа (цифровые финансовые активы) итога не даёт.
                logger.info("%-28s наш %14s   брокер итога не даёт", account.name, f"{ours:,.2f}")
                continue
            theirs = to_money(raw_total)
            diff = ours - theirs
            # Процент печатается рядом: без него читатель вынужден делить в уме,
            # а именно доля отличает шум округления от потерянной бумаги.
            share = abs(diff) / abs(theirs) * 100 if theirs else Decimal("0")
            within = abs(diff) <= abs(theirs) * TOLERANCE_RATIO and abs(diff) <= TOLERANCE_ABSOLUTE
            logger.info(
                "%-28s наш %14s   брокер %14s   разница %12s (%5.2f%%)  %s",
                account.name, f"{ours:,.2f}", f"{theirs:,.2f}", f"{diff:,.2f}", share,
                "ок" if within else "РАСХОЖДЕНИЕ",
            )
            total_ours += ours
            total_theirs += theirs

        logger.info("")
        logger.info("Итого сопоставимых счетов: наш %s, брокер %s, разница %s",
                    f"{total_ours:,.2f}", f"{total_theirs:,.2f}",
                    f"{total_ours - total_theirs:,.2f}")
        logger.info("Оценено позиций: %s из %s", overview.valued_positions,
                    overview.positions_total)
        logger.info("Из них недоступно к продаже: %s", f"{overview.restricted_value:,.2f}")


if __name__ == "__main__":
    main()
