from datetime import date
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.labels import UNKNOWN_ACCOUNT_LABEL, account_label
from app.analytics.service import portfolio_overview
from app.models import Account, DailySnapshot


def take_snapshot(session: Session, on_date: date) -> DailySnapshot:
    overview = portfolio_overview(session)

    values = {
        "on_date": on_date,
        "total_value": overview.total_value,
        "by_asset_class": {k: str(v) for k, v in overview.by_asset_class.items()},
        # Ключ — идентификатор счёта, а не его подпись. Подпись меняется вместе
        # с именем счёта и вместе с составом выборки, а снимок живёт годами:
        # снимки, снятые до и после переименования (или до и после появления
        # второго счёта с тем же именем), переставали склеиваться по счёту.
        # JSONB хранит ключи строками, поэтому идентификатор здесь — строка.
        "by_account": {str(account_id): str(value) for account_id, value in overview.by_account.items()},
    }

    statement = insert(DailySnapshot).values(**values).on_conflict_do_update(
        index_elements=[DailySnapshot.on_date],
        set_={
            "total_value": values["total_value"],
            "by_asset_class": values["by_asset_class"],
            "by_account": values["by_account"],
        },
    )
    session.execute(statement)
    session.flush()

    return session.query(DailySnapshot).filter(DailySnapshot.on_date == on_date).one()


def snapshot_by_account(accounts: dict[int, Account], snapshot: DailySnapshot) -> dict[str, Decimal]:
    """Разбивка снимка по счетам, подписанная для показа.

    Подпись строится здесь, при чтении, единственной на проект функцией
    (app/accounts/labels.py) — в самом снимке лежит устойчивый идентификатор.

    Снимки, снятые до этой правки, хранят ключом уже готовую подпись. Их
    ключи не числовые и не соответствуют ни одному счёту, поэтому отдаются как
    есть: переписывать историю ради формата ключа незачем, а терять её тем
    более. Отдельной миграции данных для этого не нужно.

    Счета приходят снаружи готовым словарём, а не выбираются здесь: читатель
    (`/portfolio/history`) зовёт эту функцию на каждую точку окна истории — до
    90 в сутки при снимке раз в день, — и запрос без фильтра внутри такого
    цикла превращал бы один обход в 1 + N SQL-запросов. Три соседних
    обработчика в routes_portfolio.py (`get_overview`, `get_positions`,
    `get_cash`) по той же причине выбирают счета в словарь один раз на запрос
    и передают его дальше; здесь тот же приём, просто на один уровень глубже.
    """
    result: dict[str, Decimal] = {}
    for key, value in (snapshot.by_account or {}).items():
        account = accounts.get(int(key)) if key.lstrip("-").isdigit() else None
        if account is not None:
            label = account_label(account)
        elif key.lstrip("-").isdigit():
            # Счёт был удалён из базы, а снимок остался — подпись восстановить
            # не из чего, но сумму терять нельзя.
            label = UNKNOWN_ACCOUNT_LABEL
        else:
            label = key  # снимок старого формата: ключ уже подпись
        result[label] = Decimal(value)
    return result
