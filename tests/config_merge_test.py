# Copyright 2026 Google Inc. All rights reserved.
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

import unittest

import json5
from json5.config_merge import (
    LIST_APPEND,
    LIST_REPLACE,
    REFERENCE_KEY,
    ConfigMergeError,
    load_config,
)
from tests.host_fake import FakeHost

ROOT = '/tmp/confroot'

BASE = """{
    name: 'collector',
    fields: {host: '*', port: 8080},
    tags: ['base'],
    only_base: true,
}"""

A = """{
    $references: ['shared/base.json5'],
    fields: {port: 9001, region: 'cn'},
    tags: ['a'],
    from_a: 1,
}"""

B = """{
    $references: ['shared/base.json5'],
    fields: {host: 'example.com'},
    tags: ['b'],
    from_b: 2,
}"""

ENTRY = """{
    $references: ['a.json5', 'b.json5'],
    fields: {port: 7000},
    top: 'entry',
}"""


class ConfigMergeTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.host = FakeHost()
        self.host.write_text_file(f'{ROOT}/shared/base.json5', BASE)
        self.host.write_text_file(f'{ROOT}/a.json5', A)
        self.host.write_text_file(f'{ROOT}/b.json5', B)
        self.host.write_text_file(f'{ROOT}/entry.json5', ENTRY)

    def _load(self, entry='entry.json5', **kwargs):
        return load_config(
            self.host, f'{ROOT}/{entry}', ROOT, **kwargs
        )

    def test_diamond_merge_replaces_values(self):
        result = self._load()
        self.assertEqual(
            result.value,
            {
                'name': 'collector',
                'fields': {
                    'host': 'example.com',
                    'port': 7000,
                    'region': 'cn',
                },
                'tags': ['b'],
                'only_base': True,
                'from_a': 1,
                'from_b': 2,
                'top': 'entry',
            },
        )
        self.assertNotIn(REFERENCE_KEY, result.value)
        # The shared base is read once even though both a and b use it.
        self.assertEqual(
            result.files_loaded,
            [
                f'{ROOT}/shared/base.json5',
                f'{ROOT}/a.json5',
                f'{ROOT}/b.json5',
                f'{ROOT}/entry.json5',
            ],
        )

    def test_sources_identify_origin_of_each_key(self):
        result = self._load()
        sources = result.sources
        self.assertEqual(
            sources['name'], f'{ROOT}/shared/base.json5'
        )
        self.assertEqual(sources['from_a'], f'{ROOT}/a.json5')
        self.assertEqual(sources['from_b'], f'{ROOT}/b.json5')
        self.assertEqual(sources['top'], f'{ROOT}/entry.json5')
        self.assertEqual(
            sources['fields'],
            {
                'host': f'{ROOT}/b.json5',
                'port': f'{ROOT}/entry.json5',
                'region': f'{ROOT}/a.json5',
            },
        )
        self.assertEqual(sources['tags'], [f'{ROOT}/b.json5'])

    def test_list_policy_replace(self):
        result = self._load(list_policy=LIST_REPLACE)
        self.assertEqual(result.value['tags'], ['b'])
        self.assertEqual(result.sources['tags'], [f'{ROOT}/b.json5'])

    def test_list_policy_append(self):
        result = self._load(list_policy=LIST_APPEND)
        # base feeds both a and b through the diamond, so its item appears
        # once per path that reaches the entry.
        self.assertEqual(
            result.value['tags'], ['base', 'a', 'base', 'b']
        )
        self.assertEqual(
            result.sources['tags'],
            [
                f'{ROOT}/shared/base.json5',
                f'{ROOT}/a.json5',
                f'{ROOT}/shared/base.json5',
                f'{ROOT}/b.json5',
            ],
        )

    def test_append_does_not_mutate_cached_files(self):
        first = self._load(list_policy=LIST_APPEND)
        second = self._load(list_policy=LIST_APPEND)
        self.assertEqual(first.value['tags'], second.value['tags'])

    def test_repeated_loads_are_stable(self):
        first = self._load()
        second = self._load()
        self.assertEqual(first.value, second.value)
        self.assertEqual(first.sources, second.sources)

    def test_single_file_loads_gives_references_no_special_meaning(self):
        plain = json5.loads(A)
        self.assertEqual(
            plain[REFERENCE_KEY], ['shared/base.json5']
        )

    def test_relative_paths_resolve_from_referencing_directory(self):
        # base.json5 is referenced from a.json5 at the root, but a nested
        # file references the same base relative to its own directory.
        self.host.write_text_file(
            f'{ROOT}/nested/leaf.json5',
            "{$references: ['../shared/base.json5'], leaf: true}",
        )
        result = load_config(
            self.host, f'{ROOT}/nested/leaf.json5', ROOT
        )
        self.assertEqual(result.value['name'], 'collector')
        self.assertTrue(result.value['leaf'])

    def test_missing_reported_with_chain(self):
        self.host.write_text_file(
            f'{ROOT}/m.json5', "{$references: ['nope.json5']}"
        )
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/m.json5', ROOT)
        self.assertIn('not found', ctx.exception.message)
        self.assertEqual(
            ctx.exception.chain,
            [f'{ROOT}/m.json5', f'{ROOT}/nope.json5'],
        )

    def test_parse_error_reported_with_chain(self):
        self.host.write_text_file(f'{ROOT}/bad.json5', '{oops: ')
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/bad.json5', ROOT)
        self.assertIn('failed to parse', ctx.exception.message)
        self.assertEqual(ctx.exception.chain, [f'{ROOT}/bad.json5'])

    def test_parse_error_inside_reference_keeps_full_chain(self):
        self.host.write_text_file(
            f'{ROOT}/p.json5', "{$references: ['broken.json5']}"
        )
        self.host.write_text_file(f'{ROOT}/broken.json5', '{oops: ')
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/p.json5', ROOT)
        self.assertEqual(
            ctx.exception.chain,
            [f'{ROOT}/p.json5', f'{ROOT}/broken.json5'],
        )

    def test_cycle_error_lists_actual_file_order(self):
        self.host.write_text_file(
            f'{ROOT}/x.json5', "{$references: ['y.json5'], x: 1}"
        )
        self.host.write_text_file(
            f'{ROOT}/y.json5', "{$references: ['z.json5'], y: 1}"
        )
        self.host.write_text_file(
            f'{ROOT}/z.json5', "{$references: ['x.json5'], z: 1}"
        )
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/x.json5', ROOT)
        self.assertEqual(
            ctx.exception.chain,
            [
                f'{ROOT}/x.json5',
                f'{ROOT}/y.json5',
                f'{ROOT}/z.json5',
                f'{ROOT}/x.json5',
            ],
        )
        self.assertIn('circular reference', ctx.exception.message)
        self.assertIn('x.json5', ctx.exception.message)

    def test_self_reference_is_a_cycle(self):
        self.host.write_text_file(
            f'{ROOT}/self.json5', "{$references: ['self.json5']}"
        )
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/self.json5', ROOT)
        self.assertEqual(
            ctx.exception.chain,
            [f'{ROOT}/self.json5', f'{ROOT}/self.json5'],
        )

    def test_references_must_stay_inside_config_root(self):
        self.host.write_text_file(
            f'{ROOT}/esc.json5', "{$references: ['../escape.json5']}"
        )
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/esc.json5', ROOT)
        self.assertIn('outside the config root', ctx.exception.message)
        self.assertEqual(ctx.exception.chain, [f'{ROOT}/esc.json5'])

    def test_absolute_references_are_rejected(self):
        self.host.write_text_file(
            f'{ROOT}/abs.json5',
            "{$references: ['/tmp/confroot/a.json5']}",
        )
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/abs.json5', ROOT)
        self.assertIn('relative paths', ctx.exception.message)

    def test_entry_must_be_inside_config_root(self):
        self.host.write_text_file('/tmp/outside.json5', '{a: 1}')
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(
                self.host, '/tmp/outside.json5', ROOT
            )
        self.assertIn('outside the config root', ctx.exception.message)

    def test_top_level_must_be_an_object(self):
        self.host.write_text_file(f'{ROOT}/arr.json5', '[1, 2, 3]')
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/arr.json5', ROOT)
        self.assertIn('must be an object', ctx.exception.message)

    def test_references_must_be_a_string_list(self):
        self.host.write_text_file(
            f'{ROOT}/wrong.json5', "{$references: 'a.json5'}"
        )
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(self.host, f'{ROOT}/wrong.json5', ROOT)
        self.assertIn('list of strings', ctx.exception.message)

    def test_unknown_list_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            load_config(
                self.host, f'{ROOT}/entry.json5', ROOT,
                list_policy='nope',
            )

    def test_strict_flag_is_passed_to_the_parser(self):
        self.host.write_text_file(
            f'{ROOT}/loose.json5', "{x: 'line1\nline2'}"
        )
        loose = load_config(
            self.host, f'{ROOT}/loose.json5', ROOT, strict=False
        )
        self.assertEqual(loose.value['x'], 'line1\nline2')
        with self.assertRaises(ConfigMergeError):
            load_config(
                self.host, f'{ROOT}/loose.json5', ROOT, strict=True
            )


if __name__ == '__main__':
    unittest.main()


class ConfigMergeDecodeTest(unittest.TestCase):
    maxDiff = None

    def test_invalid_utf8_is_reported_as_a_parse_error(self):
        class BadHost(FakeHost):
            def read_text_file(self, *comps):
                raise UnicodeDecodeError(
                    'utf-8', b'\xff', 0, 1, 'invalid start byte'
                )

        host = BadHost()
        with self.assertRaises(ConfigMergeError) as ctx:
            load_config(host, f'{ROOT}/entry.json5', ROOT)
        self.assertIn('failed to parse', ctx.exception.message)
        self.assertEqual(ctx.exception.chain, [f'{ROOT}/entry.json5'])
