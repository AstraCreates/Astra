import pytest

pytest.importorskip("temporalio", reason="temporalio not installed in this environment yet — Wave 1 scaffolding only")

from backend.control_plane.temporal.codec import PassthroughPayloadCodec
from backend.control_plane.temporal.testing import local_workflow_environment


@pytest.mark.asyncio
async def test_local_workflow_environment_starts_and_shuts_down_cleanly():
    async with local_workflow_environment() as env:
        assert env is not None


@pytest.mark.asyncio
async def test_passthrough_codec_returns_payloads_unchanged():
    codec = PassthroughPayloadCodec()
    payloads = ["a", "b", "c"]  # stand-in objects; codec is a pure passthrough
    encoded = await codec.encode(payloads)
    decoded = await codec.decode(encoded)
    assert encoded == payloads
    assert decoded == payloads
