from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import SyncRunOut
from app.config import get_settings
from app.connectors.base import BrokerConnector
from app.connectors.tbank.connector import TBankConnector
from app.db import get_session
from app.models import Account, SyncRun
from app.sync.service import sync_broker

router = APIRouter(prefix="/api/sync", tags=["sync"])

# Подпись счёта, когда в записи прогона нет ссылки на него: SAVEPOINT
# откатывает и сам счёт, если сбой случился ещё на его заведении, так что
# восстановить, о каком именно счёте шла речь, уже нечем — текст ошибки
# прогона (run.error) остаётся единственным источником подробностей.
UNKNOWN_ACCOUNT_LABEL = "счёт не определён"


def get_tbank_connector() -> BrokerConnector:
    """Зависимость FastAPI, а не создание коннектора прямо в обработчике —
    так тесты подменяют её двойником через app.dependency_overrides, не
    затрагивая ни сеть, ни настоящий токен."""
    token = get_settings().tbank_token
    if not token:
        raise HTTPException(status_code=400, detail="Не задан TBANK_TOKEN в .env")
    return TBankConnector(token)


def _account_label(session: Session, run: SyncRun) -> str:
    """Читаемая и однозначно различимая подпись счёта для ответа синхронизации.

    Одного имени недостаточно: коннектор Т-Банка подставляет одинаковую
    заглушку «Счёт», если брокер имени не дал, поэтому в подпись всегда
    входит и внешний идентификатор, а не только имя."""
    if run.account_id is None:
        return UNKNOWN_ACCOUNT_LABEL
    account = session.get(Account, run.account_id)
    if account is None:
        return UNKNOWN_ACCOUNT_LABEL
    return f"{account.name} ({account.external_id})"


@router.post("/tbank", response_model=list[SyncRunOut])
def sync_tbank(
    session: Session = Depends(get_session),
    connector: BrokerConnector = Depends(get_tbank_connector),
) -> list[SyncRunOut]:
    runs = sync_broker(session, connector)
    return [
        SyncRunOut(
            account=_account_label(session, run), broker=run.broker, status=run.status,
            inserted=run.inserted, skipped=run.skipped, mismatches=run.mismatches, error=run.error,
        )
        for run in runs
    ]
