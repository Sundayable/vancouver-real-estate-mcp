# Vancouver Real Estate MCP

An MCP server that gives any AI agent 35 years of Metro Vancouver and Fraser
Valley benchmark prices — 1991-06 to 2026-06, 136 areas, 61,034 monthly points.

Everything here is built from public board publications. Aggregate statistics
only: no listings, no individual transactions.

## Layout

```
ingest/     data pipeline (Python)
data/raw/   downloaded sources, gitignored except the small ones
data/out/   parsed + merged output, including the SQLite the server ships
server/     Next.js MCP server, deployed to Vercel
```

## Sources

| Source | Coverage | Granularity |
|---|---|---|
| [CREA MLS® HPI archive](https://www.crea.ca/housing-market-stats/mls-home-price-index/hpi-tool/) | 2005-01 → current | board |
| [GVR monthly stats packages](https://www.gvrealtors.ca/) | 2018-12 → current | neighbourhood |
| [FVREB monthly stats packages](https://www.fvreb.bc.ca/statistics/) | 2008-01 → current | neighbourhood |
| [FVREB HPIMLX database](https://www.fvreb.bc.ca/statistics/HPIMLX_DB.xlsx) | 1991-06 → 2011-09 | neighbourhood, both boards |

## The one thing to understand

The boards have **restated** the MLS® HPI more than once. FVREB publishes the
proof itself — a workbook of "Revised Benchmark Price" against "Original
Benchmark Price". The effects are large:

- the legacy HPIMLX series sits up to ~35% away from the current CREA
  benchmark on their 2005-2011 overlap;
- within a single source, FVREB's own packages jump: Fraser Valley Board reads
  index 223.9 in the June 2010 package and 144.3 in June 2012.

So the sources cannot simply be concatenated. Instead:

1. every source is cut into segments wherever its own month-over-month move
   exceeds 20% (no real market moves that fast — Vancouver's worst months were
   around -5%), which catches restatement boundaries wherever they fall;
2. segments are sorted newest-first, so the most recent data defines the level;
3. each older segment is chain-linked on — by the overlap ratio where the
   segments overlap, by the adjacent-month ratio where they merely abut, and
   across long holes by carrying the wider market's growth over the hole.

Each point records how it was placed:

| basis | meaning | count |
|---|---|---|
| `as_published` | exactly what the board published | 43,222 |
| `chain_linked` | rescaled onto the current index level | 10,676 |
| `bridged` | level inferred across a hole in the record | 7,136 |

Activity data is merged onto 5,348 of those points.

The MCP tools surface this: `*` marks chain-linked, `+` marks estimated.

## Known gaps

- **GVR neighbourhood data before 2018-12 is partial.** The board only serves
  packages back to 2018-12. `discover_wayback.py` recovers 112 more months of
  archived REBGV packages (2012-07 onward), which fills much of the hole —
  2016-08, the month the foreign-buyer tax landed, goes from 32 to 107 of 113
  municipality series. Coverage between 2012 and 2018 is still intermittent,
  roughly every other month in places. Packages older than 2012 exist in the
  archive but predate the tabular HPI layout, so nothing parses out of them.
  Board-level Greater Vancouver is unaffected (CREA covers it continuously
  from 2005).
- **2025-01 and 2025-02 GVR HPI tables.** GVR withdrew them: "a technical error
  in the data feed used for the calculation of the Home Price Index". The
  corrected packages omit the tables, so we leave those months empty.
- **2022-06 GVR package** — no URL found under any known naming pattern.
- FVREB packages before 2015 carry no ten-year change column, since the index
  only began in 2005.

## Rebuilding

```bash
PY="$HOME/Desktop/Claude Code/.venv/bin/python"
cd ingest
$PY -m unittest discover -s tests  # scraper unit tests, no network
$PY fvreb_hpi_db.py      # legacy 1991-2011 (needs data/raw/HPIMLX_DB.xlsx)
$PY crea_hpi.py          # finds and downloads the current CREA archive
$PY discover_gvr.py      # probes GVR PDF URLs -> data/out/gvr_pdf_index.json
$PY discover_wayback.py  # archived REBGV packages covering the pre-2019 gap
$PY boards_pdf.py both   # downloads and parses both boards' packages
$PY boards_activity.py   # sales / listings / inventory from the same PDFs
$PY build.py             # merge + chain-link -> series.jsonl
$PY verify.py            # must print PASS
$PY to_sqlite.py         # -> data/out/vanre.db
cp ../data/out/vanre.db ../server/data/
```

`verify.py` checks the merged series against twelve figures the boards
published themselves, and fails on any month-over-month jump above 20% that
the merge introduced. Jumps already present in the boards' own figures are
reported but do not fail the run — Burnaby South townhouses genuinely read
+21% for 2022-05 in GVR's package, and both independent copies of that
package agree.

### Monthly refresh

`.github/workflows/monthly-update.yml` does this automatically on the 6th of
each month, after both boards have posted and CREA has regenerated its archive.
It only commits and deploys when `verify.py` passes, so a layout change or a
bad merge leaves production serving the last good build and opens an issue
instead. Board PDFs never change once published, so `data/raw` is cached
between runs and only the new month is fetched.

Trigger it by hand with `gh workflow run monthly-update.yml`.

One caveat on reproducing the database byte-for-byte: `pdftotext` output varies
slightly between poppler releases, so a local rebuild can differ from the
runner's by a handful of rows out of ~10,000. The runner is the source of
truth; `verify.py` is what guards quality, not byte equality.

## Server

```bash
cd server
pnpm install
REQUIRE_API_KEY=false pnpm dev     # MCP at http://localhost:3000/mcp
```

Environment:

| var | purpose |
|---|---|
| `API_KEY_SECRET` | required — HMAC secret for issuing/verifying keys |
| `RESEND_API_KEY` | optional — emails the key to the requester |
| `MAIL_FROM` | optional — sender address |
| `NOTIFY_EMAIL` | optional — copy of each issuance |
| `PUBLIC_HOST` | optional — host shown in instructions |
| `REQUIRE_API_KEY` | set `false` to disable auth locally |

Keys are stateless: claims plus an HMAC, so verification needs no database.
The SQLite file is bundled with the deployment and read via Node's built-in
`node:sqlite`, so there is no native module to compile and no database to run.

## Tools

`data_coverage`, `list_areas`, `get_price`, `get_price_history`,
`compare_periods`, `compare_areas`, `rank_areas`, `market_activity`,
`market_extremes`.

## Market activity

Beyond prices, the packages carry sales, new listings and active inventory.
`boards_activity.py` extracts them, and `market_activity` exposes the
sales-to-active-listings ratio the boards themselves cite (under 12% sustained
means downward pressure, over 20% upward).

The two boards print this very differently. FVREB uses a vertical block per
area, which parses cleanly — 2009-01 onward, per area. GVR uses a wide matrix
with area names set vertically, which pdftotext shreds ("Burnab" / "y" on
separate lines); mapping a column back to an area by position would be
guesswork, so only the board total is taken, and only when it reconciles
against the sum of the columns before it.

## Disclaimer

Not affiliated with GVR, FVREB or CREA. Figures are provided as-is for
research; verify against the boards before relying on them for a transaction.
