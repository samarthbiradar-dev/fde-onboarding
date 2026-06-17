#!/usr/bin/env python3
import os
import sys
from collections import defaultdict


def format_size(bytes_count):
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 ** 2:
        return f"{bytes_count / 1024:.1f} KB"
    elif bytes_count < 1024 ** 3:
        return f"{bytes_count / 1024 ** 2:.2f} MB"
    else:
        return f"{bytes_count / 1024 ** 3:.2f} GB"


def analyze_folder(folder_path):
    if not os.path.isdir(folder_path):
        print(f"Error: '{folder_path}' is not a valid directory.")
        sys.exit(1)

    total_size = 0
    file_count = 0
    largest_file = ("", 0)
    type_stats = defaultdict(lambda: {"count": 0, "size": 0})

    for root, _, files in os.walk(folder_path):
        for name in files:
            full_path = os.path.join(root, name)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue

            file_count += 1
            total_size += size

            if size > largest_file[1]:
                largest_file = (full_path, size)

            ext = os.path.splitext(name)[1].lstrip(".").lower() or "no extension"
            type_stats[ext]["count"] += 1
            type_stats[ext]["size"] += size

    print(f"\nFolder: {os.path.abspath(folder_path)}")
    print("=" * 50)
    print(f"Total files : {file_count:,}")
    print(f"Total size  : {format_size(total_size)}")

    if largest_file[0]:
        rel = os.path.relpath(largest_file[0], folder_path)
        print(f"Largest file: {rel} ({format_size(largest_file[1])})")

    print("\nBreakdown by file type:")
    print(f"  {'Extension':<16} {'Count':>6}  {'Size':>10}  {'% of total':>10}")
    print(f"  {'-'*16}  {'-'*6}  {'-'*10}  {'-'*10}")

    sorted_types = sorted(type_stats.items(), key=lambda x: x[1]["size"], reverse=True)
    for ext, stats in sorted_types:
        pct = (stats["size"] / total_size * 100) if total_size else 0
        print(f"  {ext:<16}  {stats['count']:>6,}  {format_size(stats['size']):>10}  {pct:>9.1f}%")

    print()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    analyze_folder(path)
