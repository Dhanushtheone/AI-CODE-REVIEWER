from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import subprocess
import sys
import os
import re
from datetime import datetime
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

UPLOAD_FOLDER = "uploads"
REPORT_FOLDER = "reports"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)

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
    "E": {"label": "Error",      "color": "#ef4444", "bg": "#fef2f2", "icon": "✕", "desc": "Critical issues that will cause the program to fail or crash."},
    "W": {"label": "Warning",    "color": "#f59e0b", "bg": "#fffbeb", "icon": "⚠", "desc": "Potential problems that may cause unexpected behavior."},
    "C": {"label": "Convention", "color": "#3b82f6", "bg": "#eff6ff", "icon": "≡", "desc": "Style violations against PEP 8 coding conventions."},
    "R": {"label": "Refactor",   "color": "#8b5cf6", "bg": "#f5f3ff", "icon": "↻", "desc": "Code that works but could be written in a cleaner way."},
    "I": {"label": "Info",       "color": "#6b7280", "bg": "#f9fafb", "icon": "i", "desc": "Informational messages about the code structure."},
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


def parse_pylint_output(output: str, code_lines: list[str]) -> list[dict]:
    # symbol is always the LAST parenthesized token (lowercase-hyphenated)
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
            context_lines.append({
                "number": i + 1,
                "content": code_lines[i].rstrip(),
                "is_error": i == line_idx
            })
        full_code = cat + code_num
        ref = PEP_REFS.get(symbol, {})
        meta = CATEGORY_META.get(cat, CATEGORY_META["I"])
        issues.append({
            "line":         int(line_no),
            "col":          int(col_no),
            "category":     cat,
            "code":         full_code,
            "symbol":       symbol,
            "message":      message.strip(),
            "source_line":  source_line,
            "context":      context_lines,
            "pep":          ref.get("pep", ""),
            "pep_section":  ref.get("section", ""),
            "pep_url":      ref.get("url", ""),
            "tip":          ref.get("tip", ""),
            "label":        meta["label"],
            "color":        meta["color"],
            "bg":           meta["bg"],
            "icon":         meta["icon"],
            "friendly_name": BEGINNER_NAMES.get(symbol, symbol.replace("-", " ").title()),
        })
    return issues


def build_tree(issues: list[dict]) -> dict:
    tree = {}
    for cat, meta in CATEGORY_META.items():
        cat_issues = [i for i in issues if i["category"] == cat]
        if not cat_issues:
            continue
        by_symbol = {}
        for issue in cat_issues:
            sym = issue["symbol"]
            if sym not in by_symbol:
                by_symbol[sym] = {"name": issue["friendly_name"], "symbol": sym, "findings": [], "color": meta["color"], "pep": issue["pep"], "pep_url": issue["pep_url"]}
            by_symbol[sym]["findings"].append(issue)
        tree[cat] = {
            "label":  meta["label"],
            "color":  meta["color"],
            "bg":     meta["bg"],
            "icon":   meta["icon"],
            "desc":   meta["desc"],
            "count":  len(cat_issues),
            "groups": list(by_symbol.values()),
        }
    return tree


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
        if codefile and codefile.filename:
            if not codefile.filename.endswith(".py"):
                return templates.TemplateResponse("result.html", {
                    "request": request, "error_msg": "Only Python (.py) files are allowed.",
                    "issues": [], "tree": {}, "score": "0", "errors": 0,
                    "warnings": 0, "conventions": 0, "refactors": 0, "status": "Invalid",
                    "highlighted_code": "", "css_style": "", "total_lines": 0,
                })
            file_path = os.path.join(UPLOAD_FOLDER, codefile.filename)
            file_bytes = await codefile.read()
            with open(file_path, "wb") as f:
                f.write(file_bytes)
            with open(file_path, "r", encoding="utf-8") as f:
                code_content = f.read()
        else:
            file_path = os.path.join(UPLOAD_FOLDER, "sample.py")
            code_content = code.replace("\r\n", "\n")
            with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(code_content)

        code_lines = code_content.splitlines()

        result = subprocess.run(
            [sys.executable, "-m", "pylint", file_path, "--output-format=text", "--score=yes"],
            capture_output=True, text=True
        )
        review_output = result.stdout

        score_match = re.search(r"rated at\s+([-\d\.]+)/10", review_output)
        score = score_match.group(1) if score_match else "0.0"
        score_value = float(score)

        issues = parse_pylint_output(review_output, code_lines)
        tree = build_tree(issues)

        errors      = sum(1 for i in issues if i["category"] == "E")
        warnings    = sum(1 for i in issues if i["category"] == "W")
        conventions = sum(1 for i in issues if i["category"] == "C")
        refactors   = sum(1 for i in issues if i["category"] == "R")

        if score_value >= 8:
            status = "Excellent"
        elif score_value >= 6:
            status = "Good"
        elif score_value >= 4:
            status = "Needs Improvement"
        else:
            status = "Poor"

        highlighted_code = highlight(code_content, PythonLexer(), HtmlFormatter(style="monokai", linenos="table"))
        css_style = HtmlFormatter(style="monokai", linenos="table").get_style_defs(".highlight")

        with open("reports/review_history.txt", "a", encoding="utf-8") as log:
            log.write("\n" + "=" * 60 + "\n")
            log.write(f"{datetime.now()}\n")
            log.write(f"Score: {score}/10 | Issues: {len(issues)}\n")
            log.write(review_output + "\n\n")

        return templates.TemplateResponse("result.html", {
            "request":          request,
            "issues":           issues,
            "tree":             tree,
            "score":            score,
            "score_pct":        score_value * 10,
            "errors":           errors,
            "warnings":         warnings,
            "conventions":      conventions,
            "refactors":        refactors,
            "status":           status,
            "highlighted_code": highlighted_code,
            "css_style":        css_style,
            "total_lines":      len(code_lines),
            "total_issues":     len(issues),
            "error_msg":        "",
        })

    except Exception as exc:
        return templates.TemplateResponse("result.html", {
            "request": request, "error_msg": str(exc),
            "issues": [], "tree": {}, "score": "0", "score_pct": 0,
            "errors": 0, "warnings": 0, "conventions": 0, "refactors": 0,
            "status": "Error", "highlighted_code": "", "css_style": "",
            "total_lines": 0, "total_issues": 0,
        })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, log_level="info")
