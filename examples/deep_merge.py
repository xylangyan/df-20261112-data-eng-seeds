from toolz import deep_merge

# Three sources report the same device, each missing some fields.
# Missing keys were not reported; explicit None retracts the old value.
SOURCE_1 = {
    'host': {'name': 'edge-01', 'ip': '10.0.0.1'},
    'storage': {'disk': 120, 'raid': 'mirror'},
}

SOURCE_2 = {
    'host': {'name': 'edge-01', 'ip': '10.0.0.9'},
    'storage': {'raid': None, 'cache': 32},
}

SOURCE_3 = {
    'host': {'name': 'edge-02', 'rack': 'B7'},
    'storage': {'disk': 240},
}

# Rules are looked up by the full field path.  Unlisted conflicts keep
# the value from the last source that reported the field.
RULES = {
    ('host', 'ip'): lambda values: values[0],
    ('storage', 'disk'): max,
}


def render_conflict(entry):
    path, values, sources = entry
    field = '.'.join(path)
    values = ' vs '.join(repr(v) for v in values)
    sources = ' -> '.join('source %d' % i for i in sources)
    return '%s: %s (%s)' % (field, values, sources)


if __name__ == '__main__':
    result, report = deep_merge(SOURCE_1, SOURCE_2, SOURCE_3, rules=RULES)

    print('final nested values:', result)
    print('conflicts:')
    for entry in report['conflicts']:
        print('  -', render_conflict(entry))
    print('explicitly cleared fields:')
    for path in report['cleared']:
        print('  -', '.'.join(path))
