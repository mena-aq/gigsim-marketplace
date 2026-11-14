"""Local drafts, exact previews, and approval-gated simulator sends."""

from sqlalchemy import select

from apps.api.models import Job, Message, Proposal
from mcp_servers.common.security import ToolFailure
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter


class MarketplaceService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.adapter = GigSimAdapter(runtime)

    async def proposal(self, who, request, *, draft):
        tool = "create_proposal_draft" if draft else "submit_proposal"
        payload = {
            **request.model_dump(
                mode="json", exclude={"dry_run", "expected_connects_cost"}
            ),
            "dry_run": False,
        }

        async def execute(session, preview):
            quote = await self.adapter.request(
                who, "POST", "/proposals", payload={**payload, "dry_run": True}
            )
            cost = quote["connects_spent"]
            result = {
                "status": "dry_run" if preview else "drafted",
                "payload": payload,
                "connects_cost": cost,
            }
            if preview:
                return result
            if draft:
                job = (
                    await session.execute(
                        select(Job).where(
                            Job.user_id == who.user_id,
                            Job.marketplace == "gigsim",
                            Job.external_id == request.job_id,
                        )
                    )
                ).scalar_one_or_none()
                if job is None:
                    remote = await self.adapter.get_job(who, request.job_id)
                    job = Job(
                        user_id=who.user_id,
                        marketplace="gigsim",
                        external_id=request.job_id,
                        title=remote["title"],
                        description=remote["description"],
                    )
                    session.add(job)
                    await session.flush()
                proposal = Proposal(
                    user_id=who.user_id,
                    job_id=job.id,
                    idempotency_key=request.idempotency_key,
                    cover_letter=request.cover_letter,
                    connects_cost=cost,
                )
                session.add(proposal)
                await session.flush()
                result["draft_id"] = proposal.id
            else:
                from agent.config import load_graph_config

                reserve = load_graph_config()["orchestration"][
                    "minimum_connects_reserve"
                ]
                # Runtime holds the tenant write lock here. Recheck the reserve
                # after other approved runs may have spent Connects. An upstream
                # replay has already committed and must recover its old receipt.
                if (
                    quote["status"] == "dry_run"
                    and quote["connects_remaining"] < reserve
                ):
                    raise ToolFailure(
                        "connects_reserve", "Sending would exceed the Connects reserve"
                    )
                if request.expected_connects_cost != cost:
                    raise ToolFailure(
                        "preview_changed",
                        "Confirm the current Connects cost before sending",
                    )
                remote = await self.adapter.request(
                    who, "POST", "/proposals", payload={**payload, "dry_run": False}
                )
                result.update(
                    status=remote["status"],
                    external_id=str(remote["id"]),
                    connects_cost=remote["connects_spent"],
                )
            return result

        return await self.runtime.write(who, tool, request, execute, approval=not draft)

    async def message(self, who, request):
        payload = {
            **request.model_dump(mode="json", exclude={"dry_run"}),
            "dry_run": False,
        }

        async def execute(session, preview):
            remote = await self.adapter.request(
                who, "POST", "/messages", payload={**payload, "dry_run": preview}
            )
            result = {
                "status": "dry_run" if preview else "sent",
                "payload": payload,
                "connects_cost": 0,
            }
            if not preview:
                result["external_id"] = str(remote["id"])
                session.add(
                    Message(
                        user_id=who.user_id,
                        marketplace="gigsim",
                        external_id=str(remote["id"]),
                        conversation_id=request.conversation_id,
                        sender="freelancer",
                        body=request.body,
                        status="sent",
                    )
                )
            return result

        return await self.runtime.write(
            who, "send_message", request, execute, approval=True
        )
