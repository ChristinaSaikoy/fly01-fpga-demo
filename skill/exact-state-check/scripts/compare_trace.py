"""Read-only complete integer trace comparison. Standard library only."""
import argparse
import json
from itertools import zip_longest
from pathlib import Path
import re


def unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('Duplicate JSON key: ' + key)
        obj[key] = value
    return obj


def load_line(line):
    return json.loads(line, object_pairs_hook=unique)


def identity(stream):
    row = load_line(next(stream, ''))
    if not isinstance(row, dict) or not isinstance(row.get('model'), str) or not row['model']:
        raise ValueError('Missing model identity')
    if not isinstance(row.get('inputs_sha256'), str) or not re.fullmatch('[a-f0-9]{64}', row['inputs_sha256']):
        raise ValueError('Invalid inputs_sha256')
    for field in ('state_words', 'dn_slots'):
        if type(row.get(field)) is not int or row[field] <= 0:
            raise ValueError('Invalid dimension: ' + field)
    return {key: row[key] for key in ('model', 'inputs_sha256', 'state_words', 'dn_slots')}


def validate(row, step, ident):
    if not isinstance(row, dict) or type(row.get('step')) is not int or row['step'] != step:
        raise ValueError('Missing, repeated or out-of-order step: ' + str(step))
    for field, count in (('state', ident['state_words']), ('dn', ident['dn_slots'])):
        values = row.get(field)
        if not isinstance(values, list) or len(values) != count or any(type(v) is not int for v in values):
            raise ValueError('Incomplete or non-integer ' + field + ' at step ' + str(step))


def compare(expected, actual):
    with Path(expected).open(encoding='utf-8') as left, Path(actual).open(encoding='utf-8') as right:
        ident = identity(left)
        if ident != identity(right):
            raise ValueError('Model/input/dimension identity mismatch')
        count = 0
        for step, lines in enumerate(zip_longest(left, right)):
            if None in lines:
                raise ValueError('Trace length mismatch at step ' + str(step))
            rows = [load_line(line) for line in lines]
            for row in rows:
                validate(row, step, ident)
            for field in ('state', 'dn'):
                for index, (a, b) in enumerate(zip(rows[0][field], rows[1][field])):
                    if a != b:
                        raise ValueError('Mismatch step=' + str(step) + ' field=' + field + ' index=' + str(index))
            count += 1
        if count == 0:
            raise ValueError('Empty trace')
        return dict(status='EXACT_MATCH', steps=count, **ident, hardware='NONE')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('expected', type=Path)
    parser.add_argument('actual', type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.expected, args.actual)
    except (ValueError, OSError) as error:
        print(json.dumps(dict(status='REJECTED', reason=str(error)), ensure_ascii=True))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
