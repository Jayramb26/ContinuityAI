from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    documents = relationship("SourceDocument", back_populates="project", cascade="all, delete-orphan")
    items = relationship("KnowledgeItem", back_populates="project", cascade="all, delete-orphan")

class SourceDocument(Base):
    __tablename__ = "source_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    project = relationship("Project", back_populates="documents")

class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"), nullable=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="needs_review")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    project = relationship("Project", back_populates="items")
