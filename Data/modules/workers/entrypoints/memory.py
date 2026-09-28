"""Worker Fabric entrypoint — memory pool."""

from __future__ import annotations

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx, job):
    from Data.modules.memory.worker import process_memory_job

    return process_memory_job(ctx, job)


def main(argv=None):
    return main_for_pool("memory", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
