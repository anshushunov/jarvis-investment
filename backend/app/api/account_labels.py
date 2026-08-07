from sqlalchemy.orm import Session

from app.models import Account

# Подпись счёта, когда узнать её не из чего (например, у прогона синхронизации
# нет ссылки на счёт — см. account_label ниже).
UNKNOWN_ACCOUNT_LABEL = "счёт не определён"


def account_label(session: Session, account_id: int | None) -> str:
    """Читаемая и однозначно различимая подпись счёта для ответов API.

    Одного имени недостаточно: коннектор Т-Банка подставляет одинаковую
    заглушку «Счёт», если брокер имени не дал, поэтому в подпись всегда
    входит и внешний идентификатор, а не только имя. Используется и в ответе
    синхронизации (`routes_sync`), и в ответе сверки (`routes_portfolio`) —
    один и тот же формат, чтобы подпись одного и того же счёта выглядела
    одинаково на обоих экранах."""
    if account_id is None:
        return UNKNOWN_ACCOUNT_LABEL
    account = session.get(Account, account_id)
    if account is None:
        return UNKNOWN_ACCOUNT_LABEL
    return f"{account.name} ({account.external_id})"
