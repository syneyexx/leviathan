from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Data.modules.brain import BrainQueryFacade
from Data.modules.knowledge import KnowledgeStore
from Data.modules.memory import MemoryStore, MemoryStatus


class BrainCatalogTests(unittest.TestCase):
    def test_real_sqlite_documents_beyond_250_and_owner_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = KnowledgeStore(Path(tmp) / 'catalog.db')
            store.initialize()
            with store.connect() as conn:
                conn.executemany(
                    'INSERT INTO knowledge_documents(id,title,content,created_at,updated_at) VALUES (?,?,?,?,?)',
                    [(f'd{i:04}', f'Document {i}', 'content', '2026-09-30', '2026-09-30') for i in range(603)],
                )
            calls = []
            def page(offset, limit):
                calls.append((offset, limit))
                return store.list_documents(offset=offset, limit=limit)
            facade = BrainQueryFacade(page_sources={'knowledge_list': page}, module_list=lambda: [
                {'module_id': 'last-module', 'name': 'Module', 'capabilities': []},
            ])
            nodes = {}
            source = offset = 0
            while True:
                result = facade.catalog_page(source=source, offset=offset)
                nodes.update((n['id'], n) for n in result['nodes'])
                cursor = result['page']
                if cursor['complete']:
                    break
                source, offset = cursor['next_source'], cursor['next_offset']
            docs = [n for n in nodes.values() if n['type'] == 'knowledge.document']
            self.assertEqual(len(docs), 603)
            self.assertIn('knowledge:document:d0602', nodes)
            self.assertTrue(any(n['type'] == 'module' for n in nodes.values()))
            self.assertTrue(all(n <= 51 for _, n in calls))
            self.assertEqual(store.list_documents(offset=600, limit=3)[-1].document_id, 'd0602')

    def test_all_memory_pages_include_archived_records_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / 'memory.db')
            store.initialize()
            for i in range(503):
                record = store.create(content=f'Memory {i}')
                if i == 0:
                    store.set_status(record.memory_id, MemoryStatus.ARCHIVED)
            facade = BrainQueryFacade(page_sources={'memory_list': lambda o, n: store.list(limit=n, offset=o, status=None)})
            source = facade.CATALOG_SOURCES.index('memory_list')
            seen = set()
            offset = 0
            while True:
                page = facade.catalog_page(source=source, offset=offset)
                seen.update(n['id'] for n in page['nodes'] if n['type'] == 'memory')
                if page['page']['next_source'] != source:
                    break
                offset = page['page']['next_offset']
            self.assertEqual(len(seen), 503)

    def test_cross_page_edges_and_no_cap_on_a_modules_referenced_capabilities(self):
        facade = BrainQueryFacade(module_list=lambda: [{'manifest': {'module_id': 'm', 'name': 'M', 'capabilities': [{'capability_id': f'c{i}'} for i in range(320)]}}],
            atlas_list=lambda: [{'atlas_id': 'a', 'evidence_record_refs': ['ev-outside-page']}])
        modules = facade.catalog_page(source=facade.CATALOG_SOURCES.index('module_list'))
        self.assertEqual(len(modules['nodes']), 321)
        atlas = facade.catalog_page(source=facade.CATALOG_SOURCES.index('atlas_list'))
        self.assertEqual(atlas['edges'][0]['target'], 'evidence:ev-outside-page')

    def test_owner_offset_queries_and_http_cursor_validation(self):
        from Data.modules.evidence import EvidenceStore
        from Data.modules.research.store import ResearchStore
        from Data.modules.workflows.store import WorkflowStore
        from Data.modules.knowledge.atlas import AtlasStore
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from Data.backend.routes.brain import build_brain_router
        with tempfile.TemporaryDirectory() as tmp:
            for cls, method in [(EvidenceStore, 'list'), (ResearchStore, 'list_projects'), (WorkflowStore, 'list'), (AtlasStore, 'list_page')]:
                store = cls(Path(tmp) / f'{cls.__name__}.db')
                store.initialize()
                self.assertEqual(getattr(store, method)(limit=51, offset=500), [])
            knowledge = KnowledgeStore(Path(tmp) / 'relations.db')
            knowledge.initialize()
            self.assertEqual(knowledge.list_relation_atoms(limit=51, offset=500), [])
        app = FastAPI()
        app.include_router(build_brain_router(BrainQueryFacade()))
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/brain/catalog?source=0&offset=0').status_code, 200)
            self.assertEqual(client.get('/api/brain/catalog?source=99').status_code, 422)
            self.assertEqual(client.get('/api/brain/catalog?offset=-1').status_code, 422)
