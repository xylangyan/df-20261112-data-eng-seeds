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

"""Multi-file config merging with reference resolution and source tracking.

This module is only used when multi-file mode is explicitly turned on (see
``json5.tool``). In ordinary single-file mode ``json5.loads()`` is used and
the reference key below has no special meaning at all.

Each config file must contain a JSON5 object. A file may list relative
references to other files:

    {
        "$references": ["shared/base.json5"],
        ...
    }

Referenced files are loaded first (in listed order), and the values in the
current file then override what the references contributed. The directory of
the referencing file is used as the base for each relative path, and every
resolved path must stay inside a configured config root.

Merging is a deep merge of objects. The way lists combine is configurable:
either whole-item replacement (the default) or append. The reference key is
removed from the merged result; a parallel source tree records which file each
value landed from so an operator can trace a value back to its origin.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import json5

REFERENCE_KEY = '$references'

LIST_REPLACE = 'replace'
LIST_APPEND = 'append'
_LIST_POLICIES = (LIST_REPLACE, LIST_APPEND)


class ConfigMergeError(Exception):
    """Raised when a multi-file config cannot be resolved."""

    def __init__(self, message, *, chain=None):
        super().__init__(message)
        self.message = message
        # The files traversed when the error happened, entry file first.
        self.chain = list(chain) if chain else []


@dataclass
class _Node:
    """A value paired with a parallel source tree.

    ``value`` is always a plain Python value: a dict whose children are also
    _Node objects, a list of _Node objects, or a scalar. ``sources`` mirrors
    that shape: dicts map keys to child source trees, lists hold a source
    entry per list item, and scalars record the path of the file the value
    came from.
    """

    value: Any
    sources: Any


@dataclass
class _ParsedFile:
    obj: Dict[str, _Node]
    references: List[str]


@dataclass
class MergeResult:
    """The outcome of resolving a multi-file config."""

    value: Dict[str, Any]
    sources: Dict[str, Any]
    # Every file that contributed, in install order: referenced files
    # appear before the files that reference them.
    files_loaded: List[str] = field(default_factory=list)


class _Loader:
    def __init__(self, host, config_root, list_policy, strict):
        self.host = host
        self.config_root = config_root
        self.real_root = host.realpath(config_root)
        self.list_policy = list_policy
        self.strict = strict
        self._cache = {}
        self.files_loaded = []

    def merge_entry(self, entry_path):
        entry = self._normalize(entry_path)
        self._ensure_within_root(entry, None)
        merged = self._merge(entry, [])
        return MergeResult(
            value=_plain_tree(merged),
            sources=merged.sources,
            files_loaded=list(self.files_loaded),
        )

    def _normalize(self, path):
        return self.host.normpath(self.host.abspath(path))

    def _resolve_reference(self, ref, referencing_file):
        if not isinstance(ref, str) or not ref:
            raise ConfigMergeError(
                f'{REFERENCE_KEY} entries must be non-empty strings in '
                f'{referencing_file}',
                chain=[referencing_file],
            )
        if self.host.isabs(ref):
            raise ConfigMergeError(
                f'{REFERENCE_KEY} entries must be relative paths, got '
                f'{ref!r} in {referencing_file}',
                chain=[referencing_file],
            )
        base_dir = self.host.dirname(referencing_file)
        resolved = self.host.normpath(self.host.join(base_dir, ref))
        if not self.host.isabs(resolved):
            resolved = self.host.normpath(self.host.abspath(resolved))
        self._ensure_within_root(resolved, referencing_file)
        return resolved

    def _ensure_within_root(self, candidate, referencing_file):
        chain = [referencing_file] if referencing_file else []
        if not self._is_inside(candidate, self.config_root):
            raise ConfigMergeError(
                f'reference {candidate} is outside the config root '
                f'{self.config_root}',
                chain=chain,
            )
        real_candidate = self.host.realpath(candidate)
        if not self._is_inside(real_candidate, self.real_root):
            raise ConfigMergeError(
                f'reference {candidate} resolves outside the config root '
                f'{self.config_root}',
                chain=chain,
            )

    def _is_inside(self, candidate, root):
        root_with_sep = root.rstrip(self.host.sep) + self.host.sep
        return candidate == root or candidate.startswith(root_with_sep)

    def _load(self, path, chain):
        if path in self._cache:
            return self._cache[path]

        try:
            text = self.host.read_text_file(path)
        except FileNotFoundError:
            raise ConfigMergeError(
                f'referenced config file not found: {path}',
                chain=list(chain) + [path],
            )
        except OSError as error:
            raise ConfigMergeError(
                f'could not read config file {path}: {error}',
                chain=list(chain) + [path],
            )
        except UnicodeDecodeError as error:
            raise ConfigMergeError(
                f'failed to parse {path}: {error}',
                chain=list(chain) + [path],
            )

        try:
            parsed_value, err, _ = json5.parse(text, strict=self.strict)
        except ValueError as error:
            raise ConfigMergeError(
                f'failed to parse {path}: {error}',
                chain=list(chain) + [path],
            )
        if err is not None:
            raise ConfigMergeError(
                f'failed to parse {path}: {err}',
                chain=list(chain) + [path],
            )

        tagged = _tag_value(parsed_value, path)
        if not isinstance(tagged.value, dict):
            raise ConfigMergeError(
                f'top-level value in {path} must be an object, got '
                f'{type(tagged.value).__name__}',
                chain=list(chain) + [path],
            )

        reference_node = tagged.value.pop(REFERENCE_KEY, None)
        references = []
        if reference_node is not None:
            if not isinstance(reference_node.value, list) or any(
                not isinstance(item.value, str)
                for item in reference_node.value
            ):
                raise ConfigMergeError(
                    f'{REFERENCE_KEY} in {path} must be a list of strings',
                    chain=list(chain) + [path],
                )
            references = [item.value for item in reference_node.value]
            tagged.sources.pop(REFERENCE_KEY, None)

        result = _ParsedFile(obj=tagged.value, references=references)
        self._cache[path] = result

        for ref in references:
            ref_path = self._resolve_reference(ref, path)
            if ref_path in chain or ref_path == path:
                cycle = list(chain) + [path, ref_path]
                raise ConfigMergeError(
                    'circular reference detected: ' + ' -> '.join(cycle),
                    chain=cycle,
                )
            self._load(ref_path, list(chain) + [path])
        # Record after the references so the list mirrors install order,
        # not traversal order.
        self.files_loaded.append(path)
        return result

    def _merge(self, path, chain):
        if path in chain:
            cycle = chain[chain.index(path):] + [path]
            raise ConfigMergeError(
                'circular reference detected: ' + ' -> '.join(cycle),
                chain=cycle,
            )
        parsed = self._load(path, chain)
        merged = {}
        for ref in parsed.references:
            ref_path = self._resolve_reference(ref, path)
            ref_node = self._merge(ref_path, list(chain) + [path])
            _deep_merge(merged, ref_node, self.list_policy)
        overlay_sources = {
            key: node.sources for key, node in parsed.obj.items()
        }
        _deep_merge(
            merged,
            _Node(parsed.obj, overlay_sources),
            self.list_policy,
        )
        return _Node(
            merged,
            {key: node.sources for key, node in merged.items()},
        )


def _tag_value(value, source):
    """Recursively tag a parsed Python value with its source file."""
    if isinstance(value, dict):
        children = {}
        sources = {}
        for key, child_value in value.items():
            child = _tag_value(child_value, source)
            children[key] = child
            sources[key] = child.sources
        return _Node(children, sources)
    if isinstance(value, list):
        children = [_tag_value(item, source) for item in value]
        return _Node(children, [child.sources for child in children])
    return _Node(value, source)


def _deep_merge(target, incoming, list_policy):
    """Merge dict-valued ``incoming`` node into the ``target`` node dict.

    Dicts merge recursively. Lists are replaced wholesale by default, or
    appended when ``list_policy`` is ``LIST_APPEND``. Every other value is
    replaced by the incoming value. Sources travel alongside the values.

    Nodes are treated as immutable: a cached file may be referenced through
    a diamond, so nodes are copied before being placed in a new result.
    """
    for key, child in incoming.value.items():
        child = _Node(child.value, incoming.sources[key])
        existing = target.get(key)
        if existing is None:
            target[key] = _copy_node(child)
            continue

        if isinstance(existing.value, dict) and isinstance(child.value, dict):
            merged_children = dict(existing.value)
            _deep_merge(merged_children, child, list_policy)
            target[key] = _Node(
                merged_children,
                {
                    sub_key: sub_node.sources
                    for sub_key, sub_node in merged_children.items()
                },
            )
        elif (
            list_policy == LIST_APPEND
            and isinstance(existing.value, list)
            and isinstance(child.value, list)
        ):
            target[key] = _Node(
                list(existing.value) + list(child.value),
                list(existing.sources) + list(child.sources),
            )
        else:
            target[key] = _copy_node(child)


def _copy_node(node):
    """Return a structurally independent copy of ``node``."""
    if isinstance(node.value, dict):
        children = {
            key: _copy_node(child) for key, child in node.value.items()
        }
        return _Node(
            children,
            {key: child.sources for key, child in children.items()},
        )
    if isinstance(node.value, list):
        children = [_copy_node(item) for item in node.value]
        return _Node(
            children, [child.sources for child in children]
        )
    return _Node(node.value, node.sources)


def _plain_tree(node_or_value):
    if isinstance(node_or_value, _Node):
        return _plain_tree(node_or_value.value)
    if isinstance(node_or_value, dict):
        return {
            key: _plain_tree(value)
            for key, value in node_or_value.items()
        }
    if isinstance(node_or_value, list):
        return [_plain_tree(item) for item in node_or_value]
    return node_or_value


def load_config(host, entry_path, config_root, list_policy=LIST_REPLACE,
                strict=True):
    """Load ``entry_path`` and its references, returning a MergeResult.

    ``config_root`` bounds every file that may be read. ``list_policy``
    must be one of ``LIST_REPLACE`` or ``LIST_APPEND``. ``strict`` is
    passed through to the JSON5 parser for every file.
    """
    if list_policy not in _LIST_POLICIES:
        raise ValueError(f'unknown list policy: {list_policy!r}')
    root = host.normpath(host.abspath(config_root))
    loader = _Loader(host, root, list_policy, strict)
    return loader.merge_entry(entry_path)
