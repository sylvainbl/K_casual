import csv
import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "owkin_take_home_data.csv"

with DATA_FILE.open(encoding="utf-8", newline="") as file:
    EXPRESSIONS: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(file):
        EXPRESSIONS.setdefault(row["cancer_indication"], {})[row["gene"]] = float(
            row["median_value"]
        )


# Simple mode tools
def get_targets(cancer_name: str) -> list[str]:
    """Return the genes associated with this cancer in the dataset."""
    return list(EXPRESSIONS.get(cancer_name, {}))


def get_expressions(cancer_name: str, genes: list[str]) -> dict[str, float]:
    """Return the recorded expression medians for these genes in this cancer."""
    values = EXPRESSIONS.get(cancer_name, {})
    return {gene: values[gene] for gene in genes if gene in values}


# Advanced mode SQL tools and limits
MAX_ROWS = 100
QUERY_TIMEOUT_SECONDS = 1
ALLOWED_FUNCTIONS = frozenset(
    {
        "abs", "avg", "coalesce", "count", "dense_rank", "glob", "group_concat",
        "ifnull", "length", "like", "lower", "max", "min", "nullif", "rank",
        "round", "row_number", "substr", "sum", "total", "trim", "upper",
    }
)


class SQLQueryError(Exception):
    """A generated query failed, with an indication of whether to attempt a correction."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def query_expressions(sql: str) -> dict:
    """Query expressions(cancer_indication, gene, median_value) and return a bounded table."""
    denied = False

    def authorize(action, name, detail, database, _source):
        nonlocal denied
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and name == "expressions" and database in (None, "main"):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and detail in ALLOWED_FUNCTIONS:
            return sqlite3.SQLITE_OK
        denied = True
        return sqlite3.SQLITE_DENY

    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute(
            "CREATE TABLE expressions (cancer_indication TEXT, gene TEXT, median_value REAL)"
        )
        connection.executemany(
            "INSERT INTO expressions VALUES (?, ?, ?)",
            (
                (cancer, gene, value)
                for cancer, genes in EXPRESSIONS.items()
                for gene, value in genes.items()
            ),
        )
        connection.commit()
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_DQS_DML, False)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 8_192)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 16_384)
        connection.set_authorizer(authorize)

        deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
        connection.set_progress_handler(lambda: time.monotonic() >= deadline, 1_000)

        try:
            cursor = connection.execute(sql)
            if cursor.description is None:
                raise SQLQueryError("Expected a query that returns a table.", retryable=True)
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchmany(MAX_ROWS + 1)
        except sqlite3.ProgrammingError as exc:
            raise SQLQueryError("Expected a single SQL query without parameters.") from exc
        except sqlite3.DatabaseError as exc:
            if denied:
                raise SQLQueryError("The SQL query requested an operation that is not allowed.") from exc
            error_code = getattr(exc, "sqlite_errorcode", None)
            if error_code == sqlite3.SQLITE_INTERRUPT:
                raise SQLQueryError("The SQL query exceeded its execution time limit.") from exc
            raise SQLQueryError(str(exc), retryable=error_code == sqlite3.SQLITE_ERROR) from exc

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    if any(
        isinstance(value, bytes) or (isinstance(value, float) and not math.isfinite(value))
        for row in rows
        for value in row
    ):
        raise SQLQueryError("SQL results must contain text, finite numbers or NULL.")
    return {"columns": columns, "rows": [list(row) for row in rows], "truncated": truncated}
