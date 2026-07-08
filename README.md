# AI Code Reviewer

A web-based Python code review tool that analyzes code quality, detects issues, and provides actionable suggestions using pylint and FastAPI.

## Overview

AI Code Reviewer is a modern web application designed to help developers improve their Python code quality. It provides instant feedback on code structure, style, and best practices through an intuitive web interface.

## Features

✨ **Core Features:**
- 🔍 **Python Code Analysis** - Comprehensive analysis using pylint
- ⭐ **Quality Scoring** - Rate code from 0-10
- 🐛 **Issue Detection** - Identify errors, warnings, and convention violations
- 💡 **Smart Suggestions** - Get actionable recommendations for improvement
- 🎨 **Syntax Highlighting** - Beautiful code display with Monokai theme
- 📤 **Flexible Input** - Upload `.py` files or paste code directly
- 📊 **Review History** - Track all reviews in a persistent log
- 🚀 **Fast & Responsive** - Real-time analysis with modern UI

## Project Structure

```
.
├── app.py                    # Main FastAPI application
├── config.py                 # Configuration (API keys, settings)
├── lab_report.py             # College lab report PDF generation
├── setup_matlab_engine.py    # One-time MATLAB engine build/install (optional)
├── matlab_shims/
│   └── waitfor.m             # Overrides waitfor() so scripts don't hang the server
├── pyproject.toml            # Project metadata and dependencies
├── README.md                 # This file
├── project.spec              # PyInstaller specification
├── reviews.txt               # Review records
├── test_groq.py              # Testing utilities
├── static/
│   ├── style.css             # Custom styling
│   └── vendor/codemirror/    # Self-hosted code editor (syntax highlighting, autocomplete)
├── templates/
│   ├── index.html            # Home page with upload/paste interface
│   └── result.html           # Results display page
├── uploads/                  # Temporary uploaded files
└── reports/
    └── review_history.txt    # Review history log
```

## Technology Stack

- **Backend**: FastAPI 0.109.1
- **Server**: Uvicorn 0.23.2
- **Code Analysis**: Pylint 4.0.5
- **Syntax Highlighting**: Pygments 2.16.1
- **Templates**: Jinja2 3.1.6
- **Frontend**: Bootstrap 5.3.3
- **Python**: 3.13+

## Installation

### Prerequisites
- Python 3.13 or higher
- pip or uv package manager

### Setup

1. **Clone/Navigate to the project:**
   ```bash
   cd "AI Code Reviewer"
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -e .
   ```
   
   Or using uv (recommended — also installs the spaCy English model, declared
   directly in `pyproject.toml` so it can't get silently dropped by a sync):
   ```bash
   uv sync
   ```

4. **(Optional) Enable MATLAB support:**

   MATLAB's Engine API for Python isn't a normal PyPI package — it ships bundled
   inside your MATLAB installation and has to be built from there directly, so
   `uv sync` can't install it on its own. If you have MATLAB installed (R2025b
   was used to build/test this), run:
   ```bash
   uv run python setup_matlab_engine.py
   ```
   This is safe to skip — Python and NLP code are unaffected either way, and
   MATLAB code will still run even without it (falling back to a fresh
   `matlab -batch` process per request), just slower (~30-90s startup per run
   instead of a warm, persistent session) and without plot image capture or
   safe handling of `waitfor()`-style scripts. Re-run this script any time the
   `.venv` is recreated, or after upgrading to a different MATLAB release (the
   engine binary is version-locked to the MATLAB release it ships with).

## Running the Application

Start the development server:

```bash
uvicorn app:app --reload
```

The application will be available at `http://localhost:8000`

## Usage

### Web Interface

1. **Open the Application**: Navigate to `http://localhost:8000`

2. **Review Code** - Choose one of two methods:
   - **Upload**: Click to upload a Python file (`.py` extension required)
   - **Paste**: Paste Python code directly into the text area

3. **Submit**: Click "Review Code" to analyze

4. **View Results**:
   - **Score**: Overall code quality rating (0-10)
   - **Status**: Excellent, Good, Needs Improvement, or Poor
   - **Metrics**: Count of errors, warnings, and convention violations
   - **Suggestions**: Specific recommendations for improvement
   - **Highlighted Code**: Formatted code with syntax highlighting

### Review History

All reviews are logged to `reports/review_history.txt` with:
- Timestamp
- Quality score
- Full pylint output
- Analysis details

## API Endpoints

### `GET /`
Returns the home page with upload interface

### `POST /review`
Analyzes code and returns results

**Parameters:**
- `code` (string): Python code to review (optional)
- `codefile` (file): Python file upload (optional)

**Returns:**
- HTML page with analysis results

## Score Interpretation

| Score | Status | Meaning |
|-------|--------|---------|
| 8-10 | Excellent | High-quality, well-written code |
| 6-8 | Good | Solid code with minor issues |
| 4-6 | Needs Improvement | Several issues to address |
| 0-4 | Poor | Significant issues requiring fixes |

## Common Issues Detected

- Missing docstrings on functions and modules
- Missing final newlines
- Naming convention violations
- Unused imports and variables
- Code complexity issues
- Style guideline violations

## Configuration

Edit `config.py` to customize:
- API keys
- Application settings
- Integration parameters

## Development

### Running Tests
```bash
python test_groq.py
```

### Building Executable
```bash
pyinstaller project.spec
```

## Future Enhancements

- Integration with AI models for enhanced suggestions
- Support for multiple programming languages
- Team collaboration features
- Custom rule configuration
- Detailed refactoring suggestions
- Performance profiling

## License

MIT License - Feel free to use and modify for your projects

## Support

For issues, suggestions, or contributions, please refer to the code comments or review the application logs.

---

**Version**: 0.1.0  
**Status**: Alpha  
**Last Updated**: 2026