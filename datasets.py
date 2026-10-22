"""Part 1: load an uploaded dataset (CSV or Excel) into a SQLite table, and describe the table for the LLM.
Every dataset becomes one table in datasets.db. The description (columns, types, values and some rows)
is what the LLM reads in part 2, so it can write SQL "based on the structure and contents of the dataset".
"""
import io
import re
import sqlite3
from pathlib import Path

import pandas as pd

DATABASE_FILE = "datasets.db"   # one SQLite file for all the uploaded datasets
SAMPLE_ROWS = 3                 # rows shown to the LLM as an example of the contents
MAX_LISTED_VALUES = 10          # a text column with at most 10 different values gets all its values listed


def clean_name(name, default):
    """Turn a file or column name into a simple SQL name."""
    # Examples:
    #   "Total Sales ($)"  ->  "total_sales"
    #   "Sales 2025"       ->  "sales_2025"           (a file name without .csv)
    #   "2025 target"      ->  "column_2025_target"   (a SQL name cannot start with a digit)
    #   "سعر الوحدة"        ->  "سعر_الوحدة"           (Arabic letters are kept)
    name = re.sub(r"\W+", "_", str(name).strip()).strip("_").lower()
    if not name:
        return default
    if name[0].isdigit():
        return f"{default}_{name}"
    return name


def read_file(file_name, data):
    """Read the bytes of an uploaded file into a DataFrame. CSV and Excel (.xlsx) files are supported."""
    if file_name.lower().endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(data))
    if not file_name.lower().endswith(".csv"):
        raise ValueError("Please upload a .csv or .xlsx file.")
    try:
        return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")   # utf-8-sig also reads files saved as "CSV UTF-8" by Excel
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(data), encoding="cp1256")      # older Arabic Windows files use this encoding


def load_dataset(file_name, data):
    """Save the file as a table in datasets.db and return the table name, for example "sales.csv" -> "sales"."""
    df = read_file(file_name, data)
    if df.empty:
        raise ValueError("The file has no rows.")

    # Simple column names make the SQL easier for the LLM: "Total Sales ($)" becomes total_sales
    columns = []
    for column in df.columns:
        name = clean_name(column, "column")
        while name in columns:   # two columns with the same clean name: add _2 to the second one
            name += "_2"
        columns.append(name)
    df.columns = columns

    table = clean_name(Path(file_name).stem, "dataset")
    connection = sqlite3.connect(DATABASE_FILE)
    # if_exists="replace": uploading a file with the same name again replaces the old table
    df.to_sql(table, connection, if_exists="replace", index=False)
    connection.close()
    return table


def list_datasets():
    """The names of all the tables in datasets.db."""
    connection = sqlite3.connect(DATABASE_FILE)
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
    connection.close()
    return [row[0] for row in rows]


def describe_table(table):
    """Describe the table for the LLM: its size, its columns with their types, the values of short text columns
    and the first rows."""
    # Example of the result:
    #   Table: sales (60 rows)
    #   Columns:
    #   - order_id (INTEGER)
    #   - city (TEXT), values: Amman, Cairo, Dubai, Riyadh
    #   - total_price (REAL)
    #   First 3 rows:
    #    order_id  order_date  city ...
    #           1  2025-01-10 Amman ...
    # Only tables that load_dataset created are accepted. Their names and column names come from clean_name
    # (letters, digits and _ only), so they are safe inside the SQL text.
    if table not in list_datasets():
        raise ValueError(f"There is no dataset named {table}.")
    connection = sqlite3.connect(DATABASE_FILE)
    row_count = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    lines = [f"Table: {table} ({row_count} rows)", "Columns:"]

    # PRAGMA table_info gives one row per column: (position, name, type, ...)
    for column in connection.execute(f'PRAGMA table_info("{table}")').fetchall():
        name, sql_type = column[1], column[2]
        line = f"- {name} ({sql_type})"
        if sql_type == "TEXT":
            # we ask for one value more than the limit, so we know if the column has too many values to list
            rows = connection.execute(
                f'SELECT DISTINCT "{name}" FROM "{table}" ORDER BY "{name}" LIMIT {MAX_LISTED_VALUES + 1}'
            ).fetchall()
            if len(rows) <= MAX_LISTED_VALUES:
                line += ", values: " + ", ".join(str(row[0]) for row in rows)
        lines.append(line)

    sample = pd.read_sql(f'SELECT * FROM "{table}" LIMIT {SAMPLE_ROWS}', connection)
    connection.close()
    lines.append(f"First {SAMPLE_ROWS} rows:")
    lines.append(sample.to_string(index=False))
    return "\n".join(lines)


if __name__ == "__main__":
    # 1) The sample dataset of the project
    data = Path("sample_data/sales.csv").read_bytes()
    table = load_dataset("sales.csv", data)
    print("Table:", table)
    print(describe_table(table))

    # 2) A small file with messy and Arabic column names, to see how the names are cleaned
    messy = "Order ID,Total Sales ($),2025 Target,المدينة\n1,120.5,100,عمان\n2,80,100,القاهرة\n".encode("utf-8")
    table = load_dataset("Messy File.csv", messy)
    print("\n" + describe_table(table))

    print("\nAll datasets:", list_datasets())
