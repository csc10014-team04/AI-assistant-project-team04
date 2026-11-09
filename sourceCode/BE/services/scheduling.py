
from datetime import datetime,timedelta

from sqlalchemy.orm import Session

from database import VN_TZ,to_db_utc
from models import (
    PriorityLevel,
    PrioritySource,
    Proposal,
    ProposalStatus,
    Task,
    TaskStatus,
)
from services.nlu import NluResult
from services.search_engine import find_user_free_slots


def create_schedule_proposal(
    db:Session,
    owner_id:int,
    prompt:str,
    nlu:NluResult,
    reference_now:datetime,
    reschedule_proposal_id:int|None=None,
)->dict:
    if nlu.intent not in ("schedule_task","reschedule"):
        return {
            "fallback_mode":False,
            "ai_reply":nlu.clarification_question or "I could not identify a scheduling request.",
            "proposal":None,
        }

    if nlu.needs_clarification or not nlu.title or not nlu.duration_minutes:
        return {
            "fallback_mode":False,
            "ai_reply":nlu.clarification_question or "Please provide the task name and duration.",
            "proposal":None,
        }

    window_start=datetime.combine(
        nlu.window_start or reference_now.astimezone(VN_TZ).date(),
        datetime.min.time(),
        tzinfo=VN_TZ,
    )
    window_end=datetime.combine(
        nlu.window_end or (window_start.date()+timedelta(days=6)),
        datetime.max.time(),
        tzinfo=VN_TZ,
    )

    task=Task(
        owner_id=owner_id,
        title=nlu.title,
        duration_minutes=nlu.duration_minutes,
        priority=nlu.priority or PriorityLevel.LOW,
        priority_source=PrioritySource.AI if nlu.priority else PrioritySource.DEFAULT,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()

    slots=find_user_free_slots(
        db,
        owner_id,
        window_start,
        window_end,
        nlu.duration_minutes,
        respect_preferences=True,
    )

    matching=[]
    for slot in slots:
        start=slot.start
        end=start+timedelta(minutes=nlu.duration_minutes)

        if end<=slot.end:
            if nlu.preferred_time_of_day=="morning" and start.hour>=12:
                continue
            if nlu.preferred_time_of_day=="afternoon" and not 12<=start.hour<17:
                continue
            if nlu.preferred_time_of_day=="evening" and start.hour<17:
                continue
            if nlu.avoid_time_of_day=="morning" and start.hour<12:
                continue
            if nlu.avoid_time_of_day=="afternoon" and 12<=start.hour<17:
                continue
            if nlu.avoid_time_of_day=="evening" and start.hour>=17:
                continue
            matching.append((start,end))

    if not matching:
        db.rollback()
        return {
            "fallback_mode":True,
            "task_title":nlu.title,
            "duration":nlu.duration_minutes,
            "available_slots":[],
            "ai_reply":"No suitable free slots were found in the requested date range.",
        }

    start,end=matching[0]

    proposal=Proposal(
        owner_id=owner_id,
        task_id=task.id,
        parent_id=reschedule_proposal_id,
        start_time=to_db_utc(start),
        end_time=to_db_utc(end),
        rationale="Selected from available time slots while respecting existing hard schedule constraints.",
        source_prompt=prompt,
        status=ProposalStatus.PROPOSED,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    return {
        "fallback_mode":False,
        "ai_reply":"I found an available time slot. Please review the proposal.",
        "proposal":{
            "id":proposal.id,
            "task_id":task.id,
            "task_title":task.title,
            "start_time":start.isoformat(),
            "end_time":end.isoformat(),
            "rationale":proposal.rationale,
            "status":proposal.status.value,
        },
    }
