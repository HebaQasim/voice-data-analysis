"""Part 2 (step B): the LLM writes a SQLite query for a question about a dataset, in English or Arabic.
The LLM reads the description of the table from part 1, so it uses the real table name, column names and values."""
from langchain_core.prompts import PromptTemplate

from datasets import describe_table
from llm import llm

# The rules are the same for a new query and for a corrected one, so they are written once
RULES = """Rules:
- Use only the table and the columns described above, with their names written exactly as above.
- Write one SELECT query only. Never change the data (no INSERT, UPDATE, DELETE, DROP or ALTER).
- The question can be in English or Arabic. Write text values exactly as they appear in the table:
  for example, if the question says "باريس" and the values of the column have "Paris", write 'Paris'.
- Dates are stored as text like 2025-01-31: use SQLite date functions such as strftime('%Y-%m', column).
- Give calculated columns short English names with AS, for example COUNT(*) AS row_count.
- When the question asks for the highest, the lowest or a ranking, also select the value used to compare
  (for example the total next to the name), so the answer can show the number.
- If the question cannot be answered from this table, reply with NO_SQL only.
- Reply with the SQL query only: no explanation and no Markdown code marks."""

SQL_PROMPT = PromptTemplate.from_template(
    """You are a data analyst who writes SQLite queries.
Write one SQL query that answers the user's question about this table:

{description}

{rules}

Question:
{question}"""
)

FIX_PROMPT = PromptTemplate.from_template(
    """You are a data analyst who writes SQLite queries.
This query was written for the user's question, but SQLite returned an error. Write a corrected query.

{description}

Question:
{question}

Query:
{sql}

Error:
{error}

{rules}"""
)

NO_SQL = "NO_SQL"


def clean_sql(answer):
    """Keep only the query: remove Markdown code marks around it and the ; at the end."""
    # Example: "```sql\nSELECT city FROM sales;\n```"  ->  "SELECT city FROM sales"
    sql = answer.strip()
    if sql.startswith("`"):   # the LLM put the query in a Markdown code block, even though we asked not to
        sql = sql.strip("`")
        if sql.lower().startswith("sql"):
            sql = sql[3:]   # the word "sql" after the opening marks
    return sql.strip().rstrip(";").strip()


def generate_sql(question, table):
    """Return the SQL query that answers the question, or None if the table cannot answer it."""
    prompt = SQL_PROMPT.format(description=describe_table(table), rules=RULES, question=question)
    sql = clean_sql(llm.invoke(prompt).content)
    if sql.upper().startswith(NO_SQL):
        return None
    return sql


def fix_sql(question, table, sql, error):
    """Ask the LLM to correct a query that failed, using the error message from SQLite (used in part 4)."""
    prompt = FIX_PROMPT.format(description=describe_table(table), rules=RULES, question=question, sql=sql, error=error)
    fixed = clean_sql(llm.invoke(prompt).content)
    if fixed.upper().startswith(NO_SQL):
        return None
    return fixed


if __name__ == "__main__":
    from pathlib import Path

    from datasets import load_dataset

    table = load_dataset("sales.csv", Path("sample_data/sales.csv").read_bytes())
    questions = [
        "Show me total sales by product category",
        "Which city had the highest sales?",
        "How many orders were there in March 2025?",
        "ما هو مجموع المبيعات في عمان؟",
        "كم عدد الطلبات لكل فئة؟",
        "What is the weather today?",   # not about the table: the answer should be None
    ]
    for question in questions:
        print("Question:", question)
        print("SQL:", generate_sql(question, table))
        print()

    print("===== Fixing a query with a wrong column name")
    print(fix_sql("Show me total sales by product category", table,
                  "SELECT categry, SUM(total_price) FROM sales GROUP BY categry", "no such column: categry"))
