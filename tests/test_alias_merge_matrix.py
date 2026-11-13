import csv
import io
import unittest
from pathlib import Path

from license_expression import build_spdx_licensing

from tests.alias_merge_matrix import collect_rows
from tests.alias_merge_matrix import index_versions
from tests.alias_merge_matrix import write_matrix


class AliasMergeMatrixTest(unittest.TestCase):
    def test_index_load_order_does_not_change_conflict_free_results(self):
        rows = collect_rows()
        comparable_fields = (
            "scenario",
            "raw_token",
            "strict",
            "build_result",
            "build_detail",
            "tokenize_result",
            "tokenize_detail",
            "parse_result",
            "parse_detail",
        )
        merged_normal = [
            {field: row[field] for field in comparable_fields}
            for row in rows
            if row["index_version"] == "merged-normal"
            and row["scenario"] != "unchanged-short-key"
        ]
        merged_reversed = [
            {field: row[field] for field in comparable_fields}
            for row in rows
            if row["index_version"] == "merged-reversed"
            and row["scenario"] != "unchanged-short-key"
        ]
        self.assertEqual(merged_normal, merged_reversed)

    def test_long_alias_consumes_previously_distinct_operators(self):
        rows = {
            (row["index_version"], row["scenario"]): row
            for row in collect_rows()
        }
        baseline = rows[("baseline", "longest-or-boundary")]
        merged = rows[("merged-normal", "longest-or-boundary")]

        self.assertIn("OPERATOR[OR]", baseline["tokenize_detail"])
        self.assertIn("EXPRESSION[MIT OR LATER]", baseline["parse_detail"])
        self.assertEqual("SYMBOL[custom-mit-or-later]('MIT OR LATER'@0)", merged["tokenize_detail"])
        self.assertEqual("EXPRESSION[custom-mit-or-later]", merged["parse_detail"])

        baseline_suffix = rows[("baseline", "longest-and-nonmatching-suffix")]
        merged_suffix = rows[("merged-normal", "longest-and-nonmatching-suffix")]
        self.assertEqual(baseline_suffix["tokenize_detail"], merged_suffix["tokenize_detail"])
        self.assertEqual("EXPRESSION[MIT AND BSDX]", merged_suffix["parse_detail"])

    def test_with_alias_changes_token_class_and_strict_result(self):
        rows = {
            (row["index_version"], row["scenario"]): row
            for row in collect_rows()
        }
        baseline = rows[("baseline", "with-true-exception-key-strict")]
        merged = rows[("merged-normal", "with-true-exception-key-strict")]

        self.assertEqual("accepted", baseline["parse_result"])
        self.assertIn(
            "EXPRESSION[GPL-2.0-only WITH Classpath-exception-2.0]",
            baseline["parse_detail"],
        )
        self.assertEqual("rejected", merged["parse_result"])
        self.assertIn(
            "A license exception symbol can only be used as an exception",
            merged["parse_detail"],
        )

    def test_case_variant_alias_equal_to_own_key_is_allowed(self):
        rows = {
            (row["index_version"], row["scenario"]): row
            for row in collect_rows()
        }
        baseline = rows[("baseline", "alias-equals-own-key-case")]
        self_alias = rows[("self-alias", "alias-equals-own-key-case")]

        self.assertEqual("accepted", self_alias["build_result"])
        self.assertEqual("SYMBOL[custom-self]('CUSTOM-SELF'@0)", self_alias["tokenize_detail"])
        self.assertEqual("EXPRESSION[custom-self]", self_alias["parse_detail"])
        self.assertEqual("SYMBOL[CUSTOM-SELF]('CUSTOM-SELF'@0)", baseline["tokenize_detail"])
        self.assertEqual("EXPRESSION[CUSTOM-SELF]", baseline["parse_detail"])

    def test_alias_equal_to_another_true_key_is_rejected_regardless_of_order(self):
        rows = {
            (row["index_version"], row["scenario"]): row
            for row in collect_rows()
        }
        for version in ("collision-custom-first", "collision-baseline-first"):
            row = rows[(version, "unchanged-short-key")]
            self.assertEqual("rejected", row["build_result"])
            self.assertIn("Invalid duplicated alias", row["build_detail"])
            self.assertEqual("not-run", row["tokenize_result"])
            self.assertEqual("not-run", row["parse_result"])

    def test_overlapping_prefix_alias_can_silently_drop_exception_suffix(self):
        rows = {
            (row["index_version"], row["scenario"]): row
            for row in collect_rows()
        }
        baseline = rows[("baseline", "with-wordy-exception")]
        prefix = rows[("overlap-prefix", "with-wordy-exception")]

        self.assertIn(
            "WITH_GROUP[GPL-2.0-only WITH Classpath exception-2.0]",
            baseline["tokenize_detail"],
        )
        self.assertEqual(
            "SYMBOL[custom-gpl-with-classpath-prefix]('GPL-2.0-only WITH Classpath'@0)",
            prefix["tokenize_detail"],
        )
        self.assertEqual(
            "EXPRESSION[custom-gpl-with-classpath-prefix]",
            prefix["parse_detail"],
        )

    def test_checked_in_matrix_matches_generated_rows(self):
        matrix_path = Path(__file__).parent / "data" / "alias_merge_matrix.csv"
        with matrix_path.open(newline="") as matrix_file:
            checked_in_rows = list(csv.DictReader(matrix_file))
        self.assertEqual(collect_rows(), checked_in_rows)

    def test_matrix_is_written_as_rerunnable_csv(self):
        output = io.StringIO()
        write_matrix(output)
        rows = list(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual(collect_rows(), rows)

    def test_collision_indexes_cannot_be_built(self):
        for version in ("collision-custom-first", "collision-baseline-first"):
            with self.assertRaises(ValueError) as error:
                build_spdx_licensing(index_versions()[version])
            self.assertIn("Invalid duplicated alias", str(error.exception))


if __name__ == "__main__":
    unittest.main()
