#!/usr/bin/env python3
import json, sys
query = sys.argv[1] if len(sys.argv) > 1 else ""
print(json.dumps({
  "summary": f"results for {query}",
  "sources": [
    {
      "title": "One",
      "url": "https://example.com/1",
      "source": "web",
      "summary": "alpha",
      "published_at": "2026-09-01T12:00:00+00:00",
      "available_at": "2026-09-01T12:05:00+00:00",
    },
    {
      "title": "Two",
      "url": "https://example.com/2",
      "source": "web",
      "summary": "beta",
      "published_at": "2026-09-15T08:30:00+00:00",
    },
  ],
  "items": [{"id": 1}, {"id": 2}],
}))
