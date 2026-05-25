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

**Subsequent runs** skip papers whose citation count hasn't changed and whose citations are fully fetched, so they're much faster.

### `report.py` — offline reporting

Reads `scholar_db.json` locally — no network access needed. Every run also writes `errors.tsv` flagging suspicious citation records (impossible years, missing years).

```bash
conda run -n test python report.py                        # DB stats: papers, citation counts, completeness
conda run -n test python report.py --since 2024           # citing papers published in 2024 or later, full detail
conda run -n test python report.py --since 2024 --nolist  # same, counts-only summary table
```

The `--since` filter is by the **citing paper's publication year**, not the date it was scraped.

## Configuration

One constant to set in `report.py`:

```python
EARLIEST_PUB_YEAR = 1977   # your actual earliest publication year
```

This is used to detect impossible citation years (a paper claiming to cite you before you published anything). Don't derive it from the DB — GS may be missing your older papers.

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

`citations_complete: false` means GS cut off the scrape for that paper. Re-running `scholar.py` will resume those automatically.

## Data quality notes

- GS year metadata is unreliable — years on both your papers and citing papers are sometimes wrong.
- GS occasionally mixes references *from* a paper into the list of papers *citing* it.
- The `errors.tsv` written on each `report.py` run captures missing years and years that predate `EARLIEST_PUB_YEAR`.
- GS uses non-breaking spaces (`\xa0`) in its author/venue/year info lines — the scraper normalises these before parsing.
- Scholar ID is hardcoded as `weAbyM4AAAAJ` in `scholar.py`.
