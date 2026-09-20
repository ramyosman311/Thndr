import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import CreatedAtMixin


class User(CreatedAtMixin, Base):
    """A local shadow record of a Supabase Auth user (P0-3A).

    `id` is deliberately NOT auto-generated (no `UUIDPrimaryKeyMixin`,
    which defaults via `uuid.uuid4`) -- it must always equal the exact
    `auth.users.id` value from the verified Supabase JWT's `sub` claim
    (see app/core/auth.py, `require_supabase_user`). This table is the
    only place this project's own schema represents "who a request is
    from"; everything else (portfolio ownership, etc.) hangs off this
    row's `id`, never off the JWT directly.

    Deliberately minimal: no email, no profile fields. Nothing in this
    phase reads or displays user profile data, and Supabase's own
    auth.users table already owns that information -- duplicating it
    here without a reader would be exactly the kind of speculative
    field FINANCIAL_RULES.md and this project's own conventions
    consistently avoid elsewhere (see e.g. Notification's read_at
    instead of a redundant boolean).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
