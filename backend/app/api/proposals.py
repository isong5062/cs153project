"""Proposal inbox: list pending, approve (with optional edits), reject."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.schemas import ApproveRequest, ProposalOut, VersionOut
from app.db.session import get_db
from app.engine.learning.service import ProposalService
from app.models.user import User

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("", response_model=list[ProposalOut])
def list_proposals(
    strategy_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return ProposalService(db).pending(strategy_id)


@router.post("/{proposal_id}/approve", response_model=VersionOut)
def approve(
    proposal_id: int,
    body: ApproveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    try:
        return ProposalService(db).approve(proposal_id, body.edited_spec)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{proposal_id}/reject", response_model=ProposalOut)
def reject(proposal_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        return ProposalService(db).reject(proposal_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
