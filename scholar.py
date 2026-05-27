#!/usr/bin/env python3
"""
Google Scholar citation tracker.
Uses Playwright to drive a real browser — GS has no API and blocks plain HTTP scrapers.

First run fetches all papers and all their citations (slow — may take many minutes).
Subsequent runs only re-scrape papers whose citation count changed.

Usage:
  python scholar.py              # Update DB, show citations from last 30 days
  python scholar.py --days 60    # Show citations from last 60 days
  python scholar.py --full       # Force re-scrape all citations
  python scholar.py --report     # Show report without hitting the network
  python scholar.py --visible    # Show browser window (lets you solve CAPTCHAs manually)
"""

import json
import sys
import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    sys.exit("playwright not installed. Run: pip install playwright && playwright install chromium")

SCHOLAR_ID = "weAbyM4AAAAJ"
DB_FILE     = Path(__file__).parent / "scholar_db.json"
BASE_URL    = "https://scholar.google.com"
NAV_DELAY_MIN   = 5_000   # ms — random delay range after each page load
NAV_DELAY_MAX   = 15_000
CLICK_DELAY_MIN = 5_000   # ms — random delay range after clicking "Show more"
CLICK_DELAY_MAX = 15_000

def nav_delay():
    """Return a random delay (ms) in [NAV_DELAY_MIN, NAV_DELAY_MAX]."""
    return random.randint(NAV_DELAY_MIN, NAV_DELAY_MAX)

def click_delay():
    """Return a random delay (ms) in [CLICK_DELAY_MIN, CLICK_DELAY_MAX]."""
    return random.randint(CLICK_DELAY_MIN, CLICK_DELAY_MAX)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_db():
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {
        "author": {},
        "papers":    {},   # paper_id -> {title, year, citation_count, cite_url, last_checked}
        "citations": {},   # paper_id -> [{title, authors, year, venue, url, first_seen}]
        "last_updated": None,
    }


def save_db(db):
    DB_FILE.write_text(json.dumps(db, indent=2))


def now_str():
    return datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
    window.chrome = {runtime: {}};
"""


def new_context(playwright, headless):
    # Prefer system Chrome — it has a real fingerprint GS won't flag.
    # Falls back to Playwright's Chromium if Chrome isn't installed.
    try:
        browser = playwright.chromium.launch(headless=headless, channel="chrome")
    except Exception:
        browser = playwright.chromium.launch(headless=headless)
    ctx = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    ctx.add_init_script(STEALTH_JS)
    return browser, ctx


CAPTCHA_TIMEOUT = 300_000  # 5 minutes — enough time to solve a CAPTCHA manually


def expect(page, selector, label=""):
    """
    Wait for selector. Prints a prompt the first time so the user knows to
    solve any CAPTCHA visible in the browser window.
    """
    try:
        page.wait_for_selector(selector, timeout=5000)
        return  # fast path — no CAPTCHA
    except PlaywrightTimeout:
        pass

    print(f"\n  [waiting] Solve any CAPTCHA in the browser, then the script will continue automatically ...")
    try:
        page.wait_for_selector(selector, timeout=CAPTCHA_TIMEOUT)
    except PlaywrightTimeout:
        print(f"\nTimed out waiting for '{selector}' on {page.url}")
        print("GS may have blocked the request permanently.")
        if label:
            print(label)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Scraping — author profile
# ---------------------------------------------------------------------------

def scrape_profile(page):
    """
    Load the GS author profile, expand all papers, and return:
      author_name: str
      papers: list of dicts with id, title, year, citation_count, cite_url
    """
    url = f"{BASE_URL}/citations?user={SCHOLAR_ID}&hl=en&sortby=pubdate&pagesize=100"
    print(f"  Loading: {url}")
    page.goto(url)
    expect(page, "#gsc_a_b", "Try --visible so you can solve any CAPTCHA manually.")
    page.wait_for_timeout(nav_delay())

    # Get author name
    name_el = page.query_selector("#gsc_prf_in")
    author_name = name_el.inner_text().strip() if name_el else SCHOLAR_ID

    # Expand full paper list ("Show more" button, may need multiple clicks)
    while True:
        btn = page.query_selector("button#gsc_bpf_more")
        if not btn or not btn.is_enabled():
            break
        btn.click()
        page.wait_for_timeout(click_delay())

    rows = page.query_selector_all("#gsc_a_b .gsc_a_tr")
    papers = []
    for row in rows:
        title_el = row.query_selector(".gsc_a_t a")
        cite_el  = row.query_selector(".gsc_a_c a.gsc_a_ac")
        year_el  = row.query_selector(".gsc_a_y span")

        if not title_el:
            continue

        title = title_el.inner_text().strip()
        href  = title_el.get_attribute("href") or ""

        # Stable paper key extracted from the GS URL parameter
        if "citation_for_view=" in href:
            paper_id = href.split("citation_for_view=")[-1].split("&")[0]
        else:
            paper_id = title[:64]

        raw_count = (cite_el.inner_text().strip() if cite_el else "") or "0"
        try:
            cite_count = int(raw_count)
        except ValueError:
            cite_count = 0

        cite_href = cite_el.get_attribute("href") if cite_el else None
        if cite_href and cite_href.startswith("/"):
            cite_url = BASE_URL + cite_href
        else:
            cite_url = cite_href

        papers.append({
            "id":             paper_id,
            "title":          title,
            "year":           year_el.inner_text().strip() if year_el else "",
            "citation_count": cite_count,
            "cite_url":       cite_url,
        })

    return author_name, papers


# ---------------------------------------------------------------------------
# Scraping — citations for one paper
# ---------------------------------------------------------------------------

def _next_url(page):
    """Return the URL of the 'Next' pagination link, or None."""
    for sel in ["a[aria-label='Next']", "#gs_n a:has-text('Next')", "a.gs_btnPR[aria-label='Next']"]:
        el = page.query_selector(sel)
        if el:
            href = el.get_attribute("href")
            if href:
                return (BASE_URL + href) if href.startswith("/") else href
    # Fall back: look for any link in the pagination area whose text is "Next"
    links = page.query_selector_all("#gs_n a")
    for link in links:
        if "Next" in (link.inner_text() or ""):
            href = link.get_attribute("href")
            if href:
                return (BASE_URL + href) if href.startswith("/") else href
    return None


def _parse_info_line(info):
    """Split 'Authors - Venue, Year' into (authors, venue, year).
    GS uses non-breaking spaces (\xa0) around the hyphen separator."""
    # Normalise: replace non-breaking spaces so the split works reliably
    info = info.replace("\xa0", " ")
    parts = info.split(" - ", 1)
    authors = parts[0].strip()
    venue_year = parts[1].strip() if len(parts) > 1 else ""

    year = ""
    venue = venue_year
    if venue_year:
        tokens = venue_year.rsplit(",", 1)
        candidate = tokens[-1].strip() if len(tokens) > 1 else ""
        if candidate.isdigit() and len(candidate) == 4:
            year = candidate
            venue = tokens[0].strip()

    return authors, venue, year


def scrape_citing_papers(page, cite_url, existing_titles):
    """
    Generator: walks paginated GS cited-by results and yields new citation dicts.
    existing_titles: set of lowercased titles already in the DB (mutated in place).
    """
    url = cite_url
    while url:
        page.goto(url)
        try:
            page.wait_for_selector("#gs_res_ccl_mid, #gs_res_ccl", timeout=5000)
        except PlaywrightTimeout:
            print("    [waiting] Solve any CAPTCHA in the browser ...")
            try:
                page.wait_for_selector("#gs_res_ccl_mid, #gs_res_ccl", timeout=CAPTCHA_TIMEOUT)
            except PlaywrightTimeout:
                print("    Warning: timed out on citations page — stopping here")
                return
        page.wait_for_timeout(nav_delay())

        results = page.query_selector_all("#gs_res_ccl_mid .gs_ri, #gs_res_ccl .gs_ri")
        for result in results:
            title_el = result.query_selector("h3.gs_rt")
            info_el  = result.query_selector(".gs_a")

            if not title_el:
                continue

            a_el  = title_el.query_selector("a")
            title = (a_el or title_el).inner_text().strip()
            # Strip content-type prefixes GS sometimes adds
            for prefix in ("[CITATION]", "[PDF]", "[HTML]", "[BOOK]", "[B]"):
                title = title.replace(prefix, "").strip()

            if not title or title.lower() in existing_titles:
                continue

            link = a_el.get_attribute("href") if a_el else ""
            info = info_el.inner_text().strip() if info_el else ""
            authors, venue, year = _parse_info_line(info)

            existing_titles.add(title.lower())
            yield {
                "title":      title,
                "authors":    authors,
                "year":       year,
                "venue":      venue,
                "url":        link,
                "first_seen": now_str(),
            }

        url = _next_url(page)


# ---------------------------------------------------------------------------
# Main update loop
# ---------------------------------------------------------------------------

def update(db, force_full=False, headless=True):
    with sync_playwright() as pw:
        browser, ctx = new_context(pw, headless)
        page = ctx.new_page()
        try:
            print("Fetching author profile ...")
            author_name, papers = scrape_profile(page)
            db["author"] = {"name": author_name, "scholar_id": SCHOLAR_ID}
            print(f"Found {len(papers)} paper(s) for {author_name}\n")

            for p in papers:
                pid           = p["id"]
                title         = p["title"]
                current_count = p["citation_count"]
                stored_count  = db["papers"].get(pid, {}).get("citation_count", -1)

                already_complete = db["papers"].get(pid, {}).get("citations_complete", False)
                db["papers"][pid] = {
                    "title":              title,
                    "year":               p["year"],
                    "citation_count":     current_count,
                    "cite_url":           p["cite_url"],
                    "last_checked":       now_str(),
                    "citations_complete": already_complete,  # preserved until we finish a full fetch
                }
                db["citations"].setdefault(pid, [])

                if current_count == 0 or not p["cite_url"]:
                    print(f"  [skip]  {title[:65]} (0 citations)")
                    db["papers"][pid]["citations_complete"] = True
                    continue

                # Skip only if count is unchanged AND we previously finished a full fetch
                if not force_full and current_count == stored_count and already_complete:
                    print(f"  [skip]  {title[:65]} ({current_count} citations, unchanged)")
                    continue

                if not force_full and current_count == stored_count and not already_complete:
                    print(f"  [resume] {title[:65]} ({current_count} citations, incomplete last time) ...")
                elif not force_full and current_count != stored_count:
                    print(f"  [fetch] {title[:65]} ({current_count} citations, was {stored_count}) ...")
                else:
                    print(f"  [fetch] {title[:65]} ({current_count} citations) ...")

                existing = {c["title"].lower() for c in db["citations"][pid]}
                new_ones = list(scrape_citing_papers(page, p["cite_url"], existing))
                db["citations"][pid].extend(new_ones)
                db["papers"][pid]["citations_complete"] = True  # mark done only on success
                print(f"          +{len(new_ones)} new citation(s)")

                # Save after each paper so a crash loses minimal work
                save_db(db)

        finally:
            browser.close()

    db["last_updated"] = now_str()
    save_db(db)
    print(f"\nDatabase saved to {DB_FILE}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report(db, days):
    cutoff = datetime.now() - timedelta(days=days)
    recent = []

    for pid, citations in db["citations"].items():
        paper_title = db["papers"].get(pid, {}).get("title", pid)
        for c in citations:
            try:
                seen = datetime.fromisoformat(c["first_seen"])
            except (KeyError, ValueError):
                continue
            if seen >= cutoff:
                recent.append({**c, "cited_paper": paper_title})

    recent.sort(key=lambda x: x["first_seen"], reverse=True)

    if not recent:
        print(f"\nNo new citations found in the last {days} days.")
        return

    print(f"\n=== {len(recent)} citation(s) first seen in the last {days} days ===\n")
    for r in recent:
        date_str = datetime.fromisoformat(r["first_seen"]).strftime("%Y-%m-%d")
        print(f"[{date_str}] {r['title']}")
        if r.get("authors"):
            print(f"  Authors: {r['authors']}")
        if r.get("year"):
            print(f"  Year:    {r['year']}")
        if r.get("venue"):
            print(f"  Venue:   {r['venue']}")
        print(f"  Cites:   {r['cited_paper']}")
        if r.get("url"):
            print(f"  URL:     {r['url']}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Google Scholar citation tracker")
    ap.add_argument("--days", type=int, default=30,
                    help="Days to look back when reporting (default: 30)")
    ap.add_argument("--full",    action="store_true",
                    help="Re-scrape all citations, not just changed papers")
    ap.add_argument("--report",  action="store_true",
                    help="Show report only — skip network update")
    ap.add_argument("--headless", action="store_true",
                    help="Run browser in headless mode (may get blocked by GS)")
    args = ap.parse_args()

    db = load_db()

    if not args.report:
        update(db, force_full=args.full, headless=args.headless)

    report(db, days=args.days)


if __name__ == "__main__":
    main()
