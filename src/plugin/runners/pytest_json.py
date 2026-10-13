"""A pytest plugin that records every test's outcome as JSON: loaded with ``-p``, no dependencies.

Copied into each run folder as ``nanoagent_pytest_json.py``. Outcomes are ``passed``, ``failed``,
``skipped``, ``error`` (setup or teardown failed), ``xfailed`` and ``xpassed``; collection errors
are kept apart, by the node that failed to collect.
"""

import json


def pytest_addoption(parser):
    parser.addoption("--nanoagent-json", action="store", default=None, help="where to write the JSON record")


def _first_line(longrepr):
    crash = getattr(longrepr, "reprcrash", None)
    message = getattr(crash, "message", None)
    if not message:
        lines = [line for line in str(longrepr).strip().splitlines() if line.strip()]
        message = lines[-1] if lines else ""
    return message.strip()[:300]


class Recorder:
    def __init__(self, path):
        self.path = path
        self.collected = []
        self.outcomes = {}
        self.messages = {}
        self.collection_errors = {}

    def pytest_collection_modifyitems(self, session, config, items):
        self.collected = [item.nodeid for item in items]

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_errors[report.nodeid or "."] = _first_line(report.longrepr)

    def pytest_runtest_logreport(self, report):
        outcome = None
        if report.when == "call":
            outcome = report.outcome
            if hasattr(report, "wasxfail"):
                outcome = "xfailed" if report.outcome == "skipped" else "xpassed"
        elif report.when == "setup":
            if report.outcome == "failed":
                outcome = "error"
            elif report.outcome == "skipped":
                outcome = "xfailed" if hasattr(report, "wasxfail") else "skipped"
        elif report.when == "teardown" and report.outcome == "failed":
            outcome = "error"
        if outcome is None:
            return
        self.outcomes[report.nodeid] = outcome
        if outcome in ("failed", "error"):
            self.messages[report.nodeid] = _first_line(report.longrepr)

    def pytest_sessionfinish(self, session, exitstatus):
        record = {
            "exit_status": int(exitstatus),
            "collected": self.collected,
            "outcomes": self.outcomes,
            "messages": self.messages,
            "collection_errors": self.collection_errors,
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=1, sort_keys=True)


def pytest_configure(config):
    path = config.getoption("--nanoagent-json")
    if path:
        config.pluginmanager.register(Recorder(path), "nanoagent-json-recorder")
