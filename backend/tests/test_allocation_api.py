from decimal import Decimal

from tests.test_analytics import add_account, add_priced_position


def test_put_then_get_targets(client, session):
    account = add_account(session)
    add_priced_position(session, account, "RU0009029540", Decimal("10"), Decimal("100"))
    session.commit()

    response = client.put("/api/allocation/targets", json=[
        {"asset_class": "bonds", "share": "0.4"},
        {"isin": "RU0009029540", "share": "0.1"},
    ])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body[0]["asset_class"] == "bonds"
    assert body[0]["isin"] is None
    # Доля — строкой и дробью, как все ставки проекта.
    assert body[0]["share"] == "0.4000"
    assert body[1]["isin"] == "RU0009029540"
    assert body[1]["name"] == "RU0009029540"
    assert client.get("/api/allocation/targets").json() == body


def test_contradictory_targets_are_refused_with_a_reason(client):
    response = client.put("/api/allocation/targets", json=[
        {"asset_class": "equity", "share": "0.7"},
        {"asset_class": "bonds", "share": "0.4"},
    ])
    assert response.status_code == 400
    assert "превышает 100" in response.json()["detail"]


def test_refused_set_leaves_previous_targets_intact(client):
    first = client.put("/api/allocation/targets", json=[{"asset_class": "equity", "share": "0.5"}])
    assert first.status_code == 200
    client.put("/api/allocation/targets", json=[{"asset_class": "equities", "share": "0.5"}])
    assert [row["asset_class"] for row in client.get("/api/allocation/targets").json()] == ["equity"]
