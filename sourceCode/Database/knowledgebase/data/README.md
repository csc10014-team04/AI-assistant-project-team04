# data

Output of the crawler. **Do not edit by hand**: re-run the crawler instead (hand corrections belong in the structured
tables planned in `../README.md`, section "Next step").

- `<site id>/<page>.md`: one collected page. Starts with a front-matter block (`source_url`, `site`, `site_name`, `title`, `fetched_at`, `sha256`), then the page text.
- `index.json`: list of every collected page (site, url, title, file, fetched_at, sha256, size).

Site ids: `hcmus` (university), `fit` (Information Technology), `fbb` (Biology - Biotechnology), `chemistry`, `math`.
Phone numbers and e-mail addresses were removed from the text when it was saved.
