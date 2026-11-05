"""Tests for pyproject_check.py: the tool is run as a child process on files in temporary folders."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "pyproject_check.py"

GOOD = """
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "demo"
version = "1.0"
"""


class Run:
    def __init__(self, proc: "subprocess.CompletedProcess[str]") -> None:
        self.code = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr

    def findings(self):
        return json.loads(self.out)["findings"]

    def pairs(self):
        return [(f["rule"], f["path"]) for f in self.findings()]


class ToolCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def run_tool(self, *args: str, cwd=None) -> Run:
        proc = subprocess.run(
            [sys.executable, str(TOOL), *args],
            capture_output=True, text=True, encoding="utf-8", cwd=str(cwd or self.dir),
        )
        return Run(proc)

    def check(self, toml: str, *extra: str, name: str = "pyproject.toml") -> Run:
        (self.dir / name).write_text(toml, encoding="utf-8")
        return self.run_tool(name, "--json", *extra)

    def project(self, body: str, head: str = "") -> Run:
        return self.check(head + '\n[project]\nname = "demo"\nversion = "1.0"\n' + body)

    def assertPairs(self, run: Run, *expected) -> None:
        self.assertEqual(sorted(run.pairs()), sorted(expected), run.out)

    def assertHas(self, run: Run, rule: str, path: str) -> None:
        self.assertIn((rule, path), run.pairs(), run.out)

    def assertClean(self, run: Run) -> None:
        self.assertEqual(run.pairs(), [], run.out)


class OutputForms(ToolCase):
    def test_clean_plain(self):
        (self.dir / "pyproject.toml").write_text(GOOD)
        r = self.run_tool()
        self.assertEqual((r.code, r.out, r.err), (0, "errors: 0, warnings: 0\n", ""))

    def test_empty_file(self):
        (self.dir / "pyproject.toml").write_text("")
        r = self.run_tool()
        self.assertEqual((r.code, r.out), (0, "errors: 0, warnings: 0\n"))

    def test_empty_file_json(self):
        (self.dir / "x.toml").write_text("")
        r = self.run_tool("x.toml", "--json")
        doc = json.loads(r.out)
        self.assertTrue(r.out.endswith("\n"))
        self.assertEqual(doc["tool"], "pyproject-check")
        self.assertEqual(doc["version"], "0.1.0")
        self.assertEqual(doc["file"], "x.toml")
        self.assertEqual(doc["findings"], [])
        self.assertEqual(doc["counts"], {"error": 0, "warning": 0})

    def test_json_default_file_name(self):
        (self.dir / "pyproject.toml").write_text(GOOD)
        self.assertEqual(json.loads(self.run_tool("--json").out)["file"], "pyproject.toml")

    def test_json_file_is_path_as_given(self):
        sub = self.dir / "sub"
        sub.mkdir()
        (sub / "p.toml").write_text(GOOD)
        self.assertEqual(json.loads(self.run_tool("sub/p.toml", "--json").out)["file"], "sub/p.toml")

    def test_plain_lines_and_summary(self):
        (self.dir / "pyproject.toml").write_text('[tools]\nx = 1\n[project]\nname = "My_Pkg"\nversion = "one"\n')
        r = self.run_tool()
        self.assertEqual(r.code, 1)
        lines = r.out.splitlines()
        self.assertEqual(lines[-1], "errors: 2, warnings: 1")
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("warning name-not-normalized project.name: "))
        self.assertTrue(lines[1].startswith("error invalid-version project.version: "))
        self.assertTrue(lines[2].startswith("error unknown-table tools: "))
        self.assertTrue(r.out.endswith("\n"))

    def test_json_finding_shape(self):
        r = self.check('[project]\nname = "d"\nversion = "one"\n')
        self.assertEqual(r.code, 1)
        doc = json.loads(r.out)
        self.assertEqual(len(doc["findings"]), 1)
        f = doc["findings"][0]
        self.assertEqual((f["rule"], f["severity"], f["path"]), ("invalid-version", "error", "project.version"))
        self.assertTrue(f["message"])
        self.assertEqual(doc["counts"], {"error": 1, "warning": 0})

    def test_sorted_by_path_then_rule(self):
        r = self.check(
            '[project]\nname = "My_Pkg"\nversion = "x"\nlicense = {text = "t", file = "nope"}\n'
            '[zeta]\n[alpha]\n')
        pairs = r.pairs()
        self.assertEqual(pairs, sorted(pairs, key=lambda p: (p[1], p[0])))
        self.assertIn(("file-not-found", "project.license.file"), pairs)
        self.assertEqual([p for p in pairs if p[1] == "project.license"],
                         [("invalid-license", "project.license"), ("license-table-deprecated", "project.license")])

    def test_sort_is_by_code_point_and_text(self):
        deps = ", ".join(['"a!"'] * 12)
        r = self.project("dependencies = [%s]\n" % deps)
        paths = [p for _, p in r.pairs()]
        self.assertEqual(paths, sorted(paths))
        self.assertLess(paths.index("project.dependencies[10]"), paths.index("project.dependencies[2]"))


class Options(ToolCase):
    def test_help(self):
        r = self.run_tool("--help")
        self.assertEqual(r.code, 0)
        self.assertIn("Usage", r.out)

    def test_help_does_not_read_file(self):
        self.assertEqual(self.run_tool("missing.toml", "--help").code, 0)

    def test_help_with_usage_error_is_2(self):
        r = self.run_tool("--help", "--bogus")
        self.assertEqual((r.code, r.out), (2, ""))

    def test_usage_errors(self):
        (self.dir / "a.toml").write_text("")
        (self.dir / "b.toml").write_text("")
        cases = [
            ["a.toml", "--bogus"], ["a.toml", "-"], ["a.toml", "-x"], ["a.toml", "--"],
            ["a.toml", "--json", "--json"], ["a.toml", "--fail-on", "warning", "--fail-on", "none"],
            ["a.toml", "--help", "--help"],
            ["a.toml", "--fail-on"], ["a.toml", "--fail-on", "fatal"], ["a.toml", "--fail-on", "--json"],
            ["a.toml", "--fail-on=warning"], ["a.toml", "b.toml"],
        ]
        for args in cases:
            with self.subTest(args=args):
                r = self.run_tool(*args)
                self.assertEqual((r.code, r.out), (2, ""))
                self.assertTrue(r.err)

    def test_usage_error_found_before_reading_file(self):
        r = self.run_tool("missing.toml", "--bogus")
        self.assertEqual((r.code, r.out), (2, ""))
        self.assertIn("unknown option", r.err)

    def test_fail_on_levels(self):
        (self.dir / "w.toml").write_text('[project]\nname = "My_Pkg"\nversion = "1"\n')
        (self.dir / "e.toml").write_text('[tools]\n')
        (self.dir / "c.toml").write_text(GOOD)
        expected = {
            "w.toml": {"error": 0, "warning": 1, "none": 0},
            "e.toml": {"error": 1, "warning": 1, "none": 0},
            "c.toml": {"error": 0, "warning": 0, "none": 0},
        }
        for name, levels in expected.items():
            for level, code in levels.items():
                with self.subTest(file=name, level=level):
                    r = self.run_tool(name, "--fail-on", level)
                    self.assertEqual(r.code, code)
                    self.assertTrue(r.out.endswith("\n"))

    def test_fail_on_default_is_error(self):
        (self.dir / "pyproject.toml").write_text('[project]\nname = "My_Pkg"\nversion = "1"\n')
        self.assertEqual(self.run_tool().code, 0)
        (self.dir / "pyproject.toml").write_text('[tools]\n')
        self.assertEqual(self.run_tool().code, 1)

    def test_output_still_printed_on_exit_1(self):
        r = self.check('[tools]\n')
        self.assertEqual(r.code, 1)
        self.assertEqual(r.pairs(), [("unknown-table", "tools")])

    def test_option_order_is_free(self):
        (self.dir / "p.toml").write_text('[tools]\n')
        r = self.run_tool("--fail-on", "none", "--json", "p.toml")
        self.assertEqual(r.code, 0)
        self.assertEqual(json.loads(r.out)["counts"]["error"], 1)


class Unreadable(ToolCase):
    def assertTwo(self, r: Run) -> None:
        self.assertEqual((r.code, r.out), (2, ""))
        self.assertTrue(r.err.strip())

    def test_missing_file(self):
        self.assertTwo(self.run_tool("nope.toml"))

    def test_default_path_missing(self):
        self.assertTwo(self.run_tool())

    def test_directory(self):
        (self.dir / "d").mkdir()
        self.assertTwo(self.run_tool("d"))
        self.assertTwo(self.run_tool("d", "--json"))

    def test_invalid_utf8(self):
        (self.dir / "p.toml").write_bytes(b'[project]\nname = "\xff\xfe"\n')
        self.assertTwo(self.run_tool("p.toml"))

    def test_invalid_toml_reports_line_and_column(self):
        (self.dir / "p.toml").write_text('[project]\nname = "x"\nversion = = 1\n')
        r = self.run_tool("p.toml", "--json")
        self.assertTwo(r)
        self.assertIn("(at line 3, column 11)", r.err)

    def test_invalid_toml_duplicate_key(self):
        (self.dir / "p.toml").write_text('a = 1\na = 2\n')
        r = self.run_tool("p.toml")
        self.assertTwo(r)
        self.assertIn("line 2", r.err)

    def test_bom_is_not_toml(self):
        (self.dir / "p.toml").write_bytes(b"\xef\xbb\xbf[project]\n")
        self.assertTwo(self.run_tool("p.toml"))

    def test_non_ascii_content_survives(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\nkeywords = ["é"]\n["t\u00e9"]\n')
        self.assertEqual(r.code, 1)
        self.assertEqual(r.pairs(), [("unknown-table", '"t\u00e9"')])


class TopLevel(ToolCase):
    def test_unknown_tables_and_keys(self):
        r = self.check('foo = 1\n[tools]\na = 1\n[tool.x]\n[dependency-groups]\ntest = ["pytest"]\n')
        self.assertPairs(r, ("unknown-table", "foo"), ("unknown-table", "tools"))

    def test_quoted_top_level_key(self):
        r = self.check('"a.b" = 1\n"q\\"x" = 2\n')
        self.assertPairs(r, ("unknown-table", '"a.b"'), ("unknown-table", '"q\\"x"'))

    def test_known_keys_must_be_tables(self):
        r = self.check('build-system = 1\nproject = "x"\ntool = []\ndependency-groups = true\n')
        self.assertPairs(r, *[("wrong-type", k) for k in ("build-system", "project", "tool", "dependency-groups")])

    def test_tool_and_dependency_groups_not_checked(self):
        r = self.check('[tool.anything]\nx = [1, "a b"]\n[dependency-groups]\ntest = ["!!!", 1]\n')
        self.assertClean(r)

    def test_no_tables_no_findings(self):
        self.assertClean(self.check('[tool.x]\na = 1\n'))


class BuildSystem(ToolCase):
    def test_requires_missing(self):
        r = self.check('[build-system]\nbuild-backend = "a.b"\n')
        self.assertPairs(r, ("missing-key", "build-system.requires"))

    def test_requires_wrong_types(self):
        self.assertPairs(self.check('[build-system]\nrequires = "x"\n'), ("wrong-type", "build-system.requires"))
        r = self.check('[build-system]\nrequires = ["a", 1, "b>=", "c"]\n')
        self.assertPairs(r, ("wrong-type", "build-system.requires[1]"), ("invalid-requirement", "build-system.requires[2]"))

    def test_backend(self):
        good = ["setuptools.build_meta", "a:b", "a.b:c.d", "_x", "a_1.b2:C"]
        bad = ["", "a b", "1a", "a.", ".a", "a:", "a:b:c", "a-b", "a..b"]
        for g in good:
            with self.subTest(g=g):
                self.assertClean(self.check('[build-system]\nrequires = []\nbuild-backend = "%s"\n' % g))
        for b in bad:
            with self.subTest(b=b):
                r = self.check('[build-system]\nrequires = []\nbuild-backend = "%s"\n' % b)
                self.assertPairs(r, ("invalid-object-reference", "build-system.build-backend"))

    def test_backend_wrong_type(self):
        r = self.check('[build-system]\nrequires = []\nbuild-backend = 1\n')
        self.assertPairs(r, ("wrong-type", "build-system.build-backend"))

    def test_backend_path(self):
        self.assertClean(self.check('[build-system]\nrequires = []\nbackend-path = ["a", "b c"]\n'))
        r = self.check('[build-system]\nrequires = []\nbackend-path = ["a", 2]\n')
        self.assertPairs(r, ("wrong-type", "build-system.backend-path[1]"))
        r = self.check('[build-system]\nrequires = []\nbackend-path = "a"\n')
        self.assertPairs(r, ("wrong-type", "build-system.backend-path"))

    def test_other_keys_not_reported(self):
        self.assertClean(self.check('[build-system]\nrequires = []\nwhatever = 1\n'))

    def test_no_build_system_no_findings(self):
        self.assertClean(self.check('[project]\nname = "d"\nversion = "1"\n'))


class Name(ToolCase):
    def test_missing(self):
        r = self.check('[project]\nversion = "1"\n')
        self.assertPairs(r, ("missing-key", "project.name"))

    def test_invalid_names(self):
        for bad in ["", "-a", "a-", "a b", "a/b", ".a", "a.", "_a", "ä"]:
            with self.subTest(bad=bad):
                r = self.check('[project]\nname = "%s"\nversion = "1"\n' % bad)
                self.assertPairs(r, ("invalid-name", "project.name"))

    def test_valid_names(self):
        for good in ["a", "A", "a1", "my-package", "a.b_c-d", "0", "a--b"]:
            with self.subTest(good=good):
                r = self.check('[project]\nname = "%s"\nversion = "1"\n' % good)
                self.assertEqual([p for p in r.pairs() if p[0] == "invalid-name"], [])

    def test_normalization(self):
        for name in ["My_Package", "My.Package", "my__package", "a-_b", "Foo", "a.-b"]:
            with self.subTest(name=name):
                r = self.check('[project]\nname = "%s"\nversion = "1"\n' % name)
                self.assertPairs(r, ("name-not-normalized", "project.name"))
                self.assertEqual(r.findings()[0]["severity"], "warning")
        self.assertClean(self.check('[project]\nname = "my-package"\nversion = "1"\n'))

    def test_wrong_type(self):
        self.assertPairs(self.check('[project]\nname = 1\nversion = "1"\n'), ("wrong-type", "project.name"))


class Version(ToolCase):
    def test_valid(self):
        for v in ["1.0", "1!2.0.post1", "2024.01.05", "1.0rc1", "1.0.dev3", "v1.0", "1.0-1",
                  "1.0+ubuntu.1", "1", "1.0a", "1.0.alpha.2", "1.0-beta_3", "1.0.POST1", "V1.0RC1",
                  "1.0.post1.dev2", "1.0rev3", "1.0-r4", "0.1.0+abc-def_1", "1.0c1", "1.0pre"]:
            with self.subTest(v=v):
                self.assertClean(self.check('[project]\nname = "d"\nversion = "%s"\n' % v))

    def test_invalid(self):
        for v in ["1.0.final", "one", "1..0", "1.0+", "", " 1.0", "1.0 ", "1.0.", "v", "1.0+_a", "1.0\\n", "1!", "1.0-"]:
            with self.subTest(v=v):
                r = self.check('[project]\nname = "d"\nversion = "%s"\n' % v)
                self.assertPairs(r, ("invalid-version", "project.version"))

    def test_missing(self):
        self.assertPairs(self.check('[project]\nname = "d"\n'), ("missing-key", "project.version"))

    def test_missing_but_dynamic(self):
        self.assertClean(self.check('[project]\nname = "d"\ndynamic = ["version"]\n'))

    def test_wrong_type(self):
        self.assertPairs(self.check('[project]\nname = "d"\nversion = 1.0\n'), ("wrong-type", "project.version"))


class Description(ToolCase):
    def test_line_breaks(self):
        for s in ['a\\nb', 'a\\rb', 'a\\r\\nb', '\\n']:
            with self.subTest(s=s):
                r = self.check('[project]\nname = "d"\nversion = "1"\ndescription = "%s"\n' % s)
                self.assertPairs(r, ("invalid-description", "project.description"))

    def test_fine(self):
        self.assertClean(self.check('[project]\nname = "d"\nversion = "1"\ndescription = ""\n'))
        self.assertClean(self.check('[project]\nname = "d"\nversion = "1"\ndescription = "a  b\\tc"\n'))

    def test_wrong_type(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\ndescription = ["a"]\n')
        self.assertPairs(r, ("wrong-type", "project.description"))


class Readme(ToolCase):
    HEAD = '[project]\nname = "d"\nversion = "1"\n'

    def test_string_ok(self):
        for name in ["README.md", "README.RST", "r.Txt", "docs/README.md"]:
            with self.subTest(name=name):
                path = self.dir / name
                path.parent.mkdir(exist_ok=True)
                path.write_text("x")
                self.assertClean(self.check(self.HEAD + 'readme = "%s"\n' % name))

    def test_string_not_found(self):
        self.assertPairs(self.check(self.HEAD + 'readme = "README.md"\n'), ("file-not-found", "project.readme"))

    def test_string_bad_extension_both(self):
        (self.dir / "README").write_text("x")
        r = self.check(self.HEAD + 'readme = "README"\n')
        self.assertPairs(r, ("invalid-readme", "project.readme"))
        r = self.check(self.HEAD + 'readme = "README.markdown"\n')
        self.assertPairs(r, ("invalid-readme", "project.readme"), ("file-not-found", "project.readme"))

    def test_string_is_directory(self):
        (self.dir / "d.md").mkdir()
        self.assertPairs(self.check(self.HEAD + 'readme = "d.md"\n'), ("file-not-found", "project.readme"))

    def test_file_is_relative_to_checked_file(self):
        sub = self.dir / "sub"
        sub.mkdir()
        (sub / "p.toml").write_text(self.HEAD + 'readme = "R.md"\n')
        (sub / "R.md").write_text("x")
        r = self.run_tool("sub/p.toml", "--json")
        self.assertEqual(r.pairs(), [])
        (sub / "R.md").unlink()
        (self.dir / "R.md").write_text("x")
        r = self.run_tool("sub/p.toml", "--json")
        self.assertEqual(r.pairs(), [("file-not-found", "project.readme")])

    def test_table_file(self):
        (self.dir / "R.md").write_text("x")
        self.assertClean(self.check(self.HEAD + 'readme = {file = "R.md", content-type = "text/markdown"}\n'))
        r = self.check(self.HEAD + 'readme = {file = "X.md", content-type = "text/markdown"}\n')
        self.assertPairs(r, ("file-not-found", "project.readme.file"))

    def test_table_file_extension_not_checked(self):
        (self.dir / "R").write_text("x")
        self.assertClean(self.check(self.HEAD + 'readme = {file = "R", content-type = "text/plain"}\n'))

    def test_table_text(self):
        self.assertClean(self.check(self.HEAD + 'readme = {text = "hi", content-type = "text/x-rst"}\n'))

    def test_table_neither_or_both(self):
        r = self.check(self.HEAD + 'readme = {content-type = "text/plain"}\n')
        self.assertPairs(r, ("invalid-readme", "project.readme"))
        (self.dir / "R.md").write_text("x")
        r = self.check(self.HEAD + 'readme = {file = "R.md", text = "t", content-type = "text/plain"}\n')
        self.assertPairs(r, ("invalid-readme", "project.readme"))

    def test_table_unknown_key(self):
        r = self.check(self.HEAD + 'readme = {text = "t", content-type = "text/plain", charset = "x", "a.b" = 1}\n')
        self.assertPairs(r, ("unknown-key", "project.readme.charset"), ("unknown-key", 'project.readme."a.b"'))

    def test_table_content_type(self):
        for ct in ["text/markdown; charset=UTF-8", " TEXT/Markdown ;x", "\\ttext/plain", "text/x-rst"]:
            with self.subTest(ct=ct):
                self.assertClean(self.check(self.HEAD + 'readme = {text = "t", content-type = "%s"}\n' % ct))
        for ct in ["", "text/html", "markdown", "text/markdown2", "; text/plain", "text/ plain"]:
            with self.subTest(ct=ct):
                r = self.check(self.HEAD + 'readme = {text = "t", content-type = "%s"}\n' % ct)
                self.assertPairs(r, ("invalid-readme", "project.readme.content-type"))

    def test_table_content_type_missing(self):
        r = self.check(self.HEAD + 'readme = {text = "t"}\n')
        self.assertPairs(r, ("missing-key", "project.readme.content-type"))

    def test_wrong_types(self):
        self.assertPairs(self.check(self.HEAD + 'readme = 1\n'), ("wrong-type", "project.readme"))
        self.assertPairs(self.check(self.HEAD + 'readme = ["a.md"]\n'), ("wrong-type", "project.readme"))
        r = self.check(self.HEAD + 'readme = {file = 1, content-type = 2}\n')
        self.assertPairs(r, ("wrong-type", "project.readme.file"), ("wrong-type", "project.readme.content-type"))
        r = self.check(self.HEAD + 'readme = {text = 1, content-type = "text/plain"}\n')
        self.assertPairs(r, ("wrong-type", "project.readme.text"))


class RequiresPython(ToolCase):
    HEAD = '[project]\nname = "d"\nversion = "1"\n'

    def test_valid(self):
        for s in [">=3.8, <4", ">=3.11", "==1.*", "~=1.4", "~=2.0.1", "!=3.0.*, >=2", ">= 3.8", ">=\\t3.8 ,\\t<4",
                  "===abc", "<=3", ">3.1.0rc1", "==1.0+local", "!=1.*", "~=1.0.post1", "~=1!2.0"]:
            with self.subTest(s=s):
                self.assertClean(self.check(self.HEAD + 'requires-python = "%s"\n' % s))

    def test_invalid(self):
        for s in ["", ">=3.8,", ",>=3", "3.8", "=>3.8", "~=1", ">=", ">=3.8 <4", ">=1.*", "<1.0+x", "~=1.0+x", ">=3,,<4",
                  "~=1.dev1", "~=1!2", "===", "=== a b", "==1.*.*", "==", "<>3", "===a,b", ">=1.0 .0"]:
            with self.subTest(s=s):
                r = self.check(self.HEAD + 'requires-python = "%s"\n' % s)
                self.assertPairs(r, ("invalid-specifier", "project.requires-python"))

    def test_wrong_type(self):
        self.assertPairs(self.check(self.HEAD + 'requires-python = 3\n'), ("wrong-type", "project.requires-python"))


class Requirements(ToolCase):
    def deps(self, *items: str) -> Run:
        body = "dependencies = [%s]\n" % ", ".join(json.dumps(i) for i in items)
        return self.check('[project]\nname = "d"\nversion = "1"\n' + body)

    def test_valid(self):
        good = [
            "requests", "Requests[security, socks]>=2.0,<3", "numpy (>=1.20)", "pkg @ https://example.com/p.zip",
            'tomli>=1.1; python_version < "3.11"', "  pkg  ", "a", "a.b-c_d", "pkg[]", "pkg [ a , b ]", "pkg >= 1",
            "pkg(>=1, <2)", "pkg @https://x/y", "pkg @ file:///a/b", 'pkg @ https://x/y ; os_name == "nt"',
            'pkg ;python_version>"3"', "pkg===1.0", "pkg==1.*", "pkg\t>=\t1", "pkg[extra]==1.0 ; extra == 'x'",
            "pkg (>=1) ; os_name == 'nt'", "pkg == 1.0 , != 1.1", "pkg ~= 1.4.2",
            'pkg @ git+https://github.com/a/b.git@v1 ; sys_platform == "linux"',
        ]
        for item in good:
            with self.subTest(item=item):
                self.assertClean(self.deps(item))

    def test_invalid(self):
        bad = [
            "requests>=", "requests==", "my pkg", "-e .", "requests>=2.0;", "pytest[", "requests 2.0", "", " ", "pkg ;",
            "pkg[a,]", "pkg[,a]", "pkg[a b]", "pkg[-a]", "pkg>=1,", "pkg(>=1", "pkg()", "pkg(>=1) x", "pkg @", "pkg @ foo",
            "pkg @ 1x:y", "pkg @ https://x ; ", 'pkg @ https://x; os_name == "nt"', "pkg @ https://x >=1", "pkg>=1 @ https://x",
            "pkg>=1)", "pkg ~=1", "pkg-", ".pkg", "pkg.", "pkg;python_version", 'pkg; colour == "red"', "pkg[a]x", "pkg>=1 x",
            "pkg=1", "pkg=>1", "pkg>=1\n", "pkg\n>=1", "pkg [a]]", "pkg ,", "pkg!", "pkg == 1.0 ; ; os_name == 'x'",
        ]
        r = self.deps(*bad)
        got = {p for rule, p in r.pairs() if rule == "invalid-requirement"}
        want = {"project.dependencies[%d]" % i for i in range(len(bad))}
        self.assertEqual(want - got, set(), r.out)
        self.assertEqual(got - want, set())

    def test_each_wrong_element_is_reported_and_others_checked(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\ndependencies = ["a>=", 3, "b", "c!"]\n')
        self.assertPairs(r, ("invalid-requirement", "project.dependencies[0]"), ("wrong-type", "project.dependencies[1]"),
                         ("invalid-requirement", "project.dependencies[3]"))

    def test_dependencies_wrong_type(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\ndependencies = "a"\n')
        self.assertPairs(r, ("wrong-type", "project.dependencies"))

    def test_optional_dependencies(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\n[project.optional-dependencies]\n'
                       'dev = ["pytest", "x>=", 4]\ndocs = ["sphinx"]\nbad = "x"\n')
        self.assertPairs(r, ("invalid-requirement", "project.optional-dependencies.dev[1]"),
                         ("wrong-type", "project.optional-dependencies.dev[2]"),
                         ("wrong-type", "project.optional-dependencies.bad"))

    def test_optional_dependencies_wrong_type(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\noptional-dependencies = ["a"]\n')
        self.assertPairs(r, ("wrong-type", "project.optional-dependencies"))

    def test_extra_names(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\n[project.optional-dependencies]\n'
                       '"my extra" = []\n"-x" = ["bad!"]\nok_1 = []\n')
        self.assertPairs(r, ("invalid-extra-name", 'project.optional-dependencies."my extra"'),
                         ("invalid-extra-name", "project.optional-dependencies.-x"),
                         ("invalid-requirement", "project.optional-dependencies.-x[0]"))

    def test_duplicate_extras(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\n[project.optional-dependencies]\n'
                       'Foo_Bar = []\nfoo-bar = []\n"foo.bar" = []\nother = []\n"-bad" = []\n')
        self.assertPairs(r, ("duplicate-extra", "project.optional-dependencies.foo-bar"),
                         ("duplicate-extra", 'project.optional-dependencies."foo.bar"'),
                         ("invalid-extra-name", "project.optional-dependencies.-bad"))

    def test_invalid_extra_not_counted_as_duplicate(self):
        r = self.check('[project]\nname = "d"\nversion = "1"\n[project.optional-dependencies]\n'
                       '"a b" = []\n"a-b" = []\n')
        self.assertPairs(r, ("invalid-extra-name", 'project.optional-dependencies."a b"'))


class Markers(ToolCase):
    def marker(self, m: str) -> Run:
        text = 'pkg; ' + m
        return self.check('[project]\nname = "d"\nversion = "1"\ndependencies = [%s]\n' % json.dumps(text))

    def test_valid_markers(self):
        for m in ['python_version < "3.11"', "extra == 'test' and os_name == \"nt\"",
                  '(sys_platform == "win32" or sys_platform == "cygwin") and python_version >= "3.8"',
                  '"3" < python_version', 'python_version<"3"', 'os_name not in "abc"', '"a" in platform_machine',
                  'platform_python_implementation=="CPython"', 'implementation_name != "x" or implementation_version ~= "1.0"',
                  'python_full_version === "3.9.1"', '((os_name == "a"))', 'os_name == "a" or os_name == "b" and os_name == "c"',
                  'sys_platform == "it\'s"', "os_name == 'say \"hi\"'", 'platform_release == platform_version',
                  'platform_system == "x" and (platform_machine == "y")', 'extra == "a"\t', '"" == ""']:
            with self.subTest(m=m):
                self.assertClean(self.marker(m))

    def test_invalid_markers(self):
        for m in ['python_version <', 'colour == "red"', '"3" < python_version python_version', 'os.name == "nt"',
                  '()', '(os_name == "a"', 'os_name == "a")', 'os_name == "a" and', 'and os_name == "a"',
                  'os_name = "a"', 'os_name =< "a"', 'os_name == "a', 'os_name "a"', 'os_name == "a" "b"',
                  'os_name not "a"', 'os_name == 1', 'AND', 'os_name == "a" AND os_name == "b"',
                  'OS_NAME == "a"', 'os_name == "a" & os_name == "b"', 'os_name == "a" , os_name == "b"',
                  'python_version >== "3"', 'os_name in', 'os_name not in', 'os_name == and', 'os_name == "a" or or os_name == "b"',
                  '"a" == "b" os_name', 'extra', '(os_name)', 'in == "a"', 'not in os_name', 'python_version == 3.8',
                  '1 == 1', 'os-name == "a"', '(os_name == "a" or) ', 'os_name == "a" (os_name == "b")']:
            with self.subTest(m=m):
                r = self.marker(m)
                self.assertPairs(r, ("invalid-requirement", "project.dependencies[0]"))

    def test_empty_marker_text_invalid(self):
        self.assertPairs(self.marker(""), ("invalid-requirement", "project.dependencies[0]"))
        self.assertPairs(self.marker(" \t"), ("invalid-requirement", "project.dependencies[0]"))

    def test_deeply_nested_marker(self):
        depth = 3000
        m = "(" * depth + 'os_name == "a"' + ")" * depth
        self.assertClean(self.marker(m))
        self.assertPairs(self.marker("(" * depth + 'os_name == "a"' + ")" * (depth - 1)),
                         ("invalid-requirement", "project.dependencies[0]"))


class Duplicates(ToolCase):
    def deps(self, key_table: str, *items: str) -> Run:
        arr = "[%s]" % ", ".join(json.dumps(i) for i in items)
        return self.check(key_table.replace("ARR", arr))

    P = '[project]\nname = "d"\nversion = "1"\ndependencies = ARR\n'

    def test_same_dependency(self):
        r = self.deps(self.P, "requests>=2", "requests<3", "Requests", "REQUESTS[x]", "requests[X]", "requests_2")
        self.assertPairs(r, ("duplicate-dependency", "project.dependencies[1]"), ("duplicate-dependency", "project.dependencies[2]"),
                         ("duplicate-dependency", "project.dependencies[4]"))
        self.assertEqual({f["severity"] for f in r.findings()}, {"warning"})

    def test_normalized_names(self):
        r = self.deps(self.P, "My_Pkg", "my-pkg", "my.pkg", "MY--PKG")
        self.assertPairs(r, *[("duplicate-dependency", "project.dependencies[%d]" % i) for i in (1, 2, 3)])

    def test_extras_are_sets(self):
        r = self.deps(self.P, "a[x,y]", "a[y, x]", "a[x]", "a[x,x]", "a[Y,x]", "a[Y_x,x]")
        self.assertPairs(r, *[("duplicate-dependency", "project.dependencies[%d]" % i) for i in (1, 3, 4)])

    def test_markers_are_compared_as_text(self):
        r = self.deps(self.P, 'a; os_name == "nt"', 'a ;  os_name == "nt"  ', 'a; os_name=="nt"', "a", 'a>=1; os_name == "nt"',
                      'a @ https://x ; os_name == "nt"')
        self.assertPairs(r, ("duplicate-dependency", "project.dependencies[1]"), ("duplicate-dependency", "project.dependencies[4]"),
                         ("duplicate-dependency", "project.dependencies[5]"))

    def test_invalid_entries_left_out(self):
        r = self.deps(self.P, "a>=", "a>=", "a", "a")
        self.assertPairs(r, ("invalid-requirement", "project.dependencies[0]"), ("invalid-requirement", "project.dependencies[1]"),
                         ("duplicate-dependency", "project.dependencies[3]"))

    def test_build_requires(self):
        r = self.deps('[build-system]\nrequires = ARR\n', "setuptools", "wheel", "Setuptools>=61")
        self.assertPairs(r, ("duplicate-dependency", "build-system.requires[2]"))

    def test_each_array_alone(self):
        r = self.check('[build-system]\nrequires = ["a"]\n[project]\nname = "d"\nversion = "1"\ndependencies = ["a"]\n'
                       '[project.optional-dependencies]\nx = ["a"]\ny = ["a", "a"]\n')
        self.assertPairs(r, ("duplicate-dependency", "project.optional-dependencies.y[1]"))


class License(ToolCase):
    HEAD = '[project]\nname = "d"\nversion = "1"\n'

    def lic(self, s: str) -> Run:
        return self.check(self.HEAD + "license = %s\n" % json.dumps(s))

    def test_valid_expressions(self):
        for s in ["MIT", "Apache-2.0", "GPL-2.0-or-later", "GPL-2.0+", "MIT OR Apache-2.0", "(MIT OR Apache-2.0) AND BSD-3-Clause",
                  "GPL-2.0-only WITH Classpath-exception-2.0", "LicenseRef-Proprietary", "mit or apache-2.0", "MIT\\tAND\\tBSD",
                  "((MIT))", "(MIT)AND(BSD)", "A WITH b AND C", "x1.2", "MIT with Exc"]:
            with self.subTest(s=s):
                r = self.check(self.HEAD + 'license = "%s"\n' % s)
                self.assertClean(r)

    def test_invalid_expressions(self):
        for s in ["MIT OR", "MIT AND AND Apache-2.0", "Apache 2.0", "MIT,Apache-2.0", "", " ", "(MIT", "MIT)", "()", "OR MIT", "AND",
                  "MIT WITH", "WITH x", "MIT WITH WITH x", "(A OR B) WITH x", "A WITH b WITH c", "A WITH b+", "+MIT", "-MIT", "MIT+ +",
                  "A++", "a+b", "MIT\\n", "MIT/BSD", "A WITH (b)", "MIT OR (", "MIT BSD", "MIT_1", "(A) (B)", ".MIT", "A WITH and"]:
            with self.subTest(s=s):
                r = self.check(self.HEAD + 'license = "%s"\n' % s)
                self.assertPairs(r, ("invalid-license", "project.license"))

    def test_table_deprecated_with_file(self):
        (self.dir / "LICENSE").write_text("x")
        r = self.check(self.HEAD + 'license = {file = "LICENSE"}\n')
        self.assertPairs(r, ("license-table-deprecated", "project.license"))
        self.assertEqual(r.findings()[0]["severity"], "warning")

    def test_table_with_text(self):
        r = self.check(self.HEAD + 'license = {text = "MIT"}\n')
        self.assertPairs(r, ("license-table-deprecated", "project.license"))

    def test_table_file_missing(self):
        r = self.check(self.HEAD + 'license = {file = "LICENSE"}\n')
        self.assertPairs(r, ("license-table-deprecated", "project.license"), ("file-not-found", "project.license.file"))

    def test_table_file_relative_to_checked_file(self):
        sub = self.dir / "s"
        sub.mkdir()
        (sub / "L").write_text("x")
        (sub / "p.toml").write_text(self.HEAD + 'license = {file = "L"}\n')
        self.assertEqual(self.run_tool("s/p.toml", "--json").pairs(), [("license-table-deprecated", "project.license")])

    def test_table_neither_or_both(self):
        (self.dir / "L").write_text("x")
        for body in ['license = {}\n', 'license = {file = "L", text = "t"}\n']:
            with self.subTest(body=body):
                r = self.check(self.HEAD + body)
                self.assertPairs(r, ("license-table-deprecated", "project.license"), ("invalid-license", "project.license"))

    def test_table_unknown_key(self):
        r = self.check(self.HEAD + 'license = {text = "t", url = "u"}\n')
        self.assertPairs(r, ("license-table-deprecated", "project.license"), ("unknown-key", "project.license.url"))

    def test_table_wrong_types(self):
        r = self.check(self.HEAD + 'license = {file = 1}\n')
        self.assertPairs(r, ("license-table-deprecated", "project.license"), ("wrong-type", "project.license.file"))
        r = self.check(self.HEAD + 'license = {text = 1}\n')
        self.assertPairs(r, ("license-table-deprecated", "project.license"), ("wrong-type", "project.license.text"))

    def test_wrong_type(self):
        self.assertPairs(self.check(self.HEAD + 'license = 1\n'), ("wrong-type", "project.license"))
        self.assertPairs(self.check(self.HEAD + 'license = ["MIT"]\n'), ("wrong-type", "project.license"))


class SimpleArrays(ToolCase):
    HEAD = '[project]\nname = "d"\nversion = "1"\n'

    def test_string_arrays(self):
        for key in ("license-files", "keywords", "classifiers"):
            with self.subTest(key=key):
                self.assertClean(self.check(self.HEAD + '%s = ["anything goes", ""]\n' % key))
                self.assertPairs(self.check(self.HEAD + '%s = ["a", 1]\n' % key), ("wrong-type", "project.%s[1]" % key))
                self.assertPairs(self.check(self.HEAD + '%s = "a"\n' % key), ("wrong-type", "project.%s" % key))

    def test_unknown_keys(self):
        r = self.check(self.HEAD + 'foo = 1\n"a.b" = 2\nrequires_python = ">=3"\n')
        self.assertPairs(r, ("unknown-key", "project.foo"), ("unknown-key", 'project."a.b"'), ("unknown-key", "project.requires_python"))

    def test_urls(self):
        self.assertClean(self.check(self.HEAD + '[project.urls]\nHomepage = "not a url"\n"Bug Tracker" = ""\n'))
        r = self.check(self.HEAD + '[project.urls]\nHomepage = 1\n"Bug Tracker" = ["x"]\n')
        self.assertPairs(r, ("wrong-type", "project.urls.Homepage"), ("wrong-type", 'project.urls."Bug Tracker"'))
        self.assertPairs(self.check(self.HEAD + 'urls = "x"\n'), ("wrong-type", "project.urls"))


class People(ToolCase):
    HEAD = '[project]\nname = "d"\nversion = "1"\n'

    def test_valid(self):
        self.assertClean(self.check(self.HEAD + 'authors = [{name = "A B"}, {email = "a@b"}, {name = "N", email = "a.b+c@x.org"}]\n'
                                    'maintainers = [{name = "Jean-Luc"}]\n'))

    def test_empty_array_ok(self):
        self.assertClean(self.check(self.HEAD + "authors = []\n"))

    def test_unknown_key(self):
        r = self.check(self.HEAD + 'authors = [{name = "A", url = "x"}]\nmaintainers = [{name = "A"}, {name = "B", "a.b" = 1}]\n')
        self.assertPairs(r, ("unknown-key", "project.authors[0].url"), ("unknown-key", 'project.maintainers[1]."a.b"'))

    def test_neither_name_nor_email(self):
        r = self.check(self.HEAD + 'authors = [{}, {url = "x"}]\n')
        self.assertPairs(r, ("invalid-person", "project.authors[0]"), ("invalid-person", "project.authors[1]"),
                         ("unknown-key", "project.authors[1].url"))

    def test_bad_name(self):
        r = self.check(self.HEAD + 'authors = [{name = ""}, {name = "A, B"}, {name = 1}]\n')
        self.assertPairs(r, ("invalid-person", "project.authors[0].name"), ("invalid-person", "project.authors[1].name"),
                         ("wrong-type", "project.authors[2].name"))

    def test_bad_email(self):
        for e in ["", "a", "a@", "@b", "a b@c", "a@b c", "a@b@c", "a<@b", "A <a@b>", "a,b@c", "a@b>", " a@b", "a@b\\n"]:
            with self.subTest(e=e):
                r = self.check(self.HEAD + 'authors = [{email = "%s"}]\n' % e)
                self.assertPairs(r, ("invalid-person", "project.authors[0].email"))
        self.assertPairs(self.check(self.HEAD + 'authors = [{email = 1}]\n'), ("wrong-type", "project.authors[0].email"))

    def test_wrong_types(self):
        self.assertPairs(self.check(self.HEAD + 'authors = "A"\n'), ("wrong-type", "project.authors"))
        self.assertPairs(self.check(self.HEAD + 'authors = ["A", {name = "B"}]\n'), ("wrong-type", "project.authors[0]"))
        self.assertPairs(self.check(self.HEAD + 'maintainers = [1]\n'), ("wrong-type", "project.maintainers[0]"))


class Scripts(ToolCase):
    HEAD = '[project]\nname = "d"\nversion = "1"\n'

    def test_valid(self):
        self.assertClean(self.check(self.HEAD + '[project.scripts]\ntool = "pkg.mod:main"\n"my.tool-2_x" = "a:b.c"\n'
                                    '[project.gui-scripts]\ngui = "p:q"\n'))

    def test_bad_values(self):
        for v in ["pkg.mod", "pkg:", ":x", "a:b:c", "a b:c", "a:b [extra]", "1a:b", "a.:b", "a:b.", "", "a-b:c"]:
            with self.subTest(v=v):
                for table in ("scripts", "gui-scripts"):
                    r = self.check(self.HEAD + '[project.%s]\ntool = "%s"\n' % (table, v))
                    self.assertPairs(r, ("invalid-object-reference", "project.%s.tool" % table))

    def test_bad_names(self):
        r = self.check(self.HEAD + '[project.scripts]\n"my tool" = "a:b"\n"" = "a:b"\n"a/b" = "bad"\n')
        self.assertPairs(r, ("invalid-entry-name", 'project.scripts."my tool"'), ("invalid-entry-name", 'project.scripts.""'),
                         ("invalid-entry-name", 'project.scripts."a/b"'), ("invalid-object-reference", 'project.scripts."a/b"'))

    def test_wrong_types(self):
        r = self.check(self.HEAD + '[project.scripts]\ntool = 1\n')
        self.assertPairs(r, ("wrong-type", "project.scripts.tool"))
        self.assertPairs(self.check(self.HEAD + 'scripts = "x"\n'), ("wrong-type", "project.scripts"))
        self.assertPairs(self.check(self.HEAD + 'gui-scripts = []\n'), ("wrong-type", "project.gui-scripts"))


class EntryPoints(ToolCase):
    HEAD = '[project]\nname = "d"\nversion = "1"\n'

    def test_valid(self):
        self.assertClean(self.check(self.HEAD + '[project.entry-points."my.group"]\ntool = "pkg.mod"\nother = "a:b.c"\n'
                                    '[project.entry-points.plain_1]\nx = "m"\n'))

    def test_path_with_quoted_group(self):
        r = self.check(self.HEAD + '[project.entry-points."my.group"]\n"bad name" = "m"\ntool = "a:"\n')
        self.assertPairs(r, ('invalid-entry-name', 'project.entry-points."my.group"."bad name"'),
                         ("invalid-object-reference", 'project.entry-points."my.group".tool'))

    def test_reserved_groups(self):
        r = self.check(self.HEAD + '[project.entry-points.console_scripts]\nx = "a:b"\n[project.entry-points.gui_scripts]\ny = "bad ref"\n')
        self.assertPairs(r, ("reserved-entry-point-group", "project.entry-points.console_scripts"),
                         ("reserved-entry-point-group", "project.entry-points.gui_scripts"),
                         ("invalid-object-reference", "project.entry-points.gui_scripts.y"))

    def test_bad_group_names(self):
        r = self.check(self.HEAD + '[project.entry-points."a-b"]\nx = "m"\n[project.entry-points."a..b"]\nx = "m"\n'
                       '[project.entry-points."a b"]\n[project.entry-points.".a"]\n[project.entry-points."a."]\n')
        self.assertPairs(r, ("invalid-entry-name", "project.entry-points.a-b"),
                         *[("invalid-entry-name", 'project.entry-points."%s"' % g) for g in ("a..b", "a b", ".a", "a.")])

    def test_group_name_escaping(self):
        r = self.check(self.HEAD + '[project.entry-points."a\\"b"]\nx = "m"\n[project.entry-points."c\\\\d"]\nx = "m"\n')
        self.assertPairs(r, ("invalid-entry-name", 'project.entry-points."a\\"b"'), ("invalid-entry-name", 'project.entry-points."c\\\\d"'))

    def test_wrong_types(self):
        self.assertPairs(self.check(self.HEAD + 'entry-points = []\n'), ("wrong-type", "project.entry-points"))
        self.assertPairs(self.check(self.HEAD + '[project.entry-points]\ngroup = "x"\n'), ("wrong-type", "project.entry-points.group"))
        r = self.check(self.HEAD + '[project.entry-points.group]\nname = 1\n')
        self.assertPairs(r, ("wrong-type", "project.entry-points.group.name"))
        r = self.check(self.HEAD + '[project.entry-points."a.b"]\nname = ["x"]\n')
        self.assertPairs(r, ("wrong-type", 'project.entry-points."a.b".name'))


class Dynamic(ToolCase):
    HEAD = '[project]\nname = "d"\n'

    def test_valid(self):
        self.assertClean(self.check(self.HEAD + 'dynamic = ["version", "description", "readme", "requires-python", "license", '
                                    '"license-files", "authors", "maintainers", "keywords", "classifiers", "urls", "scripts", '
                                    '"gui-scripts", "entry-points", "dependencies", "optional-dependencies"]\n'))

    def test_invalid_entries(self):
        r = self.check(self.HEAD + 'version = "1"\ndynamic = ["name", "dynamic", "versoin", "Version", ""]\n')
        self.assertPairs(r, *[("invalid-dynamic", "project.dynamic[%d]" % i) for i in range(5)])

    def test_conflict(self):
        r = self.check(self.HEAD + 'version = "1"\ndescription = "x"\ndynamic = ["version", "description", "version"]\n')
        self.assertPairs(r, ("dynamic-conflict", "project.version"), ("dynamic-conflict", "project.description"))

    def test_conflict_does_not_stop_other_rules(self):
        r = self.check(self.HEAD + 'version = "one"\ndynamic = ["version"]\n')
        self.assertPairs(r, ("dynamic-conflict", "project.version"), ("invalid-version", "project.version"))

    def test_invalid_entry_gives_no_conflict(self):
        r = self.check(self.HEAD + 'version = "1"\ndynamic = ["name"]\n')
        self.assertPairs(r, ("invalid-dynamic", "project.dynamic[0]"))

    def test_wrong_types(self):
        self.assertPairs(self.check(self.HEAD + 'version = "1"\ndynamic = "version"\n'), ("wrong-type", "project.dynamic"))
        r = self.check(self.HEAD + 'version = "1"\ndynamic = [1, "version"]\n')
        self.assertPairs(r, ("wrong-type", "project.dynamic[0]"), ("dynamic-conflict", "project.version"))

    def test_name_missing_not_excused_by_dynamic(self):
        r = self.check('[project]\nversion = "1"\ndynamic = ["name"]\n')
        self.assertPairs(r, ("missing-key", "project.name"), ("invalid-dynamic", "project.dynamic[0]"))


class PinnedLibrary(ToolCase):
    def proj(self, name: str, deps: str, extra: str = "") -> Run:
        return self.check('[project]\nname = "%s"\nversion = "1"\n%sdependencies = %s\n' % (name, extra, deps))

    def test_by_classifier(self):
        for c in ["Topic :: Software Development :: Libraries", "Topic :: Software Development :: Libraries :: Python Modules"]:
            with self.subTest(c=c):
                r = self.proj("app", '["a==1.0", "b>=1", "c"]', 'classifiers = ["%s"]\n' % c)
                self.assertPairs(r, ("pinned-library-dependency", "project.dependencies[0]"))
                self.assertEqual(r.findings()[0]["severity"], "warning")

    def test_not_a_library_classifier(self):
        for c in ["Topic :: Software Development :: Libraries2", "Topic :: Software Development :: Build Tools",
                  "topic :: software development :: libraries", " Topic :: Software Development :: Libraries"]:
            with self.subTest(c=c):
                self.assertClean(self.proj("app", '["a==1.0"]', 'classifiers = ["%s"]\n' % c))

    def test_by_name(self):
        for n in ["my-lib", "lib", "my_library", "Library.x", "x-lib-y", "LIB-a"]:
            with self.subTest(n=n):
                r = self.proj(n, '["a==1.0"]')
                self.assertIn(("pinned-library-dependency", "project.dependencies[0]"), r.pairs())
        for n in ["mylib", "libx", "library2", "mylibrary", "xlib", "app", "pyproject-check"]:
            with self.subTest(n=n):
                self.assertClean(self.proj(n, '["a==1.0"]'))

    def test_invalid_name_is_not_a_library(self):
        r = self.proj("my lib", '["a==1.0"]')
        self.assertPairs(r, ("invalid-name", "project.name"))

    def test_what_is_a_pin(self):
        r = self.proj("mylib-lib", '["a==1.0", "b==1.*", "c===1.0", "d~=1.0", "e!=1.0", "f>=1,==2", "g(==1.0)", "h == 1.0 ; os_name == \'x\'", '
                      '"i==1.0.*", "j @ https://x/y", "k<=1, ==1.0", "l==1.0+local"]')
        self.assertPairs(r, *[("pinned-library-dependency", "project.dependencies[%d]" % i) for i in (0, 5, 6, 7, 10, 11)])

    def test_only_project_dependencies(self):
        r = self.check('[build-system]\nrequires = ["setuptools==70"]\n[project]\nname = "mylib-lib"\nversion = "1"\n'
                       '[project.optional-dependencies]\ndev = ["pytest==8"]\n')
        self.assertClean(r)

    def test_not_a_library(self):
        self.assertClean(self.proj("myapp", '["a==1.0"]'))

    def test_invalid_entries_left_out(self):
        r = self.proj("mylib-lib", '["a==", "b==1"]')
        self.assertPairs(r, ("invalid-requirement", "project.dependencies[0]"), ("pinned-library-dependency", "project.dependencies[1]"))


class OwnProject(ToolCase):
    def test_own_pyproject_toml_is_clean(self):
        root = TOOL.parent
        r = subprocess.run([sys.executable, str(TOOL), str(root / "pyproject.toml"), "--fail-on", "warning"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((r.returncode, r.stdout), (0, "errors: 0, warnings: 0\n"))


class SourceShape(unittest.TestCase):
    def test_first_line_and_hints_and_main(self):
        import ast
        source = TOOL.read_text(encoding="utf-8")
        self.assertEqual(source.splitlines()[0], "#!/usr/bin/env python3")
        tree = ast.parse(source)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
                self.assertIsNotNone(node.returns, node.name)
                args = node.args
                every = args.posonlyargs + args.args + args.kwonlyargs + [a for a in (args.vararg, args.kwarg) if a]
                for a in every:
                    if a.arg not in ("self", "cls"):
                        self.assertIsNotNone(a.annotation, f"{node.name}({a.arg})")
            self.assertNotIsInstance(node, ast.Lambda)
        self.assertIn("main", names)

    def test_main_returns_exit_code(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pyproject_check_under_test", TOOL)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.toml"
            path.write_text(GOOD)
            self.assertEqual(module.main([str(path)]), 0)
            self.assertEqual(module.main([str(path), "--bogus"]), 2)


if __name__ == "__main__":
    unittest.main()
