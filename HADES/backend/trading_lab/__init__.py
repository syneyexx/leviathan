"""HADES Trading Lab.

Local research, simulation and PAPER execution environment. Nothing in this package
opens a broker session, submits a real-money order or purchases market data. The only
execution writer is ``trading_lab.execution``, which is a simulator.

Module responsibilities (kept separate on purpose; see docs/TRADING_LAB.md):

- ``contracts``    validated data contracts shared by every layer
- ``instruments``  Instrument Registry (identity, tick/lot, calendar, price-sign rule)
- ``capabilities`` capability matrix over instrument family x data level x order type
- ``store``        SQLite metadata: datasets, strategies, experiments, runs, orders, audit
- ``bar_store``    partitioned bulk market history with streamed, bounded reads
- ``data_quality`` deterministic dataset validation
- ``catalog``      Market Data Catalog: manifests, coverage, checksums, versions
- ``providers``    configurable data adapters (import / allowed download / synthetic)
- ``clock``        Simulation Clock + Point-in-Time Data Gateway
- ``accounting``   Decimal money/position ledger
- ``adapters``     per-instrument-family accounting and lifecycle rules
- ``execution``    Exchange/Broker simulator (the only writer of fills)
- ``risk``         deterministic Risk Engine with the decisive veto
- ``strategies``   Strategy Runtime and the strategy family library
- ``models``       explicit numerical model training with versioned artefacts
- ``engine``       simulation orchestration, checkpoints, rewind branches
- ``research``     Experiment Registry, bounded search, learning modes
- ``evaluation``   Independent Evaluation (walk-forward, stress, annualisation)
- ``registry``     Strategy Registry lifecycle and promotion gate
- ``agents``       logical agent roles over the existing HADES agent architecture
- ``jobs``         bounded worker queue with pause/resume/cancel/idempotent retry
- ``experience``   delayed-outcome → experience records (idempotent)
- ``regimes``      point-in-time OHLCV regime features
- ``learning``     aggregation, evidence quality, belief updates
- ``evolution``    bounded declarative strategy mutations and lineage
- ``champions``    champion/challenger admission policy
- ``learning_cycle`` durable bounded research loop
- ``service``      facade used by the HTTP layer
- ``routes``       ``/api/trading/lab/*``
"""

from __future__ import annotations

__all__ = ["TRADING_LAB_VERSION"]

TRADING_LAB_VERSION = "1.1.0"
