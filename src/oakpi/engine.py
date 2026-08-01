"""Warehouse engine adapter.

The analytical layer of this project is written in SQL, not in pandas, because
that is how it would be written in a real BI stack. To keep the repository
runnable for anyone who clones it, the same SQL runs against two engines:

* **DuckDB** - the default. Columnar, fast, reads and writes Parquet/CSV.
* **SQLite** - a zero-install fallback from the Python standard library, used
  by CI and by anyone who cannot install a wheel.

Portability is bought deliberately, not accidentally: the SQL in ``sql/`` is
restricted to the common subset of both dialects (CTEs, window functions,
standard aggregates, ``CASE``). Anything dialect specific - date arithmetic in
particular - is pre-computed into ``dim_date`` during the load step, so the
queries never call a date function.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def duckdb_available() -> bool:
    try:
        import duckdb  # noqa: F401
    except Exception:
        return False
    return True


class Warehouse:
    """A minimal, uniform interface over DuckDB and SQLite."""

    def __init__(self, kind: str, path: Path) -> None:
        self.kind = kind
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "duckdb":
            import duckdb

            self._con = duckdb.connect(str(self.path))
        elif kind == "sqlite":
            self._con = sqlite3.connect(str(self.path))
            self._con.execute("PRAGMA journal_mode=WAL")
        else:  # pragma: no cover - guarded by open_warehouse
            raise ValueError(f"Unknown engine '{kind}'")

    # -- lifecycle ---------------------------------------------------------
    @classmethod
    def open(cls, cfg, override: str | None = None) -> "Warehouse":
        requested = (override or cfg.get("warehouse.engine", "auto")).lower()
        if requested == "auto":
            requested = "duckdb" if duckdb_available() else "sqlite"
        if requested == "duckdb" and not duckdb_available():
            raise RuntimeError(
                "warehouse.engine is 'duckdb' but the duckdb package is not "
                "installed. Run `pip install duckdb` or set engine: sqlite."
            )
        key = "warehouse.path" if requested == "duckdb" else "warehouse.sqlite_path"
        return cls(requested, cfg.path(key))

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- write -------------------------------------------------------------
    def write_table(self, name: str, df: pd.DataFrame) -> int:
        """Replace ``name`` with the contents of ``df``. Returns row count."""
        df = _normalise_for_storage(df)
        if self.kind == "duckdb":
            self._con.register("_incoming", df)
            self._con.execute(f'DROP TABLE IF EXISTS "{name}"')
            self._con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _incoming')
            self._con.unregister("_incoming")
        else:
            df.to_sql(name, self._con, if_exists="replace", index=False)
            self._con.commit()
        return len(df)

    # -- read --------------------------------------------------------------
    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Run a SELECT and return a DataFrame.

        Parameters are passed as ``:name`` placeholders and are inlined as
        literals so the identical statement text works on both engines.
        """
        statement = _bind(sql, params or {})
        if self.kind == "duckdb":
            return self._con.execute(statement).fetchdf()
        return pd.read_sql_query(statement, self._con)

    def execute_script(self, sql: str, params: dict[str, Any] | None = None) -> None:
        statement = _bind(sql, params or {})
        for chunk in _split_statements(statement):
            self._con.execute(chunk)
        if self.kind == "sqlite":
            self._con.commit()

    def table_names(self) -> list[str]:
        if self.kind == "duckdb":
            rows = self._con.execute("SHOW TABLES").fetchall()
        else:
            rows = self._con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_PARAM = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _bind(sql: str, params: dict[str, Any]) -> str:
    if not params:
        return sql

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            return match.group(0)
        return _literal(params[name])

    return _PARAM.sub(repl, sql)


def _split_statements(sql: str) -> Iterable[str]:
    """Split a script into executable statements.

    A naive ``sql.split(";")`` breaks the moment a comment or a string literal
    contains a semicolon - which prose comments regularly do. This scanner
    tracks line comments, block comments, string literals and quoted
    identifiers, and only treats a semicolon outside all of them as a
    statement boundary.
    """
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_line_comment = in_block_comment = in_string = in_identifier = False

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
        elif in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 1
                in_block_comment = False
        elif in_string:
            buf.append(ch)
            if ch == "'":
                if nxt == "'":  # escaped quote
                    buf.append(nxt)
                    i += 1
                else:
                    in_string = False
        elif in_identifier:
            buf.append(ch)
            if ch == '"':
                in_identifier = False
        elif ch == "-" and nxt == "-":
            buf.append(ch)
            in_line_comment = True
        elif ch == "/" and nxt == "*":
            buf.append(ch)
            in_block_comment = True
        elif ch == "'":
            buf.append(ch)
            in_string = True
        elif ch == '"':
            buf.append(ch)
            in_identifier = True
        elif ch == ";":
            statements.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1

    statements.append("".join(buf))

    for chunk in statements:
        stripped = chunk.strip()
        if not stripped:
            continue
        body = "\n".join(
            line for line in stripped.splitlines() if not line.strip().startswith("--")
        ).strip()
        if body:
            yield stripped


def _normalise_for_storage(df: pd.DataFrame) -> pd.DataFrame:
    """SQLite has no native datetime or boolean type.

    Timestamps are stored as ISO strings and booleans as 0/1 integers so that
    the same query text sorts and filters identically on both engines.
    """
    out = df.copy()
    for col in out.columns:
        series = out[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            out[col] = series.dt.strftime("%Y-%m-%d %H:%M:%S")
        elif pd.api.types.is_bool_dtype(series):
            out[col] = series.astype("int8")
        elif series.dtype == "object":
            out[col] = series.astype(object).where(series.notna(), None)
    return out
