"""Part 3: check the SQL query that the LLM wrote, then run it on datasets.db in read-only mode.
Two protections, because we never trust a query only because we asked the LLM for a SELECT:
1. check_sql: one query, and it must start with SELECT (or WITH, for queries with a sub-query at the start)
2. the connection is read-only: SQLite itself refuses anything that writes to the database
"""
import sqlite3
import time

from datasets import DATABASE_FILE

MAX_ROWS = 50     # rows returned to the user; a bigger result is cut
TIME_LIMIT = 5    # seconds: a query that runs longer is stopped


def check_sql(sql):
    """Raise a ValueError with the reason if the query is not allowed."""
    # Examples:
    #   "SELECT city FROM sales"                    ->  allowed
    #   "DELETE FROM sales"                         ->  ValueError: Only SELECT queries are allowed.
    #   "SELECT * FROM sales; DROP TABLE sales"     ->  ValueError: Only one query is allowed.
    if not sql:
        raise ValueError("The query is empty.")
    if ";" in sql:   # clean_sql removed the ; at the end, so a ; inside means a second query
        raise ValueError("Only one query is allowed.")
    first_word = sql.split()[0].upper()
    if first_word not in ("SELECT", "WITH"):
        raise ValueError("Only SELECT queries are allowed.")


def run_sql(sql):
    """Check and run the query. Return {"columns": [...], "rows": [[...], ...], "truncated": True or False}."""
    # Example: "SELECT city, SUM(total_price) AS total_sales FROM sales GROUP BY city" returns
    #   {"columns": ["city", "total_sales"], "rows": [["Amman", 2514.0], ["Cairo", 4876.0], ...], "truncated": False}
    check_sql(sql)

    # mode=ro opens the file read-only: INSERT, UPDATE, DELETE or DROP fail with "attempt to write a readonly database"
    connection = sqlite3.connect(f"file:{DATABASE_FILE}?mode=ro", uri=True)

    # SQLite calls this function again and again while the query runs; when it returns True, the query is stopped
    start = time.monotonic()
    connection.set_progress_handler(lambda: time.monotonic() - start > TIME_LIMIT, 10_000)

    try:
        cursor = connection.execute(sql)
        rows = cursor.fetchmany(MAX_ROWS + 1)   # one row more than the limit tells us if the result was cut
        columns = [column[0] for column in cursor.description]
    except sqlite3.OperationalError as error:
        if str(error) == "interrupted":   # the progress handler stopped the query
            raise ValueError(f"The query ran for more than {TIME_LIMIT} seconds.")
        raise   # any other SQLite error (for example "no such column") goes to the caller, who can ask the LLM to fix it
    finally:
        connection.close()

    return {
        "columns": columns,
        "rows": [list(row) for row in rows[:MAX_ROWS]],
        "truncated": len(rows) > MAX_ROWS,
    }


if __name__ == "__main__":
    from pathlib import Path

    import pandas as pd

    from datasets import load_dataset

    load_dataset("sales.csv", Path("sample_data/sales.csv").read_bytes())
    queries = {
        # The queries that the LLM wrote in part 2
        "Total sales by category": "SELECT category, SUM(total_price) AS total_sales FROM sales GROUP BY category",
        "City with the highest sales": "SELECT city, SUM(total_price) AS total_sales FROM sales "
                                       "GROUP BY city ORDER BY total_sales DESC LIMIT 1",
        "Orders in March 2025": "SELECT COUNT(DISTINCT order_id) AS order_count FROM sales WHERE order_date LIKE '2025-03%'",
        "Total sales in Amman": "SELECT SUM(total_price) AS total_sales FROM sales WHERE city = 'Amman'",
        # A big result is cut at MAX_ROWS
        "All the rows": "SELECT * FROM sales",
        # Queries that must be refused or must fail
        "Delete": "DELETE FROM sales",
        "Two queries": "SELECT * FROM sales; DROP TABLE sales",
        "Delete hidden after WITH": "WITH old AS (SELECT 1) DELETE FROM sales",
        "Wrong column name": "SELECT categry FROM sales",
        "Endless query": "WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM numbers) "
                         "SELECT COUNT(*) FROM numbers",
    }
    for name, sql in queries.items():
        print("=====", name)
        print(sql)
        try:
            result = run_sql(sql)
            table = pd.DataFrame(result["rows"], columns=result["columns"])
            print(table.head(5).to_string(index=False))
            print(f"({len(table)} rows{', cut at ' + str(MAX_ROWS) if result['truncated'] else ''})")
        except (ValueError, sqlite3.Error) as error:
            print("Refused or failed:", error)
        print()

    # The data is still all there: nothing was deleted
    print("Rows in the sales table after all the tests:", run_sql("SELECT COUNT(*) AS row_count FROM sales")["rows"][0][0])
