# pyproject-check

pyproject-check reads your `pyproject.toml`, finds every mistake by a fixed set of rules, and tells you for each one the key it is at.

```
python3 pyproject_check.py
```

A real run on a file with a few mistakes:

```
$ python3 pyproject_check.py
error invalid-requirement build-system.requires[1]: not a valid PEP 508 requirement: 'wheel>=' (expected a version after '>=')
warning duplicate-dependency project.dependencies[1]: the same dependency ('requests') is already listed earlier in this array
error invalid-requirement project.dependencies[2]: not a valid PEP 508 requirement: 'numpy (>=1.20' (missing ')' after the version specifiers)
warning name-not-normalized project.name: the name 'My_Package' is not normalized, the normalized form is 'my-package'
error invalid-specifier project.requires-python: not a valid specifier set: '>=3.8,' (empty specifier)
error invalid-version project.version: not a valid PEP 440 version: 'one'
error unknown-table tools: unknown top-level key 'tools'
errors: 5, warnings: 2
$ echo $?
1
```

Python 3.11, standard library only: nothing to install, no network, and it writes no file.

## What it finds, and why it matters

A `pyproject.toml` with a misspelt table, a dependency string pip cannot parse or a version that is not PEP 440 fails at build time or, worse, publishes a broken package. pyproject-check finds those before you build or publish. It guesses nothing: it reports only what the rules below make a finding, and nothing else.

## Run it

From a clone:

```
python3 pyproject_check.py [path] [--json] [--fail-on error|warning|none] [--help]
```

Or install it with pipx (the package is not on PyPI yet, so install it from GitHub):

```
pipx install git+https://github.com/tick-ai/pyproject-check
pyproject-check path/to/pyproject.toml
```

## Options

| option | meaning |
|---|---|
| `path` | the file to check; default `pyproject.toml` in the current directory; at most one |
| `--json` | print the JSON document (below) instead of the plain form |
| `--fail-on <level>` | the lowest severity that makes the exit status 1: `error` (default), `warning` or `none`; the value is the next argument (`--fail-on=warning` is an unknown option) |
| `--help` | print the usage text on stdout and exit 0 |

A usage error is: an unknown option (any argument that starts with `-`, including a lone `-`), an option given twice, `--fail-on` without a value or with a value that is not one of the three, more than one path. Usage errors are found before the file is read.

## Exit codes

* `0`: the file was read, and no finding has a severity at `--fail-on` or above (`error` fails on errors only; `warning` fails on any finding; `none` never fails on findings).
* `1`: the file was read and at least one finding has a severity at `--fail-on` or above. The whole output is still printed.
* `2`: a usage error; or the path does not exist, is not a regular file or cannot be read; or the file is not valid UTF-8; or it is not valid TOML. A message goes on stderr and nothing on stdout. For a file that is not TOML the message holds the text of `tomllib.TOMLDecodeError`, for example `Invalid value (at line 3, column 11)`, so the line and column are the ones `tomllib` reports.

## Output

**Plain** (the default): one line per finding, then a summary line.

```
<severity> <rule> <path>: <message>
errors: <E>, warnings: <W>
```

With no finding the whole output is the single line `errors: 0, warnings: 0`.

**The key path** is the TOML key a finding is at, parts joined by `.`: `project.name`, `build-system.requires`, `project.urls.Homepage`. An array element adds `[i]` (from 0): `project.dependencies[2]`, `project.optional-dependencies.dev[0]`. A key that does not match `[A-Za-z0-9_-]+` is written between double quotes with `\` and `"` escaped: `project.entry-points."my.group".tool`.

**Order.** Findings are sorted by path, then by rule, compared code point by code point (so `dependencies[10]` comes before `dependencies[2]`). A rule gives at most one finding for one path.

## JSON format

`--json` prints exactly one JSON document and a newline:

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

`file` is the path as given on the command line (`pyproject.toml` when none was given). With no finding, `findings` is `[]` and `counts` is `{"error": 0, "warning": 0}`. The `message` is for people; rely on `rule`, `severity` and `path`.

## The rules

A value of the wrong TOML type is a `wrong-type` error at its path, and no other rule looks at that value (an element of the wrong type in an array is a finding at the element, and the other elements are still checked). If there is no `[build-system]` or no `[project]` table, that table's rules give nothing. The contents of `[tool.*]` and `[dependency-groups]` are not checked.

| rule | severity | meaning | example that triggers it |
|---|---|---|---|
| `unknown-table` | error | a top-level key other than `build-system`, `project`, `dependency-groups`, `tool` | `[tools]` |
| `unknown-key` | error | a key not allowed in `[project]`, a readme table, a license table or a person | `[project]` with `requires_python = ">=3"` |
| `missing-key` | error | a required key is missing: `build-system.requires`, `project.name`, `project.version` (unless dynamic), `project.readme.content-type` | `[project]` without `name` |
| `wrong-type` | error | a value of the wrong TOML type | `version = 1.0` |
| `invalid-name` | error | the project name does not match `[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?` | `name = "my pkg"` |
| `name-not-normalized` | warning | a valid name that differs from its normalized form (runs of `-_.` become `-`, lower case) | `name = "My_Package"` |
| `invalid-version` | error | not a PEP 440 version (the pattern below) | `version = "one"`, `"1.0.final"` |
| `invalid-specifier` | error | `requires-python` is not a specifier set | `requires-python = ">=3.8,"`, `"3.8"` |
| `invalid-requirement` | error | not a PEP 508 requirement (in `requires`, `dependencies`, `optional-dependencies`) | `"requests>="`, `"my pkg"`, `"pytest["` |
| `invalid-extra-name` | error | an extra name that does not match the project name pattern | `"my extra" = [...]` |
| `duplicate-extra` | error | two extras with the same normalized name; the later one is reported | `Foo_Bar` and `foo-bar` |
| `invalid-description` | error | the description has a `\n` or `\r` | `description = "a\nb"` |
| `invalid-readme` | error | a readme the rules refuse: extension not `.md`, `.rst`, `.txt`; not exactly one of `file`/`text`; content type not `text/markdown`, `text/x-rst`, `text/plain` | `readme = "README"` |
| `file-not-found` | error | a `readme` or `license` file that is not an existing regular file, looked up beside the checked file | `readme = "README.md"` with no such file |
| `invalid-license` | error | an invalid SPDX expression, or a license table without exactly one of `file`, `text` | `license = "MIT OR"` |
| `license-table-deprecated` | warning | the license is the older table | `license = {text = "MIT"}` |
| `invalid-person` | error | an author or maintainer with neither name nor email, an empty name or one with a `,`, or an email not matching `[^\s@<>,]+@[^\s@<>,]+` | `authors = [{email = "a"}]` |
| `invalid-object-reference` | error | a build backend, script or entry point value that is not a valid reference | `scripts` value `"pkg.main"` (needs `module:attr`) |
| `invalid-entry-name` | error | a script or entry point name, or a group name, that is not valid | a script named `"my tool"`, a group named `"a-b"` |
| `reserved-entry-point-group` | error | an entry point group `console_scripts` or `gui_scripts` | `[project.entry-points.console_scripts]` |
| `invalid-dynamic` | error | a `dynamic` entry that may not be dynamic | `dynamic = ["name"]` |
| `dynamic-conflict` | error | a field given in `[project]` and also listed in `dynamic` | `version = "1"` and `dynamic = ["version"]` |
| `duplicate-dependency` | warning | the same dependency twice in one array | `"requests>=2"` and `"requests<3"` |
| `pinned-library-dependency` | warning | a dependency pinned with `==` in a library | `"requests==2.31.0"` in `project.dependencies` of a library |

Details by table:

* **`[build-system]`**: `requires` is required, an array of valid requirements. `build-backend` is optional, a string matching `IDENT(.IDENT)*(:IDENT(.IDENT)*)?`. `backend-path` is optional, an array of strings. Other keys are not reported.
* **`[project]`** known keys: `name`, `version`, `description`, `readme`, `requires-python`, `license`, `license-files`, `authors`, `maintainers`, `keywords`, `classifiers`, `urls`, `scripts`, `gui-scripts`, `entry-points`, `dependencies`, `optional-dependencies`, `dynamic`. `license-files`, `keywords` and `classifiers` must be arrays of strings; their contents are not checked further. `urls` must be a table of strings, not checked further.
* **`scripts`, `gui-scripts`**: names match `[A-Za-z0-9_.-]+`, values match `MODULE:ATTR` (each `IDENT(.IDENT)*`). The older `[extras]` suffix is not accepted.
* **`entry-points`**: a table of tables of strings; entry names match `[A-Za-z0-9_.-]+`; values are `MODULE` or `MODULE:ATTR`; group names match `[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*`.
* **`dynamic`**: may list `version`, `description`, `readme`, `requires-python`, `license`, `license-files`, `authors`, `maintainers`, `keywords`, `classifiers`, `urls`, `scripts`, `gui-scripts`, `entry-points`, `dependencies`, `optional-dependencies`.
* **Duplicate dependencies** are looked for one array at a time (`build-system.requires`, `project.dependencies`, each array of `project.optional-dependencies`). Two entries are the same dependency when their normalized names, their sets of normalized extras and their marker texts are equal; versions are not compared. Invalid requirements are left out.
* **A pinned dependency in a library.** A project is a library when a classifier is `Topic :: Software Development :: Libraries` (or starts with that followed by ` :: `), or its valid name, normalized and split at `-`, has a part `lib` or `library`. A dependency is pinned when one of its specifiers is `==` with a version not ending in `.*` (`===` is not a pin). Only `project.dependencies` is looked at.

### The grammars

Everything is checked by these grammars, no other. Whitespace in a requirement or a specifier means a space or a tab only.

* **Version** (PEP 440), matched in full, ignoring case, no surrounding white space:

  ```
  v?(?:(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:[-_.]?(?:alpha|a|beta|b|preview|pre|c|rc)[-_.]?[0-9]*)?(?:-[0-9]+|[-_.]?(?:post|rev|r)[-_.]?[0-9]*)?(?:[-_.]?dev[-_.]?[0-9]*)?)(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?
  ```

* **Specifier set**: one or more specifiers separated by `,` (an empty piece is invalid). A specifier is the longest operator of `===`, `==`, `~=`, `!=`, `<=`, `>=`, `<`, `>` then a version: after `===` any non-empty text without white space, `,`, `;`, `(`, `)`; after `==` and `!=` a version or a prefix like `1.*`; after `<`, `>`, `<=`, `>=` a version without `+`; after `~=` the same with at least two release numbers (`~=1.4` yes, `~=1` no).
* **Requirement** (PEP 508 subset): `NAME [EXTRAS] [SPECS | URL] [; MARKER]`, where `SPECS` is a specifier set or one inside parentheses, and `URL` is `@` then `scheme:` and non-blank characters (a marker after a URL needs a space or tab before the `;`). `requests`, `Requests[security, socks]>=2.0,<3`, `numpy (>=1.20)`, `pkg @ https://example.com/p.zip` and `tomli>=1.1; python_version < "3.11"` are valid; `requests>=`, `requests==`, `my pkg`, `-e .`, `requests>=2.0;` and `pytest[` are not.
* **Marker**: comparisons joined with `and`, `or` and parentheses; each comparison is `value operator value`, where a value is a quoted string or one of `python_version`, `python_full_version`, `os_name`, `sys_platform`, `platform_release`, `platform_system`, `platform_version`, `platform_machine`, `platform_python_implementation`, `implementation_name`, `implementation_version`, `extra`, and the operator is one of `<=`, `<`, `>=`, `>`, `==`, `!=`, `~=`, `===`, `in`, `not in`.
* **SPDX license expression**: ids joined with `AND` / `OR`, `WITH` for an exception, parentheses; the ids are **not** looked up in the SPDX list. `MIT OR Apache-2.0`, `GPL-2.0+`, `GPL-2.0-only WITH Classpath-exception-2.0` and `LicenseRef-Proprietary` are valid; `MIT OR`, `Apache 2.0` and `MIT,Apache-2.0` are not.

## What it does not check

* The contents of `[tool.*]` and `[dependency-groups]`.
* Whether a package, a version or a classifier exists: classifiers are not looked up in any list, and SPDX identifiers are not looked up in the SPDX list.
* Whether a URL works, or what `urls` values contain.
* Whether the module a build backend, script or entry point names can be imported.
* Other keys of `[build-system]`.
* Anything outside the rules above: it reports only what those rules make a finding.
* It never changes a file, never installs anything and never uses the network.

## Where it came from

Built by agents on TickHub, as TickHub job `d82613d1-385f-466d-bc7c-1f06950e9971`. The job, the hand-ins and the receipt are on TickHub's public log: https://tick.company/hub/#/job/d82613d1-385f-466d-bc7c-1f06950e9971

`docs/the-job.md` is the job as it was given.

AI does the work. Tick makes it trustworthy. https://tick.company

## Licence

Apache-2.0, Copyright 2026 Parsa Esmaeili, see `LICENSE`.
