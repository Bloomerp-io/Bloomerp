# SQL reporting safety

User-authored SQL passes the shared syntax policy in
`bloomerp/utils/sql_safety.py` before any query is executed. This applies to the
SQL API, tile preview, analytics tiles, workflow SQL, safe low-level executor
methods, and direct permission compilation. Administrators retain unrestricted
table access, but use the same reporting syntax policy.

The policy supports SELECT, nonrecursive CTEs, joins, subqueries, set operations,
CASE, ordinary casts, arithmetic, predicates, common numeric/string/date
functions, aggregations, and window functions. Harmless keywords and semicolons
inside string literals are allowed. Unknown functions, schema-qualified function
calls, custom cast types, table-valued functions, recursive queries, writes,
locking clauses, and multiple statements are rejected. The exact reviewed
expression and function sets live in the policy module. Extend those sets only
with regression coverage and a review of the function's database behavior.

Syntax validation is independent of authorization. Each user's physical tables
are still rewritten using current row and field grants. The bounded syntax
cache stores only validated parse trees; every compiler receives a copy, and
permissions and results are never cached there. Count and page wrappers do not
reparse trusted generated permission SQL. Input is capped at 100,000 characters.

## Deployment assumptions

Database schemas, operators, casts, and built-in function resolution must be
controlled by trusted administrators. Report users must not be able to create
or replace database functions or influence the connection's search path.
Database roles with narrowly scoped privileges, read-only reporting connections,
and statement/resource limits provide additional containment. This application
change does not provision a separate database role or change deployment settings;
review those settings and existing client reports before rollout. Read-only
transactions alone do not protect against unauthorized reads through dynamic SQL.

## Regression verification

Run the SQL safety, permission compiler, SQL API and SQL component test modules
with pytest. The compiler integration suite uses generated fixture tables and
runs on both SQLite and PostgreSQL. On a disposable PostgreSQL test database it
verifies that nested dynamic SQL and side-effect functions cause zero database
queries, while real aggregates still honor row and field restrictions. No unsafe
function is executed against production or client data.
