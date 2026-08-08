from datetime import date
from decimal import Decimal

from app.analytics.service import portfolio_overview, position_rows
from app.models import Account, DailySnapshot, Instrument, Position, Price
from app.snapshots.service import snapshot_by_account, take_snapshot


def seed(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    share = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                       kind="share", currency="RUB", issuer="Сбербанк")
    fund = Instrument(isin="RU000A0JXMB2", ticker="TMOS", secid="TMOS",
                      kind="etf", currency="RUB", asset_class="equity")
    bond = Instrument(isin="RU000A101234", ticker="OFZ", secid="OFZ",
                      kind="bond", currency="RUB")
    session.add_all([account, share, fund, bond])
    session.flush()

    session.add_all([
        Position(account_id=account.id, instrument_id=share.id,
                 quantity=Decimal("10"), average_price=Decimal("100")),
        Position(account_id=account.id, instrument_id=fund.id,
                 quantity=Decimal("100"), average_price=Decimal("7")),
        Position(account_id=account.id, instrument_id=bond.id,
                 quantity=Decimal("5"), average_price=Decimal("1000")),
    ])
    session.add_all([
        Price(instrument_id=share.id, on_date=date(2026, 3, 12), close=Decimal("150"), source="moex"),
        Price(instrument_id=fund.id, on_date=date(2026, 3, 12), close=Decimal("8"), source="moex"),
        Price(instrument_id=bond.id, on_date=date(2026, 3, 12), close=Decimal("1010"), source="moex"),
    ])
    session.flush()
    return account


def test_total_value_uses_last_prices(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.positions_value == Decimal("7350.0000")


def test_fund_is_counted_by_its_asset_class(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.by_asset_class["equity"] == Decimal("2300.0000")
    assert overview.by_asset_class["bonds"] == Decimal("5050.0000")
    assert "etf" not in overview.by_asset_class


def test_position_row_computes_profit(session):
    seed(session)
    rows = {row.ticker: row for row in position_rows(session)}
    assert rows["SBER"].market_value == Decimal("1500.0000")
    assert rows["SBER"].profit == Decimal("500.0000")
    assert rows["SBER"].profit_percent == Decimal("50.0000")


def test_position_without_price_has_no_market_value_not_zero(session):
    account = seed(session)
    nameless = Instrument(isin="RU000NOPRICE", ticker="NONE", secid=None,
                          kind="share", currency="RUB")
    session.add(nameless)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=nameless.id,
                         quantity=Decimal("1"), average_price=Decimal("50")))
    session.flush()

    rows = {row.ticker: row for row in position_rows(session)}
    assert rows["NONE"].last_price is None
    # Не ноль: «0 ₽» читается как «бумага ничего не стоит», а тут просто нет
    # котировки. Настоящий ноль остаётся возможен — см. тест ниже про дефолт.
    assert rows["NONE"].market_value is None
    assert rows["NONE"].profit is None
    assert rows["NONE"].profit_percent is None


def test_overview_reports_valuation_coverage(session):
    """Главная цифра дашборда считается только по оценённым позициям. Сколько
    их из скольких — обязано доехать до ответа, иначе неоценённые молча
    выпадают из совокупного капитала и с экрана этого не заметить."""
    account = seed(session)
    unpriced = Instrument(isin="RU000NOPRICE", ticker="NONE", secid=None,
                          kind="share", currency="RUB")
    session.add(unpriced)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=unpriced.id,
                         quantity=Decimal("1"), average_price=Decimal("50")))
    session.flush()

    overview = portfolio_overview(session)
    assert overview.positions_total == 4
    assert overview.valued_positions == 3
    # Итог по-прежнему только по оценённым — меняется не он, а то, что рядом
    # с ним теперь видно покрытие.
    assert overview.positions_value == Decimal("7350.0000")


def test_overview_coverage_is_full_when_every_position_is_priced(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.valued_positions == overview.positions_total == 3


def test_snapshot_stores_total_and_breakdown(session):
    seed(session)
    snapshot = take_snapshot(session, date(2026, 3, 12))
    assert snapshot.total_value == Decimal("7350.0000")
    assert snapshot.by_asset_class["equity"] == "2300.0000"


def test_snapshot_same_day_is_overwritten(session):
    seed(session)
    take_snapshot(session, date(2026, 3, 12))
    take_snapshot(session, date(2026, 3, 12))
    assert session.query(DailySnapshot).count() == 1


def test_overview_as_of_uses_max_price_date(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.as_of == date(2026, 3, 12)


def test_overview_as_of_prefers_latest_of_mixed_dates(session):
    account = seed(session)
    later = Instrument(isin="RU000LATER01", ticker="LATER", secid="LATER",
                       kind="share", currency="RUB", issuer="Позже")
    session.add(later)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=later.id,
                         quantity=Decimal("1"), average_price=Decimal("10")))
    session.add(Price(instrument_id=later.id, on_date=date(2026, 3, 15),
                       close=Decimal("20"), source="moex"))
    session.flush()

    overview = portfolio_overview(session)
    assert overview.as_of == date(2026, 3, 15)


def test_overview_as_of_empty_when_no_prices(session):
    overview = portfolio_overview(session)
    assert overview.as_of is None


def test_snapshot_roundtrip_keeps_decimal(session):
    account = seed(session)
    take_snapshot(session, date(2026, 3, 12))
    session.expire_all()
    stored = session.query(DailySnapshot).filter(DailySnapshot.on_date == date(2026, 3, 12)).one()
    assert stored.by_asset_class["equity"] == "2300.0000"
    assert Decimal(stored.by_asset_class["equity"]) == Decimal("2300.0000")
    assert Decimal(stored.by_account[str(account.id)]) == Decimal("7350.0000")


def test_snapshot_keys_accounts_by_stable_identifier(session):
    """Подпись не годится ключом постоянного хранилища: она меняется вместе с
    именем счёта и вместе с составом выборки, и исторические снимки перестают
    склеиваться по счёту."""
    account = seed(session)
    take_snapshot(session, date(2026, 3, 12))
    session.expire_all()

    stored = session.query(DailySnapshot).filter(DailySnapshot.on_date == date(2026, 3, 12)).one()
    assert list(stored.by_account) == [str(account.id)]

    # Счёт переименовали — ключ снимка обязан остаться прежним.
    account.name = "Совсем другое имя"
    session.flush()
    take_snapshot(session, date(2026, 3, 13))
    session.expire_all()
    renamed = session.query(DailySnapshot).filter(DailySnapshot.on_date == date(2026, 3, 13)).one()
    assert list(renamed.by_account) == [str(account.id)]


def test_snapshot_by_account_is_labelled_at_read_time(session):
    account = seed(session)
    snapshot = take_snapshot(session, date(2026, 3, 12))

    assert snapshot_by_account(session, snapshot) == {
        "Брокерский (acc-1)": Decimal("7350.0000")
    }


def test_snapshot_of_old_format_is_still_readable(session):
    """В базе уже есть снимки, снятые до правки: ключом там лежит готовая
    подпись. Переписывать историю ради формата ключа незачем — такие ключи
    отдаются как есть, лишь бы сумма не потерялась."""
    legacy = DailySnapshot(on_date=date(2026, 2, 1), total_value=Decimal("100"),
                           by_asset_class={}, by_account={"Инвестиционный": "100.0000"})
    session.add(legacy)
    session.flush()

    assert snapshot_by_account(session, legacy) == {"Инвестиционный": Decimal("100.0000")}


def test_position_with_zero_price_shows_full_loss(session):
    account = seed(session)
    defaulted = Instrument(isin="RU000DEFAUL1", ticker="DEFLT", secid="DEFLT",
                           kind="share", currency="RUB", issuer="Дефолтный эмитент")
    session.add(defaulted)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=defaulted.id,
                         quantity=Decimal("10"), average_price=Decimal("50")))
    session.add(Price(instrument_id=defaulted.id, on_date=date(2026, 3, 12),
                       close=Decimal("0"), source="moex"))
    session.flush()

    rows = {row.ticker: row for row in position_rows(session)}
    row = rows["DEFLT"]
    assert row.last_price is not None
    assert row.market_value == Decimal("0.0000")
    assert row.profit == Decimal("-500.0000")
    assert row.profit_percent == Decimal("-100.0000")


def test_by_account_keeps_distinct_names_as_own_rows(session):
    first = Account(broker="tbank", kind="brokerage", external_id="acc-a",
                    name="ИИС", currency="RUB")
    second = Account(broker="sber", kind="brokerage", external_id="acc-b",
                     name="Брокерский Сбер", currency="RUB")
    share = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                       kind="share", currency="RUB", issuer="Сбербанк")
    session.add_all([first, second, share])
    session.flush()
    session.add_all([
        Position(account_id=first.id, instrument_id=share.id,
                 quantity=Decimal("1"), average_price=Decimal("100")),
        Position(account_id=second.id, instrument_id=share.id,
                 quantity=Decimal("2"), average_price=Decimal("100")),
    ])
    session.add(Price(instrument_id=share.id, on_date=date(2026, 3, 12),
                       close=Decimal("150"), source="moex"))
    session.flush()

    overview = portfolio_overview(session)
    # Разбивка ключуется идентификаторами счетов; подпись строится при чтении.
    assert overview.by_account[first.id] == Decimal("150.0000")
    assert overview.by_account[second.id] == Decimal("300.0000")


def _seed_foreign(session, account):
    """Позиция, номинированная не в рублях, — на живых данных таких четверть."""
    foreign = Instrument(isin="US0378331005", ticker="AAPL", secid="AAPL",
                         kind="share", currency="USD", issuer="Apple")
    session.add(foreign)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=foreign.id,
                         quantity=Decimal("10"), average_price=Decimal("150")))
    session.add(Price(instrument_id=foreign.id, on_date=date(2026, 3, 12),
                       close=Decimal("200"), source="moex"))
    session.flush()
    return foreign


def test_foreign_currency_is_kept_out_of_the_ruble_total(session):
    """Умножение количества на цену без учёта валюты и подпись рублём молча
    завышали капитал. Рублёвый итог считается только по рублёвой части."""
    account = seed(session)
    _seed_foreign(session, account)

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("7350.0000")
    assert overview.by_currency["RUB"] == Decimal("7350.0000")
    assert overview.by_currency["USD"] == Decimal("2000.0000")


def test_breakdowns_add_up_to_the_ruble_total(session):
    """Разбивки считаются по той же рублёвой части, что и итог, — иначе они
    с ним не сходятся."""
    account = seed(session)
    _seed_foreign(session, account)

    overview = portfolio_overview(session)

    assert sum(overview.by_asset_class.values()) == overview.total_value
    assert sum(overview.by_account.values()) == overview.total_value


def test_foreign_position_is_still_counted_as_valued(session):
    """Позиция в валюте оценена (котировка есть) — она не «неоценённая», она
    просто вне рублёвого итога. Путать эти две вещи нельзя."""
    account = seed(session)
    _seed_foreign(session, account)

    overview = portfolio_overview(session)
    assert overview.positions_total == 4
    assert overview.valued_positions == 4


def test_position_row_carries_its_own_currency(session):
    account = seed(session)
    _seed_foreign(session, account)

    rows = {row.ticker: row for row in position_rows(session)}
    assert rows["AAPL"].currency == "USD"
    assert rows["SBER"].currency == "RUB"
    # Стоимость строки — в её собственной валюте, без всякого пересчёта.
    assert rows["AAPL"].market_value == Decimal("2000.0000")


def test_by_account_keeps_same_name_accounts_apart(session):
    """Два счёта с одинаковым именем — не редкость (коннектор Т-Банка
    подставляет заглушку «Счёт»). Ключ разбивки их различает по построению:
    это идентификатор счёта, а не имя."""
    first = Account(broker="tbank", kind="brokerage", external_id="acc-x",
                    name="Счёт", currency="RUB")
    second = Account(broker="tbank", kind="iis", external_id="acc-y",
                     name="Счёт", currency="RUB")
    share = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                       kind="share", currency="RUB", issuer="Сбербанк")
    session.add_all([first, second, share])
    session.flush()
    session.add_all([
        Position(account_id=first.id, instrument_id=share.id,
                 quantity=Decimal("1"), average_price=Decimal("100")),
        Position(account_id=second.id, instrument_id=share.id,
                 quantity=Decimal("2"), average_price=Decimal("100")),
    ])
    session.add(Price(instrument_id=share.id, on_date=date(2026, 3, 12),
                       close=Decimal("150"), source="moex"))
    session.flush()

    overview = portfolio_overview(session)
    assert len(overview.by_account) == 2
    assert overview.by_account[first.id] == Decimal("150.0000")
    assert overview.by_account[second.id] == Decimal("300.0000")
    assert sum(overview.by_account.values()) == overview.positions_value
