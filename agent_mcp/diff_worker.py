"""Private pure-computation subprocess. No Django setup, DB, files or URLs."""
import hashlib
import json
import sys

from padif.core.differ import diff_sentences, stats_from_ops, summarize
from padif.core.diff_payload import annotate_diff_lines, op_payload

MAX_INLINE_OP_BYTES = 2048


def _reference(source_id: int | str, content: str, kind: str = 'version_markdown') -> dict:
    return {'source_kind': kind, 'source_id': source_id,
            'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
            'scope': 'whole_version', 'normalization': 'utf8-no-bom-lf'}


def compute(payload: dict) -> dict:
    old, new = payload['old'], payload['new']
    ops = diff_sentences(old, new)
    annotate_diff_lines(ops, old, new)
    offset, limit = payload['offset'], payload['limit']
    selected = ops[offset:offset+limit] if limit is not None else ops
    result = {'stats': stats_from_ops(ops), 'from_summary': summarize(old), 'to_summary': summarize(new),
              'ops': [], 'total_ops': len(ops)}
    for op in selected:
        item = op_payload(op)
        if payload['paged'] and len(json.dumps(item, ensure_ascii=False).encode('utf-8')) > MAX_INLINE_OP_BYTES:
            item = {key: value for key, value in item.items() if key not in {'text', 'inner'}}
            item.update(text='', text_complete=False)
            side = 'old' if op.op in {'delete', 'replace'} else 'new'
            item['text_ref'] = _reference(payload[side+'_id'], payload[side], payload.get('new_kind', 'version_markdown') if side == 'new' else 'version_markdown')
            if op.op == 'replace':
                item.update(inner_complete=False, before_ref=_reference(payload['old_id'], old),
                            after_ref=_reference(payload['new_id'], new, payload.get('new_kind', 'version_markdown')))
        result['ops'].append(item)
        # Legacy mode must not materialize/emit an unlimited wire payload.
        if not payload['paged'] and len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 32768:
            return {'error': 'OUTPUT_TOO_LARGE'}
    while payload['paged'] and len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 30000 and len(result['ops']) > 1:
        result['ops'].pop()
    return result


if __name__ == '__main__':
    value = compute(json.loads(sys.stdin.buffer.read().decode('utf-8')))
    encoded = json.dumps(value, ensure_ascii=False).encode('utf-8')
    if len(encoded) > 65536:
        # A paginated request can safely retry a smaller page; no partial result.
        encoded = b'{"error":"OUTPUT_TOO_LARGE"}'
    sys.stdout.buffer.write(encoded)
