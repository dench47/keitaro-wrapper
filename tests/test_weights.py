"""Тесты пересчёта весов: правила из видео заказчика."""

from app.weights import recalc_weights


class FakeOffer:
    def __init__(self, oid, share=0, state="active", pinned=False, pinned_share=0):
        self.kt_offer_id = oid
        self.share = share
        self.state = state
        self.pinned = pinned
        self.pinned_share = pinned_share

    def weights(self, offers):
        return {o.kt_offer_id: o.share for o in offers}


def test_two_active_split_evenly():
    offers = [FakeOffer(1, 100), FakeOffer(2, 0)]
    recalc_weights(offers)
    assert offers[0].share == 50 and offers[1].share == 50


def test_three_active_sum_to_100():
    offers = [FakeOffer(1, 50), FakeOffer(2, 50), FakeOffer(3, 0)]
    recalc_weights(offers)
    assert sum(o.share for o in offers) == 100
    assert sorted(o.share for o in offers) == [33, 33, 34]


def test_removed_gets_zero():
    offers = [FakeOffer(1, 33), FakeOffer(2, 33), FakeOffer(3, 34, state="removed")]
    recalc_weights(offers)
    assert offers[2].share == 0
    assert offers[0].share == 50 and offers[1].share == 50


def test_pinned_stays_frozen():
    offers = [
        FakeOffer(1, 25, pinned=True, pinned_share=25),
        FakeOffer(2, 25),
        FakeOffer(3, 25),
        FakeOffer(4, 25),
    ]
    recalc_weights(offers)
    assert offers[0].share == 25  # запиненный не тронут
    assert sum(o.share for o in offers) == 100
    assert all(o.share == 25 for o in offers[1:])


def test_pinned_survives_add_and_remove():
    # пин 50%, двое других; одного удаляем — оставшийся свободный забирает 50
    offers = [
        FakeOffer(1, 50, pinned=True, pinned_share=50),
        FakeOffer(2, 25),
        FakeOffer(3, 25),
    ]
    offers[2].state = "removed"
    recalc_weights(offers)
    assert offers[0].share == 50
    assert offers[1].share == 50
    assert offers[2].share == 0


def test_fetch_keeps_weights_of_survivors():
    # FETCH — зеркало Keitaro (видео заказчика 4:29): после удаления двух
    # офферов из четырёх по 25% выжившие остаются по 25%, пересчёта нет.
    # Пересчёт запускают только локальные операции (ADD/REMOVE/BRING BACK/PIN).
    offers = [
        FakeOffer(1, 25),
        FakeOffer(2, 25),
        FakeOffer(3, 25),
        FakeOffer(4, 25),
    ]
    offers[0].state = "removed"
    offers[0].share = 0
    offers[1].state = "removed"
    offers[1].share = 0
    assert offers[2].share == 25 and offers[3].share == 25


def test_pin_alone_does_not_recalc():
    # видео заказчика: после FETCH осталось 25+25 (зеркало KT), пин одного
    # не пересчитывает веса — пересчёт случится только на следующей операции
    offers = [FakeOffer(1, 25), FakeOffer(2, 25)]
    offers[0].pinned = True   # пин фиксирует вес, recalc_weights НЕ вызывается
    offers[0].pinned_share = offers[0].share
    assert offers[0].share == 25 and offers[1].share == 25  # всё как было
    # а вот брингбэк (возврат третьего) пересчитает: пин 25, двое делят 75
    offers.append(FakeOffer(3, 0))
    recalc_weights(offers)
    assert offers[0].share == 25
    assert offers[1].share + offers[2].share == 75
    assert sum(o.share for o in offers) == 100
