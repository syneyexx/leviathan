"""module_runtime pool — external module install/update/invoke/process lifecycle.

Owns:
  - external.module.install / update / upgrade
  - external.module.invoke
  - external.module.start / stop / restart / ensure_ready

MCP-backed module tools/call remain mcp_execution.
Heavy Knowledge assimilation remains knowledge_prepare.
"""

from __future__ import annotations

from Data.modules.workers.entrypoints._cli import main_for_pool


def main(argv: list[str] | None = None) -> int:
    # handler=None → _default_gateway_execute via ExternalModuleExecutor
    return main_for_pool("module_runtime", handler=None, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
