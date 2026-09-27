#!/usr/bin/env python3
import json, sys
query = sys.argv[1] if len(sys.argv) > 1 else ""
print(json.dumps({
  "summary": f"results for {query}",
  "sources": [
    {"title": "One", "url": "https://example.com/1", "source": "web", "summary": "alpha"},
    {"title": "Two", "url": "https://example.com/2", "source": "web", "summary": "beta"},
  ],
  "items": [{"id": 1}, {"id": 2}],
}))
