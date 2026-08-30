"""Revision inicial: processing_runs (metadados operacionais apenas)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_processing_runs"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE run_status AS ENUM ('accepted', 'completed', 'failed', 'discarded');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.create_table(
        "processing_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "accepted",
                "completed",
                "failed",
                "discarded",
                name="run_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("pdf_page_count", sa.Integer(), nullable=True),
        sa.Column("candidate_page_count", sa.Integer(), nullable=True),
        sa.Column("gemini_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("processing_runs")
    op.execute("DROP TYPE IF EXISTS run_status")
