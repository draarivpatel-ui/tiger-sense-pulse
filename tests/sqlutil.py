"""Small helpers shared by the tests: read the repo's SQL files and strip comments/strings.

Standard library only, so the suite runs without a database or any pip install.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
SQL_FILES = sorted(SQL_DIR.glob("*.sql")) + sorted((ROOT / "vector").glob("*.sql"))


def read(path):
    return Path(path).read_text(encoding="utf-8")


_DOLLAR_TAG = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def strip_sql(text):
    """Remove -- comments, /* */ comments and the contents of '...' strings (keeps the quotes).

    Handles the SQL '' escape inside strings. psql meta-command lines (\\echo ...) are dropped.
    Raises ValueError on an unterminated string or block comment.
    Raises ValueError on syntax this stripper deliberately does not model - dollar-quoted bodies
    ($$...$$ or $tag$...$tag$) and escape strings (E'...') - instead of silently misparsing them.
    """
    out, i, n = [], 0, len(text)
    lines = [l for l in text.splitlines(keepends=True) if not l.lstrip().startswith("\\")]
    text = "".join(lines)
    n = len(text)
    while i < n:
        c = text[i]
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j == -1:
                raise ValueError("unterminated /* comment")
            i = j + 2
        elif c == "'":
            k = len(out) - 1
            while k >= 0 and out[k].isspace():
                k -= 1
            prev = out[k] if k >= 0 else ""
            m = k - 1
            while m >= 0 and out[m].isspace():
                m -= 1
            before = out[m] if m >= 0 else ""
            if prev in "eE" and (not before or not (before.isalnum() or before == "_")):
                raise ValueError("escape string E'...' is not supported by strip_sql")
            j = i + 1
            while True:
                if j >= n:
                    raise ValueError("unterminated string literal")
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append("''")
            i = j + 1
        elif c == "$" and _DOLLAR_TAG.match(text, i):
            raise ValueError("dollar-quoted string is not supported by strip_sql")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def statements(text):
    """Split stripped SQL into statements (no dollar-quoted bodies are used in this repo)."""
    body = strip_sql(text)
    parts = body.split(";")
    stmts = [p.strip() for p in parts[:-1] if p.strip()]
    tail = parts[-1].strip()
    return stmts, tail


def norm(sql):
    return re.sub(r"\s+", " ", sql).strip()
