"""StrategyService: create strategies and append immutable versions.

Manual edits apply immediately (a new version becomes current). App-generated
proposals go through the approval flow (Phase 8) which also calls update_spec
with created_by=llm/feedback once approved.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.engine.strategies.spec import StrategySpec
from app.models.strategy import CreatedBy, Strategy, StrategyStatus, StrategyVersion


class StrategyService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_strategy(self, user_id: int, name: str, spec: StrategySpec) -> Strategy:
        strat = Strategy(
            user_id=user_id, name=name, mode=spec.mode, status=StrategyStatus.draft
        )
        self._db.add(strat)
        self._db.flush()  # assign strat.id

        version = StrategyVersion(
            strategy_id=strat.id,
            version_num=1,
            spec=spec.model_dump(mode="json"),
            created_by=CreatedBy.user,
            parent_version_id=None,
        )
        self._db.add(version)
        self._db.flush()  # assign version.id

        strat.current_version_id = version.id
        self._db.commit()
        self._db.refresh(strat)
        return strat

    def update_spec(
        self, strategy_id: int, spec: StrategySpec, created_by: CreatedBy = CreatedBy.user
    ) -> StrategyVersion:
        strat = self._db.get(Strategy, strategy_id)
        if strat is None:
            raise ValueError("strategy not found")

        last = (
            self._db.query(StrategyVersion)
            .filter_by(strategy_id=strategy_id)
            .order_by(StrategyVersion.version_num.desc())
            .first()
        )
        version = StrategyVersion(
            strategy_id=strategy_id,
            version_num=(last.version_num + 1) if last else 1,
            spec=spec.model_dump(mode="json"),
            created_by=created_by,
            parent_version_id=last.id if last else None,
        )
        self._db.add(version)
        self._db.flush()

        strat.current_version_id = version.id
        strat.mode = spec.mode
        self._db.commit()
        self._db.refresh(version)
        return version

    def current_spec(self, strategy: Strategy) -> StrategySpec | None:
        if strategy.current_version_id is None:
            return None
        v = self._db.get(StrategyVersion, strategy.current_version_id)
        return StrategySpec.model_validate(v.spec) if v else None

    def list_versions(self, strategy_id: int) -> list[StrategyVersion]:
        return (
            self._db.query(StrategyVersion)
            .filter_by(strategy_id=strategy_id)
            .order_by(StrategyVersion.version_num.asc())
            .all()
        )
