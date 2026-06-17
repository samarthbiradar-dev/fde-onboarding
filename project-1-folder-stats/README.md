# Project 1 — Folder Stats CLI

A Python CLI tool that analyzes a folder and reports file counts, total size, largest file, and a breakdown by file type.

## Features

- Total file count
- Total size (auto-scales: B / KB / MB / GB)
- Largest file with relative path
- Breakdown by extension — sorted by size, with percentage of total
- Recursively walks all subdirectories
- Gracefully skips unreadable files

## Usage

```bash
python3 folder_stats.py <path>
```

**Examples:**

```bash
# Analyze your Downloads folder
python3 folder_stats.py ~/Downloads

# Analyze current directory
python3 folder_stats.py .

# Analyze a specific path
python3 folder_stats.py /Users/you/Documents
```

## Sample Output

```
Folder: /Users/you/Downloads
==================================================
Total files : 13
Total size  : 200.81 MB
Largest file: GitHubDesktop-arm64.zip (174.34 MB)

Breakdown by file type:
  Extension         Count        Size  % of total
  ----------------  ------  ----------  ----------
  zip                    2   198.11 MB       98.7%
  pdf                    6     1.88 MB        0.9%
  docx                   1    657.0 KB        0.3%
```

## Requirements

- Python 3.6+
- No external dependencies (standard library only)
