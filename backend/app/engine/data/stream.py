"""Live bar streaming (Alpaca IEX). The SDK wiring is thin; the storage logic
lives in LiveBarConsumer, which is unit-testable without a network connection.

Note: Alpaca's live `bars` channel emits 1-minute bars; aggregation to 5-minute
is handled by the orchestrator loop (Phase 7).
"""

from __future__ import annotations

from app.engine.data.service import MarketDataService


class LiveBarConsumer:
    def __init__(self, service: MarketDataService, timeframe: str = "1Min") -> None:
        self._service = service
        self._timeframe = timeframe

    def on_bar(self, symbol, ts, open_, high, low, close, volume) -> bool:
        return self._service.upsert_bar(
            symbol, self._timeframe, ts, open_, high, low, close, volume
        )


class AlpacaBarStream:
    def __init__(self, api_key: str, secret_key: str, consumer: LiveBarConsumer) -> None:
        from alpaca.data.enums import DataFeed
        from alpaca.data.live import StockDataStream

        self._stream = StockDataStream(api_key, secret_key, feed=DataFeed.IEX)
        self._consumer = consumer

    def subscribe(self, *symbols: str) -> None:
        async def handler(bar):  # noqa: ANN001
            self._consumer.on_bar(
                bar.symbol, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume
            )

        self._stream.subscribe_bars(handler, *symbols)

    def run(self) -> None:
        self._stream.run()
