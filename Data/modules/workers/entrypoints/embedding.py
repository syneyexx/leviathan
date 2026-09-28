"""Embedding pool entrypoint — specialist inference via embedding.worker.

No Knowledge SQLite bulk writes here; commit ownership stays with db_commit.
"""

from __future__ import annotations

from Data.modules.workers.entrypoints._cli import main_for_pool


def _handler(ctx, job):
    from Data.modules.embedding.worker import process_embedding_job

    return process_embedding_job(ctx, job)


def main(argv=None):
    return main_for_pool("embedding", handler=_handler, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
