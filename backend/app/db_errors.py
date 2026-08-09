from sqlalchemy.exc import IntegrityError


def is_unique_violation(exc: IntegrityError, constraint_name: str) -> bool:
    """True, если `exc` вызван нарушением именно уникального ограничения/индекса
    `constraint_name` (сверка по `exc.orig.diag.constraint_name`, специфичному для
    psycopg). Используется, чтобы отличить штатный конфликт дедупликации (по
    `dedup_key` или `isin`) от других нарушений целостности (внешний ключ, NOT NULL) —
    те обязаны всплывать наружу как ошибка вызывающего кода, а не трактоваться как
    дубль."""
    diag = getattr(exc.orig, "diag", None)
    return diag is not None and diag.constraint_name == constraint_name
