"""The final send checks the reserve under the MCP tenant transaction."""

import pytest

from gigsim.models import Connects
from mcp_servers.common.errors import ToolFailure
from mcp_servers.common.schemas import ProposalRequest
from mcp_servers.common.security import Identity
from mcp_servers.marketplace.service import MarketplaceService
from tests.unit.test_mcp_layer import grant, runtime  # noqa: F401 -- shared fixture


async def test_connects_change_after_review_blocks_final_send(runtime):  # noqa: F811 -- imported fixture
    request = ProposalRequest(
        job_id="job_ml",
        cover_letter="Python forecasting",
        expected_connects_cost=8,
        idempotency_key="reserve-race",
    )
    service = MarketplaceService(runtime)
    who = Identity("alice", "ml_engineer")
    await service.proposal(
        who, request.model_copy(update={"dry_run": True}), draft=False
    )
    await grant(runtime, "submit_proposal", request)
    async with runtime.transport.app.state.sessionmaker() as session:
        session.add(Connects(freelancer_id="ml_engineer", balance=8))
        await session.commit()
    with pytest.raises(ToolFailure, match="reserve"):
        await service.proposal(who, request, draft=False)
    assert (await service.adapter.get_connects_balance(who))["balance"] == 8
