from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Годовая база. Високосные годы отдельно не учитываются: на горизонте шести лет
# разница уходит в четвёртый знак после запятой в процентах, а объяснять
# владельцу две ставки, различающиеся в четвёртом знаке, дороже этой точности.
DAYS_IN_YEAR = Decimal("365")

# Сходимость по невязке приведённой стоимости — копейка. Та же копейка, которой
# меряется признак готовности фазы: ставка, дающая ноль с точностью до копейки,
# проверяема определением, а не доверием к методу.
NPV_TOLERANCE = Decimal("0.01")

# Границы поиска. Нижняя чуть выше −100 %: ровно при −100 % основание (1 + r)
# обращается в ноль и деление на него невозможно. Верхняя — тысяча процентов
# годовых: доходность выше неё у портфеля означает ошибку в данных, а не удачу.
MIN_RATE = Decimal("-0.9999")
MAX_RATE = Decimal("10")

# Шагов бисекции: 200 половинных делений отрезка длиной 11 сужают его далеко за
# пределы значащих разрядов Decimal, то есть цикл всегда упирается в допуск, а
# не в счётчик. Счётчик здесь — предохранитель от бесконечного цикла.
BISECTION_STEPS = 200
NEWTON_STEPS = 50


@dataclass(frozen=True)
class Flow:
    """Денежный поток владельца. Знак — с его точки зрения: вложение
    отрицательно, изъятие положительно. Конечная стоимость портфеля — тоже
    изъятие: это то, что владелец получил бы, продав всё сегодня."""

    on_date: date
    amount: Decimal


def _years(flow: Flow, start: date) -> Decimal:
    return Decimal((flow.on_date - start).days) / DAYS_IN_YEAR


def npv(flows: list[Flow], rate: Decimal) -> Decimal:
    """Приведённая стоимость потоков по ставке. Точка приведения — дата первого
    потока: она сокращается при поиске корня и на ставку не влияет."""
    if not flows:
        return Decimal("0")

    start = min(flow.on_date for flow in flows)
    base = Decimal("1") + rate
    total = Decimal("0")
    for flow in flows:
        total += flow.amount / (base ** _years(flow, start))
    return total


def _derivative(flows: list[Flow], rate: Decimal) -> Decimal:
    start = min(flow.on_date for flow in flows)
    base = Decimal("1") + rate
    total = Decimal("0")
    for flow in flows:
        years = _years(flow, start)
        total -= years * flow.amount / (base ** (years + Decimal("1")))
    return total


def _has_both_signs(flows: list[Flow]) -> bool:
    return any(flow.amount > 0 for flow in flows) and any(flow.amount < 0 for flow in flows)


def _bisect(flows: list[Flow]) -> Decimal | None:
    low, high = MIN_RATE, MAX_RATE
    low_value, high_value = npv(flows, low), npv(flows, high)
    if low_value * high_value > 0:
        # Корня на отрезке нет: доходность вне разумных границ. Молча вернуть
        # край отрезка значило бы выдать границу поиска за результат расчёта.
        return None

    for _ in range(BISECTION_STEPS):
        middle = (low + high) / Decimal("2")
        value = npv(flows, middle)
        if abs(value) < NPV_TOLERANCE:
            return middle
        if value * low_value > 0:
            low, low_value = middle, value
        else:
            high = middle
    # Недостижимо при нынешних BISECTION_STEPS: 200 половинных делений отрезка
    # длиной 11 сужают его далеко за пределы значащих разрядов Decimal, и цикл
    # всегда выходит по допуску. Строка оставлена предохранителем — уменьшат
    # число делений, и функция вернёт середину последнего отрезка, а не None.
    return (low + high) / Decimal("2")


def xirr(flows: list[Flow]) -> Decimal | None:
    """Годовая ставка, при которой приведённая стоимость потоков равна нулю.

    None — законный ответ: у набора потоков одного знака корня не существует, и
    подставлять вместо него ноль или прочерк нельзя. Ноль означал бы «вложения
    ничего не принесли», а на деле неизвестно, принесли ли.
    """
    if len(flows) < 2 or not _has_both_signs(flows):
        return None

    # Все потоки в одну дату: дисконтировать нечего — база степени всегда
    # (1 + rate) ** 0 == 1, ставка на приведённую стоимость не влияет вовсе,
    # и NPV равно нулю (или не равно, если сумма не нулевая) при ЛЮБОЙ ставке.
    # Задача вырождена, а не решена: подходящая ставка либо любая, либо не
    # существует — и то и другое законно только как None.
    if min(flow.on_date for flow in flows) == max(flow.on_date for flow in flows):
        return None

    rate = Decimal("0.1")
    for _ in range(NEWTON_STEPS):
        value = npv(flows, rate)
        if abs(value) < NPV_TOLERANCE:
            return rate
        slope = _derivative(flows, rate)
        if slope == 0:
            break
        step = value / slope
        rate = rate - step
        if rate <= MIN_RATE or rate >= MAX_RATE:
            # Ньютон вылетел за область определения — дальше только бисекция.
            break

    # Ньютон не сошёлся: у знакопеременных потоков поверхность бывает пологой, и
    # шаг уводит за корень. Бисекция медленнее, но сходится всегда, когда корень
    # на отрезке есть.
    return _bisect(flows)
