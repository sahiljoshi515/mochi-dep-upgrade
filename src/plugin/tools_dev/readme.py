"""Rewrite the README's instance table (between the instances markers) from the catalog.

    uv run python -m plugin.tools_dev.readme
"""

from __future__ import annotations

import sys
from pathlib import Path

from verifier import catalog

README = Path(__file__).resolve().parents[3] / "README.md"
START, END = "<!-- instances -->", "<!-- /instances -->"


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
            f"| [{item['upstream']['commit'][:10]}]({item['upstream']['url']}): {len(item['gold']['files'])} files, +{item['gold']['added_lines']} lines "
            f"| {item.get('fit', 'local')} |"
        )
    return "\n".join(rows)


def main() -> int:
    text = README.read_text(encoding="utf-8")
    start, end = text.index(START) + len(START), text.index(END)
    README.write_text(text[:start] + "\n" + table() + "\n" + text[end:], encoding="utf-8")
    print(f"{len(catalog.load()['instances'])} instances written to the README")
    return 0


if __name__ == "__main__":
    sys.exit(main())
