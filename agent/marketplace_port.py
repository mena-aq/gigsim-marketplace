"""The sole marketplace interface agents use; implementation talks to MCP only."""

from typing import Protocol

from agent.mcp_client import MCPGateway
from mcp_servers.common.schemas import (
    ClientHistory,
    ConnectsOut,
    ConversationOut,
    JobOut,
    JobPage,
    MessageOut,
    MessageRequest,
    ProposalRequest,
    SearchJobs,
    WriteResult,
)


class MarketplacePort(Protocol):
    async def search_jobs(self, request: SearchJobs) -> JobPage: ...
    async def get_job(self, job_id: str) -> JobOut: ...
    async def get_client_history(self, client_id: str) -> ClientHistory: ...
    async def get_connects_balance(self) -> ConnectsOut: ...
    async def list_conversations(self) -> list[ConversationOut]: ...
    async def list_messages(self, conversation_id: str) -> list[MessageOut]: ...
    async def create_proposal_draft(self, request: ProposalRequest) -> WriteResult: ...
    async def submit_proposal(self, request: ProposalRequest) -> WriteResult: ...
    async def send_message(self, request: MessageRequest) -> WriteResult: ...


class MCPMarketplacePort:
    def __init__(self, gateway: MCPGateway):
        self.gateway = gateway

    async def search_jobs(self, request: SearchJobs) -> JobPage:
        return JobPage.model_validate(
            await self.gateway.call(
                "search_jobs", {"request": request.model_dump(mode="json")}
            )
        )

    async def get_job(self, job_id: str) -> JobOut:
        return JobOut.model_validate(
            await self.gateway.call("get_job", {"job_id": job_id})
        )

    async def get_client_history(self, client_id: str) -> ClientHistory:
        return ClientHistory.model_validate(
            await self.gateway.call("get_client_history", {"client_id": client_id})
        )

    async def get_connects_balance(self) -> ConnectsOut:
        return ConnectsOut.model_validate(
            await self.gateway.call("get_connects_balance", {})
        )

    async def list_conversations(self) -> list[ConversationOut]:
        return [
            ConversationOut.model_validate(item)
            for item in await self.gateway.call("list_conversations", {})
        ]

    async def list_messages(self, conversation_id: str) -> list[MessageOut]:
        return [
            MessageOut.model_validate(item)
            for item in await self.gateway.call(
                "list_messages", {"conversation_id": conversation_id}
            )
        ]

    async def create_proposal_draft(self, request: ProposalRequest) -> WriteResult:
        return WriteResult.model_validate(
            await self.gateway.call(
                "create_proposal_draft", {"request": request.model_dump(mode="json")}
            )
        )

    async def submit_proposal(self, request: ProposalRequest) -> WriteResult:
        return WriteResult.model_validate(
            await self.gateway.call(
                "submit_proposal", {"request": request.model_dump(mode="json")}
            )
        )

    async def send_message(self, request: MessageRequest) -> WriteResult:
        return WriteResult.model_validate(
            await self.gateway.call(
                "send_message", {"request": request.model_dump(mode="json")}
            )
        )
