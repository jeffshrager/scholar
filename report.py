#!/usr/bin/env python3
"""
report.py — reporting on the local Google Scholar citation database.

Usage:
  python report.py              # show DB stats
  python report.py --since YEAR # citations by papers published in YEAR or later
  python report.py --since YEAR --nolist  # summary counts only, no individual citations

Every run also writes errors.tsv with suspicious citation records (impossible years, etc.).
"""

import csv
import json
import argparse
from datetime import datetime
from pathlib import Path

DB_FILE    = Path(__file__).parent / "scholar_db.json"
ERRORS_TSV = Path(__file__).parent / "errors.tsv"

# Earliest year you published anything — used to flag impossible citation years.
# GS may not have your oldest papers, so don't derive this from the DB.
EARLIEST_PUB_YEAR = 1977


def load_db():
    if not DB_FILE.exists():
        raise SystemExit(f"Database not found: {DB_FILE}\nRun scholar.py first.")
    return json.loads(DB_FILE.read_text())


# ---------------------------------------------------------------------------
# Error detection
# ---------------------------------------------------------------------------

def find_errors(db):
    """
    Return list of suspicious citation records.
    Suspicious means the citing paper's year is impossible:
      - before the earliest publication year among your own papers, or
      - more than 1 year in the future (GS sometimes assigns wrong future years).
    Also flags citations with no year at all.
    """
    papers = db["papers"]
    citations = db["citations"]

    earliest_yours = EARLIEST_PUB_YEAR
    current_year   = datetime.now().year

    errors = []
    for pid, cites in citations.items():
        your_title = papers.get(pid, {}).get("title", pid)
        your_year  = papers.get(pid, {}).get("year", "")
        for c in cites:
            raw_year = c.get("year", "")
            if not raw_year:
                errors.append({
                    "error":       "missing_year",
                    "your_paper":  your_title,
                    "your_year":   your_year,
                    "citing_title": c.get("title", ""),
                    "citing_year": "",
                    "citing_authors": c.get("authors", ""),
                    "citing_url":  c.get("url", ""),
                })
                continue
            try:
                y = int(raw_year)
            except (ValueError, TypeError):
                errors.append({
                    "error":       "unparseable_year",
                    "your_paper":  your_title,
                    "your_year":   your_year,
                    "citing_title": c.get("title", ""),
                    "citing_year": raw_year,
                    "citing_authors": c.get("authors", ""),
                    "citing_url":  c.get("url", ""),
                })
                continue
            if y < earliest_yours:
                errors.append({
                    "error":       f"year_before_your_earliest_paper_{earliest_yours}",
                    "your_paper":  your_title,
                    "your_year":   your_year,
                    "citing_title": c.get("title", ""),
                    "citing_year": raw_year,
                    "citing_authors": c.get("authors", ""),
                    "citing_url":  c.get("url", ""),
                })
            elif y > current_year + 1:
                errors.append({
                    "error":       f"year_in_future_{current_year}",
                    "your_paper":  your_title,
                    "your_year":   your_year,
                    "citing_title": c.get("title", ""),
                    "citing_year": raw_year,
                    "citing_authors": c.get("authors", ""),
                    "citing_url":  c.get("url", ""),
                })
    return errors


def write_errors_tsv(errors):
    if not errors:
        print(f"(No suspicious citation records found — {ERRORS_TSV.name} not written)")
        return
    fields = ["error", "your_paper", "your_year",
              "citing_title", "citing_year", "citing_authors", "citing_url"]
    with open(ERRORS_TSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(errors)
    # Summary breakdown by error type
    from collections import Counter
    counts = Counter(e["error"] for e in errors)
    print(f"Wrote {len(errors)} suspicious records to {ERRORS_TSV.name}:")
    for kind, n in counts.most_common():
        print(f"  {n:4d}  {kind}")


# ---------------------------------------------------------------------------
# Stats report
# ---------------------------------------------------------------------------

def report_stats(db):
    author    = db.get("author", {})
    papers    = db["papers"]
    citations = db["citations"]

    total_gs     = sum(p["citation_count"] for p in papers.values())
    total_stored = sum(len(v) for v in citations.values())
    complete     = sum(1 for p in papers.values() if p.get("citations_complete"))
    incomplete   = len(papers) - complete

    last_updated = db.get("last_updated", "never")
    if last_updated and last_updated != "never":
        last_updated = datetime.fromisoformat(last_updated).strftime("%Y-%m-%d %H:%M")

    print(f"=== Google Scholar DB Stats ===")
    print(f"Author:          {author.get('name', '?')}  ({author.get('scholar_id', '?')})")
    print(f"Last updated:    {last_updated}")
    print(f"Papers:          {len(papers)}")
    print(f"  fully fetched: {complete}")
    print(f"  incomplete:    {incomplete}  (re-run scholar.py to finish)")
    print(f"Citations (GS):  {total_gs}")
    print(f"Citations (DB):  {total_stored}")
    print()

    rows = []
    for pid, p in papers.items():
        stored = len(citations.get(pid, []))
        rows.append((p["citation_count"], stored,
                     p.get("citations_complete", False),
                     p["title"], p.get("year", "")))
    rows.sort(reverse=True)

    print(f"{'Title':<62} {'Year':>4}  {'GS':>5}  {'DB':>5}  {'Done':>4}")
    print("-" * 85)
    for gs_n, db_n, done, title, year in rows:
        flag = "yes" if done else "no"
        print(f"{title[:62]:<62} {str(year):>4}  {gs_n:>5}  {db_n:>5}  {flag:>4}")


# ---------------------------------------------------------------------------
# Since-year report
# ---------------------------------------------------------------------------

def report_since(db, since_year, nolist=False):
    papers    = db["papers"]
    citations = db["citations"]

    by_paper = {}
    for pid, cites in citations.items():
        new = []
        for c in cites:
            try:
                year = int(c.get("year", 0))
            except (ValueError, TypeError):
                continue
            if year >= since_year:
                new.append(c)
        if new:
            new.sort(key=lambda c: int(c.get("year") or 0), reverse=True)
            by_paper[pid] = new

    if not by_paper:
        print(f"No citations found from {since_year} or later.")
        return

    total = sum(len(v) for v in by_paper.values())
    print(f"=== {total} citation(s) published in {since_year} or later ===")
    print(f"    (across {len(by_paper)} of your paper(s))\n")

    sorted_papers = sorted(by_paper.items(), key=lambda kv: len(kv[1]), reverse=True)

    if nolist:
        print(f"  {'Cites':>5}  {'Pub':>4}  Title")
        print(f"  {'─'*5}  {'─'*4}  {'─'*60}")

    for pid, cites in sorted_papers:
        p          = papers.get(pid, {})
        paper_title = p.get("title", pid)
        pub_year    = p.get("year", "")
        if nolist:
            print(f"  {len(cites):>5}  {str(pub_year):>4}  {paper_title}")
            continue
        print(f"{'=' * 72}")
        print(f"  [{len(cites)} citing]  {paper_title}")
        print(f"  {'─' * 70}")
        for c in cites:
            year_str = c.get("year") or "????"
            print(f"  [{year_str}] {c['title']}")
            if c.get("authors"):
                print(f"          Authors: {c['authors']}")
            if c.get("venue"):
                print(f"          Venue:   {c['venue']}")
            if c.get("url"):
                print(f"          URL:     {c['url']}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Google Scholar citation DB reporter")
    ap.add_argument("--since", metavar="YEAR", type=int,
                    help="Show citing papers published in YEAR or later (e.g. --since 2023)")
    ap.add_argument("--nolist", action="store_true",
                    help="With --since: show per-paper counts only, suppress individual citations")
    args = ap.parse_args()

    db = load_db()

    # Always check for and report data quality errors
    print()
    errors = find_errors(db)
    write_errors_tsv(errors)
    print()

    if args.since:
        report_since(db, args.since, nolist=args.nolist)
    else:
        report_stats(db)


if __name__ == "__main__":
    main()
