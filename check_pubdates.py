#!/usr/bin/env python3
"""
check_pubdates.py — find papers whose recorded pub year is AFTER one or more
of their stored citations, which is logically impossible and usually means
Google Scholar has the wrong year for your paper.

Usage:
  python check_pubdates.py            # print flagged papers to stdout
  python check_pubdates.py --tsv      # also write check_pubdates.tsv
  python check_pubdates.py --all      # show every offending citation,
                                      # not just the earliest-cited one
  python check_pubdates.py --tsv --all

For each flagged paper the report shows:
  • your paper's title, its recorded pub year, and its GS citation count
  • the earliest citation that predates it (--all: every such citation)
  • a suggested "pub year ≤ N" correction derived from the earliest offender

Fix workflow:
  1. Look up the paper on Google Scholar.
  2. Find the true publication year.
  3. Edit scholar_db.json — change the "year" field for that paper's entry
     under "papers".  The key is the GS paper ID shown in brackets.
"""

import json
import csv
import argparse
from pathlib import Path

DB_FILE  = Path(__file__).parent / "scholar_db.json"
TSV_FILE = Path(__file__).parent / "check_pubdates.tsv"


def load_db():
    if not DB_FILE.exists():
        raise SystemExit(f"Database not found: {DB_FILE}\nRun scholar.py first.")
    return json.loads(DB_FILE.read_text())


def find_date_inversions(db, all_offenders=False):
    """
    Return a list of dicts, one per (paper, offending-citation) pair.

    Keys:
      paper_id, paper_title, paper_year,
      gs_citation_count, citations_complete,
      cite_title, cite_year, cite_authors, cite_venue, cite_url
    """
    papers    = db["papers"]
    citations = db["citations"]

    rows = []
    for pid, p in papers.items():
        raw_year = p.get("year", "")
        if not raw_year:
            continue
        try:
            pub_year = int(raw_year)
        except (ValueError, TypeError):
            continue

        cites = citations.get(pid, [])
        offenders = []
        for c in cites:
            try:
                cy = int(c.get("year") or 0)
            except (ValueError, TypeError):
                continue
            if cy > 0 and cy < pub_year:
                offenders.append((cy, c))

        if not offenders:
            continue

        offenders.sort(key=lambda t: t[0])   # earliest first

        to_report = offenders if all_offenders else [offenders[0]]
        for cy, c in to_report:
            rows.append({
                "paper_id":           pid,
                "paper_title":        p["title"],
                "paper_year":         pub_year,
                "gs_citation_count":  p.get("citation_count", ""),
                "citations_complete": "yes" if p.get("citations_complete") else "no",
                "earliest_offender":  offenders[0][0],   # always the min, useful in TSV
                "cite_year":          cy,
                "cite_title":         c.get("title", ""),
                "cite_authors":       c.get("authors", ""),
                "cite_venue":         c.get("venue", ""),
                "cite_url":           c.get("url", ""),
            })

    # Sort output: biggest inversion first (pub_year − cite_year)
    rows.sort(key=lambda r: r["paper_year"] - r["cite_year"], reverse=True)
    return rows


def print_report(rows, all_offenders=False):
    # Group by paper for readable display
    seen = {}
    for r in rows:
        seen.setdefault(r["paper_id"], []).append(r)

    if not seen:
        print("No date inversions found — all pub years look consistent with stored citations.")
        return

    n_papers = len(seen)
    n_cites  = len(rows)
    print(f"Found {n_papers} paper(s) with pub year AFTER at least one citation "
          f"({n_cites} offending citation(s) total).\n")

    for pid, group in sorted(seen.items(),
                             key=lambda kv: kv[1][0]["paper_year"] - kv[1][0]["earliest_offender"],
                             reverse=True):
        r0 = group[0]
        inversion = r0["paper_year"] - r0["earliest_offender"]
        complete  = r0["citations_complete"]
        print(f"{'─' * 72}")
        print(f"  PAPER : {r0['paper_title']}")
        print(f"  KEY   : {pid}")
        print(f"  YEAR  : {r0['paper_year']}  "
              f"(GS cites: {r0['gs_citation_count']}, stored complete: {complete})")
        print(f"  FIX   : pub year should be ≤ {r0['earliest_offender']}  "
              f"[inversion = {inversion} yr{'s' if inversion != 1 else ''}]")
        print(f"  {'─' * 70}")
        label = "offending citations" if all_offenders else "earliest offending citation"
        print(f"  {label.upper()}:")
        for r in group:
            print(f"    [{r['cite_year']}] {r['cite_title']}")
            if r["cite_authors"]:
                print(f"           {r['cite_authors']}")
            if r["cite_venue"]:
                print(f"           {r['cite_venue']}")
            if r["cite_url"]:
                print(f"           {r['cite_url']}")
        print()


def write_tsv(rows):
    fields = [
        "inversion_years",
        "paper_year", "paper_title", "paper_id",
        "gs_citation_count", "citations_complete",
        "cite_year", "cite_title", "cite_authors", "cite_venue", "cite_url",
    ]
    # Add derived inversion_years column
    out = []
    for r in rows:
        row = dict(r)
        row["inversion_years"] = r["paper_year"] - r["cite_year"]
        out.append(row)

    with open(TSV_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", delimiter="\t")
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {len(out)} row(s) to {TSV_FILE.name}")


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Scan the scholar DB for papers whose recorded pub year is AFTER one or more "
            "of their stored citations — a logical impossibility that usually means Google "
            "Scholar has the wrong year for your paper. Outputs flagged papers so you can "
            "manually correct the 'year' field in scholar_db.json."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Fix workflow:\n"
            "  1. Look up the flagged paper on Google Scholar.\n"
            "  2. Find the true publication year.\n"
            "  3. Edit scholar_db.json: change the \"year\" field for that paper\n"
            "     under the \"papers\" key (use the GS paper ID shown as KEY).\n"
        ),
    )
    ap.add_argument(
        "--tsv", action="store_true",
        help=f"Write results to {TSV_FILE.name} in addition to stdout",
    )
    ap.add_argument(
        "--all", action="store_true",
        help=(
            "Show every citation that predates the paper's pub year, not just "
            "the earliest one.  Useful when you want to see the full extent of "
            "the problem for a given paper."
        ),
    )
    args = ap.parse_args()

    db   = load_db()
    rows = find_date_inversions(db, all_offenders=args.all)

    print()
    print_report(rows, all_offenders=args.all)

    if args.tsv:
        write_tsv(rows)


if __name__ == "__main__":
    main()
