"""module_runtime pool — external module dependency installation only.

Owns ``external.module.install`` (venv/pip/npm/build/staging/promotion).
Does not claim arbitrary ``external.module.invoke`` work.

Uses the default JobRuntime/gateway execute path (ExternalModuleExecutor).
"""

from __future__ import annotations

from Data.modules.workers.entrypoints._cli import main_for_pool


def main(argv: list[str] | None = None) -> int:
    # handler=None → _default_gateway_execute via ExternalModuleExecutor.install
    return main_for_pool("module_runtime", handler=None, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
