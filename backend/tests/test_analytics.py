from datetime import date
from decimal import Decimal

from app.accounts.cash import store_cash
from app.analytics.service import portfolio_overview, position_rows
from app.connectors.base import BrokerCash, BrokerPosition
from app.models import Account, DailySnapshot, FxRate, Instrument, Position, Price
from app.snapshots.service import snapshot_by_account, take_snapshot
from app.sync.holdings import store_holdings
from app.timeutils import moscow_today


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


def add_account(session, external_id: str = "acc-1", kind: str = "brokerage") -> Account:
    account = Account(broker="tbank", kind=kind, external_id=external_id,
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()
    return account


def add_priced_position(
    session,
    account,
    isin: str,
    quantity: Decimal,
    price: Decimal | None = None,
    currency: str = "RUB",
    reference_currency: str | None = None,
    kind: str = "share",
    restricted: bool = False,
    average_price: Decimal = Decimal("0"),
    on_date: date = date(2026, 3, 12),
) -> Instrument:
    """Позиция на счёте вместе с её последней котировкой.

    `currency` — валюта цены, а не справочника: это то, чем оценка теперь
    руководствуется. `reference_currency` задаётся отдельно только там, где они
    должны разойтись (замещающая облигация: в справочнике брокера рубли,
    котируется в юанях). `price=None` — котировки нет вовсе, позиция остаётся
    неоценённой.
    """
    instrument = Instrument(isin=isin, ticker=isin, secid=isin, kind=kind,
                            currency=reference_currency or currency,
                            trading_restricted=restricted)
    session.add(instrument)
    session.flush()

    session.add(Position(account_id=account.id, instrument_id=instrument.id,
                         quantity=quantity, average_price=average_price))
    if price is not None:
        session.add(Price(instrument_id=instrument.id, on_date=on_date,
                          close=price, currency=currency, source="tbank"))
    session.flush()
    return instrument


def add_rate(session, currency: str, rate: Decimal, source: str = "cbr") -> FxRate:
    """Курс к рублю на сегодняшнюю московскую дату.

    Именно на сегодняшнюю: оценка спрашивает курсы на `moscow_today()`, и курс
    под фиксированной датой из прошлого она бы нашла, а под датой из будущего —
    уже нет. Привязка к «сегодня» делает тест независимым от дня запуска.
    """
    stored = FxRate(currency=currency, on_date=moscow_today(), rate=rate, source=source)
    session.add(stored)
    session.flush()
    return stored


def test_total_value_uses_last_prices(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.total_value == Decimal("7350.0000")


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


def test_short_position_profit_percent_is_not_inverted(session):
    """У короткой позиции количество отрицательное, значит и себестоимость
    отрицательная. Делить прибыль на неё как есть — получить верную по модулю
    доходность с перевёрнутым знаком: выкупили дешевле, чем продали, это
    заработок, а не убыток."""
    account = seed(session)
    shorted = Instrument(isin="RU000SHORTED", ticker="SHRT", secid="SHRT",
                         kind="share", currency="RUB")
    session.add(shorted)
    session.flush()
    session.add_all([
        Position(account_id=account.id, instrument_id=shorted.id,
                 quantity=Decimal("-10"), average_price=Decimal("200")),
        Price(instrument_id=shorted.id, on_date=date(2026, 3, 12),
              close=Decimal("180"), source="moex"),
    ])
    session.flush()

    row = {r.ticker: r for r in position_rows(session)}["SHRT"]
    assert row.market_value == Decimal("-1800.0000")
    assert row.profit == Decimal("200.0000")
    assert row.profit_percent == Decimal("10.0000")


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
    assert overview.total_value == Decimal("7350.0000")


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


def _seed_foreign(session, account, source="manual"):
    """Позиция, номинированная не в рублях, — на живых данных таких четверть.

    Валюта проставлена и у бумаги, и у её цены: цена в долларах — это ровно то,
    что приходит от брокера, а MOEX за такой бумагой вообще не ходит (см.
    refresh_last_prices). Курс к рублю сознательно не заводится: тесты вокруг
    этого помощника проверяют, как ведёт себя позиция, которую в рубли перевести
    нечем."""
    foreign = Instrument(isin="US0378331005", ticker="AAPL", secid="AAPL",
                         kind="share", currency="USD", issuer="Apple")
    session.add(foreign)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=foreign.id,
                         quantity=Decimal("10"), average_price=Decimal("150")))
    session.add(Price(instrument_id=foreign.id, on_date=date(2026, 3, 12),
                       close=Decimal("200"), currency="USD", source=source))
    session.flush()
    return foreign


def test_position_currency_comes_from_its_price_not_from_the_reference(session):
    """Замещающая облигация: в справочнике брокера она рублёвая, потому что
    расчёты по ней рублёвые, а котируется в юанях. Оценка обязана верить цене —
    взять валюту из справочника значило бы посчитать юани рублями один к
    одному."""
    account = add_account(session)
    add_priced_position(session, account, isin="RU000A1054W1", quantity=Decimal("10"),
                        price=Decimal("969.20"), currency="CNY",
                        reference_currency="RUB", kind="bond")
    add_rate(session, "CNY", Decimal("12.1655"))

    overview = portfolio_overview(session)
    row = position_rows(session)[0]

    assert row.currency == "CNY"
    assert overview.by_currency == {"CNY": Decimal("9692.0000")}
    assert overview.total_value == Decimal("117908.0260")


def test_position_currencies_include_unvalued_positions(session):
    """by_currency отвечает на вопрос «сколько денег в каждой валюте» и
    позицию без котировки не видит вовсе; position_currencies отвечает на
    вопрос «портфель вообще только рублёвый» и обязан её учитывать — валюта у
    неё известна из справочника, даже когда цены нет."""
    account = seed(session)
    add_priced_position(session, account, isin="US0378331005", quantity=Decimal("10"),
                        price=None, currency="USD")

    overview = portfolio_overview(session)

    assert overview.positions_total == 4
    assert overview.valued_positions == 3
    assert "USD" not in overview.by_currency
    assert "USD" in overview.position_currencies


def test_position_without_a_rate_is_kept_out_of_the_ruble_total(session):
    """Цена в долларах есть, курса нет — в рублёвый итог такая позиция войти не
    может: подставить рубль вместо доллара значит занизить её в восемьдесят раз
    и показать это как точную цифру. В своей валюте она при этом видна."""
    account = seed(session)
    _seed_foreign(session, account)

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("7350.0000")
    assert overview.by_currency["RUB"] == Decimal("7350.0000")
    assert overview.by_currency["USD"] == Decimal("2000.0000")


def test_breakdowns_add_up_to_the_ruble_total(session):
    """Разбивки считаются по той же оценённой в рублях части, что и итог, —
    иначе они с ним не сходятся."""
    account = seed(session)
    _seed_foreign(session, account)

    overview = portfolio_overview(session)

    assert sum(overview.by_asset_class.values()) == overview.total_value
    assert sum(overview.by_account.values()) == overview.total_value


def test_breakdowns_add_up_to_the_total_with_cash_too(session):
    """Та же сходимость, но на полном составе капитала: бумаги в двух валютах,
    остатки в двух валютах и второй счёт, у которого из активов только деньги.
    Денежный цикл — самое свежее место обзора, и расхождение разбивок с итогом
    появится в нём первым; на одних бумагах его не увидеть."""
    account = add_account(session)
    add_priced_position(session, account, isin="RU0009029540", quantity=Decimal("10"),
                        price=Decimal("300"), currency="RUB")
    add_priced_position(session, account, isin="HK0000009866", quantity=Decimal("40"),
                        price=Decimal("36.90"), currency="HKD")
    store_cash(session, account, [
        BrokerCash(currency="RUB", amount=Decimal("20782.27"), blocked=Decimal("0")),
        BrokerCash(currency="HKD", amount=Decimal("150"), blocked=Decimal("0")),
    ])
    cash_only = add_account(session, external_id="acc-2")
    store_cash(session, cash_only, [BrokerCash(currency="RUB", amount=Decimal("500"),
                                               blocked=Decimal("0"))])
    add_rate(session, "HKD", Decimal("10.4724"))

    overview = portfolio_overview(session)

    assert overview.securities_value == Decimal("18457.2624")
    assert overview.cash_value == Decimal("22853.1300")
    assert overview.total_value == Decimal("41310.3924")
    assert sum(overview.by_asset_class.values()) == overview.total_value
    assert sum(overview.by_account.values()) == overview.total_value
    # Счёт без единой бумаги обязан быть в разбивке: деньги — тоже капитал.
    assert sorted(overview.by_account) == [account.id, cash_only.id]


def test_foreign_position_with_a_rate_is_counted_as_valued(session):
    """Курс появился — и валютная позиция становится полноценной частью
    капитала, а покрытие оценкой полным. Ровно этого не хватало: раньше такая
    позиция не входила в итог никогда, сколько бы курсов ни было."""
    account = seed(session)
    _seed_foreign(session, account)
    add_rate(session, "USD", Decimal("82.1665"))

    overview = portfolio_overview(session)

    assert overview.positions_total == 4
    assert overview.valued_positions == 4
    assert overview.total_value == Decimal("171683.0000")


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
    assert sum(overview.by_account.values()) == overview.total_value


def test_total_includes_cash(session):
    """Капитал — это бумаги плюс деньги. Раньше денег в системе не было вовсе,
    и главная цифра дашборда была неполна на весь денежный остаток."""
    account = add_account(session)
    add_priced_position(session, account, isin="RU0009029540", quantity=Decimal("10"),
                        price=Decimal("300"), currency="RUB")
    store_cash(session, account, [BrokerCash(currency="RUB", amount=Decimal("20782.27"),
                                             blocked=Decimal("0"))])

    overview = portfolio_overview(session)

    assert overview.securities_value == Decimal("3000.0000")
    assert overview.cash_value == Decimal("20782.2700")
    assert overview.total_value == Decimal("23782.2700")


def test_foreign_position_enters_the_total_by_rate(session):
    """Ровно та поломка, ради которой затевалась фаза: 34 валютные позиции из 59
    не входили в капитал никак."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000009866", quantity=Decimal("40"),
                        price=Decimal("36.90"), currency="HKD")
    add_rate(session, "HKD", Decimal("10.4724"))

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("15457.2624")
    assert overview.by_currency["HKD"] == Decimal("1476.0000")


def test_position_without_rate_is_counted_as_unvalued(session):
    """Цена есть, курса нет — позиция не входит в рублёвый итог и обязана быть
    посчитана как неоценённая, иначе покрытие соврёт «оценены все»."""
    account = add_account(session)
    add_priced_position(session, account, isin="US0000000000", quantity=Decimal("3"),
                        price=Decimal("79.20"), currency="USD")

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("0.0000")
    assert (overview.valued_positions, overview.positions_total) == (0, 1)


def test_cash_lands_in_its_own_asset_class(session):
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="RUB", amount=Decimal("100"),
                                             blocked=Decimal("0"))])

    overview = portfolio_overview(session)

    assert overview.by_asset_class == {"cash": Decimal("100.0000")}


def test_gold_balance_is_valued_as_metal(session):
    """Золото приходит в остатках валютным кодом XAU и граммами; курс к рублю
    берётся с MOEX. В классах активов это металл, а не деньги."""
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="XAU", amount=Decimal("10"),
                                             blocked=Decimal("0"))])
    add_rate(session, "XAU", Decimal("11410"), source="moex")

    overview = portfolio_overview(session)

    assert overview.by_asset_class == {"gold": Decimal("114100.0000")}
    assert overview.total_value == Decimal("114100.0000")


def test_blocked_quantity_counts_as_restricted(session):
    """Заблокированные бумаги никуда не делись и в капитал входят — брокер
    считает их так же. Отдельная цифра нужна, чтобы владелец видел, какой
    частью капитала он не может распоряжаться."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000123577", quantity=Decimal("92"),
                        price=Decimal("100"), currency="RUB")
    store_holdings(session, account, [BrokerPosition(isin="HK0000123577", ticker="x",
                                                     quantity=Decimal("92"),
                                                     blocked=Decimal("92"))])

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("9200.0000")
    assert overview.restricted_value == Decimal("9200.0000")


def test_partially_blocked_position_counts_only_its_blocked_share(session):
    account = add_account(session)
    add_priced_position(session, account, isin="RU0009029540", quantity=Decimal("100"),
                        price=Decimal("300"), currency="RUB")
    store_holdings(session, account, [BrokerPosition(isin="RU0009029540", ticker="SBER",
                                                     quantity=Decimal("100"),
                                                     blocked=Decimal("25"))])

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("30000.0000")
    assert overview.restricted_value == Decimal("7500.0000")


def test_instrument_restricted_in_trading_counts_whole_position(session):
    """Иностранная акция: брокер не даёт ни купить, ни продать. Заблокированного
    количества у неё при этом нет — недоступна вся позиция, а не её часть.
    Таких в портфеле владельца больше двадцати, и именно они составляют
    основную недоступную часть капитала."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000009866", quantity=Decimal("40"),
                        price=Decimal("36.90"), currency="HKD", restricted=True)
    add_rate(session, "HKD", Decimal("10.4724"))

    overview = portfolio_overview(session)

    assert overview.restricted_value == Decimal("15457.2624")


def test_blocked_more_than_the_ledger_knows_does_not_exceed_the_position(session):
    """Заблокированное количество приходит из снимка брокера, количество
    позиции — из журнала операций, и расхождение между ними система не
    предполагает, а специально ищет и хранит (сверка, quantity_mismatch). У
    HK0000123577 брокер показывает balance=0 и blocked=92; если журнал знает
    десять бумаг, доля «92 из 10» дала бы недоступного вдевятеро больше, чем
    стоит вся позиция, — на экране «недоступно 9 200 ₽» при капитале 1 000 ₽."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000123577", quantity=Decimal("10"),
                        price=Decimal("100"), currency="RUB")
    store_holdings(session, account, [BrokerPosition(isin="HK0000123577", ticker="x",
                                                     quantity=Decimal("92"),
                                                     blocked=Decimal("92"))])

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("1000.0000")
    assert overview.restricted_value == Decimal("1000.0000")


def test_blocked_short_position_does_not_flip_the_sign(session):
    """Короткая позиция стоит отрицательных денег, и заблокированная её часть —
    такое же обязательство. Деление на отрицательное количество как есть
    переворачивало знак: недоступное показывалось положительным, будто шорт чем-то
    владеет, и вдобавок не сходилось со знаком капитала."""
    account = add_account(session)
    add_priced_position(session, account, isin="RU0009029540", quantity=Decimal("-10"),
                        price=Decimal("100"), currency="RUB")
    store_holdings(session, account, [BrokerPosition(isin="RU0009029540", ticker="SBER",
                                                     quantity=Decimal("-10"),
                                                     blocked=Decimal("10"))])

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("-1000.0000")
    assert overview.restricted_value == Decimal("-1000.0000")


def test_blocked_cash_counts_as_restricted(session):
    """Заблокированные деньги — самая бесспорная часть ответа на вопрос «чем я
    не могу распорядиться»: на живом счёте валюта бывает зарезервирована
    целиком. В капитал они входят в составе остатка, а не сверх него, поэтому
    cash_value от них не меняется."""
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="RUB", amount=Decimal("20782.27"),
                                             blocked=Decimal("782.27"))])

    overview = portfolio_overview(session)

    assert overview.cash_value == Decimal("20782.2700")
    assert overview.total_value == Decimal("20782.2700")
    assert overview.restricted_value == Decimal("782.2700")


def test_blocked_foreign_cash_is_restricted_by_rate(session):
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="HKD", amount=Decimal("150"),
                                             blocked=Decimal("50"))])
    add_rate(session, "HKD", Decimal("10.4724"))

    overview = portfolio_overview(session)

    assert overview.cash_value == Decimal("1570.8600")
    assert overview.restricted_value == Decimal("523.6200")


def test_blocked_cash_without_a_rate_is_not_counted_as_restricted(session):
    """Курса нет — заблокированный остаток нечем оценить в рублях, и в
    restricted_value он войти не может, ровно как не входит в сам капитал.
    Ноль вместо оценки соврал бы в обе стороны сразу."""
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="USD", amount=Decimal("500"),
                                             blocked=Decimal("500"))])

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("0.0000")
    assert overview.restricted_value == Decimal("0.0000")
    assert overview.by_currency["USD"] == Decimal("500.0000")


def test_restriction_and_blocking_are_not_added_up(session):
    """Бумага ограничена в обороте и вдобавок заблокирована. Недоступна она
    ровно один раз: сложение дало бы больше стоимости самой позиции."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000051877", quantity=Decimal("79"),
                        price=Decimal("100"), currency="RUB", restricted=True)
    store_holdings(session, account, [BrokerPosition(isin="HK0000051877", ticker="y",
                                                     quantity=Decimal("79"),
                                                     blocked=Decimal("79"))])

    overview = portfolio_overview(session)

    assert overview.restricted_value == Decimal("7900.0000")


def test_cash_without_rate_stays_out_of_the_total_but_stays_visible(session):
    """Остаток в валюте, курса к которой нет, в капитал войти не может. Но
    исчезнуть бесследно он тоже не должен: в разбивке по валютам он виден в
    своей валюте, и владелец понимает, что деньги не потерялись."""
    account = add_account(session)
    store_cash(session, account, [BrokerCash(currency="USD", amount=Decimal("500"),
                                             blocked=Decimal("0"))])

    overview = portfolio_overview(session)

    assert overview.total_value == Decimal("0.0000")
    assert overview.cash_value == Decimal("0.0000")
    assert overview.by_currency["USD"] == Decimal("500.0000")
    assert overview.by_asset_class == {}


def test_position_row_carries_both_kinds_of_unavailability(session):
    """Наружу обе причины сводятся в одну сумму, но в строке позиции они
    остаются раздельными: `blocked` — количество на счёте, `restricted` —
    свойство самой бумаги. Иначе происхождение недоступности не увидеть."""
    account = add_account(session)
    add_priced_position(session, account, isin="RU0009029540", quantity=Decimal("100"),
                        price=Decimal("300"), currency="RUB")
    add_priced_position(session, account, isin="HK0000009866", quantity=Decimal("40"),
                        price=Decimal("36.90"), currency="HKD", restricted=True)
    store_holdings(session, account, [BrokerPosition(isin="RU0009029540", ticker="SBER",
                                                     quantity=Decimal("100"),
                                                     blocked=Decimal("25"))])
    add_rate(session, "HKD", Decimal("10.4724"))

    rows = {row.isin: row for row in position_rows(session)}

    sber = rows["RU0009029540"]
    assert (sber.blocked, sber.restricted) == (Decimal("25.00000000"), False)
    assert sber.value_base == Decimal("30000.0000")
    assert sber.price_source == "tbank"

    foreign = rows["HK0000009866"]
    assert (foreign.blocked, foreign.restricted) == (Decimal("0"), True)
    # Стоимость строки — в валюте бумаги, рублёвая оценка идёт рядом отдельно.
    assert foreign.market_value == Decimal("1476.0000")
    assert foreign.value_base == Decimal("15457.2624")


def test_fx_as_of_is_reported_separately_from_price_date(session):
    """Котировки обновляются каждые пятнадцать минут, курсы — раз в сутки.
    Одна дата «данные на» на двоих врала бы про свежесть одного из источников."""
    account = add_account(session)
    add_priced_position(session, account, isin="HK0000009866", quantity=Decimal("40"),
                        price=Decimal("36.90"), currency="HKD", on_date=date(2026, 3, 12))
    add_rate(session, "HKD", Decimal("10.4724"))

    overview = portfolio_overview(session)

    assert overview.as_of == date(2026, 3, 12)
    assert overview.fx_as_of == moscow_today()


def test_fx_as_of_is_none_without_rates(session):
    seed(session)

    assert portfolio_overview(session).fx_as_of is None
