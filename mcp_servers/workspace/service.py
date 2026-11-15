"""Persistent local calendar and email mock; no external accounts or sends."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from apps.api.models import EmailDraft, WorkspaceHold
from mcp_servers.common.security import ToolFailure

ZONE = ZoneInfo("Asia/Karachi")


class WorkspaceService:
    def __init__(self, runtime):
        self.runtime = runtime

    async def free_slots(self, who, days_ahead):
        now = datetime.now(ZONE)
        async with self.runtime.sessions() as session:
            holds = (
                (
                    await session.execute(
                        select(WorkspaceHold).where(
                            WorkspaceHold.user_id == who.user_id,
                            WorkspaceHold.ends_at > now,
                        )
                    )
                )
                .scalars()
                .all()
            )
        slots = []
        for delta in range(days_ahead):
            day = now.date() + timedelta(days=delta)
            if day.weekday() >= 5:
                continue
            for hour in range(9, 17):
                start = datetime.combine(day, time(hour), ZONE)
                end = start + timedelta(hours=1)
                if start > now and not any(
                    aware(hold.starts_at) < end and aware(hold.ends_at) > start
                    for hold in holds
                ):
                    slots.append(
                        {"starts_at": start.isoformat(), "ends_at": end.isoformat()}
                    )
        return {"timezone": "Asia/Karachi", "slots": slots}

    async def hold(self, who, request):
        async def execute(session, preview):
            start = request.slot.starts_at.astimezone(ZONE)
            end = request.slot.ends_at.astimezone(ZONE)
            if (
                start <= datetime.now(ZONE)
                or start.date() != end.date()
                or start.weekday() >= 5
                or start.time() < time(9)
                or end.time() > time(17)
            ):
                raise ToolFailure(
                    "invalid_slot",
                    "Choose a future weekday slot within 09:00–17:00 Asia/Karachi",
                )
            if session is None:
                async with self.runtime.sessions() as lookup:
                    conflict = await self.conflict(lookup, who, start, end)
            else:
                conflict = await self.conflict(session, who, start, end)
            if conflict:
                raise ToolFailure(
                    "slot_unavailable", "This slot overlaps an existing hold"
                )
            result = {
                "status": "dry_run" if preview else "held",
                "payload": request.model_dump(mode="json", exclude={"dry_run"}),
                "connects_cost": 0,
            }
            if not preview:
                hold = WorkspaceHold(
                    user_id=who.user_id,
                    title=request.title,
                    starts_at=start,
                    ends_at=end,
                )
                session.add(hold)
                await session.flush()
                result["draft_id"] = hold.id
            return result

        return await self.runtime.write(who, "create_hold", request, execute)

    async def conflict(self, session, who, start, end):
        return (
            await session.execute(
                select(WorkspaceHold.id)
                .where(
                    WorkspaceHold.user_id == who.user_id,
                    WorkspaceHold.starts_at < end,
                    WorkspaceHold.ends_at > start,
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    async def email(self, who, request):
        async def execute(session, preview):
            result = {
                "status": "dry_run" if preview else "drafted",
                "payload": request.model_dump(mode="json", exclude={"dry_run"}),
                "connects_cost": 0,
            }
            if not preview:
                draft = EmailDraft(
                    user_id=who.user_id,
                    recipient=request.to,
                    subject=request.subject,
                    body=request.body,
                )
                session.add(draft)
                await session.flush()
                result["draft_id"] = draft.id
            return result

        return await self.runtime.write(who, "create_email_draft", request, execute)


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
