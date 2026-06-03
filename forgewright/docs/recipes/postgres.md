# Recipe: Wire an agent to your Postgres

> **Difficulty:** Intermediate · **Time:** 15 minutes · **Tools used:** `MCP` (postgres server), `Bash` · **Agent:** `MCPAgent`

Connect forgewright to a Postgres database via the official MCP server, and ask natural-language questions. The agent discovers the schema, generates a SQL query, runs it through MCP, and answers in English.

This is also the cleanest demonstration of **MCP-first tool discovery** in the project: the agent learns about the database at startup, namespaces the tools (`postgres__query`, `postgres__list_tables`), and enforces the allowlist before running anything.

---

## Setup

### 1. Start a local Postgres

```bash
docker run -d --name fw-pg \
  -e POSTGRES_PASSWORD=dev \
  -e POSTGRES_DB=shop \
  -p 5432:5432 \
  postgres:16-alpine
```

### 2. Seed it with a small schema

```bash
docker exec -i fw-pg psql -U postgres -d shop <<'SQL'
CREATE TABLE customers (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  customer_id INT REFERENCES customers(id),
  total NUMERIC(10, 2) NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','paid','shipped','cancelled')),
  created_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO customers (name, email) VALUES
  ('Alice Chen',   'alice@example.com'),
  ('Bob Hernandez','bob@example.com'),
  ('Carol Schmidt','carol@example.com'),
  ('Dmitri Volkov','dmitri@example.com');

INSERT INTO orders (customer_id, total, status, created_at) VALUES
  (1, 42.00, 'paid',      now() - interval '14 days'),
  (1, 88.50, 'shipped',   now() - interval '10 days'),
  (2, 19.99, 'paid',      now() - interval '9 days'),
  (2, 124.00,'paid',      now() - interval '6 days'),
  (3, 7.50,  'cancelled', now() - interval '5 days'),
  (3, 230.00,'paid',      now() - interval '3 days'),
  (4, 18.00, 'pending',   now() - interval '2 days'),
  (4, 64.50, 'paid',      now() - interval '1 day');
SQL
```

### 3. Install the postgres MCP server

The reference server is `@modelcontextprotocol/server-postgres` from the [MCP servers repo](https://github.com/modelcontextprotocol/servers):

```bash
# one-shot install
forgewright mcp install postgres
# writes to ~/.config/forgewright/mcp.json:
#   [mcp.servers.postgres]
#   transport = "stdio"
#   command = "npx"
#   args = ["-y", "@modelcontextprotocol/server-postgres", "postgresql://postgres:dev@localhost:5432/shop"]
```

### 4. Allow the tools

```bash
forgewright mcp trust postgres__query
forgewright mcp trust postgres__list_tables
forgewright mcp trust postgres__describe_table
```

(`mcp trust` adds the tool to the allowlist for the current machine. `--scope=session` or `--scope=repo` scopes tighter.)

---

## The prompt

```bash
forgewright build "Connect to the postgres MCP server and answer: \
'How many orders were placed in the last 7 days, broken down by status?'"
```

The orchestrator sees the word "MCP" and routes to `MCPAgent`, which keeps the connection open for the lifetime of the run.

---

## What you'll see

```text
$ forgewright build "Connect to the postgres MCP server..."

  ⚒ forgewright v0.1.0  ·  claude-sonnet-4-6  ·  MCPAgent
  ▸ connecting to MCP server 'postgres' (stdio)...

  Plan
  ├─ 1. Discover the schema via postgres__list_tables
  ├─ 2. Inspect the orders table via postgres__describe_table
  ├─ 3. Generate a SQL query for the last 7 days, grouped by status
  ├─ 4. Run the query via postgres__query
  └─ 5. Translate the result into a natural-language answer

  Step 1/5  ·  list tables
  ▸ postgres__list_tables {}
  ✓ [public.customers, public.orders]

  Step 2/5  ·  describe orders
  ▸ postgres__describe_table { table: "public.orders" }
  ✓ columns: id (int4), customer_id (int4), total (numeric), status (text), created_at (timestamptz)

  Step 3/5  ·  draft query
  ✓ SELECT status, COUNT(*) AS n, SUM(total) AS revenue
    FROM orders
    WHERE created_at >= now() - interval '7 days'
    GROUP BY status
    ORDER BY n DESC;

  Step 4/5  ·  run
  ▸ postgres__query { sql: "SELECT status, COUNT(*) AS n, SUM(total) AS revenue FROM orders WHERE created_at >= now() - interval '7 days' GROUP BY status ORDER BY n DESC;" }
  ✓ 3 rows
    status     | n | revenue
    -----------+---+---------
     paid      | 3 |  324.50
     shipped   | 1 |   88.50
     pending   | 1 |   18.00

  Step 5/5  ·  answer
  ▸ (no tool call — natural-language synthesis)

  Answer
  ───────
  In the last 7 days, 5 orders were placed across 3 statuses:
    • paid:     3 orders, $324.50 revenue
    • shipped:  1 order,   $88.50 revenue
    • pending:  1 order,   $18.00 revenue

  No orders were cancelled in this window.

  Done in 12.4s  ·  4,210 in / 723 out  ·  $0.038
  MCP  ·  postgres stdio session closed cleanly
  Audit  ·  ~/.local/share/forgewright/sessions/01HYB....json  (6 events, chain verified)
```

---

## The audit log

```bash
$ forgewright audit tail --session 01HYB
2026-06-02 11:30:01  user      "Connect to the postgres MCP server..."
2026-06-02 11:30:02  mcp       connect: postgres (stdio)  ✓ session=af3a
2026-06-02 11:30:04  tool      postgres__list_tables  ✓ ok (2 tables)
2026-06-02 11:30:07  tool      postgres__describe_table  ✓ ok
2026-06-02 11:30:11  tool      postgres__query  ✓ ok (3 rows, 0.08s)
2026-06-02 11:30:13  mcp       disconnect: postgres  ✓ session=af3a
2026-06-02 11:30:14  terminate reason: "task complete"

$ forgewright audit verify --session 01HYB
✓ sha256 chain intact (6 events, 0 gaps)
```

The `mcp connect` / `mcp disconnect` events are first-class audit events — you can see exactly when the agent opened and closed the database connection. The `tool` events record the SQL that ran and the row count returned, but **not** the actual row data (to avoid leaking PII into the log; use `--audit-rows` to include them).

---

## Variations

- **Schema-agnostic queries.** *"What's the average order value for customers who signed up in the last 30 days?"* The agent joins across tables based on the inspected schema.
- **Parameter binding.** *"Run this parameterized query: SELECT * FROM orders WHERE customer_id = $1 AND status = $2" with values [3, 'paid']."* Tests that the MCP server handles parameterized calls correctly.
- **Write queries.** Allow `postgres__execute` (not just `_query`), then prompt: *"Cancel order #7 and refund the payment; tell me the new order status."* Exercises a write transaction.
- **Multiple databases.** Add a second MCP server pointing at a different database, and prompt: *"Compare the average order value in shop vs analytics."* The agent discovers two sets of tools, namespaced differently.
- **Streaming results.** For large tables: *"SELECT * FROM orders — stream the results into a CSV at workspace/orders.csv."* Exercises the streaming variant of `_query`.

---

## Security notes

- The MCP connection string contains a password. forgewright never logs the value; the audit log records *that* a connection was opened, not the URI.
- The agent cannot run a SQL query unless the corresponding tool (`postgres__query`) is in the allowlist. Default-deny applies even to MCP-discovered tools.
- Read-only mode is the default for the postgres reference server. To enable writes, opt in: `[mcp.servers.postgres.env] READ_ONLY = "false"` and re-trust `postgres__execute`.
- The connection is stdio-based and process-local. There is no exposed network surface unless you explicitly configure the `streamable-http` transport.

---

## Why this recipe is a good showcase

- **MCP tool discovery is visible in the output** — `list_tables` → `describe_table` → `query` is the natural pattern.
- **Namespacing is explicit** — every tool is `postgres__<name>`, never just `_query`, so a second MCP server can't shadow it.
- **The default-deny allowlist is exercised** — `mcp trust` is a required step. The agent cannot run a query without it.
- **The audit log records connection events, not just tool events** — you can see the stdio session open and close.
- **The agent synthesizes, doesn't just dump rows** — five orders become "5 orders across 3 statuses" with the math done.
