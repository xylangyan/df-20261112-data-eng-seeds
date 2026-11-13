"""Explicit, row-wise results for loading collections.

`Schema.load_many <marshmallow.Schema.load_many>` loads a collection one row
at a time and returns a `LoadResult` instead of raising on the first invalid
row. Each row is recorded as a `RowResult` that keeps the original input
index, the (possibly partially) deserialized value, and the row's error
messages, including nested errors.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

#: Key under which errors that cannot be attributed to a single row are
#: stored in `LoadResult.errors`. Such errors are raised by collection-level
#: processors (``pass_collection=True`` hooks) or by an input that is not a
#: sequence of mappings at all.
BATCH = "_batch"


@dataclass
class RowResult:
    """Result of loading a single row of a collection.

    :param index: Position of the row in the input collection.
    :param original: The input row, as passed to the loader.
    :param data: The deserialized row. For a valid row this is the fully
        post-processed value. For an invalid row this is the partially valid
        data, mirroring `ValidationError.valid_data
        <marshmallow.exceptions.ValidationError.valid_data>`.
    :param errors: Error messages for this row, keyed by field name. Nested
        errors keep their nested structure. ``{}`` if the row is valid.
    """

    index: int
    original: typing.Any
    data: typing.Any
    errors: dict[typing.Any, typing.Any]

    @property
    def valid(self) -> bool:
        """Whether the row loaded without errors."""
        return not self.errors


class LoadResult:
    """Result of `Schema.load_many <marshmallow.Schema.load_many>`.

    Exposes the per-row outcomes (`rows`), the valid rows in input order
    (`valid_data`), and the errors. Errors that cannot be attributed to a
    single row are stored under the `BATCH` key.
    """

    def __init__(
        self,
        rows: list[RowResult] | None = None,
        batch_errors: dict[str, typing.Any] | None = None,
    ):
        #: Per-row results, in input order.
        self.rows: list[RowResult] = list(rows) if rows is not None else []
        #: Errors that could not be attributed to a single row, e.g. errors
        #: raised by collection-level (``pass_collection=True``) processors
        #: or by an input that is not a sequence of mappings.
        self.batch_errors: dict[str, typing.Any] = (
            dict(batch_errors) if batch_errors is not None else {}
        )

    def __repr__(self) -> str:
        return (
            f"<LoadResult(valid={len(self.valid_rows)}, "
            f"invalid={len(self.invalid_rows)}, "
            f"batch_errors={bool(self.batch_errors)})>"
        )

    def __iter__(self) -> typing.Iterator[RowResult]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> RowResult:
        return self.rows[index]

    @property
    def valid_rows(self) -> list[RowResult]:
        """Rows that loaded without errors, in input order."""
        return [row for row in self.rows if row.valid]

    @property
    def invalid_rows(self) -> list[RowResult]:
        """Rows that failed to load, in input order."""
        return [row for row in self.rows if not row.valid]

    @property
    def valid_data(self) -> list[typing.Any]:
        """Deserialized values of the valid rows, in input order."""
        return [row.data for row in self.valid_rows]

    @property
    def errors(self) -> dict[typing.Any, typing.Any]:
        """All errors, keyed by row index.

        Errors that cannot be attributed to a single row are stored under
        the `BATCH` key.
        """
        errors: dict[typing.Any, typing.Any] = {
            row.index: row.errors for row in self.rows if not row.valid
        }
        if self.batch_errors:
            errors[BATCH] = self.batch_errors
        return errors
