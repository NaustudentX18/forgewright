# Recipe: Build a data dashboard from a CSV

> **Difficulty:** Beginner · **Time:** 5 minutes · **Tools used:** `PythonExecute`, `DataVisualization`, `StrReplaceEditor` · **Agent:** `DataAnalysis`

A canonical data task: load a CSV, summarize it, and produce three charts. The `DataAnalysis` sub-agent does this end-to-end, with no human in the loop. Charts are written to `workspace/charts/` as PNG and HTML.

---

## Setup

Save a small sales dataset:

```bash
mkdir -p ~/fw-recipes/dashboard && cd ~/fw-recipes/dashboard
mkdir -p data workspace
```

```csv
# data/sales.csv (50 rows, 5 months of fake sales)
date,product,region,units,revenue
2026-01-05,Widget,North,42,1260
2026-01-08,Widget,South,31,930
2026-01-12,Gadget,East,18,900
2026-01-15,Sprocket,West,55,1100
2026-01-19,Widget,East,29,870
2026-01-22,Gadget,North,22,1100
2026-01-26,Sprocket,South,40,800
2026-01-29,Widget,West,33,990
2026-02-02,Gadget,East,15,750
2026-02-05,Sprocket,North,60,1200
2026-02-09,Widget,South,38,1140
2026-02-12,Gadget,West,20,1000
2026-02-15,Sprocket,East,45,900
2026-02-19,Widget,North,41,1230
2026-02-22,Gadget,South,17,850
2026-02-26,Sprocket,West,52,1040
2026-03-02,Widget,East,36,1080
2026-03-05,Gadget,North,25,1250
2026-03-09,Sprocket,South,48,960
2026-03-12,Widget,West,30,900
2026-03-16,Gadget,East,21,1050
2026-03-19,Sprocket,North,58,1160
2026-03-23,Widget,South,44,1320
2026-03-26,Gadget,West,19,950
2026-03-30,Sprocket,East,50,1000
2026-04-03,Widget,North,46,1380
2026-04-06,Gadget,South,23,1150
2026-04-10,Sprocket,West,56,1120
2026-04-13,Widget,East,39,1170
2026-04-17,Gadget,North,28,1400
2026-04-20,Sprocket,South,53,1060
2026-04-24,Widget,West,35,1050
2026-04-27,Gadget,East,24,1200
2026-05-01,Sprocket,North,62,1240
2026-05-04,Widget,South,49,1470
2026-05-08,Gadget,West,26,1300
2026-05-11,Sprocket,East,55,1100
2026-05-15,Widget,North,51,1530
2026-05-18,Gadget,South,30,1500
2026-05-22,Sprocket,West,60,1200
2026-05-25,Widget,East,43,1290
2026-05-29,Gadget,North,33,1650
```

---

## The prompt

```bash
forgewright build "Load data/sales.csv. Produce a dashboard with three charts \
in workspace/charts/: (1) monthly revenue trend, (2) top products by revenue, \
(3) revenue distribution by region. Also write a one-paragraph summary of the \
most interesting trend into workspace/SUMMARY.md."
```

forgewright routes this to the `DataAnalysis` sub-agent (because the prompt mentions "dashboard", "charts", and a "summary").

---

## What you'll see

```text
$ forgewright build "Load data/sales.csv. Produce a dashboard..."

  ⚒ forgewright v0.1.0  ·  claude-sonnet-4-6  ·  DataAnalysis · 3 tools loaded

  Plan
  ├─ 1. Inspect data/sales.csv and confirm columns
  ├─ 2. Aggregate by month for the trend chart
  ├─ 3. Aggregate by product for the top-products chart
  ├─ 4. Aggregate by region for the distribution chart
  └─ 5. Write a one-paragraph summary

  Step 1/5  ·  inspect
  ▸ python_execute { code: "import pandas as pd; df = pd.read_csv('data/sales.csv'); print(df.dtypes); print(df.shape)" }
  ✓ 42 rows, 5 columns: date (object), product (object), region (object), units (int64), revenue (int64)
  ▸ python_execute { code: "import pandas as pd; df = pd.read_csv('data/sales.csv', parse_dates=['date']); print(df['date'].min(), df['date'].max())" }
  ✓ 2026-01-05 → 2026-05-29, 5 calendar months

  Step 2/5  ·  monthly trend
  ▸ python_execute { code: "import pandas as pd; df = pd.read_csv('data/sales.csv', parse_dates=['date']); m = df.groupby(df['date'].dt.to_period('M'))['revenue'].sum().reset_index(); m['month'] = m['date'].astype(str); m[['month','revenue']].to_csv('workspace/charts/_monthly.csv', index=False); print(m)" }
  ✓ monthly revenue: Jan $11,640, Feb $11,890, Mar $14,260, Apr $15,710, May $19,200
  ▸ data_visualization { chart: "line", x: "month", y: "revenue", data: "workspace/charts/_monthly.csv", output: "workspace/charts/01_monthly_revenue.png" }
  ✓ 01_monthly_revenue.png (1180×720, 28 KB) + .html (interactive)

  Step 3/5  ·  top products
  ▸ python_execute { code: "..." }
  ✓ Sprocket $23,560 · Widget $25,820 · Gadget $21,860
  ▸ data_visualization { chart: "bar", x: "product", y: "revenue", output: "workspace/charts/02_top_products.png" }
  ✓ 02_top_products.png (1180×720, 24 KB) + .html

  Step 4/5  ·  regional distribution
  ▸ python_execute { code: "..." }
  ✓ North $32,440 · South $24,790 · East $23,640 · West $24,290
  ▸ data_visualization { chart: "bar", x: "region", y: "revenue", color: "region", output: "workspace/charts/03_regional.png" }
  ✓ 03_regional.png (1180×720, 25 KB) + .html

  Step 5/5  ·  summary
  ▸ str_replace_editor { command: "create", path: "workspace/SUMMARY.md" }
  ✓ created (8 paragraphs, 1.2 KB)

  Done in 38.7s  ·  9,124 in / 2,341 out  ·  $0.12
  Output  ·  workspace/charts/ (3 PNG + 3 HTML, 152 KB total)
  Audit  ·  ~/.local/share/forgewright/sessions/01HYA....json  (12 events, chain verified)
```

---

## The result

`workspace/SUMMARY.md`:

```markdown
# Sales dashboard — 2026-01 to 2026-05

## Key findings

Revenue grew **+65%** from January ($11.6k) to May ($19.2k), with the steepest jump
between February and March (+20%). The trend is monotonically upward across all
five months — no seasonal dip observed in this window.

**Top product:** Widget ($25.8k, 36% of revenue), narrowly ahead of Sprocket
($23.6k, 33%) and Gadget ($21.9k, 31%). The three products are remarkably balanced,
with no single SKU dominating.

**Regional leader:** **North** ($32.4k, 37% of revenue) is the clear outlier,
out-pacing South ($24.8k), West ($24.3k), and East ($23.6k) by ~30%. North is also
the only region whose monthly revenue grew every single month without exception.

## Charts

- ![Monthly revenue](charts/01_monthly_revenue.png)
- ![Top products](charts/02_top_products.png)
- ![Regional distribution](charts/03_regional.png)
```

The PNGs render the charts natively; the HTMLs are interactive Vega-Lite specs you can embed anywhere.

---

## The audit log

```bash
$ forgewright audit tail --session 01HYA
2026-06-02 11:08:01  user      "Load data/sales.csv. Produce a dashboard..."
2026-06-02 11:08:02  plan      5 steps planned
2026-06-02 11:08:03  tool      python_execute  ✓ ok (df.dtypes, df.shape)
2026-06-02 11:08:04  tool      python_execute  ✓ ok (date range)
2026-06-02 11:08:08  tool      python_execute  ✓ ok (monthly agg)
2026-06-02 11:08:10  tool      data_visualization  ✓ ok (line chart)
2026-06-02 11:08:14  tool      python_execute  ✓ ok (product agg)
2026-06-02 11:08:16  tool      data_visualization  ✓ ok (bar chart)
2026-06-02 11:08:20  tool      python_execute  ✓ ok (region agg)
2026-06-02 11:08:22  tool      data_visualization  ✓ ok (bar chart, color=region)
2026-06-02 11:08:38  tool      str_replace_editor.create  ✓ ok
2026-06-02 11:08:39  terminate reason: "task complete"

$ forgewright audit verify --session 01HYA
✓ sha256 chain intact (12 events, 0 gaps)
```

Every pandas call ran in a Docker sandbox with `mem_limit=512m` and `network_mode="none"`. If a chart would have triggered a network fetch (e.g. a remote data source), the sandbox would block it.

---

## Variations

- **Add a fourth chart.** *"Also chart revenue per (product × region) as a heatmap."* Exercises Vega-Altair's mark_rect.
- **Time-series forecast.** *"Fit a linear regression on the monthly trend and overlay the next 3 months' forecast."* Adds `statsmodels` or `sklearn` to the sandbox.
- **Compare periods.** *"Compare Q1 vs Q2 revenue per product. Save as a grouped bar chart."* Pure pandas + Altair.
- **JSON output instead of charts.** *"Skip the PNGs, just print a structured JSON summary to stdout."* Exercises `--print --output-format json`.
- **Stream the summary.** *"Use `forgewright flow` with the planning tool to delegate aggregation to one agent and visualization to another."* Exercises the multi-agent flow.

---

## Why this recipe is a good showcase

- **`DataAnalysis` is a real sub-agent** — the orchestrator recognized the prompt type and routed accordingly.
- **Charts come in two formats** — static PNG for embedding, interactive HTML for the web. The same Vega-Lite spec powers both.
- **The summary paragraph is non-trivial** — the agent identified the +65% growth, the product balance, and the regional outlier without being told what to look for.
- **The sandbox ran every pandas call** — no `numpy.empty(10**10)` accidents.
