#!/usr/bin/env python3
"""
report.py — reporting on the local Google Scholar citation database.

Usage:
  python report.py              # show DB stats
  python report.py --since DATE # citations first seen on or after DATE (YYYY-MM-DD)
"""

import json
import argparse
from datetime import datetime
from pathlib import Path

DB_FILE = Path(__file__).parent / "scholar_db.json"


def load_db():
    if not DB_FILE.exists():
        raise SystemExit(f"Database not found: {DB_FILE}\nRun scholar.py first.")
    return json.loads(DB_FILE.read_text())


# ---------------------------------------------------------------------------
# Stats report
# ---------------------------------------------------------------------------

def report_stats(db):
    author = db.get("author", {})
    papers = db["papers"]
    citations = db["citations"]

    total_gs = sum(p["citation_count"] for p in papers.values())
    total_stored = sum(len(v) for v in citations.values())
    complete = sum(1 for p in papers.values() if p.get("citations_complete"))
    incomplete = len(papers) - complete

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

    # Per-paper table, sorted by GS count descending
    rows = []
    for pid, p in papers.items():
        stored = len(citations.get(pid, []))
        rows.append((p["citation_count"], stored, p.get("citations_complete", False), p["title"], p.get("year", "")))
    rows.sort(reverse=True)

    print(f"{'Title':<62} {'Year':>4}  {'GS':>5}  {'DB':>5}  {'Done':>4}")
    print("-" * 85)
    for gs_n, db_n, done, title, year in rows:
        flag = "yes" if done else "no"
        print(f"{title[:62]:<62} {str(year):>4}  {gs_n:>5}  {db_n:>5}  {flag:>4}")


# ---------------------------------------------------------------------------
# Since-date report
# ---------------------------------------------------------------------------

def report_since(db, since_year, nolist=False):
    papers = db["papers"]
    citations = db["citations"]

    # Gather matching citations grouped by paper, filtered by the citing paper's year
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

    # Sort papers by citation count descending
    sorted_papers = sorted(by_paper.items(), key=lambda kv: len(kv[1]), reverse=True)

    for pid, cites in sorted_papers:
        paper_title = papers.get(pid, {}).get("title", pid)
        if nolist:
            print(f"  {len(cites):4d}  {paper_title}")
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
                    help="With --since: show only the per-paper counts, suppress individual citations")
    args = ap.parse_args()

    db = load_db()

    if args.since:
        report_since(db, args.since, nolist=args.nolist)
    else:
        report_stats(db)


if __name__ == "__main__":
    main()
