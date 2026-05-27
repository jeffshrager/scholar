#!/usr/bin/env python3
"""
report.py — reporting on the local Google Scholar citation database.

Usage:
  python report.py              # show DB stats
  python report.py --since YEAR # citations by papers published in YEAR or later
  python report.py --since YEAR --nolist  # summary counts only, no individual citations
  python report.py --hist       # horizontal-bar histogram, sorted by --sortby

Every run (except --hist) also writes errors.tsv with suspicious citation records
(impossible years, etc.).
"""

import csv
import json
import shutil
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
# Sorting helpers
# ---------------------------------------------------------------------------

def get_sort_key(sortby, paper, cites, frequency_count=None):
    """
    Return a numeric sort key (higher → ranked first).

    sortby choices:
      frequency   — total citation count (frequency_count if supplied, else len(cites))
      recency     — most recent citation year
      distance    — max(cite_year) − pub_year  [crude longevity]
      centroid    — mean(cite_years) − pub_year  [where citations cluster in time]
      longevity   — max(cite_year) − min(cite_year)  [how long in circulation]
      latebloomer — median(cite_years) − pub_year  [delayed recognition]
      momentum    — recency-weighted mean(cite_year) − pub_year; each citation is
                    weighted by its own distance from pub_year, so recent citations
                    count more than early ones

    Papers/cites with no usable years sort to the bottom (key = -1).
    """
    if sortby == "frequency":
        return frequency_count if frequency_count is not None else len(cites)

    # Collect valid citation years
    years = []
    for c in cites:
        try:
            y = int(c.get("year") or 0)
            if y > 0:
                years.append(y)
        except (ValueError, TypeError):
            pass

    if not years:
        return -1

    # Parse pub year once (used by several metrics)
    try:
        pub_year = int(paper.get("year") or 0)
    except (ValueError, TypeError):
        pub_year = 0

    if sortby == "recency":
        return max(years)

    if sortby == "distance":
        return (max(years) - pub_year) if pub_year > 0 else -1

    if sortby == "centroid":
        mean_year = sum(years) / len(years)
        return (mean_year - pub_year) if pub_year > 0 else mean_year

    if sortby == "longevity":
        return max(years) - min(years)

    if sortby == "latebloomer":
        sy = sorted(years)
        n  = len(sy)
        median = (sy[n // 2 - 1] + sy[n // 2]) / 2 if n % 2 == 0 else sy[n // 2]
        return (median - pub_year) if pub_year > 0 else median

    if sortby == "momentum":
        # Weight each citation by (cite_year − pub_year), floor 1.
        # Papers whose recent citations dominate score highest.
        base = pub_year if pub_year > 0 else min(years)
        weights = [max(y - base, 1) for y in years]
        w_mean  = sum(y * w for y, w in zip(years, weights)) / sum(weights)
        return (w_mean - pub_year) if pub_year > 0 else w_mean

    # Fallback
    return frequency_count if frequency_count is not None else len(cites)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_score(v):
    """Format a sort-key score: integer if whole, else one decimal place."""
    try:
        if v == int(v):
            return str(int(v))
    except (TypeError, ValueError, OverflowError):
        pass
    return f"{v:.1f}"


# ---------------------------------------------------------------------------
# Stats report
# ---------------------------------------------------------------------------

def report_stats(db, sortby="frequency"):
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
    print(f"Sorted by:       {sortby}")
    print()

    rows = []
    for pid, p in papers.items():
        stored    = len(citations.get(pid, []))
        sort_key  = get_sort_key(sortby, p, citations.get(pid, []),
                                 frequency_count=p.get("citation_count", 0))
        rows.append((sort_key, p.get("citation_count", 0), stored,
                     p.get("citations_complete", False),
                     p["title"], p.get("year", "")))
    rows.sort(key=lambda r: r[0], reverse=True)

    show_score = sortby != "frequency"
    if show_score:
        print(f"{'Title':<62} {'Year':>4}  {'GS':>5}  {'DB':>5}  {'Done':>4}  {sortby[:8]:>8}")
        print("-" * 96)
    else:
        print(f"{'Title':<62} {'Year':>4}  {'GS':>5}  {'DB':>5}  {'Done':>4}")
        print("-" * 85)
    for key, gs_n, db_n, done, title, year in rows:
        flag = "yes" if done else "no"
        if show_score:
            score_str = fmt_score(key) if key >= 0 else "n/a"
            print(f"{title[:62]:<62} {str(year):>4}  {gs_n:>5}  {db_n:>5}  {flag:>4}  {score_str:>8}")
        else:
            print(f"{title[:62]:<62} {str(year):>4}  {gs_n:>5}  {db_n:>5}  {flag:>4}")


# ---------------------------------------------------------------------------
# Since-year report
# ---------------------------------------------------------------------------

def report_since(db, since_year, nolist=False, sortby="frequency"):
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
    print(f"    (across {len(by_paper)} of your paper(s))  [sorted by: {sortby}]\n")

    show_score = sortby != "frequency"

    # Pre-compute sort keys so we can display them
    sorted_papers = []
    for pid, cites in by_paper.items():
        sk = get_sort_key(sortby, papers.get(pid, {}), cites, frequency_count=len(cites))
        sorted_papers.append((sk, pid, cites))
    sorted_papers.sort(key=lambda t: t[0], reverse=True)

    if nolist:
        if show_score:
            print(f"  {'Cites':>5}  {sortby[:8]:>8}  {'Pub':>4}  Title")
            print(f"  {'─'*5}  {'─'*8}  {'─'*4}  {'─'*60}")
        else:
            print(f"  {'Cites':>5}  {'Pub':>4}  Title")
            print(f"  {'─'*5}  {'─'*4}  {'─'*60}")

    for sk, pid, cites in sorted_papers:
        p          = papers.get(pid, {})
        paper_title = p.get("title", pid)
        pub_year    = p.get("year", "")
        score_str  = (fmt_score(sk) if sk >= 0 else "n/a") if show_score else None
        if nolist:
            if show_score:
                print(f"  {len(cites):>5}  {score_str:>8}  {str(pub_year):>4}  {paper_title}")
            else:
                print(f"  {len(cites):>5}  {str(pub_year):>4}  {paper_title}")
            continue
        print(f"{'=' * 72}")
        if show_score:
            print(f"  [{len(cites)} citing | {sortby}: {score_str}]  {paper_title}")
        else:
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
# Histogram report
# ---------------------------------------------------------------------------

def report_hist(db, sortby="frequency"):
    """
    Print a horizontal-bar histogram: one row per paper, bars proportional to
    GS citation count, papers ordered top→bottom by the chosen sortby metric.
    """
    papers    = db["papers"]
    citations = db["citations"]

    rows = []
    for pid, p in papers.items():
        gs_count = p.get("citation_count", 0) or 0
        sort_key = get_sort_key(sortby, p, citations.get(pid, []),
                                frequency_count=gs_count)
        rows.append((sort_key, gs_count, p.get("title", pid), p.get("year", "")))
    rows.sort(key=lambda r: r[0], reverse=True)

    if not rows:
        print("No papers in database.")
        return

    max_gs = max(r[1] for r in rows) or 1

    try:
        term_width = shutil.get_terminal_size((100, 24)).columns
    except Exception:
        term_width = 100

    show_score = sortby != "frequency"
    score_w    = max(len(sortby), 5) if show_score else 0  # column width for score

    BAR_CHAR  = "█"
    BAR_MAX   = max(10, min(50, term_width // 2))
    count_w   = len(str(max_gs))          # width of the citation-count field
    # title gets whatever is left after bar + spaces + count + (score col) + spaces
    extra     = (score_w + 2) if show_score else 0
    title_w   = max(10, term_width - BAR_MAX - count_w - 4 - extra)

    author = db.get("author", {})
    print(f"Citation histogram — {author.get('name', '?')}  "
          f"[sorted by: {sortby}]")
    print()

    for key, gs_count, title, year in rows:
        bar_len   = round(gs_count / max_gs * BAR_MAX)
        bar       = BAR_CHAR * bar_len
        year_tag  = f" ({year})" if year else ""
        label     = (title + year_tag)[:title_w]
        if show_score:
            score_str = fmt_score(key) if key >= 0 else "n/a"
            print(f"{bar:<{BAR_MAX}}  {gs_count:{count_w}d}  {score_str:>{score_w}}  {label}")
        else:
            print(f"{bar:<{BAR_MAX}}  {gs_count:{count_w}d}  {label}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Google Scholar citation DB reporter")
    ap.add_argument("--since", metavar="YEAR", type=int,
                    help="Show citing papers published in YEAR or later (e.g. --since 2023)")
    ap.add_argument("--nolist", action="store_true",
                    help="With --since: show per-paper counts only, suppress individual citations")
    ap.add_argument("--hist", action="store_true",
                    help="Display a horizontal-bar histogram ranked by --sortby (no other output)")
    ap.add_argument(
        "--sortby",
        choices=["frequency", "recency", "distance",
                 "centroid", "longevity", "latebloomer", "momentum"],
        default="frequency",
        metavar="METRIC",
        help=(
            "How to rank papers in the report (default: frequency).\n"
            "For any metric other than 'frequency', the computed score is\n"
            "displayed alongside the citation count in every report mode.\n\n"
            "  frequency   — total citation count (GS number in stats mode,\n"
            "                filtered count in --since mode); score column\n"
            "                omitted since count IS the score\n\n"
            "  recency     — year of the most recent stored citation\n\n"
            "  distance    — most_recent_cite_year minus pub_year; raw longevity\n"
            "                signal, but one stray late cite dominates\n\n"
            "  centroid    — mean(cite_years) minus pub_year; shows where the\n"
            "                centre of citation mass actually sits in time\n\n"
            "  longevity   — most_recent_cite_year minus first_cite_year;\n"
            "                how long the paper has stayed in circulation,\n"
            "                independent of pub date\n\n"
            "  latebloomer — median(cite_years) minus pub_year; rewards papers\n"
            "                where the majority of attention arrived late\n\n"
            "  momentum    — recency-weighted mean(cite_years) minus pub_year;\n"
            "                each citation is weighted by its own distance from\n"
            "                pub_year, so a cluster of recent cites scores much\n"
            "                higher than an equal-sized early cluster\n\n"
            "Choices: frequency | recency | distance | centroid |\n"
            "         longevity | latebloomer | momentum"
        ),
    )
    args = ap.parse_args()

    db = load_db()

    if args.hist:
        report_hist(db, sortby=args.sortby)
        return

    # Always check for and report data quality errors
    print()
    errors = find_errors(db)
    write_errors_tsv(errors)
    print()

    if args.since:
        report_since(db, args.since, nolist=args.nolist, sortby=args.sortby)
    else:
        report_stats(db, sortby=args.sortby)


if __name__ == "__main__":
    main()
