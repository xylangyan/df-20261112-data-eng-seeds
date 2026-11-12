"""Track source cursor positions for lazily consumed partitions."""

from toolz import partitionby_iter


class Cursor:
    def __init__(self, records):
        self.records = records
        self.pulled = 0

    def __iter__(self):
        for record in self.records:
            self.pulled += 1
            yield record


def reducer(total, record):
    return total + record["value"]


def failing_reducer(total, record):
    if record["session"] == "c" and record["n"] == 2:
        raise RuntimeError("bad record in third partition")
    return total + record["value"]


def run_full(cursor):
    summaries = []
    for partition in partitionby_iter("session", cursor, reducer, 0):
        list(partition)
        summaries.append(partition.summary)
    return summaries, cursor.pulled


def run_skip_middle(cursor):
    groups = iter(partitionby_iter("session", cursor, reducer, 0))
    first = next(groups)
    list(first)
    middle = next(groups)
    skipped = middle.skip()
    third = next(groups)
    return first.summary, skipped, third.key, cursor.pulled


def run_error_in_third(cursor):
    groups = iter(partitionby_iter("session", cursor, failing_reducer, 0))
    summaries = []
    failed = None
    for partition in groups:
        try:
            list(partition)
            summaries.append(partition.summary)
        except RuntimeError as error:
            failed = (error, partition.key, partition.count, cursor.pulled)
            break
    return summaries, failed


records = [
    {"session": "a", "n": 1, "value": 1},
    {"session": "a", "n": 2, "value": 2},
    {"session": "a", "n": 3, "value": 3},
    {"session": "b", "n": 1, "value": 4},
    {"session": "b", "n": 2, "value": 5},
    {"session": "b", "n": 3, "value": 6},
    {"session": "c", "n": 1, "value": 7},
    {"session": "c", "n": 2, "value": 8},
    {"session": "c", "n": 3, "value": 9},
]


if __name__ == "__main__":
    print("full:", run_full(Cursor(records)))
    print("skip middle:", run_skip_middle(Cursor(records)))
    print("error in third:", run_error_in_third(Cursor(records)))
