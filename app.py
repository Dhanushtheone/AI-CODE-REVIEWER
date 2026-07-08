"""PyLens — AI-powered Python code reviewer with DS/ML/security analysis."""
import asyncio
import ast
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from datetime import datetime

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from groq import Groq
from pygments import highlight
from pygments.lexers import PythonLexer  # pylint: disable=no-name-in-module
from pygments.formatters import HtmlFormatter  # pylint: disable=no-name-in-module

from config import GROQ_API_KEY
from lab_report import generate_lab_report

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

UPLOAD_FOLDER = "uploads"
REPORT_FOLDER = "reports"
MATLAB_PATH = shutil.which("matlab")

# Forces UTF-8 for every Python subprocess we spawn to run student code. Without
# this, Windows can default a piped (non-console) child's stdout to the ANSI
# codepage (cp1252), which crashes with UnicodeEncodeError on anything outside
# that codepage — emoji, most non-English scripts, even some "smart quotes".
SUBPROCESS_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)

try:
    # MATLAB Engine officially supports Python 3.9-3.12 and warns on newer versions;
    # verified working correctly on 3.13, so the warning is just noise here.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="matlab")
        import matlab.engine as matlab_engine_mod
    MatlabExecutionError = matlab_engine_mod.MatlabExecutionError
except ImportError:
    matlab_engine_mod = None
    MatlabExecutionError = Exception  # placeholder; never raised since the engine stays unavailable

MATLAB_ENGINE = None
MATLAB_ENGINE_LOCK = asyncio.Lock()
_matlab_engine_ready = threading.Event()
MATLAB_SHIM_DIR = os.path.abspath("matlab_shims")


def _boot_matlab_engine():
    """Starts one warm MATLAB session in the background so later runs skip the ~10-60s startup cost."""
    global MATLAB_ENGINE  # pylint: disable=global-statement
    try:
        MATLAB_ENGINE = matlab_engine_mod.start_matlab("-nodesktop -nosplash")
        # Shadows the built-in waitfor with our own (see matlab_shims/waitfor.m):
        # student scripts that block waiting for a human to close a figure would
        # otherwise hang this shared session forever, since nobody is at the
        # server to close anything. The override captures+closes instead.
        MATLAB_ENGINE.addpath(MATLAB_SHIM_DIR, nargout=0)
    except Exception:  # pylint: disable=broad-exception-caught
        MATLAB_ENGINE = None
    finally:
        _matlab_engine_ready.set()


if MATLAB_PATH and matlab_engine_mod is not None:
    threading.Thread(target=_boot_matlab_engine, daemon=True).start()
else:
    _matlab_engine_ready.set()

PEP_REFS = {
    "line-too-long":             {"pep": "PEP 8", "section": "Maximum Line Length", "url": "https://peps.python.org/pep-0008/#maximum-line-length", "tip": "Keep lines under 79 characters. Break long lines using parentheses or backslash."},
    "trailing-whitespace":       {"pep": "PEP 8", "section": "Whitespace in Expressions", "url": "https://peps.python.org/pep-0008/#whitespace-in-expressions-and-statements", "tip": "Remove trailing spaces at the end of lines. Most editors can do this automatically."},
    "missing-final-newline":     {"pep": "PEP 8", "section": "Source File Encoding", "url": "https://peps.python.org/pep-0008/#source-file-encoding", "tip": "Always end your file with a blank line (press Enter once at the very end)."},
    "missing-module-docstring":  {"pep": "PEP 257", "section": "Module Docstrings", "url": "https://peps.python.org/pep-0257/#multi-line-docstrings", "tip": 'Add a triple-quoted string at the top of the file explaining what the module does. Example: """This module handles user authentication."""'},
    "missing-class-docstring":   {"pep": "PEP 257", "section": "Class Docstrings", "url": "https://peps.python.org/pep-0257/#class-docstrings", "tip": 'Add a triple-quoted string right after the class definition line. Example: """Represents a user in the system."""'},
    "missing-function-docstring":{"pep": "PEP 257", "section": "Function Docstrings", "url": "https://peps.python.org/pep-0257/#one-line-docstrings", "tip": 'Add a triple-quoted string right after the def line. Example: """Calculate and return the total price."""'},
    "invalid-name":              {"pep": "PEP 8", "section": "Naming Conventions", "url": "https://peps.python.org/pep-0008/#naming-conventions", "tip": "Use snake_case for variables/functions (my_variable), PascalCase for classes (MyClass), and UPPER_CASE for constants (MAX_SIZE)."},
    "unused-import":             {"pep": "PEP 8", "section": "Imports", "url": "https://peps.python.org/pep-0008/#imports", "tip": "Remove imports you are not using in this file. Unused imports waste memory and confuse readers."},
    "unused-variable":           {"pep": "PEP 8", "section": "Programming Recommendations", "url": "https://peps.python.org/pep-0008/#programming-recommendations", "tip": "Either use the variable or remove it. If it's intentionally unused, prefix it with underscore: _unused."},
    "unused-argument":           {"pep": "PEP 8", "section": "Naming Conventions", "url": "https://peps.python.org/pep-0008/#naming-conventions", "tip": "If a function argument is not needed, prefix it with an underscore: def func(_unused_arg)."},
    "undefined-variable":        {"pep": "Python Basics", "section": "Variable Scope", "url": "https://docs.python.org/3/reference/executionmodel.html#naming-and-binding", "tip": "You're using a variable that hasn't been defined yet. Check for typos or make sure to assign a value before using it."},
    "pointless-statement":       {"pep": "PEP 8", "section": "Programming Recommendations", "url": "https://peps.python.org/pep-0008/#programming-recommendations", "tip": "This line does nothing — it evaluates an expression but doesn't store or use the result. Did you forget to assign it or call a function?"},
    "dangerous-default-value":   {"pep": "Python Gotchas", "section": "Mutable Default Arguments", "url": "https://docs.python.org/3/faq/programming.html#why-are-default-values-shared-between-objects", "tip": "Never use [] or {} as a default argument. Use None instead and create the list/dict inside the function body."},
    "consider-using-enumerate":  {"pep": "PEP 20", "section": "Pythonic Code", "url": "https://peps.python.org/pep-0020/", "tip": "Instead of range(len(items)), use enumerate(items) to get both index and value at once."},
    "no-self-use":               {"pep": "PEP 8", "section": "Class Design", "url": "https://peps.python.org/pep-0008/#class-names", "tip": "This method doesn't use 'self', so it could be a static method. Add @staticmethod decorator or move it outside the class."},
    "too-many-arguments":        {"pep": "PEP 8", "section": "Function Design", "url": "https://peps.python.org/pep-0008/#function-annotations", "tip": "Functions with too many arguments are hard to use. Group related parameters into a dataclass or dictionary."},
    "too-many-branches":         {"pep": "PEP 8", "section": "Code Complexity", "url": "https://peps.python.org/pep-0008/", "tip": "Too many if/elif branches make code hard to read. Consider breaking the function into smaller helper functions."},
    "redefined-outer-name":      {"pep": "PEP 8", "section": "Naming", "url": "https://peps.python.org/pep-0008/#naming-conventions", "tip": "You reused a name that already exists in an outer scope. Rename the inner variable to avoid confusion."},
    "broad-except":              {"pep": "PEP 8", "section": "Error Handling", "url": "https://peps.python.org/pep-0008/#programming-recommendations", "tip": "Avoid catching all exceptions with 'except Exception'. Catch specific exceptions like ValueError or TypeError instead."},
    "wildcard-import":           {"pep": "PEP 8", "section": "Imports", "url": "https://peps.python.org/pep-0008/#imports", "tip": "Avoid 'from module import *'. It pollutes the namespace and makes it unclear where names come from. Import explicitly."},
    "syntax-error":              {"pep": "Python Reference", "section": "Syntax", "url": "https://docs.python.org/3/reference/index.html", "tip": "Python cannot parse this code. Check for missing colons (:), mismatched parentheses, or incorrect indentation."},
    "indentation-error":         {"pep": "PEP 8", "section": "Indentation", "url": "https://peps.python.org/pep-0008/#indentation", "tip": "Python requires consistent indentation. Use 4 spaces per level (not tabs). Make sure all lines in a block are aligned."},
    "mixed-indentation":         {"pep": "PEP 8", "section": "Indentation", "url": "https://peps.python.org/pep-0008/#indentation", "tip": "Don't mix tabs and spaces. Configure your editor to always insert spaces when you press Tab."},
    "wrong-import-order":        {"pep": "PEP 8", "section": "Imports", "url": "https://peps.python.org/pep-0008/#imports", "tip": "Order imports as: 1) standard library, 2) third-party packages, 3) local modules. Separate each group with a blank line."},
    "reimported":                {"pep": "PEP 8", "section": "Imports", "url": "https://peps.python.org/pep-0008/#imports", "tip": "This module is imported more than once. Keep only the first import and remove the duplicate."},
    "comparison-to-none":        {"pep": "PEP 8", "section": "Programming Recommendations", "url": "https://peps.python.org/pep-0008/#programming-recommendations", "tip": "Use 'is None' or 'is not None' instead of '== None' or '!= None'."},
    "use-a-generator":           {"pep": "PEP 289", "section": "Generator Expressions", "url": "https://peps.python.org/pep-0289/", "tip": "Use a generator expression instead of a list comprehension when passing to sum(), any(), or all(). It's more memory-efficient."},
}

CATEGORY_META = {
    "E":   {"label": "Error",        "color": "#ef4444", "bg": "#fef2f2", "icon": "✕",  "desc": "Critical issues that will cause the program to fail or crash."},
    "W":   {"label": "Warning",      "color": "#f59e0b", "bg": "#fffbeb", "icon": "⚠",  "desc": "Potential problems that may cause unexpected behavior."},
    "C":   {"label": "Convention",   "color": "#3b82f6", "bg": "#eff6ff", "icon": "≡",  "desc": "Style violations against PEP 8 coding conventions."},
    "R":   {"label": "Refactor",     "color": "#8b5cf6", "bg": "#f5f3ff", "icon": "↻",  "desc": "Code that works but could be written in a cleaner way."},
    "I":   {"label": "Info",         "color": "#6b7280", "bg": "#f9fafb", "icon": "i",  "desc": "Informational messages about the code structure."},
    "DS":  {"label": "Data Science", "color": "#f97316", "bg": "#fff7ed", "icon": "⚡", "desc": "Data science anti-patterns that hurt performance or correctness."},
    "ML":  {"label": "ML Smell",     "color": "#ec4899", "bg": "#fdf2f8", "icon": "🧪", "desc": "Machine learning code smells that may lead to incorrect results."},
    "SEC": {"label": "Security",     "color": "#dc2626", "bg": "#fff1f2", "icon": "🔒", "desc": "Security vulnerabilities like hardcoded secrets or unsafe functions."},
}

BEGINNER_NAMES = {
    "line-too-long":              "Line Is Too Long",
    "missing-module-docstring":   "File Has No Description",
    "missing-function-docstring": "Function Has No Description",
    "missing-class-docstring":    "Class Has No Description",
    "invalid-name":               "Name Doesn't Follow Convention",
    "unused-import":              "Import Is Never Used",
    "unused-variable":            "Variable Is Never Used",
    "unused-argument":            "Function Argument Is Never Used",
    "undefined-variable":         "Variable Used Before Being Defined",
    "trailing-whitespace":        "Extra Spaces at End of Line",
    "missing-final-newline":      "File Doesn't End with a Newline",
    "dangerous-default-value":    "Risky Default Argument Value",
    "broad-except":               "Exception Is Too Broad",
    "wildcard-import":            "Wildcard Import Used",
    "syntax-error":               "Syntax Error — Code Cannot Run",
    "comparison-to-none":         "Wrong Way to Check for None",
    "wrong-import-order":         "Imports Are in Wrong Order",
    "pointless-statement":        "Statement Has No Effect",
}

# ── DS anti-pattern rules ─────────────────────────────────────────────────────
DS_RULES = [
    ("ds-iterrows",     r"\.iterrows\(\)",
     "Slow DataFrame Iteration",
     "iterrows() is extremely slow for large DataFrames",
     "Use vectorized operations, df.apply(), or df.itertuples() instead — up to 100x faster."),
    ("ds-df-append",    r"\bdf\.append\s*\(",
     "Deprecated DataFrame.append()",
     "DataFrame.append() was removed in pandas 2.0",
     "Use pd.concat([df, new_df], ignore_index=True) instead of df.append()."),
    ("ds-ix-accessor",  r"\.ix\[",
     "Removed .ix[] Accessor",
     "DataFrame.ix[] was removed in pandas 1.0",
     "Use .loc[] for label-based or .iloc[] for integer-based indexing."),
    ("ds-inplace",      r"inplace\s*=\s*True",
     "Avoid inplace=True",
     "inplace=True is slower in modern pandas and causes bugs with chained operations",
     "Prefer reassignment: df = df.dropna()  instead of  df.dropna(inplace=True)."),
    ("ds-read-csv-no-dtype", r"pd\.read_csv\s*\([^)]*\)(?!.*dtype)",
     "read_csv Without dtype Specified",
     "Not specifying dtype lets pandas guess column types, which is slow and error-prone",
     "Add dtype={'col': str} or use dtype=str to control type inference and speed up loading."),
]

# ── ML code smell rules ───────────────────────────────────────────────────────
ML_RULES = [
    ("ml-hardcoded-hyperparams",
     r"\b(n_estimators|max_depth|learning_rate|num_leaves|batch_size|epochs)\s*=\s*\d+",
     "Hardcoded Hyperparameter",
     "Hardcoded hyperparameters make experiments hard to tune and reproduce",
     "Define hyperparameters as named constants or a config dict at the top of your script."),
]

# ── Security rules ────────────────────────────────────────────────────────────
SEC_RULES = [
    ("sec-eval",           r"\beval\s*\(",
     "Unsafe eval() Usage",
     "eval() executes arbitrary code — critical security risk",
     "Never use eval() on external input. Use ast.literal_eval() for safe literal parsing."),
    ("sec-exec",           r"\bexec\s*\(",
     "Unsafe exec() Usage",
     "exec() executes arbitrary Python code strings",
     "Redesign your logic to avoid exec(). If required, ensure input is fully controlled."),
    ("sec-pickle",         r"pickle\.(load|loads)\s*\(",
     "Unsafe Pickle Deserialization",
     "Loading pickle from untrusted sources can execute arbitrary code",
     "Use JSON or safer formats. Only load pickle from trusted, internal sources."),
    ("sec-shell-true",     r"shell\s*=\s*True",
     "Shell Injection Risk",
     "subprocess with shell=True is vulnerable to shell injection attacks",
     "Use shell=False (default) and pass arguments as a list: subprocess.run(['cmd', 'arg'])."),
    ("sec-os-system",      r"\bos\.system\s*\(",
     "Unsafe os.system() Usage",
     "os.system() passes commands to the shell — injection risk",
     "Replace with subprocess.run(['cmd', 'arg'], check=True) for safety and error handling."),
    ("sec-hardcoded-secret",
     r'(?i)(?<!\w)(password|passwd|secret|api_key|token|apikey)\s*=\s*["\'][^"\']{4,}["\']',
     "Hardcoded Secret Detected",
     "Hardcoded credentials or secrets in source code are a major security risk",
     "Store secrets in environment variables: os.environ.get('SECRET') or use python-dotenv."),
]


def _make_issue(line_no: int, code_lines: list[str], symbol: str, category: str,
                message: str, friendly_name: str, tip: str) -> dict:
    meta = CATEGORY_META.get(category, CATEGORY_META["I"])
    idx = line_no - 1
    context = []
    for i in range(max(0, idx - 2), min(len(code_lines), idx + 3)):
        context.append({"number": i + 1, "content": code_lines[i].rstrip(), "is_error": i == idx})
    return {
        "line": line_no, "col": 0,
        "category": category, "code": symbol, "symbol": symbol,
        "message": message,
        "source_line": code_lines[idx].rstrip() if idx < len(code_lines) else "",
        "context": context,
        "pep": "", "pep_section": "", "pep_url": "",
        "tip": tip,
        "label": meta["label"], "color": meta["color"], "bg": meta["bg"], "icon": meta["icon"],
        "friendly_name": friendly_name,
        "ai_explanation": "",
    }


def extract_notebook_code(content: bytes) -> str:
    nb = json.loads(content)
    cells = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") == "code":
            src = cell.get("source", [])
            if isinstance(src, list):
                src = "".join(src)
            if src.strip():
                cells.append(f"# ── Notebook Cell {i + 1} ──\n{src}")
    return "\n\n".join(cells)


def parse_history() -> list[dict]:
    path = os.path.join(REPORT_FOLDER, "review_history.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    entries = []
    for block in re.split(r"={40,}", content):
        block = block.strip()
        if not block:
            continue
        dm = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", block)
        sm = re.search(r"Score:\s*([-\d.]+)/10\s*\|\s*Issues:\s*(\d+)", block)
        if dm and sm:
            entries.append({
                "date":   dm.group(1),
                "score":  float(sm.group(1)),
                "issues": int(sm.group(2)),
            })
    return entries


NLP_LIBRARIES = r"nltk|spacy|transformers|textblob|gensim|vaderSentiment|sentence_transformers"


def detect_language(code: str) -> str:
    """Best-effort detection of whether a snippet is Python, NLP-flavored Python, or MATLAB source."""
    try:
        ast.parse(code)
        if re.search(rf"\b(?:import|from)\s+({NLP_LIBRARIES})\b", code, re.IGNORECASE):
            return "nlp"
        return "python"
    except SyntaxError:
        pass

    matlab_score = 0
    python_score = 0
    for raw_line in code.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("%"):
            matlab_score += 1
        elif line.startswith("#"):
            python_score += 1
        if re.match(r"(function|endfunction|endif|endfor|endwhile|elseif)\b", line):
            matlab_score += 2
        if re.search(r";\s*(%.*)?$", line):
            matlab_score += 1
        if re.match(r"(def |import |from |class |print\()", line):
            python_score += 2

    return "matlab" if matlab_score > python_score else "python"


def detect_ds_antipatterns(code: str, code_lines: list[str]) -> list[dict]:
    if not re.search(r'\bimport\s+pandas\b|from\s+pandas\b', code):
        return []
    issues = []
    seen = set()
    for symbol, pattern, friendly, message, tip in DS_RULES:
        for idx, line in enumerate(code_lines):
            line_stripped = line.strip()
            if line_stripped.startswith("#"):
                continue
            if re.search(pattern, line) and (symbol, idx) not in seen:
                seen.add((symbol, idx))
                issues.append(_make_issue(idx + 1, code_lines, symbol, "DS", message, friendly, tip))
    return issues


def detect_ml_smells(code: str, code_lines: list[str]) -> list[dict]:
    has_sklearn = bool(re.search(r'\bimport\s+sklearn\b|from\s+sklearn\b', code))
    has_tf      = bool(re.search(r'\bimport\s+tensorflow\b|from\s+tensorflow\b|import\s+keras\b|from\s+keras\b', code))
    has_torch   = bool(re.search(r'\bimport\s+torch\b|from\s+torch\b', code))
    if not (has_sklearn or has_tf or has_torch):
        return []

    issues = []
    seen_symbols = set()

    # Hardcoded hyperparameters (flag first occurrence only)
    sym, pattern, friendly, message, tip = ML_RULES[0]
    for idx, line in enumerate(code_lines):
        if line.strip().startswith("#"):
            continue
        if re.search(pattern, line) and sym not in seen_symbols:
            seen_symbols.add(sym)
            issues.append(_make_issue(idx + 1, code_lines, sym, "ML", message, friendly, tip))

    # train_test_split without random_state
    for idx, line in enumerate(code_lines):
        if re.search(r'train_test_split\s*\(', line):
            block = "\n".join(code_lines[idx: min(len(code_lines), idx + 6)])
            if "random_state" not in block and "ml-no-random-state" not in seen_symbols:
                seen_symbols.add("ml-no-random-state")
                issues.append(_make_issue(
                    idx + 1, code_lines,
                    "ml-no-random-state", "ML",
                    "train_test_split called without random_state — results won't be reproducible",
                    "Missing random_state in train_test_split",
                    "Add random_state=42 to get the same train/test split every run: "
                    "train_test_split(X, y, test_size=0.2, random_state=42)",
                ))

    # Possible data leakage: .fit() appears before train_test_split
    fit_line = next((i for i, line in enumerate(code_lines) if re.search(r'(?<!\w)fit\s*\(', line)
                     and not line.strip().startswith("#")), None)
    split_line = next((i for i, line in enumerate(code_lines) if re.search(r'train_test_split\s*\(', line)
                       and not line.strip().startswith("#")), None)
    if fit_line is not None and split_line is not None and fit_line < split_line:
        issues.append(_make_issue(
            fit_line + 1, code_lines,
            "ml-data-leakage", "ML",
            "Model/scaler .fit() called before train_test_split — possible data leakage",
            "Possible Data Leakage",
            "Always call train_test_split() first, then fit your scaler/model ONLY on X_train.",
        ))

    return issues


def detect_security_issues(code_lines: list[str]) -> list[dict]:
    issues = []
    seen_symbols = set()
    for symbol, pattern, friendly, message, tip in SEC_RULES:
        for idx, line in enumerate(code_lines):
            if line.strip().startswith("#"):
                continue
            if re.search(pattern, line) and symbol not in seen_symbols:
                seen_symbols.add(symbol)
                issues.append(_make_issue(idx + 1, code_lines, symbol, "SEC", message, friendly, tip))
    return issues


def get_ai_explanations(code: str, issues: list[dict]) -> dict:
    if not GROQ_API_KEY or not issues:
        return {}
    pylint_issues = [i for i in issues if i["category"] in ("E", "W", "C", "R", "I")]
    if not pylint_issues:
        return {}
    unique = {}
    for issue in pylint_issues:
        sym = issue["symbol"]
        if sym not in unique:
            unique[sym] = {"message": issue["message"], "line": issue["line"], "context": issue.get("source_line", "")}
    issues_text = "\n".join(
        f'- {sym}: {data["message"]} (line {data["line"]}): `{data["context"]}`'
        for sym, data in unique.items()
    )
    prompt = (
        "You are a Python code review assistant helping a beginner developer.\n\n"
        "Analyze this Python code and the Pylint issues found in it.\n\n"
        f"```python\n{code[:3000]}\n```\n\n"
        f"Pylint found these issues:\n{issues_text}\n\n"
        "For each issue symbol, write exactly 2 sentences:\n"
        "1. What the issue means in this specific code context.\n"
        "2. The exact change the developer should make to fix it.\n\n"
        "Respond ONLY with a valid JSON object where keys are the issue symbols "
        "and values are the explanation strings. No markdown, no extra text."
    )
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1024,
        )
        text = response.choices[0].message.content.strip()
        m = re.search(r"\{[\s\S]+\}", text)
        if m:
            text = m.group(0)
        return json.loads(text)
    except Exception:  # pylint: disable=broad-exception-caught
        return {}


def get_code_summary(code: str) -> str:
    if not GROQ_API_KEY or not code.strip():
        return ""
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                "Summarize what this Python code does in 2-3 plain English sentences. "
                "Be specific about what it accomplishes (e.g. 'loads a CSV, filters rows where salary > 50k, "
                "adds a bonus column, and prints the top earners'). "
                "Target audience: beginner data science student. No bullet points.\n\n"
                f"```python\n{code[:3000]}\n```"
            )}],
            temperature=0.3,
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except Exception:  # pylint: disable=broad-exception-caught
        return ""


def parse_pylint_output(output: str, code_lines: list[str]) -> list[dict]:
    pattern = re.compile(
        r"^(.+?):(\d+):(\d+):\s+([EWCRI])(\d+):\s+(.+?)\s+\(([a-z][a-z0-9-]+)\)\s*$",
        re.MULTILINE
    )
    issues = []
    for match in pattern.finditer(output):
        _, line_no, col_no, cat, code_num, message, symbol = match.groups()
        line_idx = int(line_no) - 1
        source_line = code_lines[line_idx].rstrip() if 0 <= line_idx < len(code_lines) else ""
        context_lines = []
        for i in range(max(0, line_idx - 2), min(len(code_lines), line_idx + 3)):
            context_lines.append({"number": i + 1, "content": code_lines[i].rstrip(), "is_error": i == line_idx})
        full_code = cat + code_num
        ref  = PEP_REFS.get(symbol, {})
        meta = CATEGORY_META.get(cat, CATEGORY_META["I"])
        issues.append({
            "line":          int(line_no),
            "col":           int(col_no),
            "category":      cat,
            "code":          full_code,
            "symbol":        symbol,
            "message":       message.strip(),
            "source_line":   source_line,
            "context":       context_lines,
            "pep":           ref.get("pep", ""),
            "pep_section":   ref.get("section", ""),
            "pep_url":       ref.get("url", ""),
            "tip":           ref.get("tip", ""),
            "label":         meta["label"],
            "color":         meta["color"],
            "bg":            meta["bg"],
            "icon":          meta["icon"],
            "friendly_name": BEGINNER_NAMES.get(symbol, symbol.replace("-", " ").title()),
        })
    return issues


def build_tree(issues: list[dict]) -> dict:
    tree = {}
    for cat, meta in CATEGORY_META.items():
        cat_issues = [i for i in issues if i["category"] == cat]
        if not cat_issues:
            continue
        by_symbol: dict = {}
        for issue in cat_issues:
            sym = issue["symbol"]
            if sym not in by_symbol:
                by_symbol[sym] = {
                    "name": issue["friendly_name"], "symbol": sym,
                    "findings": [], "color": meta["color"],
                    "pep": issue["pep"], "pep_url": issue["pep_url"],
                }
            by_symbol[sym]["findings"].append(issue)
        tree[cat] = {
            "label": meta["label"], "color": meta["color"], "bg": meta["bg"],
            "icon": meta["icon"], "desc": meta["desc"],
            "count": len(cat_issues), "groups": list(by_symbol.values()),
        }
    return tree


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/review", response_class=HTMLResponse)
async def review(
    request: Request,
    code: str = Form(""),
    codefile: UploadFile | None = File(None)
):
    try:
        is_notebook = False

        if codefile and codefile.filename:
            fname = codefile.filename
            if not (fname.endswith(".py") or fname.endswith(".ipynb")):
                return templates.TemplateResponse("result.html", {
                    "request": request, "error_msg": "Only .py and .ipynb files are supported.",
                    "issues": [], "tree": {}, "score": "0", "errors": 0, "warnings": 0,
                    "conventions": 0, "refactors": 0, "ds_issues": 0, "ml_issues": 0,
                    "sec_issues": 0, "status": "Invalid", "highlighted_code": "",
                    "css_style": "", "total_lines": 0, "total_issues": 0,
                    "code_summary": "", "score_pct": 0, "code_content_json": "\"\"",
                    "issues_summary_json": "\"\"",
                })
            file_bytes = await codefile.read()
            if fname.endswith(".ipynb"):
                is_notebook = True
                code_content = extract_notebook_code(file_bytes)
            else:
                code_content = file_bytes.decode("utf-8")
            safe_name = re.sub(r"[^\w.]", "_", fname)
            file_path = os.path.join(UPLOAD_FOLDER, safe_name if safe_name.endswith(".py") else safe_name + ".py")
            with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(code_content)
        else:
            file_path    = os.path.join(UPLOAD_FOLDER, "sample.py")
            code_content = code.replace("\r\n", "\n")
            with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(code_content)

        code_lines = code_content.splitlines()

        # Run the code and capture output. run_in_executor for both calls below:
        # subprocess.run() blocks its thread until the child exits, and calling it
        # directly in this async route would freeze the whole event loop — every
        # other concurrent request (Live Output runs, other users) would stall
        # until this one finishes.
        loop = asyncio.get_event_loop()
        try:
            _t0 = time.time()
            exec_result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [sys.executable, file_path],
                    capture_output=True, encoding="utf-8", errors="replace", timeout=10,
                    check=False, env=SUBPROCESS_ENV,
                ),
            )
            exec_time   = round(time.time() - _t0, 3)
            code_stdout = exec_result.stdout
            code_stderr = exec_result.stderr
        except subprocess.TimeoutExpired:
            code_stdout = ""
            code_stderr = "Execution timed out after 10 seconds."
            exec_time   = 10.0

        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [
                    sys.executable, "-m", "pylint", file_path,
                    "--output-format=text", "--score=yes",
                    "--ignored-modules=pandas,numpy,sklearn,matplotlib,seaborn,"
                    "torch,tensorflow,keras,scipy,statsmodels,cv2,plotly,xgboost,lightgbm",
                ],
                capture_output=True, encoding="utf-8", errors="replace", check=False, env=SUBPROCESS_ENV,
            ),
        )
        review_output = result.stdout

        score_match = re.search(r"rated at\s+([-\d\.]+)/10", review_output)
        score       = score_match.group(1) if score_match else "0.0"
        score_value = float(score)

        pylint_issues = parse_pylint_output(review_output, code_lines)
        ds_found      = detect_ds_antipatterns(code_content, code_lines)
        ml_found      = detect_ml_smells(code_content, code_lines)
        sec_found     = detect_security_issues(code_lines)

        all_issues = pylint_issues + ds_found + ml_found + sec_found

        ai_explanations = get_ai_explanations(code_content, pylint_issues)
        for issue in all_issues:
            issue["ai_explanation"] = ai_explanations.get(issue["symbol"], "")

        code_summary = get_code_summary(code_content)

        tree = build_tree(all_issues)

        errors      = sum(1 for i in pylint_issues if i["category"] == "E")
        warnings    = sum(1 for i in pylint_issues if i["category"] == "W")
        conventions = sum(1 for i in pylint_issues if i["category"] == "C")
        refactors   = sum(1 for i in pylint_issues if i["category"] == "R")
        ds_count    = len(ds_found)
        ml_count    = len(ml_found)
        sec_count   = len(sec_found)

        if score_value >= 8:
            status = "Excellent"
        elif score_value >= 6:
            status = "Good"
        elif score_value >= 4:
            status = "Needs Improvement"
        else:
            status = "Poor"

        highlighted_code = highlight(code_content, PythonLexer(), HtmlFormatter(style="monokai", linenos="table"))
        css_style        = HtmlFormatter(style="monokai", linenos="table").get_style_defs(".highlight")

        with open(os.path.join(REPORT_FOLDER, "review_history.txt"), "a", encoding="utf-8") as log:
            log.write("\n" + "=" * 60 + "\n")
            log.write(f"{datetime.now()}\n")
            log.write(f"Score: {score}/10 | Issues: {len(all_issues)}\n")
            log.write(review_output + "\n\n")

        issues_summary = "\n".join(
            f"- {i['symbol']}: {i['message']} (line {i['line']})"
            for i in all_issues
        )

        return templates.TemplateResponse("result.html", {
            "request":             request,
            "issues":              all_issues,
            "tree":                tree,
            "score":               score,
            "score_pct":           score_value * 10,
            "errors":              errors,
            "warnings":            warnings,
            "conventions":         conventions,
            "refactors":           refactors,
            "ds_issues":           ds_count,
            "ml_issues":           ml_count,
            "sec_issues":          sec_count,
            "status":              status,
            "highlighted_code":    highlighted_code,
            "css_style":           css_style,
            "total_lines":         len(code_lines),
            "total_issues":        len(all_issues),
            "code_summary":        code_summary,
            "is_notebook":         is_notebook,
            "error_msg":           "",
            "code_stdout":         code_stdout,
            "code_stderr":         code_stderr,
            "exec_time":           exec_time,
            "code_content_json":   json.dumps(code_content),
            "issues_summary_json": json.dumps(issues_summary),
        })

    except Exception as exc:  # pylint: disable=broad-exception-caught
        return templates.TemplateResponse("result.html", {
            "request": request, "error_msg": str(exc),
            "issues": [], "tree": {}, "score": "0", "score_pct": 0,
            "errors": 0, "warnings": 0, "conventions": 0, "refactors": 0,
            "ds_issues": 0, "ml_issues": 0, "sec_issues": 0,
            "status": "Error", "highlighted_code": "", "css_style": "",
            "total_lines": 0, "total_issues": 0, "code_summary": "",
            "is_notebook": False, "code_stdout": "", "code_stderr": str(exc),
            "exec_time": 0, "code_content_json": "\"\"",
            "issues_summary_json": "\"\"",
        })


@app.post("/api/autofix")
async def api_autofix(request: Request):
    if not GROQ_API_KEY:
        return JSONResponse({"error": "Groq API key not configured."}, status_code=400)
    try:
        data         = await request.json()
        code         = data.get("code", "")
        issues_text  = data.get("issues_text", "")
        if not code.strip():
            return JSONResponse({"error": "No code provided."}, status_code=400)
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                "You are a Python code fixer. Fix ALL of the listed issues in the code below. "
                "Return ONLY the corrected Python code — no explanations, no markdown fences.\n\n"
                f"Issues to fix:\n{issues_text}\n\n"
                f"Original code:\n```python\n{code[:4000]}\n```\n\n"
                "Fixed Python code:"
            )}],
            temperature=0.2,
            max_tokens=2048,
        )
        fixed = response.choices[0].message.content.strip()
        fixed = re.sub(r"^```python\s*", "", fixed)
        fixed = re.sub(r"\s*```$", "", fixed)
        return JSONResponse({"fixed_code": fixed})
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/docstrings")
async def api_docstrings(request: Request):
    if not GROQ_API_KEY:
        return JSONResponse({"error": "Groq API key not configured."}, status_code=400)
    try:
        data = await request.json()
        code = data.get("code", "")
        if not code.strip():
            return JSONResponse({"error": "No code provided."}, status_code=400)
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": (
                "Add Google-style docstrings to all functions, classes, and the module in this Python code. "
                "Return ONLY the complete Python code with docstrings added — no explanations, no markdown.\n\n"
                f"```python\n{code[:4000]}\n```\n\n"
                "Python code with docstrings:"
            )}],
            temperature=0.2,
            max_tokens=2048,
        )
        result = response.choices[0].message.content.strip()
        result = re.sub(r"^```python\s*", "", result)
        result = re.sub(r"\s*```$", "", result)
        return JSONResponse({"code": result})
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/lab_report")
async def api_lab_report(request: Request):
    image_path = None
    try:
        data = await request.json()
        code = data.get("code", "")
        if not code.strip():
            return JSONResponse({"error": "No code provided."}, status_code=400)
        output_text = data.get("output", "")
        error_text = data.get("error", "")
        combined_output = output_text + (f"\n{error_text}" if error_text else "")
        language = (data.get("language") or "Python").lower()
        code_type = "matlab" if language == "matlab" else ("nlp" if language == "nlp" else "python")

        image_b64 = data.get("image_base64")
        if image_b64:
            image_path = tempfile.mktemp(suffix="_lab_report_plot.png")
            with open(image_path, "wb") as img_f:
                img_f.write(base64.b64decode(image_b64))

        report_path = os.path.join(REPORT_FOLDER, f"lab_report_{int(time.time())}.pdf")
        generate_lab_report(code_type, code, combined_output, image_path=image_path, output_path=report_path)
        return FileResponse(report_path, filename="lab_report.pdf", media_type="application/pdf")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JSONResponse({"error": str(exc)}, status_code=500)
    finally:
        if image_path:
            try:
                os.unlink(image_path)
            except OSError:
                pass


@app.post("/api/run")
async def api_run(request: Request):
    global MATLAB_ENGINE  # pylint: disable=global-statement
    try:
        data = await request.json()
        code = data.get("code", "").strip()
        if not code:
            return JSONResponse({"output": "", "error": "", "exec_time": 0, "language": ""})

        language = detect_language(code)

        if language == "matlab":
            if not MATLAB_PATH:
                return JSONResponse({
                    "output": "", "error": "MATLAB was detected but is not installed on this server.",
                    "exec_time": 0, "language": "MATLAB",
                })
            with tempfile.NamedTemporaryFile(mode="w", suffix=".m", delete=False, encoding="utf-8") as f:
                f.write(code)
                tmp_path = f.name
            script_path = tmp_path.replace(os.sep, "/")
            try:
                start = time.time()

                # Wait (once) for the warm engine to finish its one-time boot, so we
                # don't fall back to a cold `matlab -batch` process unnecessarily.
                if not _matlab_engine_ready.is_set():
                    await asyncio.get_event_loop().run_in_executor(
                        None, _matlab_engine_ready.wait, 120)

                if MATLAB_ENGINE is not None:
                    # Route through MATLAB's own `diary` file logging rather than the
                    # engine API's stdout=/stderr= capture — the latter has proven
                    # unreliable (silently returns empty output) once the engine is
                    # driven from a worker thread under uvicorn's event loop.
                    log_path = tempfile.mktemp(suffix="_matlab_log.txt").replace(os.sep, "/")
                    img_path = tempfile.mktemp(suffix="_matlab_plot.png").replace(os.sep, "/")
                    wrapper_code = (
                        f"diary('{log_path}'); diary on;\n"
                        f"setappdata(0, 'PylensCapturePath', '{img_path}');\n"
                        f"try\n"
                        f"  run('{script_path}');\n"
                        f"  pylensErr = '';\n"
                        f"catch pylensExc\n"
                        f"  pylensErr = getReport(pylensExc);\n"
                        f"end\n"
                        # Scripts that call waitfor() already got captured+closed by our
                        # waitfor shim (matlab_shims/waitfor.m). This covers the more
                        # common case: a script that just plots and returns normally,
                        # leaving the figure open with nothing having captured it yet.
                        # Known limitation: live per-frame animations (a loop that does
                        # h.SomeProperty = X; drawnow; repeatedly) reliably fail with
                        # "Invalid or deleted object" partway through when driven via
                        # the persistent Engine API — reproduced even with no wrapper/
                        # nesting and with -nodisplay, so it isn't something in this
                        # file. Static single-shot plots (surf/mesh/plot) and waitfor
                        # scripts are unaffected and capture correctly.
                        f"try\n"
                        f"  pylensFigs = findall(0, 'Type', 'figure');\n"
                        f"  if ~isempty(pylensFigs)\n"
                        f"    exportgraphics(pylensFigs(1), '{img_path}', 'Resolution', 150);\n"
                        f"    close(pylensFigs);\n"
                        f"  end\n"
                        f"catch\n"
                        f"end\n"
                        f"setappdata(0, 'PylensCapturePath', '');\n"
                        f"diary off;\n"
                    )
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".m", delete=False, encoding="utf-8") as wf:
                        wf.write(wrapper_code)
                        wrapper_path = wf.name.replace(os.sep, "/")

                    def _run_on_engine():
                        MATLAB_ENGINE.eval(f"run('{wrapper_path}')", nargout=0)
                        return MATLAB_ENGINE.workspace["pylensErr"]

                    engine_broken = False
                    try:
                        async with MATLAB_ENGINE_LOCK:
                            try:
                                stderr_text = await asyncio.get_event_loop().run_in_executor(None, _run_on_engine)
                            except MatlabExecutionError as exc:
                                # A normal script-level failure (syntax/runtime error in the
                                # user's own code) — the engine session itself is fine.
                                stderr_text = str(exc)
                            except Exception:  # pylint: disable=broad-exception-caught
                                # The engine session itself broke (not the user's script).
                                # Self-heal: drop it and reboot in the background so the
                                # NEXT request gets a fresh warm engine instead of this one
                                # failing forever for the rest of a demo/presentation.
                                engine_broken = True
                                stderr_text = (
                                    "The MATLAB session hit an internal error and is restarting "
                                    "in the background — try running this again in ~15-20 seconds."
                                )
                        stdout_text = (
                            open(log_path, encoding="utf-8", errors="replace").read()
                            if os.path.exists(log_path) else ""
                        )
                        image_base64 = (
                            base64.b64encode(open(img_path, "rb").read()).decode("ascii")
                            if os.path.exists(img_path) else None
                        )
                        returncode = 1 if stderr_text else 0
                    finally:
                        for path in (wrapper_path, log_path, img_path):
                            try:
                                os.unlink(path)
                            except OSError:
                                pass
                        if engine_broken:
                            MATLAB_ENGINE = None  # pylint: disable=invalid-name
                            _matlab_engine_ready.clear()
                            threading.Thread(target=_boot_matlab_engine, daemon=True).start()
                    elapsed = round(time.time() - start, 3)
                    return JSONResponse({
                        "output":       stdout_text,
                        "error":        stderr_text,
                        "returncode":   returncode,
                        "exec_time":    elapsed,
                        "language":     "MATLAB",
                        "image_base64": image_base64,
                    })

                # Warm engine unavailable — fall back to a cold, one-off MATLAB process.
                # run_in_executor for the same reason as the Python path above: this
                # call blocks for up to 90s, which would otherwise freeze every other
                # concurrent request on the server.
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(
                        [MATLAB_PATH, "-batch", f"run('{script_path}')"],
                        capture_output=True, encoding="utf-8", errors="replace", timeout=90,
                        check=False,
                    ),
                )
                elapsed = round(time.time() - start, 3)
                return JSONResponse({
                    "output":      result.stdout,
                    "error":       result.stderr,
                    "returncode":  result.returncode,
                    "exec_time":   elapsed,
                    "language":    "MATLAB",
                })
            except subprocess.TimeoutExpired:
                return JSONResponse({
                    "output": "", "error": "Timed out after 90 seconds.", "returncode": -1,
                    "exec_time": 90, "language": "MATLAB",
                })
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        exec_label   = "NLP" if language == "nlp" else "Python"
        # NLP libraries (nltk/spacy/textblob corpora, etc.) can take 40+ seconds to
        # import cold — 45s cut it dangerously close in testing, so this leaves
        # real margin rather than risking a mid-demo timeout.
        exec_timeout = 75 if language == "nlp" else 30

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name

        # If the script uses matplotlib, run it through a small wrapper that forces
        # the non-interactive Agg backend and redirects plt.show() to a file save —
        # a plt.show() with no real display would otherwise hang/no-op here, and we
        # want the plotted figure available for the lab report either way. The user
        # code itself is untouched and compiled with its own real path, so tracebacks
        # still report the correct filename/line numbers.
        uses_matplotlib = re.search(r"\bmatplotlib\b", code) is not None
        exec_target = tmp_path
        wrapper_path = None
        img_path = tempfile.mktemp(suffix="_py_plot.png") if uses_matplotlib else None
        if uses_matplotlib:
            wrapper_code = (
                "import matplotlib as _pylens_mpl\n"
                "_pylens_mpl.use('Agg')\n"
                "import matplotlib.pyplot as _pylens_plt\n"
                "def _pylens_show(*_a, **_k):\n"
                "    _fig = _pylens_plt.gcf()\n"
                f"    _fig.savefig({img_path!r}, dpi=150, bbox_inches='tight')\n"
                "    _pylens_plt.close('all')\n"
                "_pylens_plt.show = _pylens_show\n"
                f"with open({tmp_path!r}, encoding='utf-8') as _pylens_f:\n"
                "    _pylens_src = _pylens_f.read()\n"
                f"exec(compile(_pylens_src, {tmp_path!r}, 'exec'), {{'__name__': '__main__'}})\n"
            )
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as wf:
                wf.write(wrapper_code)
                wrapper_path = wf.name
            exec_target = wrapper_path

        try:
            start = time.time()
            stdin_data = data.get("stdin", "")
            # run_in_executor: subprocess.run() blocks its calling thread until the
            # child exits. Called directly, that would freeze the whole asyncio
            # event loop — meaning every other request (a concurrent MATLAB run,
            # even an unrelated page load) would stall until this one finishes.
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [sys.executable, exec_target],
                    input=stdin_data,
                    capture_output=True, encoding="utf-8", errors="replace", timeout=exec_timeout,
                    check=False, env=SUBPROCESS_ENV,
                ),
            )
            elapsed = round(time.time() - start, 3)
            image_base64 = (
                base64.b64encode(open(img_path, "rb").read()).decode("ascii")
                if img_path and os.path.exists(img_path) else None
            )
            stderr_text = result.stderr
            needs_more_stdin = "EOFError: EOF when reading a line" in stderr_text
            if needs_more_stdin:
                # input() ran out of lines to read — near-guaranteed cause is that
                # the stdin box didn't have (enough) values for this script, not a
                # bug in the script or the runner. Lead with that instead of a raw
                # EOFError traceback few students will recognize.
                stderr_text = (
                    "This program called input() but ran out of values to read.\n"
                    "Add the value(s) it needs in the 'Program Input (stdin)' box "
                    "above (one per line), then run again.\n\n" + stderr_text
                )
            return JSONResponse({
                "output":          result.stdout,
                "error":           stderr_text,
                "returncode":      result.returncode,
                "exec_time":       elapsed,
                "language":        exec_label,
                "image_base64":    image_base64,
                "needs_more_stdin": needs_more_stdin,
            })
        except subprocess.TimeoutExpired:
            return JSONResponse({
                "output": "", "error": f"Timed out after {exec_timeout} seconds.", "returncode": -1,
                "exec_time": exec_timeout, "language": exec_label,
            })
        finally:
            for path in (tmp_path, wrapper_path, img_path):
                if not path:
                    continue
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JSONResponse({"output": "", "error": str(exc), "exec_time": 0}, status_code=500)


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    entries = parse_history()
    avg_score  = round(sum(e["score"] for e in entries) / len(entries), 2) if entries else 0
    best_score = max((e["score"] for e in entries), default=0)
    return templates.TemplateResponse("history.html", {
        "request":       request,
        "entries":       entries,
        "entry_count":   len(entries),
        "avg_score":     avg_score,
        "best_score":    best_score,
        "total_issues":  sum(e["issues"] for e in entries),
        "dates_json":    json.dumps([e["date"][:10] for e in entries]),
        "scores_json":   json.dumps([e["score"]  for e in entries]),
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, log_level="info")
