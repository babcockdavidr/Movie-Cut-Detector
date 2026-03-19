# Movie Cut Detector — for Plex
### Identify and label alternate cuts of films in your Plex library — no filename editing required.

**v1.0.2** · Python 3.10+ · Windows GUI + Cross-platform CLI · MIT License

---

## What it does

Movie Cut Detector scans your Plex movie library, cross-references each film against [The Movie Database (TMDb)](https://www.themoviedb.org/), and identifies movies where your file's runtime suggests you have a Director's Cut, Extended Edition, Unrated Cut, or other alternate edit of the film — not the standard theatrical release.

When it finds a likely match, it writes that information directly to Plex's built-in `editionTitle` metadata field. That's the field that displays as the edition badge on movie posters in Plex Web and Plex apps:

```
Aliens (1986)
┌─────────────────────────────┐
│  🎬  Aliens                 │
│  ─────────────────────────  │
│  Director's Cut             │  ← this badge
└─────────────────────────────┘
```

No file renaming. No YAML configuration. No Docker containers. Connect, scan, review, apply.

---

## Who this is for

If you've been using Plex for years and have a library full of movies that you know include extended cuts, director's cuts, and unrated versions — but you never went back and added `{edition-Director's Cut}` to the filenames — this tool is for you.

Most Plex users don't rename their files with inline edition tags. Life's too short. If your copy of *Aliens* is called `Aliens.1986.BluRay.mkv` and it's 17 minutes longer than the theatrical cut, Plex has no idea it's the Director's Cut and shows nothing. Movie Cut Detector figures that out for you.

---

## How it's different from Edition Manager

There are a couple of excellent tools in this space, and it's worth being clear about what each one does.

**[Edition Manager for Plex](https://github.com/x1ao4/plex-edition-manager)** and **[Entree3k's Edition Manager](https://github.com/Entree3k/edition-manager)** are powerful tools that write technical metadata — resolution, codec, HDR format, content rating, bitrate, and more — into the edition field. They're great for people who want their library to display something like:

```
2160p · Dolby Vision · TrueHD Atmos · REMUX
```

Those tools work by reading technical properties from your file and the Plex database. They don't try to identify *which cut of the film* you have. And importantly, they can search for cut version information through filenames or movie metadata, but this works best when the edition information is already encoded in the filename.

**Movie Cut Detector is different.** It ignores technical file properties entirely and focuses on one question: *is this the theatrical cut, or is it something else?*

It does this by:
1. Reading the TMDb ID that Plex already matched to your movie
2. Fetching that movie's release history and alternative title metadata from TMDb
3. Comparing your file's actual runtime against TMDb's theatrical runtime
4. Cross-referencing runtime differences with known edition labels found in release notes and alternative titles

This means it works on files named anything — `movie.mkv`, `Aliens.1986.BluRay.mkv`, or anything else. If your file is 17 minutes longer than the theatrical cut and TMDb's release notes reference a "Director's Cut," it'll propose that label.

| | Movie Cut Detector | Edition Manager |
|---|---|---|
| **Purpose** | Identify which *cut* of a film you have | Display technical specs of your file |
| **Data source** | TMDb runtime + release metadata | File metadata, Plex database |
| **Requires filename tags** | No | Recommended for best results |
| **What it writes** | `Director's Cut`, `Extended Edition`, etc. | `2160p · DV · TrueHD`, etc. |
| **Review before applying** | Yes — full interactive UI | Automated |
| **Undo support** | Yes — Remove Editions tab | Reset command |

They're complementary, not competing. You can use both. Run Movie Cut Detector first to identify cuts, then use Edition Manager if you want technical specs appended.

---

## Features

- **Windows GUI** with a dark Plex-inspired interface — no terminal required for everyday use
- **Cross-platform CLI** for Linux, macOS, and Windows PowerShell — scriptable and automatable
- **Two-stage detection** — runtime comparison + TMDb metadata scan (release notes, alternative titles)
- **Plex GUID matching** — uses the TMDb ID Plex already has stored, not a text search, so The Lion King (2019) will never accidentally match the 1994 original
- **Interactive review** — all proposed changes are shown before anything is written; approve all, select individually, or deselect specific items
- **Multi-option handling** — when TMDb finds more than one possible cut label for a film, those movies are separated into a review section; only one label can be selected per movie
- **Mutual exclusion** — selecting one cut label for a movie automatically deselects any others
- **Existing edition detection** — movies that already have an `editionTitle` set are hidden from the main results by default and shown separately to prevent accidental overwrites
- **Remove Editions tab** — review and clear edition tags you've previously applied
- **Export CSV** — export a full spreadsheet of scan results for auditing or sharing
- **Incremental scanning** — after an initial full scan, subsequent runs skip already-processed movies and only check new additions
- **Ignore list** — permanently hide specific movies from results with a `✕ Ignore` button; stored in `movie_cut_ignore.json` and reversible at any time
- **Live scan stats** — real-time counters for proposed changes, existing editions, and errors during scanning
- **ETA** — rolling estimated time remaining based on the last 10–20 movies processed
- **Debug log** — step-by-step connection and lookup output, opens automatically for the Remove Editions tab
- **Dry run mode** — simulate everything without writing anything to Plex

---

## Quick start

### Requirements
- Python 3.10 or newer
- A Plex Media Server (local or remote)
- A free [TMDb API key](https://www.themoviedb.org/settings/api)

### Install
```bash
pip install plexapi requests python-dotenv colorama
```

### Configure
Create a `.env` file next to the scripts:
```
PLEX_URL=http://localhost:32400
PLEX_TOKEN=your_token_here
TMDB_API_KEY=your_tmdb_key_here
```

**Finding your Plex Token:** Sign in to Plex Web → browse to any movie → click `...` → Get Info → View XML → look in the URL bar for `?X-Plex-Token=...`

Full guide: https://support.plex.tv/articles/204059436

### Run (CLI)
```bash
# Test on 20 movies first
python movie_cut_detector.py --limit 20 --dry-run

# Full scan
python movie_cut_detector.py

# Only scan movies added since last run
python movie_cut_detector.py --incremental
```

### Run (Windows GUI)
```
python movie_cut_detector_gui.py
```

Or build a standalone `.exe`:
```
build.bat
```
The `.exe` will appear in `dist\MovieCutDetector.exe` — no Python required on the end user's machine.

---

## How the detection works

Detection uses a two-stage approach:

**Stage 1 — Runtime comparison**
Your file's duration is compared against TMDb's theatrical runtime. A difference of 8+ minutes triggers a flag. A large positive difference (+15 min or more) is a strong signal for an extended or director's cut. A large negative difference suggests a TV cut or theatrical version shorter than your file.

**Stage 2 — Metadata scan**
TMDb's release date notes and alternative titles are scanned for known cut keywords. The label name preserves whatever word TMDb uses — "Extended Edition" stays "Extended Edition" rather than being renamed to "Extended Cut."

**Keyword list:**
`Director's Cut` · `Extended Cut` · `Extended Edition` · `Unrated Cut` · `Unrated Edition` · `Theatrical Cut` · `Final Cut` · `Ultimate Cut` · `Ultimate Edition` · `Redux` · `Workprint` · `Complete Cut` · `Assembly Cut` · `Producer's Cut` · `Television Cut`

Intentionally excluded: International Cut, Special Edition, Remastered — these appear too broadly in TMDb metadata (film festival notes, Blu-ray marketing) and rarely indicate a genuinely different edit.

---

## Files

| File | Description |
|---|---|
| `movie_cut_detector.py` | CLI script — cross-platform, fully interactive |
| `movie_cut_detector_gui.py` | Windows GUI — run directly or compile to `.exe` |
| `build.bat` | One-click PyInstaller builder for the `.exe` |
| `movie_cut_report.json` | Saved after each scan — full record of every movie processed |
| `movie_cut_ignore.json` | Persistent ignore list — movies to skip in future scans |
| `.env` | Your credentials — created automatically on first run |

---

## Important notes

- **This tool is not affiliated with or endorsed by Plex Inc. or The Movie Database.**
- Plex Pass is required for the `editionTitle` field to display in the Plex UI. On servers without Plex Pass, the tool will fall back to writing a Plex label tag instead.
- Always run with `--dry-run` first on a new installation to preview changes before applying them.
- TMDb's database does not store per-edition runtimes. Detection is based on runtime inference and metadata clues, not a direct lookup. Results should be reviewed before applying.
- The tool reads the TMDb ID that Plex already has stored for each movie (via `movie.guids`), rather than doing a text search. This significantly improves accuracy for remakes and films with similar titles.

---

## Contributing

Issues and pull requests are welcome. Some areas that would benefit from contribution:

- Additional cut keyword coverage for non-English TMDb metadata
- IMDb runtime cross-reference to reduce false positives
- Confidence scoring for proposed labels
- macOS/Linux GUI wrapper (currently CLI-only on those platforms)
- Scheduled / headless mode for automated scanning with notification support

---

## License

MIT License. See `LICENSE` for details.

Not affiliated with or endorsed by Plex Inc. or The Movie Database (TMDb).
