from datetime import date

from app.models import OperationType
from tests.test_api import client
from tests.test_returns_flows import add_tx
from tests.test_returns_service import add_snapshot


def test_returns_endpoint_answers(client, session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 8, 13), amount="100000")
    add_snapshot(session, date(2024, 8, 13), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")
    session.commit()

    response = client.get("/api/analytics/returns?period=all")
    assert response.status_code == 200
    body = response.json()
    assert body["period"]["from"] == "2024-08-13"
    # Деньги — строки, как везде: точность Decimal через float не проходит.
    assert isinstance(body["portfolio"]["profit"], str)
    assert body["unattributed"]["profit"] == "0.0000"


def test_unknown_period_is_rejected(client):
    response = client.get("/api/analytics/returns?period=forever")
    assert response.status_code == 422


def test_accounts_are_labelled_not_numbered(client, session, account):
    add_snapshot(session, date(2026, 8, 13), "100000")
    session.commit()

    body = client.get("/api/analytics/returns?period=all").json()
    # account_label() — единственная на проект функция подписи счёта, и её
    # формат «Имя (external_id)» (app/accounts/labels.py), а не голое имя:
    # уникальна только пара (broker, external_id), см. docstring функции и
    # четыре соседних обработчика в routes_portfolio.py.
    assert body["by_account"][0]["title"] == "Инвестиционный (acc-1)"
