"""Обёртка над Keitaro: FastAPI-приложение.

Часть 1 (создание кампании) и часть 2 (редактор офферов) живут здесь.
Фронт — static/index.html, общается с /api/*.
"""

import re
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from . import models  # noqa: F401 — регистрация моделей в Base
from .keitaro_api import KeitaroClient, KeitaroError
from .settings import settings
from .weights import recalc_weights

app = FastAPI(title="Keitaro wrapper")


def make_alias(name: str) -> str:
    """Keitaro требует alias: слаг имени + короткий уникальный хвост."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "campaign"
    return f"{slug}-{uuid.uuid4().hex[:6]}"


# --- утилиты ---

def clean_geo(raw: str) -> list[str]:
    """'au, mx' -> ['AU', 'MX']: верхний регистр, обрезка пробелов, без пустых."""
    return [p.strip().upper() for p in re.split("[,;\\s]+", raw) if p.strip()]


def kt_payload_for_stream(stream: models.Stream) -> dict:
    """Собрать тело PUT /streams/{id} из локального состояния потока.

    Формат выверен по живым потокам трекера: URL у redirect-потока лежит
    в action_payload строкой, action_type у обоих схем http.
    """
    active = [o for o in stream.offers if o.state == "active"]
    if stream.schema == "redirect":
        return {
            "schema": "redirect",
            "action_type": "http",
            "action_payload": "https://google.com",
        }
    return {
        "schema": "landings",
        "action_type": "http",
        "offers": [
            {"offer_id": o.kt_offer_id, "share": int(o.share), "state": "active"}
            for o in active
        ],
    }


def serialize_offer(o: models.StreamOffer) -> dict:
    return {
        "id": o.id,
        "kt_offer_id": o.kt_offer_id,
        "name": o.offer_name,
        "share": int(o.share) if o.state == "active" else 0,
        "pinned": o.pinned,
        "state": o.state,
    }


def serialize_stream(s: models.Stream) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "kt_stream_id": s.kt_stream_id,
        "schema": s.schema,
        "dirty": s.dirty,
        "offers": [serialize_offer(o) for o in s.offers],
    }


def serialize_campaign(c: models.Campaign) -> dict:
    return {
        "id": c.id,
        "kt_campaign_id": c.kt_campaign_id,
        "name": c.name,
        "geo": c.geo,
        "group": c.group_name,
        "source": c.source_name,
        "domain": c.domain_name,
        "streams": [serialize_stream(s) for s in c.streams],
    }


# --- Часть 1: создание кампании ---

class CreateCampaignIn(BaseModel):
    name: str
    geo: str
    offer_id: int


def _ensure_group(kt: KeitaroClient, name: str) -> int:
    for g in kt.groups():
        if g.get("name") == name:
            return g["id"]
    return kt.create_group(name)["id"]


def _ensure_source(kt: KeitaroClient, name: str) -> int:
    for s in kt.traffic_sources():
        if s.get("name") == name:
            return s["id"]
    return kt.create_traffic_source(name)["id"]


def _ensure_domain(kt: KeitaroClient, name: str) -> int | None:
    for d in kt.domains():
        if d.get("name") == name:
            return d["id"]
    created = kt.create_domain(name)
    return created.get("id")


@app.post("/api/campaigns")
def create_campaign(body: CreateCampaignIn, db: Session = Depends(get_db)):
    """Создать кампанию в Keitaro: домен, группа, источник, два потока."""
    kt = KeitaroClient()
    geo = clean_geo(body.geo)
    if not geo:
        raise HTTPException(400, "geo пустой: укажи хотя бы один код страны")
    if not body.name.startswith(settings.campaign_name_prefix):
        name = settings.campaign_name_prefix + body.name
    else:
        name = body.name

    try:
        group_id = _ensure_group(kt, settings.keitaro_group_name)

        # Домен и источник: тестовый API-ключ не имеет прав на их создание
        # (403 Domains / TrafficSources, как и у кампаний других кандидатов:
        # traffic_source_id=0, domain=null). Пробуем настроить, при запрете
        # кампания остаётся на домене трекера по умолчанию.
        try:
            source_id = _ensure_source(kt, settings.keitaro_source_name)
        except KeitaroError:
            source_id = 0
        try:
            domain_id = _ensure_domain(kt, settings.keitaro_domain_name)
        except KeitaroError:
            domain_id = None

        campaign = kt.create_campaign({
            "name": name,
            "alias": make_alias(name),
            "type": "position",
            "state": "active",
            "cost_type": "CPC",
            "cost_currency": "USD",
            "cost_auto": True,
            "group_id": group_id,
            "traffic_source_id": source_id,
            "domain_id": domain_id,
        })
        kt_campaign_id = campaign["id"]

        # Поток 1: все из geo -> google
        stream1 = kt.create_stream({
            "campaign_id": kt_campaign_id,
            "name": f"{','.join(geo)} -> Google",
            "schema": "redirect",
            "action_type": "http",
            "action_payload": "https://google.com",
            "state": "active",
            "position": 1,
            "filter_or": False,
            "filters": [{"name": "country", "mode": "accept", "payload": geo}],
        })
        # Поток 2: остальные -> выбранный оффер
        stream2 = kt.create_stream({
            "campaign_id": kt_campaign_id,
            "name": "Offers",
            "schema": "landings",
            "action_type": "http",
            "state": "active",
            "position": 2,
            "offers": [{"offer_id": body.offer_id, "share": 100, "state": "active"}],
        })

        offer_meta = next((o for o in kt.offers(limit=1000) if o["id"] == body.offer_id), None)
        offer_name = offer_meta["name"] if offer_meta else str(body.offer_id)
    except KeitaroError as e:
        raise HTTPException(502, str(e))

    local = models.Campaign(
        kt_campaign_id=kt_campaign_id,
        name=name,
        geo=",".join(geo),
        group_name=settings.keitaro_group_name,
        source_name=settings.keitaro_source_name,
        domain_name=settings.keitaro_domain_name,
    )
    s1 = models.Stream(name=f"{','.join(geo)} -> Google", position=1, schema="redirect", kt_stream_id=stream1["id"])
    s2 = models.Stream(name="Offers", position=2, schema="landings", kt_stream_id=stream2["id"])
    s2.offers.append(models.StreamOffer(
        kt_offer_id=body.offer_id, offer_name=offer_name, share=100, state="active",
    ))
    local.streams.extend([s1, s2])
    db.add(local)
    db.commit()
    return serialize_campaign(local)


@app.get("/api/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    return [serialize_campaign(c) for c in db.query(models.Campaign).all()]


class ImportIn(BaseModel):
    kt_campaign_id: int


@app.post("/api/campaigns/import")
def import_campaign(body: ImportIn, db: Session = Depends(get_db)):
    """Открыть в редакторе существующую кампанию Keitaro (задание 2).

    Тянем кампанию и её потоки из трекера: потоки без офферов остаются
    строкой-заголовком (как в видео заказчика 1:04: не пытаться показать
    про них ничего), потоки с офферами становятся редактируемыми.
    """
    exists = db.query(models.Campaign).filter_by(kt_campaign_id=body.kt_campaign_id).first()
    if exists:
        return serialize_campaign(exists)

    kt = KeitaroClient()
    try:
        remote_campaign = kt.campaign(body.kt_campaign_id)
        remote_streams = kt.campaign_streams(body.kt_campaign_id)
    except KeitaroError as e:
        raise HTTPException(502, str(e))

    local = models.Campaign(
        kt_campaign_id=remote_campaign["id"],
        name=remote_campaign.get("name", str(body.kt_campaign_id)),
        geo="",  # гео известно только потоку-фильтру, у кампании его нет
        group_name=remote_campaign.get("group") or "",
        source_name="",
        domain_name=remote_campaign.get("domain") or "",
    )
    for i, st in enumerate(remote_streams, start=1):
        kt_offers = st.get("offers") or []
        local_stream = models.Stream(
            name=st.get("name") or f"Flow {i}",
            position=st.get("position") or i,
            schema=st.get("schema") or ("landings" if kt_offers else "redirect"),
            kt_stream_id=st.get("id"),
        )
        for o in kt_offers:
            local_stream.offers.append(models.StreamOffer(
                kt_offer_id=o["offer_id"], offer_name=str(o["offer_id"]),
                share=o.get("share", 0), state="active",
            ))
        local.streams.append(local_stream)
    db.add(local)
    db.commit()
    return serialize_campaign(local)


@app.get("/api/kt/campaigns")
def kt_campaigns():
    """Все кампании трекера — для выбора существующей в редактор."""
    try:
        return [{"id": c["id"], "name": c.get("name", ""), "state": c.get("state", "")}
                for c in KeitaroClient().campaigns()]
    except KeitaroError as e:
        raise HTTPException(502, str(e))


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Campaign, campaign_id)
    if not c:
        raise HTTPException(404, "campaign not found")
    return serialize_campaign(c)


# --- Часть 2: редактор потоков ---

class OfferIn(BaseModel):
    offer_id: int


class PinIn(BaseModel):
    pinned: bool


def _get_stream(db: Session, stream_id: int) -> models.Stream:
    s = db.get(models.Stream, stream_id)
    if not s:
        raise HTTPException(404, "stream not found")
    return s


@app.get("/api/streams/{stream_id}")
def get_stream(stream_id: int, db: Session = Depends(get_db)):
    return serialize_stream(_get_stream(db, stream_id))


@app.post("/api/streams/{stream_id}/fetch")
def fetch_stream(stream_id: int, db: Session = Depends(get_db), drop_missing: bool = False):
    """Синхронизация потока из Keitaro.

    Офферы, которых в Keitaro больше нет, уходят в removed (Bring Back).
    drop_missing=True (используется отменой) — удаляет их из базы совсем:
    так ведёт себя CANCEL в интерфейсе заказчика: неподтверждённые
    привязки стираются, поток возвращается к опубликованному состоянию.
    """
    s = _get_stream(db, stream_id)
    if not s.kt_stream_id:
        raise HTTPException(400, "у потока нет kt_stream_id (redirect-поток не синхронизируется)")
    kt = KeitaroClient()
    try:
        remote = kt.stream(s.kt_stream_id)
    except KeitaroError as e:
        raise HTTPException(502, str(e))

    remote_offers = {o["offer_id"]: o for o in remote.get("offers", [])}
    for o in list(s.offers):
        if o.kt_offer_id not in remote_offers:
            if drop_missing:
                s.offers.remove(o)
                db.delete(o)
            else:
                o.state = "removed"
                o.share = 0
        else:
            r = remote_offers[o.kt_offer_id]
            o.state = "active"
            o.offer_name = o.offer_name or str(o.kt_offer_id)
            if not o.pinned:
                o.share = r.get("share", o.share)
    # новых с ремоута добавляем, если их нет
    existing = {o.kt_offer_id for o in s.offers}
    for oid, r in remote_offers.items():
        if oid not in existing:
            s.offers.append(models.StreamOffer(
                kt_offer_id=oid, offer_name=str(oid), share=r.get("share", 0), state="active",
            ))
    # FETCH — зеркало Keitaro: веса выживших не пересчитываем.
    # Если там после удаления осталось 25+25, показываем 25+25 (как в видео
    # заказчика, 4:29); пересчёт — только результат локальных операций
    # ADD/REMOVE/BRING BACK/PIN, которые публикуются через PUSH.
    s.dirty = False
    db.commit()
    return serialize_stream(s)


@app.post("/api/streams/{stream_id}/offers")
def add_offer(stream_id: int, body: OfferIn, db: Session = Depends(get_db)):
    """Добавить оффер локально: пересчёт весов, поток становится грязным."""
    s = _get_stream(db, stream_id)
    if any(o.kt_offer_id == body.offer_id for o in s.offers):
        raise HTTPException(400, "оффер уже в потоке")
    kt = KeitaroClient()
    offer_name = str(body.offer_id)
    try:
        meta = next((o for o in kt.offers(limit=1000) if o["id"] == body.offer_id), None)
        if meta:
            offer_name = meta["name"]
    except KeitaroError:
        pass
    s.offers.append(models.StreamOffer(kt_offer_id=body.offer_id, offer_name=offer_name, share=0, state="active"))
    recalc_weights(s.offers)
    s.dirty = True
    db.commit()
    return serialize_stream(s)


@app.delete("/api/streams/{stream_id}/offers/{offer_row_id}")
def remove_offer(stream_id: int, offer_row_id: int, db: Session = Depends(get_db)):
    s = _get_stream(db, stream_id)
    o = next((o for o in s.offers if o.id == offer_row_id), None)
    if not o:
        raise HTTPException(404, "offer not found")
    o.state = "removed"
    o.share = 0
    recalc_weights(s.offers)
    s.dirty = True
    db.commit()
    return serialize_stream(s)


@app.post("/api/streams/{stream_id}/offers/{offer_row_id}/restore")
def restore_offer(stream_id: int, offer_row_id: int, db: Session = Depends(get_db)):
    """Bring Back: вернуть удалённый оффер в поток."""
    s = _get_stream(db, stream_id)
    o = next((o for o in s.offers if o.id == offer_row_id), None)
    if not o:
        raise HTTPException(404, "offer not found")
    o.state = "active"
    recalc_weights(s.offers)
    s.dirty = True
    db.commit()
    return serialize_stream(s)


@app.post("/api/streams/{stream_id}/offers/{offer_row_id}/pin")
def pin_offer(stream_id: int, offer_row_id: int, body: PinIn, db: Session = Depends(get_db)):
    """Закрепить/открепить вес оффера.

    Пин только замораживает текущий вес и не пересчитывает остальные:
    пересчёт запускают последующие операции ADD/REMOVE/BRING BACK
    (как в видео заказчика: после пина 25% пересчёт случился лишь на брингбэке).
    """
    s = _get_stream(db, stream_id)
    o = next((o for o in s.offers if o.id == offer_row_id), None)
    if not o:
        raise HTTPException(404, "offer not found")
    o.pinned = body.pinned
    if body.pinned:
        o.pinned_share = o.share
    s.dirty = True
    db.commit()
    return serialize_stream(s)


@app.post("/api/streams/{stream_id}/push")
def push_stream(stream_id: int, db: Session = Depends(get_db)):
    """Опубликовать изменения в Keitaro: пересобрать поток с активными офферами."""
    s = _get_stream(db, stream_id)
    if not s.kt_stream_id:
        raise HTTPException(400, "у потока нет kt_stream_id")
    kt = KeitaroClient()
    payload = kt_payload_for_stream(s)
    try:
        kt.update_stream(s.kt_stream_id, payload)
    except KeitaroError as e:
        raise HTTPException(502, str(e))
    s.dirty = False
    db.commit()
    return serialize_stream(s)


@app.post("/api/streams/{stream_id}/cancel")
def cancel_stream(stream_id: int, db: Session = Depends(get_db)):
    """Отменить несохранённые изменения: вернуть поток к состоянию в Keitaro.

    Добавленные до публикации офферы удаляются из базы полностью,
    пины и удаления откатываются — как CANCEL в интерфейсе заказчика.
    """
    s = _get_stream(db, stream_id)
    if not s.kt_stream_id:
        raise HTTPException(400, "у потока нет kt_stream_id")
    for o in s.offers:
        o.pinned = False
        if o.state == "removed":
            o.state = "active"
    db.commit()
    return fetch_stream(stream_id, db, drop_missing=True)


# --- автокомплит офферов ---

_offer_cache: list | None = None


@app.get("/api/offers/search")
def offers_search(q: str = "", limit: int = 15):
    """Поиск офферов по подстроке в id или имени, для автокомплита."""
    global _offer_cache
    kt = KeitaroClient()
    if _offer_cache is None:
        try:
            _offer_cache = kt.all_offers()
        except KeitaroError as e:
            raise HTTPException(502, str(e))
    needle = q.strip().lower()
    result = []
    for o in _offer_cache:
        hay = f"{o['id']} {o.get('name', '')}".lower()
        if not needle or needle in hay:
            result.append({"id": o["id"], "name": o.get("name", "")[:120]})
        if len(result) >= limit:
            break
    return result


# --- фронт ---

@app.get("/api/config")
def config():
    return {
        "kt_ui_base": settings.keitaro_base_url + "/admin",
        "campaign_name_prefix": settings.campaign_name_prefix,
    }


@app.get("/")
def index():
    return FileResponse("static/index.html", media_type="text/html")


@app.get("/create.html")
def create_page():
    return FileResponse("static/create.html", media_type="text/html")


app.mount("/static", StaticFiles(directory="static"), name="static")
