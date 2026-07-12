"""Wave 1 control plane: workflow payload codec seam.

System invariant this exists to satisfy (PLAN.md): "Workflow inputs contain
IDs and versions only. Goals, vault text, credentials, and founder documents
do not enter Temporal history" and "Any unavoidable sensitive Temporal
payload uses an encrypted payload codec."

This module only builds the seam -- PassthroughPayloadCodec is a no-op, NOT
encryption. Real encryption is future work (Wave 4, when Temporal actually
executes production side effects) -- do not treat this as done.

Subclasses temporalio.converter.PayloadCodec when the temporalio SDK is
installed (real Temporal client/worker wiring uses that ABC directly). Falls
back to a local Protocol with the identical async encode/decode shape when
temporalio isn't installed, so this module stays importable in environments
that haven't installed the SDK yet -- like this one.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

try:
    from temporalio.api.common.v1 import Payload
    from temporalio.converter import PayloadCodec as _BaseCodec
    _HAS_TEMPORALIO = True
except ImportError:
    _HAS_TEMPORALIO = False
    if TYPE_CHECKING:
        from temporalio.api.common.v1 import Payload  # type: ignore[no-redef]

    class _BaseCodec:  # type: ignore[no-redef]
        """Stand-in with the same async encode/decode shape as
        temporalio.converter.PayloadCodec, used only when temporalio isn't
        installed. Real code should never hit this branch in production."""

        async def encode(self, payloads: Sequence["Payload"]) -> list:
            raise NotImplementedError

        async def decode(self, payloads: Sequence["Payload"]) -> list:
            raise NotImplementedError


class PassthroughPayloadCodec(_BaseCodec):
    """No-op codec: returns payloads unchanged.

    Placeholder until Wave 4 wires real encryption for any payload that
    can't be reduced to an ID/version (which should be rare -- most workflow
    inputs should just BE IDs and versions per the invariant above, making
    encryption unnecessary for the common case).
    """

    async def encode(self, payloads: Sequence["Payload"]) -> list:
        return list(payloads)

    async def decode(self, payloads: Sequence["Payload"]) -> list:
        return list(payloads)

    # TODO(wave 4): real encryption for the rare unavoidable sensitive
    # payload. Do not half-implement crypto here -- this stays a no-op until
    # that wave deliberately builds it.
