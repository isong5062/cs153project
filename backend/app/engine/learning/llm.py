"""#4 Claude strategy proposer.

Sends the current spec + backtest performance to Claude and parses back a JSON
spec edit + rationale. The Anthropic client is injectable so this is unit-testable
without network/keys. The system prompt is marked for prompt caching.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.engine.strategies.spec import StrategySpec

DEFAULT_MODEL = "claude-sonnet-4-6"

_SYSTEM = (
    "You are a quantitative trading strategy optimizer. You receive a strategy spec "
    "(regime -> target exposure / leverage / entry-exit rules) and its walk-forward "
    "backtest performance. Propose an improved spec.\n"
    'Respond with ONLY a JSON object: {"rationale": "<concise why>", "spec": <full spec JSON>}. '
    "Keep the existing schema and regime labels. Never set leverage above 1.5 or "
    "max_risk_per_trade above 0.01."
)


@dataclass
class ProposalDraft:
    proposed_spec: StrategySpec
    rationale: str
    input_tokens: int
    output_tokens: int


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in LLM response")
    return json.loads(text[start : end + 1])


class LLMProposer:
    def __init__(self, client=None, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self._model = model

    def _ensure_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def propose(self, spec: StrategySpec, performance: dict) -> ProposalDraft:
        client = self._ensure_client()
        user = json.dumps(
            {"current_spec": spec.model_dump(mode="json"), "performance": performance}
        )
        resp = client.messages.create(
            model=self._model,
            max_tokens=1500,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        data = _extract_json(text)
        proposed = StrategySpec.model_validate(data["spec"])
        return ProposalDraft(
            proposed_spec=proposed,
            rationale=str(data.get("rationale", "")),
            input_tokens=int(resp.usage.input_tokens),
            output_tokens=int(resp.usage.output_tokens),
        )
