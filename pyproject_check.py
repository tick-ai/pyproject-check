#!/usr/bin/env python3
"""pyproject-check: what is wrong with your pyproject.toml, before you build or publish.

Reads a pyproject.toml with the standard library's tomllib, applies the rules of the
pyproject-check job (docs/the-job.md) and prints every finding with the TOML key it is at.
Python 3.11, standard library only. It writes no file.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import stat
import sys
import tomllib
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path
from typing import Any, NamedTuple, TextIO

TOOL = "pyproject-check"
VERSION = "0.1.0"
DEFAULT_PATH = "pyproject.toml"

WS = " \t"
LEVELS = ("error", "warning", "none")

RULE_SEVERITY = {
    "unknown-table": "error",
    "unknown-key": "error",
    "missing-key": "error",
    "wrong-type": "error",
    "invalid-name": "error",
    "name-not-normalized": "warning",
    "invalid-version": "error",
    "invalid-specifier": "error",
    "invalid-requirement": "error",
    "invalid-extra-name": "error",
    "duplicate-extra": "error",
    "invalid-description": "error",
    "invalid-readme": "error",
    "file-not-found": "error",
    "invalid-license": "error",
    "license-table-deprecated": "warning",
    "invalid-person": "error",
    "invalid-object-reference": "error",
    "invalid-entry-name": "error",
    "reserved-entry-point-group": "error",
    "invalid-dynamic": "error",
    "dynamic-conflict": "error",
    "duplicate-dependency": "warning",
    "pinned-library-dependency": "warning",
}

TOP_LEVEL_KEYS = ("build-system", "project", "dependency-groups", "tool")

PROJECT_KEYS = (
    "name", "version", "description", "readme", "requires-python", "license",
    "license-files", "authors", "maintainers", "keywords", "classifiers", "urls",
    "scripts", "gui-scripts", "entry-points", "dependencies", "optional-dependencies",
    "dynamic",
)

DYNAMIC_ALLOWED = (
    "version", "description", "readme", "requires-python", "license", "license-files",
    "authors", "maintainers", "keywords", "classifiers", "urls", "scripts",
    "gui-scripts", "entry-points", "dependencies", "optional-dependencies",
)

README_EXTENSIONS = (".md", ".rst", ".txt")
README_CONTENT_TYPES = ("text/markdown", "text/x-rst", "text/plain")
RESERVED_GROUPS = ("console_scripts", "gui_scripts")

MARKER_VARIABLES = (
    "python_version", "python_full_version", "os_name", "sys_platform",
    "platform_release", "platform_system", "platform_version", "platform_machine",
    "platform_python_implementation", "implementation_name", "implementation_version",
    "extra",
)
MARKER_OPERATORS = ("<=", "<", ">=", ">", "==", "!=", "~=", "===")
SPECIFIER_OPERATORS = ("===", "==", "~=", "!=", "<=", ">=", "<", ">")
ASCII_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
MARKER_WORD_START = ASCII_LETTERS + "_"
MARKER_WORD_CHARS = ASCII_LETTERS + "0123456789_."
SPDX_OPERATORS = ("AND", "OR", "WITH")

_NAME = r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?"
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_DOTTED = _IDENT + r"(\." + _IDENT + r")*"

NAME_RE = re.compile(_NAME)
BARE_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")
OBJECT_REFERENCE_RE = re.compile(_DOTTED + "(:" + _DOTTED + ")?")
SCRIPT_REFERENCE_RE = re.compile(_DOTTED + ":" + _DOTTED)
ENTRY_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+")
GROUP_NAME_RE = re.compile(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*")
EMAIL_RE = re.compile(r"[^\s@<>,]+@[^\s@<>,]+")
URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:[^ \t]+")
NORMALIZE_RE = re.compile(r"[-_.]+")
SPDX_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*\+?")
SPDX_EXCEPTION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")
SPDX_TOKEN_RE = re.compile(r"[A-Za-z0-9.+-]+")
TRIPLE_EQUAL_VERSION_RE = re.compile(r"[^ \t,;()]+")
# The version pattern of the job, with one capture group around the release.
VERSION_RE = re.compile(
    r"v?(?:(?:[0-9]+!)?([0-9]+(?:\.[0-9]+)*)"
    r"(?:[-_.]?(?:alpha|a|beta|b|preview|pre|c|rc)[-_.]?[0-9]*)?"
    r"(?:-[0-9]+|[-_.]?(?:post|rev|r)[-_.]?[0-9]*)?"
    r"(?:[-_.]?dev[-_.]?[0-9]*)?)"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?",
    re.IGNORECASE,
)
VERSION_PREFIX_RE = re.compile(r"v?(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*\.\*", re.IGNORECASE)

USAGE = "Usage: python3 pyproject_check.py [path] [--json] [--fail-on error|warning|none] [--help]"
HELP = USAGE + """

Finds what is wrong in a pyproject.toml and says, for each finding, the key it is at.

  path               the file to check (default: pyproject.toml); at most one
  --json             print one JSON document instead of the plain form
  --fail-on <level>  the lowest severity that makes the exit status 1:
                     error (the default), warning or none
  --help             print this text and exit 0

Exit status: 0 nothing at --fail-on or above, 1 at least one finding at --fail-on
or above, 2 a usage error or a file that cannot be read or parsed.
"""


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    path: str
    message: str


class Report:
    """Collects findings; one rule gives at most one finding for one path."""

    def __init__(self) -> None:
        self._found: dict[tuple[str, str], Finding] = {}

    def add(self, rule: str, path: str, message: str) -> None:
        self._found.setdefault((path, rule), Finding(rule, RULE_SEVERITY[rule], path, message))

    def ordered(self) -> list[Finding]:
        return sorted(self._found.values(), key=attrgetter("path", "rule"))


def format_key(key: str) -> str:
    if BARE_KEY_RE.fullmatch(key):
        return key
    return '"' + key.replace("\\", "\\\\").replace('"', '\\"') + '"'


def join_path(parent: str, key: str) -> str:
    return format_key(key) if parent == "" else parent + "." + format_key(key)


def normalize_name(name: str) -> str:
    return NORMALIZE_RE.sub("-", name).lower()


def describe(value: Any) -> str:
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, int):
        return "an integer"
    if isinstance(value, float):
        return "a float"
    if isinstance(value, list):
        return "an array"
    if isinstance(value, dict):
        return "a table"
    if isinstance(value, datetime.datetime):
        return "a datetime"
    if isinstance(value, datetime.date):
        return "a date"
    if isinstance(value, datetime.time):
        return "a time"
    return "a value of another type"


def has_type(report: Report, path: str, value: Any, expected: type, label: str) -> bool:
    """True when value has the TOML type; otherwise reports wrong-type at path."""
    if isinstance(value, expected):
        return True
    report.add("wrong-type", path, f"expected {label}, found {describe(value)}")
    return False


def string_items(report: Report, path: str, value: Any) -> list[tuple[int, str]]:
    """Checks an array of strings; returns the (index, string) pairs that are strings."""
    if not has_type(report, path, value, list, "an array"):
        return []
    items: list[tuple[int, str]] = []
    for index, item in enumerate(value):
        if has_type(report, f"{path}[{index}]", item, str, "a string"):
            items.append((index, item))
    return items


# ---------------------------------------------------------------------------
# Grammars: specifier sets, markers, requirements, SPDX expressions
# ---------------------------------------------------------------------------

def check_specifier_version(operator: str, version: str) -> str:
    """Returns '' when the version is valid after the operator, else the problem."""
    if version == "":
        return f"expected a version after {operator!r}"
    if operator == "===":
        if TRIPLE_EQUAL_VERSION_RE.fullmatch(version):
            return ""
        return f"{version!r} is not a valid arbitrary version after '==='"
    if operator in ("==", "!="):
        if VERSION_RE.fullmatch(version) or VERSION_PREFIX_RE.fullmatch(version):
            return ""
        return f"{version!r} is not a PEP 440 version or a prefix like '1.2.*' after {operator!r}"
    match = VERSION_RE.fullmatch(version)
    if match is None or "+" in version:
        return f"{version!r} is not a PEP 440 version without a local part after {operator!r}"
    if operator == "~=" and len(match.group(1).split(".")) < 2:
        return f"{version!r} needs at least two release numbers after '~='"
    return ""


def parse_specifier_set(text: str) -> tuple[tuple[tuple[str, str], ...], str]:
    """Returns (specifiers as (operator, version) pairs, problem); problem is '' when valid."""
    specifiers: list[tuple[str, str]] = []
    for piece in text.split(","):
        piece = piece.strip(WS)
        if piece == "":
            return (), "empty specifier"
        operator = next((op for op in SPECIFIER_OPERATORS if piece.startswith(op)), "")
        if operator == "":
            return (), f"specifier {piece!r} does not start with an operator"
        version = piece[len(operator):].lstrip(WS)
        problem = check_specifier_version(operator, version)
        if problem:
            return (), problem
        specifiers.append((operator, version))
    return tuple(specifiers), ""


def tokenize_marker(text: str) -> tuple[list[tuple[str, str]], str]:
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in WS:
            i += 1
        elif c in "()":
            tokens.append(("paren", c))
            i += 1
        elif c in "'\"":
            end = text.find(c, i + 1)
            if end < 0:
                return [], "unterminated string"
            tokens.append(("string", text[i + 1:end]))
            i = end + 1
        elif c in "<>=!~":
            j = i
            while j < n and text[j] in "<>=!~":
                j += 1
            tokens.append(("operator", text[i:j]))
            i = j
        elif c in MARKER_WORD_START:
            j = i + 1
            while j < n and text[j] in MARKER_WORD_CHARS:
                j += 1
            tokens.append(("word", text[i:j]))
            i = j
        else:
            return [], f"unexpected character {c!r}"
    return tokens, ""


def is_marker_value(token: tuple[str, str]) -> bool:
    kind, text = token
    return kind == "string" or (kind == "word" and text in MARKER_VARIABLES)


def check_marker(text: str) -> str:
    """Returns '' when the marker is valid, else the problem."""
    tokens, problem = tokenize_marker(text)
    if problem:
        return problem
    if not tokens:
        return "empty marker"
    n = len(tokens)
    depth = 0
    i = 0
    expect_atom = True
    while i < n:
        kind, text_ = tokens[i]
        if expect_atom:
            if kind == "paren" and text_ == "(":
                depth += 1
                i += 1
                continue
            if not is_marker_value(tokens[i]):
                return f"expected a quoted string or a marker variable, found {text_!r}"
            i += 1
            if i >= n:
                return "the comparison is incomplete"
            kind, text_ = tokens[i]
            if kind == "operator" and text_ in MARKER_OPERATORS:
                i += 1
            elif kind == "word" and text_ == "in":
                i += 1
            elif kind == "word" and text_ == "not" and i + 1 < n and tokens[i + 1] == ("word", "in"):
                i += 2
            else:
                return f"expected a comparison operator, found {text_!r}"
            if i >= n or not is_marker_value(tokens[i]):
                return "expected a quoted string or a marker variable after the operator"
            i += 1
            expect_atom = False
        elif kind == "paren" and text_ == ")":
            if depth == 0:
                return "unbalanced ')'"
            depth -= 1
            i += 1
        elif kind == "word" and text_ in ("and", "or"):
            expect_atom = True
            i += 1
        else:
            return f"expected 'and', 'or' or ')', found {text_!r}"
    if expect_atom:
        return "the marker ends where a comparison is expected"
    if depth:
        return "unclosed '('"
    return ""


class Requirement(NamedTuple):
    name: str
    extras: frozenset[str]
    specifiers: tuple[tuple[str, str], ...]
    marker: str


def parse_requirement(text: str) -> tuple[Requirement | None, str]:
    """Returns (requirement, '') when valid, else (None, problem)."""
    s = text.strip(WS)
    match = NAME_RE.match(s)
    if match is None:
        return None, "does not start with a package name"
    name = match.group(0)
    rest = s[match.end():].lstrip(WS)
    extras: set[str] = set()
    if rest.startswith("["):
        end = rest.find("]")
        if end < 0:
            return None, "the extras list is not closed with ']'"
        inner = rest[1:end]
        if inner.strip(WS) != "":
            for piece in inner.split(","):
                piece = piece.strip(WS)
                if NAME_RE.fullmatch(piece) is None:
                    return None, f"{piece!r} is not a valid extra name"
                extras.add(normalize_name(piece))
        rest = rest[end + 1:].lstrip(WS)
    specifiers: tuple[tuple[str, str], ...] = ()
    marker_text: str | None = None
    if rest == "":
        pass
    elif rest[0] == ";":
        marker_text = rest[1:]
    elif rest[0] == "@":
        url = rest[1:].lstrip(WS)
        url_match = URL_RE.match(url)
        if url_match is None:
            return None, "expected a URL like 'https://host/file.zip' after '@'"
        after = url[url_match.end():].lstrip(WS)
        if after == "":
            pass
        elif after[0] == ";":
            marker_text = after[1:]
        else:
            return None, "unexpected text after the URL"
    elif rest[0] == "(":
        end = rest.find(")")
        if end < 0:
            return None, "missing ')' after the version specifiers"
        specifiers, problem = parse_specifier_set(rest[1:end])
        if problem:
            return None, problem
        after = rest[end + 1:].lstrip(WS)
        if after == "":
            pass
        elif after[0] == ";":
            marker_text = after[1:]
        else:
            return None, "unexpected text after the version specifiers"
    elif rest[0] in "<>=!~":
        semicolon = rest.find(";")
        body = rest if semicolon < 0 else rest[:semicolon]
        specifiers, problem = parse_specifier_set(body)
        if problem:
            return None, problem
        if semicolon >= 0:
            marker_text = rest[semicolon + 1:]
    else:
        return None, f"unexpected text {rest!r} after the package name"
    marker = ""
    if marker_text is not None:
        marker = marker_text.strip(WS)
        if marker == "":
            return None, "empty marker after ';'"
        problem = check_marker(marker)
        if problem:
            return None, f"invalid marker: {problem}"
    return Requirement(name, frozenset(extras), specifiers, marker), ""


def tokenize_spdx(text: str) -> tuple[list[str], str]:
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in WS:
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        else:
            match = SPDX_TOKEN_RE.match(text, i)
            if match is None:
                return [], f"unexpected character {c!r}"
            tokens.append(match.group(0))
            i = match.end()
    return tokens, ""


def check_spdx(text: str) -> str:
    """Returns '' when text is a valid SPDX license expression (no list lookup), else the problem."""
    tokens, problem = tokenize_spdx(text)
    if problem:
        return problem
    if not tokens:
        return "empty expression"
    operators = {op.lower() for op in SPDX_OPERATORS}
    depth = 0
    # states: atom (a license or "(" is expected), after_id (id: operator, WITH or ")"),
    # exception (an exception id is expected), after (a compound is complete)
    state = "atom"
    for token in tokens:
        is_operator = token.lower() in operators
        if state == "atom":
            if token == "(":
                depth += 1
            elif SPDX_ID_RE.fullmatch(token) and not is_operator:
                state = "after_id"
            else:
                return f"expected a license identifier or '(', found {token!r}"
        elif state == "exception":
            if SPDX_EXCEPTION_RE.fullmatch(token) and not is_operator:
                state = "after"
            else:
                return f"expected a license exception identifier after WITH, found {token!r}"
        else:
            upper = token.upper()
            if token == ")":
                if depth == 0:
                    return "unbalanced ')'"
                depth -= 1
                state = "after"
            elif upper in ("AND", "OR"):
                state = "atom"
            elif upper == "WITH" and state == "after_id":
                state = "exception"
            else:
                return f"expected AND, OR or ')', found {token!r}"
    if state in ("atom", "exception"):
        return "the expression ends where a license identifier is expected"
    if depth:
        return "unclosed '('"
    return ""


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def check_requirements(report: Report, path: str, value: Any) -> list[tuple[str, Requirement]]:
    """Checks an array of requirement strings; returns the valid ones with their element path."""
    valid: list[tuple[str, Requirement]] = []
    for index, text in string_items(report, path, value):
        element = f"{path}[{index}]"
        requirement, problem = parse_requirement(text)
        if requirement is None:
            report.add("invalid-requirement", element, f"not a valid PEP 508 requirement: {text!r} ({problem})")
        else:
            valid.append((element, requirement))
    return valid


def check_duplicate_dependencies(report: Report, valid: list[tuple[str, Requirement]]) -> None:
    seen: set[tuple[str, frozenset[str], str]] = set()
    for element, requirement in valid:
        key = (normalize_name(requirement.name), requirement.extras, requirement.marker)
        if key in seen:
            report.add("duplicate-dependency", element,
                       f"the same dependency ({requirement.name!r}) is already listed earlier in this array")
        seen.add(key)


def file_exists(base_dir: Path, name: str) -> bool:
    try:
        return (base_dir / name).is_file()
    except (OSError, ValueError):
        return False


def check_build_system(report: Report, table: dict[str, Any]) -> None:
    path = "build-system"
    if "requires" not in table:
        report.add("missing-key", f"{path}.requires", "the required key 'requires' is missing")
    else:
        valid = check_requirements(report, f"{path}.requires", table["requires"])
        check_duplicate_dependencies(report, valid)
    if "build-backend" in table:
        backend_path = f"{path}.build-backend"
        backend = table["build-backend"]
        if has_type(report, backend_path, backend, str, "a string"):
            if OBJECT_REFERENCE_RE.fullmatch(backend) is None:
                report.add("invalid-object-reference", backend_path,
                           f"not a valid object reference: {backend!r}")
    if "backend-path" in table:
        string_items(report, f"{path}.backend-path", table["backend-path"])


def check_readme(report: Report, value: Any, base_dir: Path) -> None:
    path = "project.readme"
    if isinstance(value, str):
        if not value.lower().endswith(README_EXTENSIONS):
            report.add("invalid-readme", path, f"the readme file name must end in .md, .rst or .txt: {value!r}")
        if not file_exists(base_dir, value):
            report.add("file-not-found", path, f"readme file not found: {value!r}")
        return
    if not isinstance(value, dict):
        has_type(report, path, value, str, "a string or a table")
        return
    for key in value:
        if key not in ("file", "text", "content-type"):
            report.add("unknown-key", join_path(path, key), f"unknown key {key!r} in the readme table")
    if ("file" in value) == ("text" in value):
        report.add("invalid-readme", path, "the readme table needs exactly one of 'file' and 'text'")
    if "file" in value:
        file_path = f"{path}.file"
        if has_type(report, file_path, value["file"], str, "a string"):
            if not file_exists(base_dir, value["file"]):
                report.add("file-not-found", file_path, f"readme file not found: {value['file']!r}")
    if "text" in value:
        has_type(report, f"{path}.text", value["text"], str, "a string")
    content_path = f"{path}.content-type"
    if "content-type" not in value:
        report.add("missing-key", content_path, "the required key 'content-type' is missing")
    elif has_type(report, content_path, value["content-type"], str, "a string"):
        kind = value["content-type"].split(";", 1)[0].strip(WS).lower()
        if kind not in README_CONTENT_TYPES:
            report.add("invalid-readme", content_path,
                       f"the content type must be text/markdown, text/x-rst or text/plain: {value['content-type']!r}")


def check_license(report: Report, value: Any, base_dir: Path) -> None:
    path = "project.license"
    if isinstance(value, str):
        problem = check_spdx(value)
        if problem:
            report.add("invalid-license", path, f"not a valid SPDX license expression: {value!r} ({problem})")
        return
    if not isinstance(value, dict):
        has_type(report, path, value, str, "a string or a table")
        return
    report.add("license-table-deprecated", path,
               "the license table is deprecated, use an SPDX expression string")
    for key in value:
        if key not in ("file", "text"):
            report.add("unknown-key", join_path(path, key), f"unknown key {key!r} in the license table")
    if ("file" in value) == ("text" in value):
        report.add("invalid-license", path, "the license table needs exactly one of 'file' and 'text'")
    if "file" in value:
        file_path = f"{path}.file"
        if has_type(report, file_path, value["file"], str, "a string"):
            if not file_exists(base_dir, value["file"]):
                report.add("file-not-found", file_path, f"license file not found: {value['file']!r}")
    if "text" in value:
        has_type(report, f"{path}.text", value["text"], str, "a string")


def check_people(report: Report, path: str, value: Any) -> None:
    if not has_type(report, path, value, list, "an array"):
        return
    for index, person in enumerate(value):
        element = f"{path}[{index}]"
        if not has_type(report, element, person, dict, "a table"):
            continue
        for key in person:
            if key not in ("name", "email"):
                report.add("unknown-key", join_path(element, key), f"unknown key {key!r} for a person")
        if "name" not in person and "email" not in person:
            report.add("invalid-person", element, "a person needs a 'name' or an 'email'")
        if "name" in person:
            name_path = join_path(element, "name")
            name = person["name"]
            if has_type(report, name_path, name, str, "a string") and (name == "" or "," in name):
                report.add("invalid-person", name_path, f"the name must not be empty or hold a comma: {name!r}")
        if "email" in person:
            email_path = join_path(element, "email")
            email = person["email"]
            if has_type(report, email_path, email, str, "a string") and EMAIL_RE.fullmatch(email) is None:
                report.add("invalid-person", email_path, f"not a valid email address: {email!r}")


def check_string_table(report: Report, path: str, value: Any) -> None:
    if has_type(report, path, value, dict, "a table"):
        for key, item in value.items():
            has_type(report, join_path(path, key), item, str, "a string")


def check_scripts(report: Report, path: str, value: Any) -> None:
    if not has_type(report, path, value, dict, "a table"):
        return
    for key, item in value.items():
        key_path = join_path(path, key)
        if ENTRY_NAME_RE.fullmatch(key) is None:
            report.add("invalid-entry-name", key_path, f"not a valid script name: {key!r}")
        if has_type(report, key_path, item, str, "a string") and SCRIPT_REFERENCE_RE.fullmatch(item) is None:
            report.add("invalid-object-reference", key_path,
                       f"not a valid MODULE:ATTR reference: {item!r}")


def check_entry_points(report: Report, path: str, value: Any) -> None:
    if not has_type(report, path, value, dict, "a table"):
        return
    for group, entries in value.items():
        group_path = join_path(path, group)
        if group in RESERVED_GROUPS:
            report.add("reserved-entry-point-group", group_path,
                       f"{group!r} is reserved, use [project.scripts] or [project.gui-scripts]")
        elif GROUP_NAME_RE.fullmatch(group) is None:
            report.add("invalid-entry-name", group_path, f"not a valid entry point group name: {group!r}")
        if not has_type(report, group_path, entries, dict, "a table"):
            continue
        for name, target in entries.items():
            entry_path = join_path(group_path, name)
            if ENTRY_NAME_RE.fullmatch(name) is None:
                report.add("invalid-entry-name", entry_path, f"not a valid entry point name: {name!r}")
            if has_type(report, entry_path, target, str, "a string") and OBJECT_REFERENCE_RE.fullmatch(target) is None:
                report.add("invalid-object-reference", entry_path,
                           f"not a valid MODULE or MODULE:ATTR reference: {target!r}")


def check_optional_dependencies(report: Report, value: Any) -> None:
    path = "project.optional-dependencies"
    if not has_type(report, path, value, dict, "a table"):
        return
    seen: set[str] = set()
    for extra, items in value.items():
        extra_path = join_path(path, extra)
        if NAME_RE.fullmatch(extra) is None:
            report.add("invalid-extra-name", extra_path, f"not a valid extra name: {extra!r}")
        else:
            normalized = normalize_name(extra)
            if normalized in seen:
                report.add("duplicate-extra", extra_path,
                           f"the extra {extra!r} has the same normalized name {normalized!r} as an earlier extra")
            seen.add(normalized)
        valid = check_requirements(report, extra_path, items)
        check_duplicate_dependencies(report, valid)


def is_library(name: Any, classifiers: Any) -> bool:
    if isinstance(classifiers, list):
        library = "Topic :: Software Development :: Libraries"
        for classifier in classifiers:
            if isinstance(classifier, str) and (classifier == library or classifier.startswith(library + " :: ")):
                return True
    if isinstance(name, str) and NAME_RE.fullmatch(name):
        parts = normalize_name(name).split("-")
        return "lib" in parts or "library" in parts
    return False


def is_pinned(requirement: Requirement) -> bool:
    return any(op == "==" and not version.endswith(".*") for op, version in requirement.specifiers)


def check_dynamic(report: Report, table: dict[str, Any]) -> set[str]:
    """Checks project.dynamic; returns the valid fields listed in it."""
    listed: set[str] = set()
    if "dynamic" not in table:
        return listed
    for index, field in string_items(report, "project.dynamic", table["dynamic"]):
        if field in DYNAMIC_ALLOWED:
            listed.add(field)
        else:
            report.add("invalid-dynamic", f"project.dynamic[{index}]",
                       f"{field!r} may not be listed in dynamic")
    for field in sorted(listed):
        if field in table:
            report.add("dynamic-conflict", join_path("project", field),
                       f"{field!r} is given in [project] and also listed in dynamic")
    return listed


def check_project(report: Report, table: dict[str, Any], base_dir: Path) -> None:
    for key in table:
        if key not in PROJECT_KEYS:
            report.add("unknown-key", join_path("project", key), f"unknown key {key!r} in [project]")
    listed = check_dynamic(report, table)

    if "name" not in table:
        report.add("missing-key", "project.name", "the required key 'name' is missing")
    else:
        name = table["name"]
        if has_type(report, "project.name", name, str, "a string"):
            if NAME_RE.fullmatch(name) is None:
                report.add("invalid-name", "project.name", f"not a valid project name: {name!r}")
            elif normalize_name(name) != name:
                report.add("name-not-normalized", "project.name",
                           f"the name {name!r} is not normalized, the normalized form is {normalize_name(name)!r}")

    if "version" not in table:
        if "version" not in listed:
            report.add("missing-key", "project.version", "the required key 'version' is missing")
    else:
        version = table["version"]
        if has_type(report, "project.version", version, str, "a string"):
            if VERSION_RE.fullmatch(version) is None:
                report.add("invalid-version", "project.version", f"not a valid PEP 440 version: {version!r}")

    if "description" in table:
        description = table["description"]
        if has_type(report, "project.description", description, str, "a string"):
            if "\n" in description or "\r" in description:
                report.add("invalid-description", "project.description", "the description must be on one line")

    if "readme" in table:
        check_readme(report, table["readme"], base_dir)

    if "requires-python" in table:
        spec = table["requires-python"]
        if has_type(report, "project.requires-python", spec, str, "a string"):
            _, problem = parse_specifier_set(spec)
            if problem:
                report.add("invalid-specifier", "project.requires-python",
                           f"not a valid specifier set: {spec!r} ({problem})")

    if "license" in table:
        check_license(report, table["license"], base_dir)

    for key in ("license-files", "keywords", "classifiers"):
        if key in table:
            string_items(report, join_path("project", key), table[key])

    for key in ("authors", "maintainers"):
        if key in table:
            check_people(report, join_path("project", key), table[key])

    if "urls" in table:
        check_string_table(report, "project.urls", table["urls"])
    for key in ("scripts", "gui-scripts"):
        if key in table:
            check_scripts(report, join_path("project", key), table[key])
    if "entry-points" in table:
        check_entry_points(report, "project.entry-points", table["entry-points"])

    if "dependencies" in table:
        valid = check_requirements(report, "project.dependencies", table["dependencies"])
        check_duplicate_dependencies(report, valid)
        if is_library(table.get("name"), table.get("classifiers")):
            for element, requirement in valid:
                if is_pinned(requirement):
                    report.add("pinned-library-dependency", element,
                               f"{requirement.name!r} is pinned with == in a library, "
                               "which makes it hard to install beside other packages")

    if "optional-dependencies" in table:
        check_optional_dependencies(report, table["optional-dependencies"])


def check_document(document: dict[str, Any], base_dir: Path) -> list[Finding]:
    report = Report()
    for key, value in document.items():
        if key not in TOP_LEVEL_KEYS:
            report.add("unknown-table", format_key(key), f"unknown top-level key {key!r}")
        else:
            has_type(report, format_key(key), value, dict, "a table")
    build_system = document.get("build-system")
    if isinstance(build_system, dict):
        check_build_system(report, build_system)
    project = document.get("project")
    if isinstance(project, dict):
        check_project(report, project, base_dir)
    return report.ordered()


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

@dataclass
class Options:
    path: str | None = None
    as_json: bool = False
    fail_on: str = "error"
    show_help: bool = False


def parse_args(args: list[str]) -> tuple[Options, str]:
    """Returns (options, usage error); the error is '' when the arguments are fine."""
    options = Options()
    seen_json = seen_help = seen_fail = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--json":
            if seen_json:
                return options, "--json given twice"
            seen_json = options.as_json = True
        elif arg == "--help":
            if seen_help:
                return options, "--help given twice"
            seen_help = options.show_help = True
        elif arg == "--fail-on":
            if seen_fail:
                return options, "--fail-on given twice"
            seen_fail = True
            if i + 1 >= len(args):
                return options, "--fail-on needs a value: error, warning or none"
            value = args[i + 1]
            if value not in LEVELS:
                return options, f"--fail-on: {value!r} is not one of error, warning, none"
            options.fail_on = value
            i += 1
        elif arg.startswith("-"):
            return options, f"unknown option {arg!r}"
        elif options.path is not None:
            return options, "more than one path given"
        else:
            options.path = arg
        i += 1
    return options, ""


def emit(stream: TextIO, text: str) -> None:
    """Writes text as UTF-8 whatever the locale is."""
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        stream.flush()
        buffer.write(text.encode("utf-8", "backslashreplace"))
        buffer.flush()
    else:
        stream.write(text)
        stream.flush()


def usage_error(message: str) -> int:
    emit(sys.stderr, f"{TOOL}: error: {message}\n{USAGE}\n")
    return 2


def read_document(path: str) -> tuple[dict[str, Any] | None, str]:
    """Returns (document, '') or (None, the message for stderr)."""
    try:
        mode = os.stat(path).st_mode
    except OSError as error:
        return None, f"{TOOL}: cannot read {path}: {error.strerror or error}"
    if not stat.S_ISREG(mode):
        return None, f"{TOOL}: {path} is not a regular file"
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as error:
        return None, f"{TOOL}: cannot read {path}: {error.strerror or error}"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        return None, f"{TOOL}: {path} is not valid UTF-8: {error}"
    try:
        return tomllib.loads(text), ""
    except tomllib.TOMLDecodeError as error:
        return None, f"{TOOL}: {path}: invalid TOML: {error}"
    except RecursionError:
        return None, f"{TOOL}: {path}: invalid TOML: nested too deeply"


def render_plain(findings: list[Finding], errors: int, warnings: int) -> str:
    lines = [f"{f.severity} {f.rule} {f.path}: {f.message}" for f in findings]
    lines.append(f"errors: {errors}, warnings: {warnings}")
    return "\n".join(lines) + "\n"


def render_json(findings: list[Finding], errors: int, warnings: int, file: str) -> str:
    document = {
        "tool": TOOL,
        "version": VERSION,
        "file": file,
        "findings": [
            {"rule": f.rule, "severity": f.severity, "path": f.path, "message": f.message}
            for f in findings
        ],
        "counts": {"error": errors, "warning": warnings},
    }
    return json.dumps(document, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    options, error = parse_args(list(args))
    if error:
        return usage_error(error)
    if options.show_help:
        emit(sys.stdout, HELP)
        return 0
    path = options.path if options.path is not None else DEFAULT_PATH
    document, message = read_document(path)
    if document is None:
        emit(sys.stderr, message + "\n")
        return 2
    findings = check_document(document, Path(path).parent)
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = len(findings) - errors
    if options.as_json:
        emit(sys.stdout, render_json(findings, errors, warnings, path))
    else:
        emit(sys.stdout, render_plain(findings, errors, warnings))
    if options.fail_on == "error" and errors > 0:
        return 1
    if options.fail_on == "warning" and errors + warnings > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
