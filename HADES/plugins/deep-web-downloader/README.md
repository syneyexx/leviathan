# HADES Deep Web Downloader

A HADES-native multi-hop crawler/downloader for public-domain, licensed, owned, or otherwise authorized web content.

## What it does

- Starts from any manually supplied HTTP/HTTPS URL.
- Follows redirects and nested links up to a configurable depth.
- Traverses the start domain plus any additional domains you explicitly add to `allowed_domains`.
- Detects real downloads using URL extension, `Content-Type`, and `Content-Disposition`.
- Physically saves PDFs, Office documents, EPUBs, archives, text/data files and other binary downloads.
- Optionally saves traversed HTML pages too.
- Extracts links from `href`, `src`, iframe/embed/object/data attributes, meta refresh, and absolute URLs embedded in HTML.
- Deduplicates identical downloaded files by SHA-256.
- Writes `crawl-manifest.json` with visited URLs, local file paths, hashes, errors and crawl statistics.
- Includes `open_terminal` to launch an interactive downloader terminal.

## HADES runtime

Use **crawl_url** from Plugins and provide at minimum:
- `url`
- `authorized: true`

Useful defaults:
- `max_depth: 6`
- `max_pages: 500`
- `max_files: 500`
- `allowed_domains: "cdn.example.org,files.example.org"` when needed
- `robots.txt` is always enforced
- `output_dir: downloads`

Use **inspect_url** first when you want to see redirects and candidate links without downloading.

Use **open_terminal** to open a new console and enter the URL/settings interactively.

## Direct CLI

```bash
python crawler.py interactive
```

or:

```bash
python crawler.py crawl   --url "https://example.org/"   --output downloads   --max-depth 6   --max-pages 500   --max-files 500   --allowed-domains "cdn.example.org"   --authorized true
```

## Boundaries

The plugin does not implement credential theft, login bypass, paywall bypass, CAPTCHA circumvention, DRM removal, or exploit-based access. It downloads resources reachable through normal public HTTP/HTTPS requests and is intended only for content you are authorized to retrieve.
