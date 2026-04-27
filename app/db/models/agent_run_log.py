import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin


class AgentRunLog(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_run_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    inputs_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    outputs_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tool_calls: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
