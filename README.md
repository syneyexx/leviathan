# LEVIATHAN — Standalone browser shell

Fluid HTML/CSS/JS recreation of the LEVIATHAN Command layout.

## Open

Serve the folder (recommended) or open `index.html` directly:

```bash
python -m http.server 8765 --directory LEVIATHAN
```

Then open `http://localhost:8765`.

## Notes

- Design tokens live in `css/tokens.css` (canonical visual system).
- Layout scales with the browser via `clamp()`, fluid grid columns, and responsive breakpoints.
- No backend is bundled; controls are visual/demo interactions.
