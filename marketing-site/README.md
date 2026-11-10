# InternTrack product site

This directory contains the public, buildless marketing site for InternTrack.

- Live URL: <https://interntrack-student-beta.alanyan-study.chatgpt.site>
- Hosting manifest: `.openai/hosting.json`
- Static output: `dist/`
- Product source: <https://github.com/jhyan-beep/interntrack>

The site is deliberately honest about the product's early-beta status. It does not claim customer counts, outcomes, or a generally available installer. The current calls to action point to the public repository while the signed desktop release process is completed.

## Local preview

From this directory, serve `dist/` with any static HTTP server. For example:

```bash
python -m http.server 4173 --directory dist
```

Then open <http://127.0.0.1:4173>.

## Publishing

The tracked Sites project ID belongs to this product site. Publish from this directory with the Sites source workflow so the pushed source commit, packaged static output, and deployed version remain identical. Do not create another Site for routine edits.

Privacy and terms pages are part of the same static output. Update them whenever the product's data handling or commercial status changes.

