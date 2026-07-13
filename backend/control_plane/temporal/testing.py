"""Wave 1 control plane: shared Temporal test-environment fixture.

Wraps temporalio.testing.WorkflowEnvironment (the SDK's built-in local test
server) so later waves (Wave 3 writes the first real workflow tests) don't
each reinvent environment setup/teardown. This module itself does not test
any workflow -- there isn't one yet -- it only proves the fixture works.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional


@asynccontextmanager
async def local_workflow_environment(*, database_filename: Optional[str] = None) -> AsyncIterator["object"]:
    """Yields a temporalio.testing.WorkflowEnvironment started against a
    local, ephemeral test server. Import is deferred inside the function so
    this module stays importable even when temporalio isn't installed."""
    from temporalio.testing import WorkflowEnvironment

    kwargs = {}
    if database_filename:
        kwargs["dev_server_database_filename"] = database_filename
    env = await WorkflowEnvironment.start_local(**kwargs)
    try:
        yield env
    finally:
        await env.shutdown()
