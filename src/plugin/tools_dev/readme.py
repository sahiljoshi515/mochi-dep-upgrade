"""Rewrite the README's instance table (between the instances markers) from the catalog.

    uv run python -m plugin.tools_dev.readme
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from verifier import catalog

README = Path(__file__).resolve().parents[3] / "README.md"
REJECTED = Path(__file__).resolve().parent / "rejected.json"
START, END = "<!-- instances -->", "<!-- /instances -->"
REJECTED_START, REJECTED_END = "<!-- rejected -->", "<!-- /rejected -->"


def files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


def table() -> str:
    rows = [
        "| Instance | Repository (licence) | Upgrade | Judged tests: public / hidden | Upstream's change | Fit |",
        "|---|---|---|---|---|---|",
    ]
    for item in catalog.load()["instances"]:
        excluded = len(item["public"]["excluded"])
        rows.append(
            f"| `{item['id']}` | [{item['repo']}](https://github.com/{item['repo']}) ({item['license']}) "
            f"| {item['dependency']} {item['from_version']} → {item['target_version']} (Python {item['python']}) "
            f"| {len(item['public']['ids'])} ({excluded} excluded) / {len(item['hidden']['ids'])} "
            f"| [{item['upstream']['commit'][:10]}]({item['upstream']['url']}): {files(len(item['gold']['files']))}, +{item['gold']['added_lines']} lines "
            f"| {item.get('fit', 'local')} |"
        )
    return "\n".join(rows)


def rejected_table() -> str:
    rows = ["| Candidate | Upgrade | Why it is not offered |", "|---|---|---|"]
    for item in json.loads(REJECTED.read_text(encoding="utf-8")):
        rows.append(f"| [{item['repo']}](https://github.com/{item['repo']}/commit/{item['upstream_commit']}) | {item['dependency']} | {item['reason']} |")
    return "\n".join(rows)


def replace(text: str, start_mark: str, end_mark: str, body: str) -> str:
    start, end = text.index(start_mark) + len(start_mark), text.index(end_mark)
    return text[:start] + "\n" + body + "\n" + text[end:]


def main() -> int:
    text = README.read_text(encoding="utf-8")
    text = replace(text, START, END, table())
    text = replace(text, REJECTED_START, REJECTED_END, rejected_table())
    README.write_text(text, encoding="utf-8")
    print(f"{len(catalog.load()['instances'])} instances written to the README")
    return 0


if __name__ == "__main__":
    sys.exit(main())
