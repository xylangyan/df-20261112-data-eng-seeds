import csv
import sys

from license_expression import LicenseSymbol
from license_expression import LicenseWithExceptionSymbol
from license_expression import TOKEN_AND
from license_expression import TOKEN_OR
from license_expression import TOKEN_WITH
from license_expression import build_spdx_licensing
from license_expression import get_license_index


def record(key, aliases=(), is_exception=False):
    return {
        "license_key": key,
        "spdx_license_key": key,
        "other_spdx_license_keys": list(aliases),
        "is_exception": is_exception,
        "is_deprecated": False,
    }


def baseline_index():
    baseline_keys = {
        "mit",
        "gpl-2.0",
        "classpath-exception-2.0",
        "bsd-simplified",
    }
    fields = (
        "license_key",
        "spdx_license_key",
        "other_spdx_license_keys",
        "is_exception",
        "is_deprecated",
    )
    return [
        {field: entry[field] for field in fields}
        for entry in get_license_index()
        if entry["license_key"] in baseline_keys
    ]


def merged_aliases():
    return [
        record("custom-mit-or-later", ["MIT OR LATER"]),
        record("custom-mit-and-bsd", ["MIT AND BSD"]),
        record(
            "custom-gpl-with-classpath",
            ["GPL-2.0-only WITH Classpath exception-2.0"],
        ),
        record(
            "custom-gpl-with-classpath-exception",
            ["GPL-2.0-only WITH Classpath-exception-2.0"],
            is_exception=True,
        ),
        record("custom-bsd-two-clause", ["BSD TWO CLAUSE"]),
    ]


def overlapping_aliases():
    return [
        record(
            "custom-gpl-with-classpath-prefix",
            ["GPL-2.0-only WITH Classpath"],
        ),
        record(
            "custom-classpath-exception-alias",
            ["Classpath exception-2.0"],
            is_exception=True,
        ),
    ]


def index_versions():
    baseline = baseline_index()
    merged = baseline + merged_aliases()
    return {
        "baseline": baseline,
        "merged-normal": merged,
        "merged-reversed": list(reversed(merged)),
        "overlap-prefix": baseline + overlapping_aliases(),
        "self-alias": baseline + [record("custom-self", ["custom-self", "CUSTOM-SELF"])],
        "collision-custom-first": [record("custom-collision", ["MIT"])] + baseline,
        "collision-baseline-first": baseline + [record("custom-collision", ["MIT"])],
    }


def matrix_probes():
    return [
        ("longest-or-boundary", "MIT OR LATER", False),
        ("longest-and-boundary", "mit and bsd", False),
        ("longest-and-nonmatching-suffix", "MIT AND BSDX", False),
        ("case-insensitive-longest", "BSD TWO CLAUSE", False),
        ("case-insensitive-longest-lowercase", "bsd two clause", False),
        ("with-wordy-exception", "GPL-2.0-only WITH Classpath exception-2.0", False),
        ("with-true-exception-key", "GPL-2.0-only WITH Classpath-exception-2.0", False),
        ("with-wordy-exception-strict", "GPL-2.0-only WITH Classpath exception-2.0", True),
        ("with-true-exception-key-strict", "GPL-2.0-only WITH Classpath-exception-2.0", True),
        ("unchanged-short-key", "MIT", False),
        ("alias-equals-own-key-case", "CUSTOM-SELF", False),
    ]


def one_line(value):
    return " | ".join(line.strip() for line in str(value).splitlines() if line.strip())


def render_token(value, original):
    if isinstance(value, LicenseWithExceptionSymbol):
        return f"WITH_GROUP[{value}]"
    if isinstance(value, LicenseSymbol):
        return f"SYMBOL[{value.key}]"
    operators = {
        TOKEN_AND: "AND",
        TOKEN_OR: "OR",
        TOKEN_WITH: "WITH",
    }
    return f"OPERATOR[{operators.get(value, value)}]"


def tokenize_result(licensing, expression, strict):
    try:
        tokens = list(licensing.tokenize(expression, strict=strict))
    except Exception as error:
        return "rejected", f"TOKENIZE_ERROR[{type(error).__name__}: {one_line(error)}]"
    rendered = " ; ".join(
        f"{render_token(value, original)}({original!r}@{position})"
        for value, original, position in tokens
    )
    return "accepted", rendered


def parse_result(licensing, expression, strict):
    try:
        parsed = licensing.parse(expression, strict=strict)
    except Exception as error:
        return "rejected", f"PARSE_ERROR[{type(error).__name__}: {one_line(error)}]"
    return "accepted", f"EXPRESSION[{parsed}]"


def collect_rows():
    rows = []
    for version, index in index_versions().items():
        try:
            licensing = build_spdx_licensing(index)
        except Exception as error:
            for scenario, expression, strict in matrix_probes():
                rows.append(
                    {
                        "index_version": version,
                        "scenario": scenario,
                        "raw_token": expression,
                        "strict": str(strict).lower(),
                        "build_result": "rejected",
                        "build_detail": f"{type(error).__name__}: {one_line(error)}",
                        "tokenize_result": "not-run",
                        "tokenize_detail": "index build rejected",
                        "parse_result": "not-run",
                        "parse_detail": "index build rejected",
                    }
                )
            continue

        for scenario, expression, strict in matrix_probes():
            token_status, token_detail = tokenize_result(licensing, expression, strict)
            parse_status, parse_detail = parse_result(licensing, expression, strict)
            rows.append(
                {
                    "index_version": version,
                    "scenario": scenario,
                    "raw_token": expression,
                    "strict": str(strict).lower(),
                    "build_result": "accepted",
                    "build_detail": "",
                    "tokenize_result": token_status,
                    "tokenize_detail": token_detail,
                    "parse_result": parse_status,
                    "parse_detail": parse_detail,
                }
            )
    return rows


def write_matrix(stream):
    fieldnames = [
        "index_version",
        "scenario",
        "raw_token",
        "strict",
        "build_result",
        "build_detail",
        "tokenize_result",
        "tokenize_detail",
        "parse_result",
        "parse_detail",
    ]
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(collect_rows())


if __name__ == "__main__":
    write_matrix(sys.stdout)
