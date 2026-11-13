"""Модели локальной базы обёртки.

Обёртка хранит собственное зеркало кампаний/потоков/офферов, чтобы уметь:
- показывать офферы, удалённые в Keitaro (статус removed + Bring Back),
- держать локальные несохранённые изменения (dirty-статус потока),
- пинить веса офферов при пересчёте.
"""

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kt_campaign_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    geo: Mapped[str] = mapped_column(String(255), default="")  # "AU,MX,RO"
    group_name: Mapped[str] = mapped_column(String(255), default="")
    source_name: Mapped[str] = mapped_column(String(255), default="")
    domain_name: Mapped[str] = mapped_column(String(255), default="")

    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="Stream.position"
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    kt_stream_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    schema: Mapped[str] = mapped_column(String(50), default="landings")  # landings | redirect
    # Есть ли несохранённые изменения (жёлтый поток в их интерфейсе)
    dirty: Mapped[bool] = mapped_column(Boolean, default=False)

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", order_by="StreamOffer.id"
    )


class StreamOffer(Base):
    __tablename__ = "stream_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id"), index=True)
    kt_offer_id: Mapped[int] = mapped_column(Integer)
    offer_name: Mapped[str] = mapped_column(String(512), default="")
    share: Mapped[float] = mapped_column(Float, default=0.0)
    # Закреплённый вес: не пересчитывается при добавлении/удалении других офферов
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned_share: Mapped[float] = mapped_column(Float, default=0.0)
    # active | removed (серый оффер с кнопкой Bring Back)
    state: Mapped[str] = mapped_column(String(20), default="active")

    stream: Mapped[Stream] = relationship(back_populates="offers")
