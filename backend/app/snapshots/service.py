from datetime import date
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.labels import UNKNOWN_ACCOUNT_LABEL, account_label
from app.analytics.service import Overview, portfolio_overview
from app.models import SNAPSHOT_LIVE, Account, DailySnapshot


def store_snapshot(
    session: Session, on_date: date, overview: Overview, source: str
) -> DailySnapshot:
    """Записывает точку истории, не затирая более полную.

    Правило одно: перезаписать можно свою же точку (повторный прогон обязан
    обновлять то, что сам записал) либо чужую, у которой покрытие меньше или
    неизвестно вовсе. Живой снимок не свят — свято покрытие: точка 09.08.2026
    снята живьём, но кодом, не знавшим ни денег, ни двух третей позиций.

    Выражено правилом, а не разовой правкой руками: прогон повторяется, и через
    месяц никто не вспомнит, какие даты правились.
    """
    values = {
        "on_date": on_date,
        "total_value": overview.total_value,
        "by_asset_class": {k: str(v) for k, v in overview.by_asset_class.items()},
        # Ключ — идентификатор счёта, а не его подпись. Подпись меняется вместе
        # с именем счёта и вместе с составом выборки, а снимок живёт годами:
        # снимки, снятые до и после переименования (или до и после появления
        # второго счёта с тем же именем), переставали склеиваться по счёту.
        # JSONB хранит ключи строками, поэтому идентификатор здесь — строка.
        # Читающая сторона знает это же правило — snapshot_by_account ниже.
        "by_account": {str(account_id): str(value) for account_id, value in overview.by_account.items()},
        "source": source,
        "positions_total": overview.positions_total,
        "valued_positions": overview.valued_positions,
        "unpriced": overview.unpriced,
    }

    statement = insert(DailySnapshot).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[DailySnapshot.on_date],
        set_={key: value for key, value in values.items() if key != "on_date"},
        where=or_(
            DailySnapshot.source == source,
            DailySnapshot.valued_positions.is_(None),
            DailySnapshot.valued_positions < statement.excluded.valued_positions,
        ),
    )
    session.execute(statement)
    session.flush()

    return session.query(DailySnapshot).filter(DailySnapshot.on_date == on_date).one()


def take_snapshot(session: Session, on_date: date) -> DailySnapshot:
    """Снимок сегодняшнего состояния — тот, что снимает планировщик."""
    return store_snapshot(session, on_date, portfolio_overview(session), SNAPSHOT_LIVE)


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
