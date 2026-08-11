from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.accounts.labels import account_label_by_id
from app.api.schemas import SyncRunOut
from app.config import get_settings
from app.connectors.base import BrokerConnector
from app.connectors.tbank.connector import TBankConnector
from app.db import get_session
from app.sync.service import sync_broker

router = APIRouter(prefix="/api/sync", tags=["sync"])


def get_tbank_connector() -> BrokerConnector:
    """Зависимость FastAPI, а не создание коннектора прямо в обработчике —
    так тесты подменяют её двойником через app.dependency_overrides, не
    затрагивая ни сеть, ни настоящий токен."""
    token = get_settings().tbank_token
    if not token:
        raise HTTPException(status_code=400, detail="Не задан TBANK_TOKEN в .env")
    return TBankConnector(token)


@router.post("/tbank", response_model=list[SyncRunOut])
def sync_tbank(
    session: Session = Depends(get_session),
    connector: BrokerConnector = Depends(get_tbank_connector),
) -> list[SyncRunOut]:
    runs = sync_broker(session, connector)
    return [
        SyncRunOut(
            # SAVEPOINT откатывает и сам счёт, если сбой случился ещё на его
            # заведении, так что восстановить, о каком именно счёте шла речь,
            # уже нечем (account_label_by_id вернёт UNKNOWN_ACCOUNT_LABEL) —
            # текст ошибки прогона (run.error) остаётся единственным источником
            # подробностей в этом случае.
            account=account_label_by_id(session, run.account_id), broker=run.broker, status=run.status,
            inserted=run.inserted, skipped=run.skipped, mismatches=run.mismatches,
            corrected=run.corrected, error=run.error,
        )
        for run in runs
    ]
