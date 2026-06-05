"""ProposalService: generate self-learning proposals (gated) and apply approvals.

Manual strategies generate nothing. For self-learning strategies, #2 (feedback)
and #4 (Claude, budget-gated) each produce a proposal with a *mandatory* backtest
preview. Nothing changes the live strategy until a human approves; approval (or
edit-and-approve) creates a new immutable version.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.engine.backtest.walkforward import run_walk_forward
from app.engine.learning.budget import LearningBudget, can_run_llm, record_usage
from app.engine.learning.feedback import propose_from_performance
from app.engine.learning.llm import LLMProposer
from app.engine.risk.limits import clamp_spec
from app.engine.strategies.service import StrategyService
from app.engine.strategies.spec import StrategySpec
from app.models.backtest import Backtest
from app.models.proposal import Proposal, ProposalSource, ProposalStatus
from app.models.strategy import CreatedBy, Strategy, StrategyMode

_SOURCE_TO_CREATED_BY = {
    ProposalSource.feedback: CreatedBy.feedback,
    ProposalSource.llm: CreatedBy.llm,
    ProposalSource.user: CreatedBy.user,
}


class ProposalService:
    def __init__(
        self,
        db: Session,
        llm: LLMProposer | None = None,
        budget: LearningBudget | None = None,
        backtest_kwargs: dict | None = None,
    ) -> None:
        self._db = db
        self._llm = llm or LLMProposer()
        self._budget = budget or LearningBudget()
        self._bt_kwargs = backtest_kwargs or {}
        self._strategies = StrategyService(db)

    def _run_backtest(self, version_id: int | None, spec: StrategySpec, prices, features):
        result = run_walk_forward(prices, features, spec, **self._bt_kwargs)
        bt = Backtest(
            strategy_version_id=version_id or 0,
            config=dict(self._bt_kwargs),
            result=result.to_dict(),
        )
        self._db.add(bt)
        self._db.commit()
        self._db.refresh(bt)
        return bt, result

    def _create_proposal(
        self,
        strategy: Strategy,
        proposed: StrategySpec,
        source: ProposalSource,
        rationale,
        prices,
        features,
    ) -> Proposal:
        clamped = clamp_spec(proposed)
        bt, _ = self._run_backtest(strategy.current_version_id, clamped, prices, features)
        p = Proposal(
            strategy_id=strategy.id,
            source=source,
            status=ProposalStatus.pending,
            rationale=rationale,
            proposed_spec=clamped.model_dump(mode="json"),
            backtest_id=bt.id,
        )
        self._db.add(p)
        self._db.commit()
        self._db.refresh(p)
        return p

    def generate_for_strategy(self, strategy: Strategy, prices, features) -> list[Proposal]:
        spec = self._strategies.current_spec(strategy)
        if spec is None or spec.mode != StrategyMode.self_learning:
            return []  # manual strategies never get app proposals

        _, baseline = self._run_backtest(strategy.current_version_id, spec, prices, features)
        proposals: list[Proposal] = []

        fb = propose_from_performance(spec, baseline.regime_breakdown)
        if fb is not None:
            proposals.append(
                self._create_proposal(
                    strategy,
                    fb,
                    ProposalSource.feedback,
                    "Adaptive parameter feedback from realized per-regime performance.",
                    prices,
                    features,
                )
            )

        if can_run_llm(self._db, self._budget):
            try:
                draft = self._llm.propose(
                    spec,
                    {"metrics": baseline.metrics, "regime_breakdown": baseline.regime_breakdown},
                )
                record_usage(
                    self._db, strategy.id, "proposal", draft.input_tokens, draft.output_tokens
                )
                proposals.append(
                    self._create_proposal(
                        strategy,
                        draft.proposed_spec,
                        ProposalSource.llm,
                        draft.rationale,
                        prices,
                        features,
                    )
                )
            except Exception:
                pass  # an LLM failure must not block the (free) feedback proposal

        return proposals

    def pending(self, strategy_id: int | None = None) -> list[Proposal]:
        q = self._db.query(Proposal).filter_by(status=ProposalStatus.pending)
        if strategy_id is not None:
            q = q.filter_by(strategy_id=strategy_id)
        return q.order_by(Proposal.created_at.desc()).all()

    def approve(self, proposal_id: int, edited_spec: dict | None = None):
        p = self._db.get(Proposal, proposal_id)
        if p is None or p.status != ProposalStatus.pending:
            raise ValueError("proposal not pending")
        spec_dict = edited_spec if edited_spec is not None else p.proposed_spec
        spec = clamp_spec(StrategySpec.model_validate(spec_dict))
        created_by = CreatedBy.user if edited_spec is not None else _SOURCE_TO_CREATED_BY[p.source]
        version = self._strategies.update_spec(p.strategy_id, spec, created_by=created_by)
        p.status = ProposalStatus.approved
        p.reviewed_at = datetime.now(UTC)
        self._db.commit()
        return version

    def reject(self, proposal_id: int) -> Proposal:
        p = self._db.get(Proposal, proposal_id)
        if p is None or p.status != ProposalStatus.pending:
            raise ValueError("proposal not pending")
        p.status = ProposalStatus.rejected
        p.reviewed_at = datetime.now(UTC)
        self._db.commit()
        return p
