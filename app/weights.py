"""Пересчёт весов офферов потока.

Правила из видео заказчика:
- активные офферы делят 100% между собой;
- запиненный вес заморожен: пересчёт затрагивает только остальных;
- сумма активных всегда 100%, последний получает остаток от округления.
"""


def recalc_weights(offers: list) -> None:
    """offers — объекты StreamOffer (SQLAlchemy). Меняет share по месту."""
    active = [o for o in offers if o.state == "active"]
    pinned_total = sum(o.pinned_share for o in active if o.pinned)
    free = [o for o in active if not o.pinned]

    if pinned_total > 100:
        pinned_total = 100
    if not free:
        # всё запинено: сумма как есть (редкий случай, доверяем пинам)
        return

    remaining = 100 - pinned_total
    base = int(remaining // len(free))
    rest = int(remaining - base * len(free))

    for i, o in enumerate(free):
        o.share = base + (1 if i < rest else 0)

    # запиненным возвращаем их зафиксированное значение
    for o in active:
        if o.pinned:
            o.share = o.pinned_share

    # удалённые всегда с нулевой долей
    for o in offers:
        if o.state == "removed":
            o.share = 0


def effective_share(o) -> float:
    """Что показывать в интерфейсе: у удалённого 0, у остальных расчётный вес."""
    return 0 if o.state == "removed" else o.share
