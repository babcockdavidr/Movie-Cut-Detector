#!/usr/bin/env python3
"""
movie_cut_detector.py  —  v1.0.1
--------------------
Scans your Plex movie library, checks each film against TMDb for known
alternate cuts, compares runtimes, then presents a REVIEW STAGE where you
can approve or deselect each proposed Plex label change before anything
is written.

Requirements:
    pip install plexapi requests python-dotenv colorama

Setup (.env file next to this script):
    PLEX_URL=http://localhost:32400
    PLEX_TOKEN=your_plex_token_here
    TMDB_API_KEY=your_tmdb_api_key_here

Get your Plex token : https://support.plex.tv/articles/204059436
Get a TMDb API key  : https://www.themoviedb.org/settings/api  (free)

Usage:
    python movie_cut_detector.py                  # full library
    python movie_cut_detector.py --limit 20       # test on first 20
    python movie_cut_detector.py --library "4K"   # different section name
    python movie_cut_detector.py --no-labels      # report only, skip label stage
    python movie_cut_detector.py --dry-run        # show everything, apply nothing
"""

import os
import sys
import time
import json
import textwrap
import argparse
import requests
from dotenv import load_dotenv

try:
    from plexapi.server import PlexServer
except ImportError:
    raise SystemExit("Missing dependency: run:  pip install plexapi requests python-dotenv colorama")

# ── ANSI colours ──────────────────────────────────────────────────────────────
try:
    import colorama
    colorama.init(autoreset=True)
except ImportError:
    pass

def _c(code, s): return f"\033[{code}m{s}\033[0m"
def bold(s):   return _c("1",       s)
def green(s):  return _c("92",      s)
def yellow(s): return _c("93",      s)
def red(s):    return _c("91",      s)
def cyan(s):   return _c("96",      s)
def dim(s):    return _c("2",       s)
def orange(s): return _c("38;5;214",s)

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()

PLEX_URL     = os.getenv("PLEX_URL",  "http://localhost:32400")
PLEX_TOKEN   = os.getenv("PLEX_TOKEN", "")
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
TMDB_BASE    = "https://api.themoviedb.org/3"

MATCH_THRESHOLD_MIN = 4    # <= 4 min diff  → same cut
ALTERNATE_FLAG_MIN  = 8    # >= 8 min diff  → flag as likely alternate
LARGE_GAP_MIN       = 15   # >= 15 min diff → strong mismatch warning

TMDB_DELAY  = 0.25         # seconds between API calls
OUTPUT_JSON = "movie_cut_report.json"

# Label templates — genuine alternate edit types only.
# "Edition" vs "Cut" suffix is preserved from source text via _derive_label().
LABEL_TEMPLATES = {
    "director's cut":      "Director's Cut",
    "director cut":        "Director's Cut",
    "extended cut":        "Extended Cut",
    "extended edition":    "Extended Edition",
    "unrated cut":         "Unrated Cut",
    "unrated edition":     "Unrated Edition",
    "unrated":             "Unrated Cut",
    "theatrical cut":      "Theatrical Cut",
    "theatrical version":  "Theatrical Cut",
    "final cut":           "Final Cut",
    "ultimate cut":        "Ultimate Cut",
    "ultimate edition":    "Ultimate Edition",
    "redux":               "Redux",
    "workprint":           "Workprint",
    "work print":          "Workprint",
    "complete cut":        "Complete Cut",
    "assembly cut":        "Assembly Cut",
    "producer's cut":      "Producer's Cut",
    "producer cut":        "Producer's Cut",
    "television cut":      "Television Cut",
    "tv cut":              "Television Cut",
    "broadcast cut":       "Television Cut",
}

def _derive_label(kw, raw_text):
    """Preserve 'Edition' or 'Cut' from the raw TMDb text where possible."""
    canonical = LABEL_TEMPLATES[kw]
    rl = raw_text.lower()
    kw_pos  = rl.find(kw)
    context = rl[kw_pos:kw_pos + len(kw) + 25] if kw_pos >= 0 else ""
    ambiguous = {"unrated", "theatrical version", "redux", "workprint", "work print"}
    if kw in ambiguous:
        base = canonical.rsplit(" ", 1)[0]
        if "edition" in context:
            return base + " Edition"
        elif "cut" in context:
            return base + " Cut"
    return canonical
CUT_KEYWORDS = list(LABEL_TEMPLATES.keys())

# All labels we consider "cut" labels (values of LABEL_TEMPLATES + common variants)
# Used to recognise manually-set cut labels already in Plex
ALL_CUT_LABELS = set(LABEL_TEMPLATES.values()) | {
    "Director's Cut", "Extended", "Extended Edition", "Unrated",
    "Unrated Edition", "Theatrical", "Theatrical Cut", "Final Cut",
    "Ultimate Cut", "Ultimate Edition", "Redux", "Complete Cut",
    "Assembly Cut", "Workprint", "Producer's Cut", "Television Cut",
}

# How many minutes a file can differ from TMDb theatrical before we
# call an existing "Theatrical Cut" label suspicious
THEATRICAL_TOLERANCE_MIN = 5

# Runtime ranges (relative to TMDb theatrical) that make an extended/DC label plausible
EXTENDED_LABEL_RANGE = (8, 999)    # file must be longer by at least this many minutes
SHORTER_LABEL_RANGE  = (-999, -8)  # file must be shorter by at least this many minutes


def existing_cut_labels(label_list):
    """Return only the cut-related labels from an existing Plex label list."""
    return [l for l in label_list if l in ALL_CUT_LABELS]


def check_label_plausibility(existing_cut, runtime_diff):
    """
    Given an existing cut label and the runtime diff (plex - tmdb, signed),
    return 'ok', 'suspicious', or 'unknown' (no TMDb runtime to compare).

    Logic:
      - "Theatrical Cut"  → file should be within ±THEATRICAL_TOLERANCE_MIN of TMDb
      - Extended/DC/etc   → file should be longer than TMDb theatrical
      - Shorter cuts      → file should be shorter
      - Labels with no runtime expectation → 'ok' (give benefit of doubt)
    """
    if runtime_diff is None:
        return "unknown"

    lbl = existing_cut.lower()

    if "theatrical" in lbl:
        return "ok" if abs(runtime_diff) <= THEATRICAL_TOLERANCE_MIN else "suspicious"

    if any(k in lbl for k in ("extended", "ultimate", "complete", "assembly", "redux", "director")):
        return "ok" if runtime_diff >= EXTENDED_LABEL_RANGE[0] else "suspicious"

    if any(k in lbl for k in ("international", "unrated")):
        # Could go either way — only flag if the gap is very large
        return "suspicious" if abs(runtime_diff) >= LARGE_GAP_MIN * 2 else "ok"

    # Final Cut, Remastered, Special Edition — hard to judge runtime, be lenient
    return "ok"


# ── Utility ───────────────────────────────────────────────────────────────────

def fmt_runtime(minutes):
    if minutes is None:
        return "?"
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m:02d}m"

def wrap(text, width=72, indent="  "):
    return textwrap.fill(text, width=width,
                         initial_indent=indent, subsequent_indent=indent)

def hr(char="─", width=72):
    print(char * width)


# ── TMDb helpers ──────────────────────────────────────────────────────────────

def get_tmdb_id_from_plex(movie):
    """Read the TMDb ID Plex already has stored for this movie via movie.guids."""
    try:
        for g in movie.guids:
            if g.id.startswith("tmdb://"):
                return int(g.id.split("tmdb://")[1])
    except Exception:
        pass
    return None


def tmdb_search_fallback(title, year):
    """Text search — only used when Plex has no TMDb ID stored."""
    params = {"api_key": TMDB_API_KEY, "query": title, "include_adult": False}
    if year:
        params["year"] = year
    r = requests.get(f"{TMDB_BASE}/search/movie", params=params, timeout=10)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results and year:
        params.pop("year")
        r = requests.get(f"{TMDB_BASE}/search/movie", params=params, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
    return results[0]["id"] if results else None


def tmdb_details(tmdb_id):
    params = {"api_key": TMDB_API_KEY,
              "append_to_response": "release_dates,alternative_titles"}
    r = requests.get(f"{TMDB_BASE}/movie/{tmdb_id}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def extract_edition_hints(details):
    """
    Scan release_date notes + alternative_titles for cut keywords.
    Returns list of {label, source, raw}.
    """
    hints = []
    seen  = set()

    for country in details.get("release_dates", {}).get("results", []):
        for rel in country.get("release_dates", []):
            note = rel.get("note", "").strip()
            if not note:
                continue
            nl = note.lower()
            for kw in LABEL_TEMPLATES:
                if kw in nl:
                    label = _derive_label(kw, note)
                    if label not in seen:
                        seen.add(label)
                        hints.append({
                            "label":  label,
                            "source": f"release note ({country['iso_3166_1']})",
                            "raw":    note,
                        })

    for at in details.get("alternative_titles", {}).get("titles", []):
        t  = at.get("title", "")
        tl = t.lower()
        for kw in LABEL_TEMPLATES:
            if kw in tl:
                label = _derive_label(kw, t)
                if label not in seen:
                    seen.add(label)
                    hints.append({
                        "label":  label,
                        "source": "alt title (" + at.get("iso_3166_1","?") + ")",
                        "raw":    t,
                    })

    return hints


def _guess_label_from_diff(plex_min, tmdb_min):
    """Last-resort guess when no edition hints exist but runtime gap is large."""
    if tmdb_min is None:
        return None
    diff = plex_min - tmdb_min
    if diff >= LARGE_GAP_MIN:
        return "Extended Cut"
    if diff <= -LARGE_GAP_MIN:
        return "Theatrical Cut"
    return None


# ── Phase 1 — Scan ───────────────────────────────────────────────────────────

def scan_library(library_name, limit=0, skip_guids=None):
    print(f"\n{bold('Connecting to Plex')} at {PLEX_URL} …")
    plex    = PlexServer(PLEX_URL, PLEX_TOKEN)
    library = plex.library.section(library_name)
    movies  = library.all()
    if limit:
        movies = movies[:limit]
    total = len(movies)
    print(f"{green('✓')} Found {bold(str(total))} movies in {cyan(repr(library_name))}\n")
    hr()

    results      = []
    plex_objects = {}

    for idx, movie in enumerate(movies, 1):
        if skip_guids and movie.guid in skip_guids:
            continue
        title    = movie.title
        year     = movie.year
        plex_min = round((movie.duration or 0) / 60000, 1)
        guid     = movie.guid

        pad = len(str(total))
        prefix = f"[{idx:>{pad}}/{total}]"
        print(f"{dim(prefix)} {title} ({year})  {dim(fmt_runtime(plex_min))}",
              end="", flush=True)

        all_existing = [lbl.tag for lbl in movie.labels]
        cut_existing = existing_cut_labels(all_existing)

        rec = {
            "guid":               guid,
            "title":              title,
            "year":               year,
            "plex_runtime":       plex_min,
            "tmdb_id":            None,
            "tmdb_runtime":       None,
            "runtime_diff":       None,
            "runtime_status":     "no_tmdb_match",
            "edition_hints":      [],
            "proposed_labels":    [],
            "existing_labels":    all_existing,
            "existing_cut_labels": cut_existing,
            "mislabel_warnings":  [],   # list of {label, reason}
            "flags":              [],
        }
        plex_objects[guid] = movie

        if not TMDB_API_KEY:
            print()
            results.append(rec)
            continue

        try:
            # Use Plex's stored TMDb ID first — avoids wrong-movie mismatches
            tmdb_id = get_tmdb_id_from_plex(movie)
            if not tmdb_id:
                # Fallback to text search for unmatched items
                tmdb_id = tmdb_search_fallback(title, year)
                time.sleep(TMDB_DELAY)

            if not tmdb_id:
                print(f"  {yellow('— no TMDb match')}")
                rec["flags"].append("no_tmdb_match")
                results.append(rec)
                continue

            rec["tmdb_id"] = tmdb_id

            details = tmdb_details(tmdb_id)
            time.sleep(TMDB_DELAY)

            tmdb_runtime = details.get("runtime")
            rec["tmdb_runtime"] = tmdb_runtime

            # Runtime diff classification
            if tmdb_runtime:
                diff = round(abs(plex_min - tmdb_runtime), 1)
                rec["runtime_diff"] = diff
                if diff <= MATCH_THRESHOLD_MIN:
                    rec["runtime_status"] = "match"
                elif diff <= ALTERNATE_FLAG_MIN:
                    rec["runtime_status"] = "close"
                else:
                    rec["runtime_status"] = "different"
                    rec["flags"].append("runtime_mismatch")
                if diff >= LARGE_GAP_MIN:
                    rec["flags"].append("large_gap")
            else:
                rec["runtime_status"] = "no_tmdb_runtime"

            # Edition hints from metadata
            hints = extract_edition_hints(details)
            rec["edition_hints"] = hints
            if hints:
                rec["flags"].append("alternate_cuts_known")

            # ── Signed diff (plex minus tmdb, can be negative) ────────────
            signed_diff = round(plex_min - (tmdb_runtime or plex_min), 1)

            # ── Check plausibility of any existing cut labels ─────────────
            mislabel_warnings = []
            for existing_cut in cut_existing:
                verdict = check_label_plausibility(existing_cut, signed_diff)
                if verdict == "suspicious":
                    reason = (
                        f"label is '{existing_cut}' but runtime diff vs TMDb theatrical "
                        f"is {signed_diff:+.0f}m — doesn't match expected range"
                    )
                    mislabel_warnings.append({"label": existing_cut, "reason": reason})
            rec["mislabel_warnings"] = mislabel_warnings
            if mislabel_warnings:
                rec["flags"].append("possible_mislabel")

            # ── Build proposed label list ─────────────────────────────────
            # Skip:  (a) already has any cut label set manually
            #        (b) label already in existing_labels for any reason
            proposed = []
            if not cut_existing:
                # No manual cut label at all — propose normally
                for hint in hints:
                    lbl = hint["label"]
                    if lbl not in rec["existing_labels"] and lbl not in proposed:
                        proposed.append(lbl)

                # Fallback: infer from runtime gap if no metadata hints
                if rec["runtime_status"] == "different" and not hints:
                    guess = _guess_label_from_diff(plex_min, tmdb_runtime)
                    if guess and guess not in rec["existing_labels"]:
                        proposed.append(guess)
                        rec["flags"].append("label_inferred")
            # else: has existing cut labels → don't propose, only flag mislabels

            rec["proposed_labels"] = proposed

            # ── Console status symbol ──────────────────────────────────────
            if mislabel_warnings:
                sym = red("!")
            elif cut_existing:
                sym = cyan("L")   # L = already Labelled
            else:
                sym = {
                    "match":           green("✓"),
                    "close":           yellow("~"),
                    "different":       red("✗"),
                    "no_tmdb_runtime": dim("?"),
                }.get(rec["runtime_status"], " ")

            diff_str = ""
            if rec["runtime_diff"] is not None:
                sign = "+" if signed_diff >= 0 else "-"
                diff_str = f"  {dim('(' + sign + str(int(rec['runtime_diff'])) + 'm)')}"

            label_str = ""
            if cut_existing:
                label_str = f"  {cyan('[' + ', '.join(cut_existing) + ']')}"
            elif hints:
                label_str = f"  {cyan(', '.join(h['label'] for h in hints[:3]))}"

            warn_str = f"  {red('⚠ possible mislabel')}" if mislabel_warnings else ""
            print(f"  {sym}{diff_str}{label_str}{warn_str}")

        except requests.HTTPError as e:
            print(f"  {red(f'HTTP {e.response.status_code}')}")
            rec["flags"].append(f"tmdb_error:{e.response.status_code}")
        except Exception as e:
            print(f"  {red('error')}: {str(e)[:60]}")
            rec["flags"].append(f"error:{str(e)[:50]}")

        results.append(rec)

    return results, plex_objects


# ── Phase 2 — Review summary ─────────────────────────────────────────────────

def print_review_summary(results):
    actionable        = [r for r in results if r["proposed_labels"]]
    mislabeled        = [r for r in results if r["mislabel_warnings"]]
    already_labelled  = [r for r in results if r["existing_cut_labels"] and not r["mislabel_warnings"]]
    flagged_no_action = [
        r for r in results
        if r["flags"]
        and not r["proposed_labels"]
        and not r["mislabel_warnings"]
        and "no_tmdb_match"     not in r["flags"]
        and "possible_mislabel" not in r["flags"]
    ]

    print()
    hr("═")
    print(bold(" SCAN COMPLETE — PROPOSED CHANGES"))
    hr("═")

    total      = len(results)
    n_action   = len(actionable)
    n_mismatch = sum(1 for r in results if "runtime_mismatch" in r["flags"])
    n_alt      = sum(1 for r in results if "alternate_cuts_known" in r["flags"])
    n_manual   = len(already_labelled)
    n_mislabel = len(mislabeled)
    n_no_match = sum(1 for r in results if "no_tmdb_match" in r["flags"])

    print(f"\n  Movies scanned          : {bold(str(total))}")
    print(f"  Already labelled (kept) : {bold(cyan(str(n_manual)))}")
    print(f"  With proposed labels    : {bold(green(str(n_action)))}")
    print(f"  Possible mislabels      : {bold(red(str(n_mislabel)))}")
    print(f"  Runtime mismatches      : {bold(yellow(str(n_mismatch)))}")
    print(f"  Known alternate cuts    : {bold(cyan(str(n_alt)))}")
    print(f"  No TMDb match           : {dim(str(n_no_match))}")

    # ── Section: Already labelled (informational, no action needed) ───────
    if already_labelled:
        print()
        hr()
        print(bold("  ALREADY LABELLED")
              + dim("  (manually set — skipped, no changes proposed)"))
        hr()
        for r in already_labelled:
            diff_str = ("  " + dim(f"runtime diff: {r['runtime_diff']:+.0f}m") if r["runtime_diff"] is not None else "")
            lbl_str  = cyan(", ".join(r["existing_cut_labels"]))
            print(f"  {r['title']} ({r['year']})  [{lbl_str}]"
                  f"  {dim(fmt_runtime(r['plex_runtime']))}{diff_str}")
        print()

    # ── Section: Possible mislabels ───────────────────────────────────────
    if mislabeled:
        print()
        hr()
        print(bold("  ⚠  POSSIBLE MISLABELS")
              + dim("  (existing label doesn't match runtime — verify manually)"))
        hr()
        for r in mislabeled:
            print(f"\n  {bold(r['title'])} ({r['year']})"
                  f"  Plex: {fmt_runtime(r['plex_runtime'])}"
                  f"  TMDb theatrical: {fmt_runtime(r['tmdb_runtime'])}")
            for w in r["mislabel_warnings"]:
                print(f"    {red('⚠')}  Label: {bold(orange(w['label']))}")
                print(f"       {dim(w['reason'])}")
            if r["tmdb_id"]:
                tmdb_url = f"https://www.themoviedb.org/movie/{r['tmdb_id']}"
        print()

    if not actionable:
        if mislabeled:
            print(f"\n{yellow('  No new labels to add.')}"
                  f"  {red(str(len(mislabeled)))} possible mislabel(s) listed above.\n")
        else:
            print(f"\n{green('  Nothing to label.')}  All movies look good.\n")
        return []

    print()
    hr()
    print(bold("  PROPOSED LABEL ADDITIONS"))
    print(dim("  All items pre-selected ✓  |  Enter numbers to deselect"))
    hr()
    print()

    items = []   # (display_index, rec, label)
    i = 1

    for rec in actionable:
        rt_tmdb  = rec["tmdb_runtime"]
        rt_plex  = rec["plex_runtime"]
        diff_str = ""
        if rec["runtime_diff"] is not None:
            sign = "+" if rt_plex > (rt_tmdb or 0) else "-"
            colour = red if rec["runtime_diff"] >= LARGE_GAP_MIN else yellow
            diff_str = "  " + colour(sign + str(int(rec["runtime_diff"])) + "m diff")

        print(f"  {bold(rec['title'])} ({rec['year']})"
              f"  {dim('Plex:')} {fmt_runtime(rt_plex)}"
              f"  {dim('TMDb:')} {fmt_runtime(rt_tmdb)}"
              f"{diff_str}")

        non_cut = [l for l in rec["existing_labels"] if l not in ALL_CUT_LABELS]
        if non_cut:
            print(f"  {dim('Other labels: ' + ', '.join(non_cut))}")

        for lbl in rec["proposed_labels"]:
            src  = next((h["source"] for h in rec["edition_hints"] if h["label"] == lbl),
                        "runtime inference")
            raw  = next((h["raw"]    for h in rec["edition_hints"] if h["label"] == lbl), "")
            raw_str = f"  {dim(repr(raw))}" if raw and raw.lower() != lbl.lower() else ""
            print(f"    [{bold(green(str(i)))}] {green('✓')}  "
                  f"{bold(orange(lbl))}  {dim(f'← {src}')}{raw_str}")
            items.append((i, rec, lbl))
            i += 1

        print()

    # Manual review section (flagged but no label proposed)
    if flagged_no_action:
        hr()
        print(bold("  MANUAL REVIEW SUGGESTED")
              + dim("  (flagged but no label inferred — check these yourself)"))
        hr()
        for rec in flagged_no_action:
            flags    = ", ".join(rec["flags"])
            diff_str = f"  diff: {rec['runtime_diff']}m" if rec["runtime_diff"] else ""
            print(f"  {rec['title']} ({rec['year']})  {dim(flags)}{diff_str}")
            if rec["tmdb_id"]:
                tmdb_url = f"https://www.themoviedb.org/movie/{r['tmdb_id']}"
        print()

    return items


# ── Phase 3 — Interactive selection ──────────────────────────────────────────

def interactive_review(items):
    """
    Returns a set of (guid, label) pairs the user approved.
    All items start pre-approved; user deselects by number.
    """
    if not items:
        return set()

    approved = {(it[1]["guid"], it[2]) for it in items}

    hr()
    print(bold("  CONFIRM CHANGES"))
    hr()
    print()
    print(wrap(
        "Press ENTER to apply ALL proposed labels as shown above.  "
        "Or type item numbers to DESELECT (space or comma separated), "
        "then press ENTER again to confirm.  "
        "Type  NONE  to cancel everything and quit without applying.",
        indent="  "
    ))
    print()

    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{yellow('  Interrupted — nothing applied.')}")
            sys.exit(0)

        if raw == "":
            # Confirm current state
            n = len(approved)
            if n == 0:
                print(f"\n  {yellow('Nothing selected. Exiting.')}")
            else:
                print(f"\n  {green(f'✓  {n} label(s) will be applied.')}")
            break

        if raw.upper() == "NONE":
            approved = set()
            print(f"\n  {yellow('Cancelled — nothing will be applied.')}")
            break

        raw_nums = raw.replace(",", " ").split()
        try:
            to_toggle = {int(n) for n in raw_nums}
        except ValueError:
            print(f"  {red('Invalid.')} Enter numbers, ENTER to confirm, or NONE to cancel.")
            continue

        unknown = to_toggle - {it[0] for it in items}
        if unknown:
            print(f"  {yellow('Unknown numbers:')} {sorted(unknown)}. Valid range: 1–{items[-1][0]}")
            continue

        for num in sorted(to_toggle):
            it  = next(x for x in items if x[0] == num)
            key = (it[1]["guid"], it[2])
            if key in approved:
                approved.discard(key)
                desc = f"{it[2]}  — {it[1]["title"]} ({it[1]["year"]})" 
                print(f"  {dim("[" + str(num) + "]")} {red(chr(10006) + "  deselected")}  {desc}")
            else:
                approved.add(key)
                desc = f"{it[2]}  — {it[1]["title"]} ({it[1]["year"]})" 
                print(f"  {dim("[" + str(num) + "]")} {green(chr(10004) + "  re-selected")}  {desc}")

        print()
        n_on  = len(approved)
        n_off = len(items) - n_on
        print(f"  {green(str(n_on))} selected  |  {red(str(n_off))} deselected")
        print(wrap("Enter more numbers to toggle, or press ENTER to confirm.", indent="  "))

    return approved


# ── Phase 4 — Apply labels ────────────────────────────────────────────────────

def apply_labels(approved, items, plex_objects, dry_run=False):
    if not approved:
        return

    print()
    hr()
    tag = f"  {bold('DRY RUN')} — " if dry_run else "  "
    print(f"{tag}{bold('WRITING LABELS TO PLEX')}")
    hr()

    # Group by movie
    by_guid = {}
    for (guid, label) in approved:
        by_guid.setdefault(guid, []).append(label)

    success = errors = 0

    for guid, labels in by_guid.items():
        movie      = plex_objects[guid]
        label_str  = "  +  ".join(orange(l) for l in labels)
        print(f"\n  {bold(movie.title)} ({movie.year})")
        print(f"    {label_str}")

        if dry_run:
            print(f"    {dim('[dry-run — no change made]')}")
            success += len(labels)
            continue

        try:
            for lbl in labels:
                movie.addLabel(lbl)
            movie.reload()
            confirmed = {l.tag for l in movie.labels}
            for lbl in labels:
                if lbl in confirmed:
                    print(f"    {green('✓')} {lbl}")
                else:
                    print(f"    {yellow('?')} {lbl}  {dim('(not confirmed after reload)')}")
            success += len(labels)
        except Exception as e:
            print(f"    {red('ERROR:')} {e}")
            errors += len(labels)

    print()
    hr()
    result_str  = green(f"✓  {success} label(s) applied")
    error_str   = f"   {red(f'{errors} error(s)')}" if errors else ""
    dry_str     = f"   {dim('(dry-run — nothing actually written)')}" if dry_run else ""
    print(f"  {result_str}{error_str}{dry_str}")


# ── Save JSON report ──────────────────────────────────────────────────────────

def save_report(results, incremental=False, previously_scanned=None):
    if incremental and previously_scanned and os.path.exists(OUTPUT_JSON):
        try:
            with open(OUTPUT_JSON, encoding="utf-8") as f:
                prev = json.load(f)
            new_guids = {r["guid"] for r in results}
            merged = [r for r in prev if r.get("guid") not in new_guids] + results
            with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
            print(f"\n  {dim(f'Report merged → {OUTPUT_JSON} ({len(merged)} records)')}")
            return
        except Exception:
            pass
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  {dim(f'Full report saved → {OUTPUT_JSON}')}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Detect alternate movie cuts in Plex and apply labels interactively."
    )
    parser.add_argument("--library",   default="Movies",
                        help="Plex library section name (default: Movies)")
    parser.add_argument("--limit",     type=int, default=0,
                        help="Only scan first N movies — useful for testing")
    parser.add_argument("--no-labels", action="store_true",
                        help="Report only — skip the label apply stage entirely")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Show all proposed changes but write nothing to Plex")
    parser.add_argument("--incremental", action="store_true",
                        help="Skip movies already in movie_cut_report.json")
    parser.add_argument("--all-libraries", action="store_true",
                        help="Scan all movie libraries on the server")
    args = parser.parse_args()

    if not PLEX_TOKEN:
        raise SystemExit(red("ERROR: Set PLEX_TOKEN in your .env file"))
    if not TMDB_API_KEY:
        print(yellow("Warning: TMDB_API_KEY not set — runtime comparison disabled.\n"))

    # ── 1. Scan ────────────────────────────────────────────────────────────
    results, plex_objects = scan_library(args.library, limit=args.limit)

    # ── 2. Review summary ──────────────────────────────────────────────────
    items = print_review_summary(results)

    save_report(results, incremental=args.incremental,
                previously_scanned=previously_scanned)

    if args.no_labels or not items:
        print()
        return

    # ── 3. Interactive selection ───────────────────────────────────────────
    approved = interactive_review(items)

    # ── 4. Apply ───────────────────────────────────────────────────────────
    apply_labels(approved, items, plex_objects, dry_run=args.dry_run)

    print()


if __name__ == "__main__":
    main()
