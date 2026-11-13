# Copyright 2017 Google Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
import sys
import unittest

from json5 import VERSION, __version__
from json5.host import Host
from json5.tool import main
from tests.host_fake import FakeHost


class ToolTest(unittest.TestCase):
    maxDiff = None

    def _write_files(self, host, files):
        for path, contents in list(files.items()):
            host.write_text_file(path, contents)

    def check(
        self, args, stdin=None, files=None, returncode=0, out=None, err=None
    ):
        # We can run the tests two ways: as a full out-of-process integration
        # test (launching a subprocess and checking stdin/out/err) and as
        # a mocked-out in-process pseudo-integration test.
        #
        # The code coverage between the two is identical (excluding the
        # coverage in this file, of course). The full integration tests
        # are slower, and running `python -m coverage` won't account for
        # the coverage in the subprocess.
        #
        # For greatest coverage, by default we run the tests both ways.
        # TODO: If there was some convention for how to pass arguments from
        # a caller of the unittest module to this code, it would be nice
        # if we had command line args to toggle the two modes off and on.
        # Or, we could also figure out how to get the coverage in the
        # subprocess correctly accounted for.
        in_proc = True
        out_of_proc = True
        assert in_proc or out_of_proc, (
            'At least one of in_proc or out_of_proc must be true'
        )

        if in_proc:
            fake_host = FakeHost()
            orig_wd = fake_host.getcwd()
            tmpdir = fake_host.mkdtemp()
            fake_host.chdir(tmpdir)

            fake_host.write_text_file('/tmp/foo', '')

            if stdin:
                fake_host.stdin.write(stdin)
                fake_host.stdin.seek(0)
            if files:
                self._write_files(fake_host, files)

            try:
                mock_ret = main(args, fake_host)
            except SystemExit as e:
                mock_ret = e.code

            fake_host.rmtree(tmpdir)
            fake_host.chdir(orig_wd)

            mock_out = fake_host.stdout.getvalue()
            mock_err = fake_host.stderr.getvalue()

            if returncode is not None:
                self.assertEqual(returncode, mock_ret)
            if out is not None:
                self.assertMultiLineEqual(out, mock_out)
            if err is not None:
                self.assertMultiLineEqual(err, mock_err)
        else:  # pragma: no cover
            pass

        if out_of_proc:
            host = Host()
            orig_wd = host.getcwd()
            tmpdir = host.mkdtemp()
            try:
                host.chdir(tmpdir)
                if files:
                    self._write_files(host, files)

                args = [sys.executable, '-m', 'json5'] + args
                with subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                ) as proc:
                    actual_out, actual_err = proc.communicate(input=stdin)
                    actual_ret = proc.returncode
                if returncode is not None:
                    self.assertEqual(returncode, actual_ret)
                if out is not None:
                    self.assertMultiLineEqual(out, actual_out)
                if err is not None:
                    self.assertMultiLineEqual(err, actual_err)

            finally:
                host.rmtree(tmpdir)
                host.chdir(orig_wd)
        else:  # pragma: no cover
            pass

        if in_proc:
            return mock_ret, mock_out, mock_err

        return actual_ret, actual_out, actual_err  # pragma: no cover

    def test_help(self):
        self.check(['--help'])

        # Run again and ignore the error code just to get coverage of
        # the test code branches in check().
        self.check(['--help'], returncode=None)

    def test_inline_expression(self):
        self.check(['-c', '{foo: 1}'], out='{\n    foo: 1,\n}\n')

    def test_indent(self):
        self.check(['--indent=None', '-c', '[1]'], out='[1]\n')
        self.check(['--indent=2', '-c', '[1]'], out='[\n  1,\n]\n')
        self.check(['--indent=  ', '-c', '[1]'], out='[\n  1,\n]\n')

    def test_as_json(self):
        self.check(
            ['--as-json', '-c', '{foo: 1}'],
            out='{\n    "foo": 1\n}\n',
        )
        self.check(
            ['--as-json', '-c', '"\\0\\v"'],
            out='"\\u0000\\u000b"\n',
        )

    def test_as_json_nonfinite(self):
        self.check(
            ['--as-json', '-c', '{value: NaN}'],
            returncode=1,
            out='',
            err='Illegal JSON5 value: nan\n',
        )
        self.check(['-c', 'NaN'], out='NaN\n')

    def test_quote_keys(self):
        self.check(
            ['--quote-keys', '-c', '{foo: 1}'],
            out='{\n    "foo": 1,\n}\n',
        )

    def test_no_quote_keys(self):
        self.check(
            ['--no-quote-keys', '-c', '{foo: 1}'],
            out='{\n    foo: 1,\n}\n',
        )

    def test_keys_are_quoted_by_default(self):
        self.check(['-c', '{foo: 1}'], out='{\n    foo: 1,\n}\n')

    def test_read_command(self):
        self.check(['-c', '"foo"'], out='"foo"\n')

    def test_read_from_stdin(self):
        self.check([], stdin='"foo"\n', out='"foo"\n')

    def test_read_from_a_file(self):
        files = {
            'foo.json5': '"foo"\n',
        }
        self.check(['foo.json5'], files=files, out='"foo"\n')

    def test_trailing_commas(self):
        self.check(
            ['--trailing-commas', '-c', '{foo: 1}'],
            out='{\n    foo: 1,\n}\n',
        )

    def test_no_trailing_commas(self):
        self.check(
            ['--no-trailing-commas', '-c', '{foo: 1}'],
            out='{\n    foo: 1\n}\n',
        )

    def test_trailing_commas_are_there_by_default(self):
        self.check(['-c', '{foo: 1}'], out='{\n    foo: 1,\n}\n')

    def test_unknown_switch(self):
        self.check(
            ['--unknown-switch'],
            returncode=2,
            err=(
                'usage: json5 [options] [FILE]\n'
                '    -h/--help for help\n'
                '\n'
                'error: unrecognized arguments: --unknown-switch\n'
            ),
        )

    def test_version(self):
        self.check(['--version'], out=str(VERSION) + '\n')
        self.check(['--version'], out=str(__version__) + '\n')


if __name__ == '__main__':  # pragma: no cover
    unittest.main()


class MultiFileToolTest(unittest.TestCase):
    maxDiff = None

    def check(self, args, files, returncode=0, out=None, err=None):
        in_proc = True
        out_of_proc = True

        if in_proc:
            fake_host = FakeHost()
            orig_wd = fake_host.getcwd()
            tmpdir = fake_host.mkdtemp()
            fake_host.chdir(tmpdir)
            for path, contents in files.items():
                fake_host.write_text_file(path, contents)
            try:
                mock_ret = main(args, fake_host)
            except SystemExit as e:
                mock_ret = e.code
            mock_out = fake_host.stdout.getvalue()
            mock_err = fake_host.stderr.getvalue()
            fake_host.rmtree(tmpdir)
            fake_host.chdir(orig_wd)
            self.assertEqual(returncode, mock_ret)
            if out is not None:
                self.assertMultiLineEqual(out, mock_out)
            if err is not None:
                self.assertMultiLineEqual(
                    err.replace('<TMPPARENT>', fake_host.dirname(tmpdir))
                    .replace('<TMP>', tmpdir),
                    mock_err,
                )

        if out_of_proc:
            host = Host()
            orig_wd = host.getcwd()
            tmpdir = host.mkdtemp()
            try:
                host.chdir(tmpdir)
                for path, contents in files.items():
                    host.makedirs(host.dirname(host.abspath(path)))
                    host.write_text_file(path, contents)
                cmd = [sys.executable, '-m', 'json5'] + args
                with subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                ) as proc:
                    actual_out, actual_err = proc.communicate()
                    actual_ret = proc.returncode
                self.assertEqual(returncode, actual_ret)
                if out is not None:
                    self.assertMultiLineEqual(out, actual_out)
                if err is not None:
                    self.assertMultiLineEqual(
                        err.replace(
                            '<TMPPARENT>', host.dirname(tmpdir)
                        ).replace('<TMP>', tmpdir),
                        actual_err,
                    )
            finally:
                host.rmtree(tmpdir)
                host.chdir(orig_wd)

        if in_proc:
            return mock_ret, mock_out, mock_err
        return actual_ret, actual_out, actual_err  # pragma: no cover

    def _diamond_files(self):
        return {
            'shared/base.json5': (
                "{name: 'collector', fields: {host: '*', port: 8080},"
                " tags: ['base'], only_base: true}"
            ),
            'a.json5': (
                "{$references: ['shared/base.json5'],"
                " fields: {port: 9001, region: 'cn'},"
                " tags: ['a'], from_a: 1}"
            ),
            'b.json5': (
                "{$references: ['shared/base.json5'],"
                " fields: {host: 'example.com'},"
                " tags: ['b'], from_b: 2}"
            ),
            'entry.json5': (
                "{$references: ['a.json5', 'b.json5'],"
                " fields: {port: 7000}, top: 'entry'}"
            ),
        }

    def test_multi_file_merge_with_sources(self):
        files = self._diamond_files()
        expected_out = """{
    value: {
        name: "collector",
        fields: {
            host: "example.com",
            port: 7000,
            region: "cn",
        },
        tags: [
            "b",
        ],
        only_base: true,
        from_a: 1,
        from_b: 2,
        top: "entry",
    },
    sources: {
        name: "shared/base.json5",
        fields: {
            host: "b.json5",
            port: "entry.json5",
            region: "a.json5",
        },
        tags: [
            "b.json5",
        ],
        only_base: "shared/base.json5",
        from_a: "a.json5",
        from_b: "b.json5",
        top: "entry.json5",
    },
    files_loaded: [
        "shared/base.json5",
        "a.json5",
        "b.json5",
        "entry.json5",
    ],
}
"""
        self.check(
            ['--multi-file', '--show-sources', 'entry.json5'],
            files,
            out=expected_out,
        )

    def test_multi_file_default_output_is_the_merged_config(self):
        files = self._diamond_files()
        expected_out = """{
    name: "collector",
    fields: {
        host: "example.com",
        port: 7000,
        region: "cn",
    },
    tags: [
        "b",
    ],
    only_base: true,
    from_a: 1,
    from_b: 2,
    top: "entry",
}
"""
        self.check(
            ['--multi-file', 'entry.json5'], files, out=expected_out
        )

    def test_multi_file_append_policy(self):
        files = self._diamond_files()
        expected_out = """{
    name: "collector",
    fields: {
        host: "example.com",
        port: 7000,
        region: "cn",
    },
    tags: [
        "base",
        "a",
        "base",
        "b",
    ],
    only_base: true,
    from_a: 1,
    from_b: 2,
    top: "entry",
}
"""
        self.check(
            ['--multi-file', '--list-policy=append', 'entry.json5'],
            files,
            out=expected_out,
        )

    def test_multi_file_cycle_reports_chain(self):
        files = {
            'x.json5': "{$references: ['y.json5'], x: 1}",
            'y.json5': "{$references: ['x.json5'], y: 1}",
        }
        expected_err = (
            'error: circular reference detected: '
            '<TMP>/x.json5 -> <TMP>/y.json5 -> <TMP>/x.json5\n'
            'reference chain: '
            '<TMP>/x.json5 -> <TMP>/y.json5 -> <TMP>/x.json5\n'
        )
        self.check(
            ['--multi-file', 'x.json5'],
            files,
            returncode=1,
            err=expected_err,
        )

    def test_multi_file_missing_reference(self):
        files = {'m.json5': "{$references: ['nope.json5']}"}
        expected_err = (
            'error: referenced config file not found: <TMP>/nope.json5\n'
            'reference chain: <TMP>/m.json5 -> <TMP>/nope.json5\n'
        )
        self.check(
            ['--multi-file', 'm.json5'],
            files,
            returncode=1,
            err=expected_err,
        )

    def test_multi_file_parse_error(self):
        files = {'bad.json5': '{oops: '}
        self.check(
            ['--multi-file', 'bad.json5'],
            files,
            returncode=1,
            err='error: failed to parse <TMP>/bad.json5: '
            '<string>:1 Unexpected end of input at column 8\n'
            'reference chain: <TMP>/bad.json5\n',
        )

    def test_multi_file_outside_root(self):
        files = {'esc.json5': "{$references: ['../escape.json5']}"}
        self.check(
            ['--multi-file', 'esc.json5'],
            files,
            returncode=1,
            err='error: reference <TMPPARENT>/escape.json5 is outside the '
            'config root <TMP>\n'
            'reference chain: <TMP>/esc.json5\n',
        )

    def test_multi_file_requires_file(self):
        self.check(
            ['--multi-file'],
            {},
            returncode=2,
            err='error: --multi-file requires a FILE argument; stdin '
            'cannot contain relative references\n',
        )

    def test_multi_file_rejects_inline_command(self):
        self.check(
            ['--multi-file', '-c', '{a: 1}'],
            {},
            returncode=2,
            err='error: --multi-file cannot be combined with -c\n',
        )

    def test_single_file_keeps_references_key(self):
        files = {'a.json5': "{$references: ['x.json5'], a: 1}"}
        expected_out = """{
    $references: [
        "x.json5",
    ],
    a: 1,
}
"""
        self.check(['a.json5'], files, out=expected_out)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
