# scholar

Utilities for tracking citations to your Google Scholar papers. GS has no API, so these tools scrape the website using a real browser and maintain a local JSON database.

## Setup

```bash
conda activate test
pip install playwright
playwright install chromium
```

## Scripts

### `scholar.py` — scrape & update

Fetches your GS profile, finds all papers, and collects every paper that cites each of them. Saves results to `scholar_db.json`.

```bash
conda run -n test python scholar.py              # update DB (default: visible browser)
conda run -n test python scholar.py --full       # force re-scrape all citations
conda run -n test python scholar.py --headless   # run without visible browser (may get blocked)
```

**First run** fetches everything and is slow — plan for GS to CAPTCHA you. A Chrome window opens; solve any CAPTCHA you see and the script continues automatically. GS will eventually rate-limit you; the script saves after each paper so re-running resumes where it left off.

**Subsequent runs** skip papers whose citation count hasn't changed, so they're much faster.

### `report.py` — offline reporting

Reads `scholar_db.json` locally — no network access needed.

```bash
conda run -n test python report.py               # DB stats: papers, citation counts, completeness
conda run -n test python report.py --since 2024  # all citing papers published in 2024 or later
conda run -n test python report.py --since 2023  # same, back to 2023
```

## Database (`scholar_db.json`)

```
{
  "author": { "name": ..., "scholar_id": ... },
  "papers": {
    "<paper_id>": {
      "title": ..., "year": ..., "citation_count": ...,
      "citations_complete": true/false,   ← false = interrupted, re-run to finish
      "last_checked": "<ISO timestamp>"
    }
  },
  "citations": {
    "<paper_id>": [
      { "title": ..., "authors": ..., "year": ..., "venue": ..., "url": ..., "first_seen": ... }
    ]
  }
}
```

`citations_complete: false` means GS cut off the scrape for that paper mid-way. Re-running `scholar.py` will resume those automatically.

## Notes

- GS uses non-breaking spaces (`\xa0`) in its info lines — the scraper normalises these.
- The `--since YEAR` filter is by the **citing paper's publication year**, not the date it was scraped.
- Scholar ID is hardcoded as `weAbyM4AAAAJ` in `scholar.py`.
