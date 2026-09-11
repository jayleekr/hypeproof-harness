"""Read-only audit of an explicitly supplied context register; no content deletion."""
import argparse
import json
from datetime import date
from pathlib import Path


def audit(data, as_of):
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('items'), list):
        raise ValueError('expected version 1 and items list')
    seen, findings, active = set(), [], {}
    for item in data['items']:
        if not isinstance(item, dict):
            raise ValueError('item must be an object')
        for key in ('id', 'key', 'value', 'owner', 'source', 'status', 'verified_at', 'review_after'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f'missing or invalid {key}')
        if item['id'] in seen:
            raise ValueError('duplicate id: ' + item['id'])
        seen.add(item['id'])
        if item['status'] not in ('active', 'closed', 'superseded'):
            raise ValueError('invalid status: ' + item['id'])
        verified, due = date.fromisoformat(item['verified_at']), date.fromisoformat(item['review_after'])
        if verified > as_of or due < verified:
            raise ValueError('inconsistent dates: ' + item['id'])
        if item['status'] != 'active':
            continue
        if due < as_of:
            findings.append({'kind': 'overdue', 'ids': [item['id']], 'owner': item['owner'], 'source': item['source']})
        active.setdefault(item['key'], []).append(item)
    for key, items in active.items():
        if len({item['value'] for item in items}) > 1:
            findings.append({'kind': 'conflict', 'key': key, 'ids': [item['id'] for item in items],
                             'owners': sorted({item['owner'] for item in items}),
                             'sources': [item['source'] for item in items]})
    return {'as_of': as_of.isoformat(), 'scope': 'explicit register only; no semantic or factual verification',
            'items_checked': len(seen), 'overdue_count': sum(f['kind'] == 'overdue' for f in findings),
            'conflict_count': sum(f['kind'] == 'conflict' for f in findings), 'findings': findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('register', type=Path)
    parser.add_argument('--as-of', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    try:
        result = audit(json.loads(args.register.read_text()), args.as_of)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f'Invalid context register: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
