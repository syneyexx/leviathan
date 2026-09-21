# BETA visual review

The BETA preview now uses page-specific layouts across all 16 navigation pages, with reference-based desktop proportions and responsive sizing. It remains a visual preview with example content; business actions are not connected.

Reviewed: Chat, Onderzoek, Bestanden, Geheugen, Modellen, Taken, Coding Agent, Mission Control, Workflows, Agents, Media, Plugins, MCP, Brain, Trading and Instellingen.

Validation on 2026-09-15: compiled the actual BETA components and styles in an isolated esbuild preview, using the repository fonts, Oni SVG and orb asset. Rendered all 16 pages in Chromium at 1672 × 941, plus Chat at 3120 × 1200 and Settings at 800 × 900. Reviewed the screenshot overview and selected full-size pages. No browser page errors or horizontal main-content overflow were reported by this preview.

This was not a production application build or functional test suite. The isolated preview used a minimal global reset and a stubbed settings API; it does not validate the full application integration. No test suite or GitHub Actions run was requested. The implementation is closer to the generated concepts, but no pixel-exact match is claimed: original generated logo details and font rendering can differ.

After pulling the merged change, rebuild the frontend with npm run build before using vite preview, then restart and refresh the browser.
