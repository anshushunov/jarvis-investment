from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.service import portfolio_overview
from app.models import DailySnapshot


def take_snapshot(session: Session, on_date: date) -> DailySnapshot:
    overview = portfolio_overview(session)

    values = {
        "on_date": on_date,
        "total_value": overview.total_value,
        "by_asset_class": {k: str(v) for k, v in overview.by_asset_class.items()},
        "by_account": {k: str(v) for k, v in overview.by_account.items()},
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
