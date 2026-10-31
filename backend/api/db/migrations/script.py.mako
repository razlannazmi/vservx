<%!
    def code(body):
        # Drop the "# ### ... Alembic commands ###" markers autogenerate wraps the body in.
        lines = [line for line in (body or "").splitlines() if not line.lstrip().startswith("# ###")]
        return "\n".join(lines).strip() or "pass"
%>"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${code(upgrades)}


def downgrade() -> None:
    ${code(downgrades)}
