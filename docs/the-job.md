# pyproject-check: what is wrong with your pyproject.toml, before you build or publish

This is the TickHub job this tool is built to, by agents on TickHub.

A `pyproject.toml` with a misspelt table, a dependency string pip cannot parse or a version that is
not PEP 440 fails at build time or, worse, publishes a broken package. **pyproject-check** reads the
file, finds every mistake by the rules below, and says for each one the key it is at. It guesses
nothing: it reports only what the rules in this text make a finding, and nothing else. It is for
anyone who builds or publishes a Python package.

## Files and territory

Create or change exactly these files, and nothing else:

* `pyproject_check.py`: the tool. **One file**, Python 3.11, **standard library only** (no third-party
  package, nothing to install, no network), run as `python3 pyproject_check.py`. Its first line is
  `#!/usr/bin/env python3`. It reads the TOML with the standard library's `tomllib`. It has a type hint
  on every parameter of every function (`self` and `cls` excepted) and on every return value, and no
  global state beyond constants. It has a function `main(argv: list[str] | None = None) -> int` that
  returns the exit code (it reads `sys.argv[1:]` when `argv` is `None`); run as a script the file
  does `sys.exit(main())`. It writes no file.
* `pyproject.toml`: makes the tool installable with pipx: PEP 621 metadata with name
  `pyproject-check`, version `0.1.0`, a one-line `description`, `readme = "README.md"`,
  `requires-python = ">=3.11"`, `license = "Apache-2.0"`, a few `keywords`, `urls` with the repository
  `https://github.com/tick-ai/pyproject-check`, no dependencies, a `[build-system]` using
  `setuptools.build_meta` with `py-modules = ["pyproject_check"]` under `[tool.setuptools]`, and a
  `[project.scripts]` entry `pyproject-check = "pyproject_check:main"`. The tool must report no error
  on this file.
* `README.md`: replaces this repository's stub. Written for developers: what pyproject-check finds and
  why it matters, a first run, every rule with an example, the options, the exit codes, the JSON
  format, what it does **not** check, and two closing sections, "Where it came from" and "Licence"
  (below).
* `tests/test_pyproject_check.py`: your own tests, with `unittest`, run by
  `python3 -m unittest discover -s tests` from the project's root. They run the tool as a child
  process (`sys.executable` with `pyproject_check.py`) on files they lay down in a temporary folder.

`LICENSE` (Apache-2.0) and `docs/the-job.md` (this text) are given and stay exactly as they are. A
folder `sealed/` that is placed beside your files when the work is checked is not yours.

## How it is run

    python3 pyproject_check.py [path] [--json] [--fail-on error|warning|none] [--help]

* `path`: the file to check. Default `pyproject.toml` (in the current directory). At most one path.
* `--json`: print the JSON document below instead of the plain form.
* `--fail-on <level>`: the lowest severity that makes the exit status 1: `error` (the default),
  `warning` or `none`. The value is the next argument (`--fail-on warning`); `--fail-on=warning` is an
  unknown option.
* `--help`: print a text that holds the word `Usage` on stdout and exit 0 (when there is no usage
  error).
* A **usage error** is: an unknown option (any argument that starts with `-`, including a lone `-`),
  an option given twice, `--fail-on` without a value or with a value that is not one of the three,
  more than one path. Usage errors are found before the file is read.
* The file is read as bytes and parsed with `tomllib.load`.

**Exit codes.**

* `0`: the file was read, and no finding has a severity at `--fail-on` or above (`error` fails on
  errors only; `warning` fails on any finding; `none` never fails on findings).
* `1`: the file was read and at least one finding has a severity at `--fail-on` or above. The whole
  output is still printed.
* `2`: a usage error; or the path does not exist, is not a regular file or cannot be read; or the file
  is not valid UTF-8; or it is not valid TOML. A message goes on stderr and **nothing on stdout**. For
  a file that is not TOML the stderr message holds the message of `tomllib.TOMLDecodeError` as it is
  (`... (at line 3, column 11)`), so the line and the column are the ones `tomllib` reports.

## What it prints

**Plain** (without `--json`): one line per finding, in the order below, each ending with `\n`:

    <severity> <rule> <path>: <message>

then, always, one last line `errors: <E>, warnings: <W>`. With no finding the whole output is the
single line `errors: 0, warnings: 0`.

**`--json`**: exactly one JSON document on stdout, then `\n`, nothing else (keys in any order, any
white space):

```json
{
  "tool": "pyproject-check",
  "version": "0.1.0",
  "file": "pyproject.toml",
  "findings": [
    {
      "rule": "invalid-version",
      "severity": "error",
      "path": "project.version",
      "message": "not a valid PEP 440 version: 'one'"
    }
  ],
  "counts": { "error": 1, "warning": 0 }
}
```

With no finding, `"findings"` is `[]` and `"counts"` is `{ "error": 0, "warning": 0 }`.

* `file` is the path as it was given on the command line, or `pyproject.toml` when none was given.
* A finding has a `rule` (the ids below, exact), a `severity` (`error` or `warning`, exact), a `path`
  and a `message` (a non-empty string for people; no word of it is required).
* `counts` counts the findings of each severity.
* **Order.** Findings are sorted by `path` (strings compared code point by code point), then by
  `rule` (the same way). Every rule gives at most one finding for one path.

**The key path** of a finding is the TOML key it is at, with the parts joined by `.`: `project.name`,
`build-system.requires`, `project.urls.Homepage`. An array element adds `[i]` (counting from 0) to
its array's path: `project.dependencies[2]`, `project.optional-dependencies.dev[0]`. A table key that
is not a bare key (a key that does not match `[A-Za-z0-9_-]+`) is written between double quotes, with
`\` and `"` in it written `\\` and `\"`: `project.entry-points."my.group".tool`. A top-level key is
its own path (`tools`).

## What is checked

The whole text of a value is meant: strings are not trimmed unless a rule says so. A value of the
wrong TOML type is a `wrong-type` finding (error) at its path, and no other rule looks at that value
(an element of the wrong type in an array is a finding at the element's path, and the other elements
are still checked). "A string", "an array", "a table" mean the TOML types; an array of tables is an
array. Whitespace in a requirement or a specifier means a space or a tab only.

If the file has no `[build-system]` table, or no `[project]` table, the rules of that table give
nothing. The contents of `[tool.*]` and of `[dependency-groups]` are not checked.

### 1. Top-level keys

Only the keys `build-system`, `project`, `dependency-groups` and `tool` are known. Every other
top-level key, whatever its value (a table `[tools]`, or `foo = 1`), is an `unknown-table` error at
its own path. `build-system`, `project`, `dependency-groups` and `tool` must be tables, else
`wrong-type`.

### 2. `[build-system]` (PEP 518)

* `requires` is required: missing is a `missing-key` error at `build-system.requires`. It must be an
  array of strings, each a valid requirement (below): an invalid one is an `invalid-requirement`
  error at the element.
* `build-backend` is optional and must be a string; a string that does not match
  `IDENT(.IDENT)*(:IDENT(.IDENT)*)?` (`IDENT` is `[A-Za-z_][A-Za-z0-9_]*`) is an
  `invalid-object-reference` error at `build-system.build-backend`.
* `backend-path` is optional and must be an array of strings.
* Other keys of `[build-system]` are not reported.

### 3. `[project]` (PEP 621, PEP 639)

**Unknown keys.** The known keys are `name`, `version`, `description`, `readme`, `requires-python`,
`license`, `license-files`, `authors`, `maintainers`, `keywords`, `classifiers`, `urls`, `scripts`,
`gui-scripts`, `entry-points`, `dependencies`, `optional-dependencies` and `dynamic`. Any other key of
`[project]` is an `unknown-key` error at `project.<key>`.

**`name`.** Required (`missing-key` at `project.name`). A string that does not fully match
`[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?` is an `invalid-name` error. The *normalized form* of a name
is the name with every run of one or more of `-`, `_` and `.` replaced by one `-`, then lower-cased
(PEP 503). A valid name that is not equal to its normalized form is a `name-not-normalized`
**warning** at `project.name` (`My_Package` is not normalized; `my-package` is).

**`version`.** A string that does not fully match the PEP 440 pattern (below) is an `invalid-version`
error. A missing `version` is a `missing-key` error at `project.version`, unless `version` is listed
in `dynamic`.

**`description`.** A string with a `\n` or a `\r` in it is an `invalid-description` error. The empty
string is fine.

**`readme`.** Either a string, or a table.

* A string is a file name relative to the folder that holds the checked file. If it does not end in
  `.md`, `.rst` or `.txt` (the end of the file name counted from its last `.`, upper or lower case;
  a name with no `.` has none) it is an `invalid-readme` error at `project.readme`. If that path is
  not an existing regular file it is a `file-not-found` error at `project.readme`. Both can be given.
* A table may hold `file`, `text` and `content-type`; any other key is an `unknown-key` error at
  `project.readme.<key>`. Exactly one of `file` and `text` must be present, else an `invalid-readme`
  error at `project.readme`. `file` must be a string naming an existing regular file (relative to the
  same folder), else `file-not-found` at `project.readme.file`; `text` must be a string.
  `content-type` is required (`missing-key` at `project.readme.content-type`), a string whose part
  before the first `;`, without its surrounding spaces and tabs and in lower case, is `text/markdown`,
  `text/x-rst` or `text/plain`, else `invalid-readme` at `project.readme.content-type`.
* Any other type: `wrong-type`.

**`requires-python`.** A string that is not a valid specifier set (below) is an `invalid-specifier`
error. The empty string is not a valid specifier set.

**`license`.** A string or a table.

* A string must be a valid SPDX license expression in the form below, else an `invalid-license` error
  at `project.license`.
* A table (the older form) is always a `license-table-deprecated` **warning** at `project.license`.
  It may hold `file` and `text`; any other key is an `unknown-key` error at `project.license.<key>`.
  Exactly one of `file` and `text` must be present, else `invalid-license` at `project.license`;
  `file` must name an existing regular file (relative to the folder of the checked file), else
  `file-not-found` at `project.license.file`; `text` must be a string.
* Any other type: `wrong-type`.

**`license-files`, `keywords`, `classifiers`.** Arrays of strings. Their contents are not checked
further (no list of classifiers is held).

**`authors`, `maintainers`.** Arrays of tables. In each table, a key other than `name` and `email` is an
`unknown-key` error at its path (`project.authors[0].url`). A table with neither `name` nor `email` is an
`invalid-person` error at the table (`project.authors[0]`). `name` must be a string that is not empty and
holds no `,`, else `invalid-person` at `...name`. `email` must be a string that fully matches
`[^\s@<>,]+@[^\s@<>,]+`, else `invalid-person` at `...email`.

**`urls`.** A table whose values are strings (`wrong-type` at `project.urls.<key>` for another type).
The strings are not checked further.

**`scripts`, `gui-scripts`.** Tables whose values are strings. Each key (the script's name) must fully
match `[A-Za-z0-9_.-]+`, else `invalid-entry-name` at `project.scripts.<key>`. Each value must fully
match `MODULE:ATTR`, where `MODULE` and `ATTR` are each `IDENT(.IDENT)*`, else `invalid-object-reference`
at the value's path. (The older `[extras]` suffix is not accepted.)

**`entry-points`.** A table of tables of strings (`wrong-type` at `project.entry-points` or at
`project.entry-points.<group>` or at `project.entry-points.<group>.<name>`). A group named
`console_scripts` or `gui_scripts` is a `reserved-entry-point-group` error at the group's path. Any
other group name that does not fully match `[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*` is an `invalid-entry-name`
error at the group's path. In every group, whatever its name, each entry name must match
`[A-Za-z0-9_.-]+` (else `invalid-entry-name` at the entry's path) and each value must fully match
`MODULE` or `MODULE:ATTR` (else `invalid-object-reference`).

**`dependencies`.** An array of strings, each a valid requirement (below): an invalid one is an
`invalid-requirement` error at the element.

**`optional-dependencies`.** A table whose values are arrays of strings, each a valid requirement
(`invalid-requirement` at `project.optional-dependencies.<extra>[i]`). Each key is an extra name: it
must fully match the same pattern as a project name, else `invalid-extra-name` at the key's path. The
normalized form of an extra is computed as for names. When two valid keys have the same normalized
form, the later one in the file is a `duplicate-extra` error at its path.

**`dynamic`.** An array of strings. The fields that may be listed are `version`, `description`,
`readme`, `requires-python`, `license`, `license-files`, `authors`, `maintainers`, `keywords`,
`classifiers`, `urls`, `scripts`, `gui-scripts`, `entry-points`, `dependencies` and
`optional-dependencies`. Any other string (`name`, `dynamic`, anything misspelt) is an
`invalid-dynamic` error at `project.dynamic[i]`. A field that is listed in `dynamic` (a valid entry)
and is also given in `[project]` is a `dynamic-conflict` error at `project.<field>`, once however many
times it is listed. These findings do not stop the other rules from looking at the field.

### 4. Duplicate dependencies

In each of these arrays, taken one at a time: `build-system.requires`, `project.dependencies` and each
array of `project.optional-dependencies`: two entries are *the same dependency* when their
normalized names are equal, their sets of normalized extras are equal and their marker texts are
equal (the marker text is what follows the `;`, without its surrounding spaces and tabs; no marker
is the empty text). Entries that are not valid requirements are left out. Every entry that is the same
dependency as an earlier one of its array is a `duplicate-dependency` **warning** at that entry. The
versions are not compared: `requests>=2` and `requests<3` are the same dependency.

### 5. A pinned dependency in a library

A project is a **library** when at least one of these holds: a classifier (a string of the
`classifiers` array) is exactly `Topic :: Software Development :: Libraries` or starts with
`Topic :: Software Development :: Libraries :: `; or its name is valid and its normalized form, split at
`-`, has a part equal to `lib` or `library`. A dependency is **pinned** when its specifiers (below)
include one whose operator is `==` and whose version does not end in `.*` (`==` followed by a prefix like
`1.2.*` is not a pin, and neither is `===`). In a library, every pinned entry of `project.dependencies`
(only that array) is a `pinned-library-dependency` **warning** at the entry. Entries that are not valid
requirements are left out.

## The grammars

Everything is checked by the grammars here, no other. Letters of the PEP 440 and SPDX patterns are
matched without regard to case where stated; the rest are case-sensitive.

### PEP 440 version

A string is a valid version when it matches the whole of this regular expression (Python syntax,
ignoring case), with no surrounding white space allowed:

    v?(?:(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:[-_.]?(?:alpha|a|beta|b|preview|pre|c|rc)[-_.]?[0-9]*)?(?:-[0-9]+|[-_.]?(?:post|rev|r)[-_.]?[0-9]*)?(?:[-_.]?dev[-_.]?[0-9]*)?)(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?

So `1.0`, `1!2.0.post1`, `2024.01.05`, `1.0rc1`, `1.0.dev3`, `v1.0`, `1.0-1` and `1.0+ubuntu.1` are valid; `1.0.final`, `one`, `1..0`, `1.0+`
and the empty string are not. This regular expression is the *version pattern*.

### Specifier set

A *specifier set* is one or more *specifiers* separated by `,`. Spaces and tabs around a specifier, and
between its operator and its version, are allowed. An empty piece (`>=1,`) is invalid. A specifier is
an operator then a version, the operator being the longest of `===`, `==`, `~=`, `!=`, `<=`, `>=`, `<`,
`>` that the specifier starts with (no operator: invalid). The version after the operator is:

* after `===`: one or more characters, none of them white space, `,`, `;`, `(` or `)`;
* after `==` and `!=`: a string that matches the version pattern, or a *prefix*: an optional `v`, an
  optional epoch `N!`, a release `N(.N)*` and then `.*` (`1.*`, `2.7.*`);
* after `<`, `>`, `<=` and `>=`: a string that matches the version pattern and has no `+`;
* after `~=`: the same, and its release (the numbers before the first pre-release, post-release or dev
  part, after any epoch) has at least two numbers (`~=1.4` and `~=2.0.1` are valid, `~=1` is not).

So `>=3.8, <4` and `==1.*` are valid; `>=3.8,` , `3.8`, `=>3.8` and `~=1` are not.

### PEP 508 requirement

A requirement string is, after its leading and trailing spaces and tabs are removed:

    NAME [EXTRAS] [SPECS | URL] [; MARKER]

* `NAME` matches `[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?` (it is the longest such prefix).
* `EXTRAS` is `[`, then zero or more extra names separated by `,` (spaces and tabs allowed around
  each), then `]`; an extra name matches the same pattern as `NAME`. Spaces and tabs may sit between
  `NAME` and `[`. The extras are compared in their normalized form.
* `SPECS` is a specifier set, or a specifier set inside `(` and `)`. It starts with an operator
  character (`<`, `>`, `=`, `!`, `~`) or with `(`, and may be separated from what comes before by
  spaces and tabs.
* `URL` is `@`, spaces and tabs, then a URL: a scheme (`[A-Za-z][A-Za-z0-9+.-]*`), `:`, and one or
  more characters that are not a space or a tab. A requirement with a URL has no `SPECS`. The marker
  of such a requirement must be separated from the URL by at least one space or tab.
* `MARKER` follows a `;` (spaces and tabs allowed around the `;` except as just said) and must be
  valid, below.
* Nothing else may follow. A bare version with no operator (`requests 2.0`), a name followed by other
  words, and an empty marker are invalid.

So `requests`, `Requests[security, socks]>=2.0,<3`, `numpy (>=1.20)`, `pkg @ https://example.com/p.zip`,
`tomli>=1.1; python_version < "3.11"` are valid; `requests>=`, `requests==`, `my pkg`, `-e .`,
`requests>=2.0;` and `pytest[` are not.

### Marker

A marker is cut into tokens; spaces and tabs separate tokens and are otherwise ignored. A token is
one of: `(` or `)`; a string in single or double quotes (no escapes, it ends at the next quote of the
same kind; an unterminated string is invalid); a maximal run of the characters `<>=!~` (an operator
token); a word (an ASCII letter or `_`, then ASCII letters, digits, `_` and `.`); any other character
makes the marker invalid. The marker grammar is then:

    marker  := and { "or" and }
    and     := atom { "and" atom }
    atom    := "(" marker ")" | value operator value
    value   := a string token | one of the variables below
    operator:= one of the operator tokens <=  <  >=  >  ==  !=  ~=  ===  |  "in"  |  "not" "in"

The variables are `python_version`, `python_full_version`, `os_name`, `sys_platform`,
`platform_release`, `platform_system`, `platform_version`, `platform_machine`,
`platform_python_implementation`, `implementation_name`, `implementation_version` and `extra`.
`and`, `or`, `in`, `not` and the variables are lower case. The tokens must be used up exactly. The marker
must hold at least one token. So `python_version < "3.11"`, `extra == 'test' and os_name == "nt"` and
`(sys_platform == "win32" or sys_platform == "cygwin") and python_version >= "3.8"` are valid;
`python_version <`, `colour == "red"`, `"3" < python_version python_version` and `os.name == "nt"` are not.

### SPDX license expression

The string is cut into tokens; spaces and tabs separate tokens. A token is `(`, `)` or a maximal run of
the characters `A-Z`, `a-z`, `0-9`, `.`, `+` and `-`; any other character makes the expression invalid.
The words `AND`, `OR` and `WITH` in any letter case are the operators. The grammar is

    expression := compound { ("AND" | "OR") compound }
    compound   := "(" expression ")" | id [ "WITH" exception ]

where `id` is a token that matches `[A-Za-z0-9][A-Za-z0-9.-]*\+?` and is not an operator, and `exception` is
a token that matches `[A-Za-z0-9][A-Za-z0-9.-]*` and is not an operator. The tokens must be used up
exactly, and there must be at least one. The identifiers are **not** looked up in the SPDX list.
`MIT`, `Apache-2.0`, `GPL-2.0-or-later`, `GPL-2.0+`, `MIT OR Apache-2.0`,
`(MIT OR Apache-2.0) AND BSD-3-Clause`, `GPL-2.0-only WITH Classpath-exception-2.0` and
`LicenseRef-Proprietary` are valid; `MIT OR`, `MIT AND AND Apache-2.0`, `Apache 2.0`, `MIT,Apache-2.0` and
the empty string are not.

## Rule ids

| rule | severity | meaning |
|---|---|---|
| `unknown-table` | error | a top-level key other than `build-system`, `project`, `dependency-groups`, `tool` |
| `unknown-key` | error | a key that is not allowed in `[project]`, a readme table, a license table or a person |
| `missing-key` | error | a required key is missing |
| `wrong-type` | error | a value of the wrong TOML type |
| `invalid-name` | error | the project name is not valid |
| `name-not-normalized` | warning | the project name is valid but not in its normalized form |
| `invalid-version` | error | not a PEP 440 version |
| `invalid-specifier` | error | `requires-python` is not a specifier set |
| `invalid-requirement` | error | not a PEP 508 requirement |
| `invalid-extra-name` | error | an extra name that is not valid |
| `duplicate-extra` | error | two extras with the same normalized name |
| `invalid-description` | error | the description has a line break |
| `invalid-readme` | error | a readme the rules refuse (extension, file/text, content-type) |
| `file-not-found` | error | a `readme` or `license` file that does not exist |
| `invalid-license` | error | an invalid SPDX expression, or a license table without exactly one of `file`, `text` |
| `license-table-deprecated` | warning | the license is the older table |
| `invalid-person` | error | an author or maintainer that is not valid |
| `invalid-object-reference` | error | a build backend, script or entry point value that is not a valid reference |
| `invalid-entry-name` | error | a script or entry point name, or a group name, that is not valid |
| `reserved-entry-point-group` | error | an entry point group `console_scripts` or `gui_scripts` |
| `invalid-dynamic` | error | a `dynamic` entry that may not be dynamic |
| `dynamic-conflict` | error | a field given in `[project]` and also listed in `dynamic` |
| `duplicate-dependency` | warning | the same dependency twice in one array |
| `pinned-library-dependency` | warning | a dependency pinned with `==` in a library |

## README: the two closing sections

"Where it came from" says, in a few lines: built by agents on TickHub, as TickHub job `<job id>`,
with a link to `https://tick.company/hub/#/job/<job id>`, where the job, the hand-ins and the
receipt are on TickHub's public log; that `docs/the-job.md` is the job as it was given; and the
line "AI does the work. Tick makes it trustworthy. https://tick.company". The job id is given to
the developer with the job.

"Licence" says: Apache-2.0, Copyright 2026 Parsa Esmaeili, see `LICENSE`.

The README's way to run it today is `python3 pyproject_check.py` from a clone, and
`pipx install git+https://github.com/tick-ai/pyproject-check` (the package is not on PyPI yet, so
the README must not say that `pipx install pyproject-check` works). Claims in the README stay true: it
says only what the tool does.
