# Codeforces problem-solving dashboard — browser edition

A **stlite** build of the dashboard. Python and Streamlit run entirely in the
browser through Pyodide/WebAssembly, and the static files can be hosted on
GitHub Pages.

It plots:

- **X axis:** problems solved
- **Y axis:** contest rating
- **Colour:** Codeforces rank tier or profile, depending on the display mode

The app calls the public Codeforces API directly from the browser. No server,
login, or API key is required.

![Single-profile dashboard](output/app_screenshot.png)

## Live deployments

| Version | URL | Runtime |
| --- | --- | --- |
| **stlite** (this branch) | https://adithya-pdf.github.io/cfgraph/ | Static GitHub Pages, Python runs in the browser via Pyodide |
| **Streamlit** | https://q-solved-vs-rating-plot-cf.streamlit.app/ | Python server on Streamlit Community Cloud |

The stlite build requires no server. The Streamlit build is the server-hosted
version on the `main` branch.

## Run locally

Because the browser fetches the Python source files, serve the directory rather
than opening `index.html` directly:

```powershell
python -m http.server 8502
```

Then open:

```text
http://localhost:8502
```

The first load downloads the Pyodide runtime and Python packages, so it is
noticeably slower than later visits. If the sidebar is collapsed, use the
circular **»** button at the top-left to reopen it.

## Deploy to GitHub Pages

This branch is designed to be served from the repository/Pages root:

1. Push the `stlite` branch.
2. GitHub → **Settings → Pages**.
3. Source: **Deploy from a branch**.
4. Branch: `stlite`, folder: `/ (root)`.
5. Save.

The page will be available at:

```text
https://<username>.github.io/<repo>/
```

The static entry point is `index.html`; `streamlit_app.py` and
`stlite_data.py` are fetched as app assets.

## Multiple profiles

The **Profiles** picker supports up to five handles:

- Choose an existing suggestion, or type a new handle and press **Enter**.
- Every selected profile is drawn on the same axes.
- Profile cards compare latest rating, peak rating, rated rounds, and solved
  counts.
- In **Profile** colour mode, each handle gets its own colour and marker shape.
- In **Rank tier** colour mode, marker fill follows the Codeforces palette and
  marker shape identifies the profile.

![Three profiles on the same chart](output/app_multi.png)

## Problem-rating filter

Use **Problem rating filter** to count only accepted problems whose problem
rating falls inside a chosen range:

- Choose **Custom range** and enter **P (min)** and **Q (max)**.
- The initial values are **P = 1600**, **Q = 1900**.
- Both values accept 0–4000, in 100-point steps.
- Problems with no rating are excluded while a custom range is active.
- The filter applies to every selected profile and to both chart views.
- The active range is shown as a pill in the page header.

For example, with **P = 1600** and **Q = 1900**, the dashboard answers:
*“How many 1600–1900-rated problems had each profile solved by each contest?”*
Leave the filter on **All ratings** to count every accepted problem as before.

![Filtered to problems rated 1600–1900](output/app_filtered.png)

## Two views

### Cumulative solved

- Every point is one rated round.
- X = filtered, distinct problems accepted up to that rating update.
- Y = rating after the round.
- The line follows the rounds in chronological order.

### Per contest

- Every point is one rated round.
- X = filtered, distinct problems accepted during that contest's official
  window.
- Y = rating after the round.
- For a single profile, the dashed line is the median rating for each solve
  count.

![Per-contest view](output/app_per_contest.png)

## Interactivity

- **Hover** a point for profile, contest name, date, rank, exact rank tier, and
  solve count.
- **Zoom / pan** in the chart; scroll to zoom.
- Toggle **Rating-tier bands** for Codeforces rank background bands.
- Toggle **Full rating scale** to keep every rank colour visible up to 3000+,
  even when your peak is lower.
- Toggle **Peak / latest markers**.
- Toggle **Hard solves only** and set a **Hardness margin (x)** to require a
  problem rating at least `your rating + x`. Positive margins are harder;
  negative margins are easier.
- Switch views and profiles without restarting the app.
- Expand **View the underlying rounds** for a sortable table.
- CSV download is hidden in the browser build because stlite does not support
  Streamlit’s server-backed download button.

## Rank colours

The dashboard uses the official Codeforces rank palette:

| Rating | Rank | Colour |
| --- | --- | --- |
| 0–1199 | Newbie | `#808080` grey |
| 1200–1399 | Pupil | `#008000` green |
| 1400–1599 | Specialist | `#03A89E` teal |
| 1600–1899 | Expert | `#0000FF` blue |
| 1900–2099 | Candidate Master | `#AA00AA` violet |
| 2100–2399 | Master / International Master | `#FF8C00` orange |
| 2400+ | Grandmaster / IGM / Legendary Grandmaster | `#FF0000` red |

The exact rank name (for example “International Master” at 2300–2399) appears
in the hover tooltip and metric cards.

By default, **Full rating scale** extends the Y axis to 3000+ so every rank
colour is visible even if your peak is lower. Turn it off to zoom the Y axis
tightly around your own rating range.

## Hard solves

Enable **Hard solves only** to count a problem only when its Codeforces problem
rating is **greater than or equal to your rating when you solved it**.

Use **Hardness margin (x)** to raise that bar:

```text
problem rating >= your rating at solve time + x
```

- `x = 0` is the original rule.
- `x = 100` means you only count problems at least 100 points above your
  rating at the time.
- `x = -100` means you also count problems up to 100 points below your rating
  at the time.
- The margin accepts -3000 to 3000, in 50-point steps.
- For a solve during a rated round, the comparison uses the rating you carried
  **into** that round — rating updates happen after the contest.
- For practice/upsolving submissions, it uses your latest rating update before
  the accepted submission.
- Solves made before your first rating update are excluded because there is no
  rating-at-the-time yet.
- Problems with no Codeforces difficulty rating are excluded.
- Hard-solve mode combines with the P/Q filter: both conditions must hold.
- The stats card, chart title, axis label, hover text, and data table all switch
  to “hard solves” terminology.

This is **not** Codeforces’ own “hard problem” label. It is relative to the
user: a 1700-rated problem is hard for a 1500-rated user, but not for a
1900-rated user.

![Hard solves with a -100 margin](output/app_hard_solves.png)

## What counts as solved

Only submissions with verdict `OK` count, and repeated accepted submissions to
the same problem count once. The API submission list is paginated when needed.

For **Per contest** mode, the app fetches `contest.list` once and only counts
accepted problems whose timestamps fall inside the contest's official
`startTimeSeconds` to `startTimeSeconds + durationSeconds` window. Later
practice/upsolving submissions do not inflate a contest result.

## API usage and caching

| Method | Purpose |
| --- | --- |
| `user.rating` | Rated contest history and rating changes |
| `user.status` | Submissions and problem ratings |
| `contest.list` | Contest start times and durations (Per contest mode) |

Requests are spaced by at least 2.05 seconds, matching Codeforces' public API
request limit. The browser build has no server-side disk cache: `st.cache_data`
keeps parsed profiles in memory for the lifetime of the page/session.

- **Refresh from Codeforces** clears the in-memory cache and forces a fresh API
  fetch for all selected profiles.
- Each visitor’s browser calls Codeforces from their own IP. The 2.05-second
  throttle is per browser session, not global.
- Codeforces must allow browser CORS requests for this architecture to work.
  Its public API currently sends `Access-Control-Allow-Origin: *`.

## Project files

| File | Purpose |
| --- | --- |
| `index.html` | Static stlite shell, theme, boot screen, GitHub Pages entry point |
| `streamlit_app.py` | Streamlit UI, Plotly charts, profile picker, filters, hard-solve mode, data table |
| `stlite_data.py` | Browser-safe Codeforces client, pagination, calculations, hard-solve filtering |
| `favicon.svg` | Browser tab icon |
| `.nojekyll` | Prevent GitHub Pages Jekyll processing |
| `output/` | Example screenshots |

## Notes

- A user must have at least one rated contest.
- The latest point is the most recent rated round, not necessarily the current
  Codeforces profile rating if a round is in progress.
- The problem-rating filter uses Codeforces' problem difficulty rating, not the
  contest rating on the Y axis.
- Browser-only means no server-side cache, no shared rate limiter, and no
  authentication. It is suitable for a public portfolio/demo app.
- First load is several MB of Pyodide + Python packages. Later loads are faster
  because the browser caches the assets.
- This is an unofficial project. Data is provided by the Codeforces public API.
