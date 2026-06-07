from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import subprocess
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
                return templates.TemplateResponse(
                    "result.html",
                    {
                        "request": request,
                        "review": "Only Python (.py) files are allowed.",
                        "score": "0",
                        "errors": 1,
                        "warnings": 0,
                        "conventions": 0,
                        "status": "Invalid",
                        "suggestions": ["Upload a valid Python file."],
                        "highlighted_code": "",
                        "css_style": ""
                    }
                )

            file_path = os.path.join(UPLOAD_FOLDER, codefile.filename)
            file_bytes = await codefile.read()

            with open(file_path, "wb") as file:
                file.write(file_bytes)

            with open(file_path, "r", encoding="utf-8") as file:
                code_content = file.read()
        else:
            file_path = os.path.join(UPLOAD_FOLDER, "sample.py")
            code_content = code.replace("\r\n", "\n")

            with open(file_path, "w", encoding="utf-8", newline="\n") as file:
                file.write(code_content)

        result = subprocess.run(
            ["pylint", file_path],
            capture_output=True,
            text=True
        )

        review_output = result.stdout
        score_match = re.search(r"rated at\s+([-\d\.]+)/10", review_output)
        score = score_match.group(1) if score_match else "0.0"

        errors = len(re.findall(r": E\d+", review_output))
        warnings = len(re.findall(r": W\d+", review_output))
        conventions = len(re.findall(r": C\d+", review_output))

        score_value = float(score)
        if score_value >= 8:
            status = "Excellent"
        elif score_value >= 6:
            status = "Good"
        elif score_value >= 4:
            status = "Needs Improvement"
        else:
            status = "Poor"

        suggestions = []
        if "missing-function-docstring" in review_output:
            suggestions.append("Add docstrings to explain your functions.")
        if "missing-module-docstring" in review_output:
            suggestions.append("Add a module description at the top of the file.")
        if "missing-final-newline" in review_output:
            suggestions.append("Add a newline at the end of the file.")
        if errors == 0 and warnings == 0 and conventions == 0:
            suggestions.append("Excellent code quality. No major issues found.")

        highlighted_code = highlight(
            code_content,
            PythonLexer(),
            HtmlFormatter(style="monokai")
        )
        css_style = HtmlFormatter(style="monokai").get_style_defs(".highlight")

        with open("reports/review_history.txt", "a", encoding="utf-8") as log:
            log.write(f"\n{{'=' * 60}}\n")
            log.write(f"{datetime.now()}\n")
            log.write(f"Score: {score}/10\n")
            log.write(review_output)
            log.write("\n\n")

        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "review": review_output,
                "score": score,
                "errors": errors,
                "warnings": warnings,
                "conventions": conventions,
                "status": status,
                "suggestions": suggestions,
                "highlighted_code": highlighted_code,
                "css_style": css_style
            }
        )
    except Exception as error:
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "review": str(error),
                "score": "0",
                "errors": 1,
                "warnings": 0,
                "conventions": 0,
                "status": "Error",
                "suggestions": ["An unexpected error occurred."],
                "highlighted_code": "",
                "css_style": ""
            }
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, log_level="info")
