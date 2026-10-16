"""The instance catalog, ``src/plugin/data/catalog.json``, and the hashed locks beside it: what each
real upstream upgrade is and how it is judged. Built and validated by ``plugin.tools_dev.onboard``;
read here by the tools and the verifier alike (the verifier reads the plugin's own folder)."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "plugin" / "data"
CATALOG = DATA / "catalog.json"


@lru_cache(maxsize=1)
def load():
    """The whole catalog: ``{"version", "instances": [entry, ...]}``."""
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("instances"), list):
        raise TypeError("the catalog is malformed")
    return data


def ids():
    return [entry["id"] for entry in load()["instances"]]


def entry(instance_id):
    """The catalog entry for ``instance_id`` (a string); raises ValueError for an unknown one."""
    for item in load()["instances"]:
        if item["id"] == instance_id:
            return item
    raise ValueError(f"unknown instance {instance_id!r}")


def entry_sha256(item):
    """sha256 of the entry's canonical JSON: the answer key and the judge record it."""
    text = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def lock_text(item, which):
    """The text of the instance's ``base`` or ``gold`` lock, checked against its recorded sha256."""
    locks = item["locks"]
    text = (DATA / locks[which]).read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != locks[f"{which}_sha256"]:
        raise ValueError(f"the {which} lock of {item['id']} does not match its recorded sha256")
    return text


def ids_sha256(test_ids):
    """sha256 over the sorted test ids, one per line: names the set the judge ran."""
    return hashlib.sha256("".join(f"{test}\n" for test in sorted(test_ids)).encode("utf-8")).hexdigest()


def hidden_digest(files):
    """sha256 over the hidden test files' sorted ``path\\0sha256`` lines."""
    return hashlib.sha256("".join(f"{path}\0{sha}\n" for path, sha in sorted(files.items())).encode("utf-8")).hexdigest()
