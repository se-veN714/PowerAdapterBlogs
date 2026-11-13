"""Pure diff serialization shared by the web API and isolated MCP worker."""
from .differ import DiffOp


def op_payload(op: DiffOp) -> dict:
    payload = {'op': op.op, 'text': op.text}
    for field in ('old_line', 'new_line'):
        value = getattr(op, field, None)
        if value is not None:
            payload[field] = value
    if op.inner:
        payload['inner'] = [op_payload(item) for item in op.inner]
    return payload


def annotate_diff_lines(ops: list[DiffOp], old_content: str, new_content: str) -> None:
    old_cursor = new_cursor = 0
    old_lines = old_content.replace('\r\n', '\n').split('\n')
    new_lines = new_content.replace('\r\n', '\n').split('\n')
    for op in ops:
        text = op.text
        if op.op in {'delete', 'replace'}:
            for index in range(old_cursor, len(old_lines)):
                if text and text.strip() in old_lines[index]:
                    op.old_line = index + 1
                    old_cursor = index
                    break
        search_text = text
        if op.op == 'replace' and op.inner:
            inserted = ''.join(item.text for item in op.inner if item.op in {'equal', 'insert'})
            if inserted:
                search_text = inserted
        if op.op in {'insert', 'replace', 'moved', 'equal'}:
            for index in range(new_cursor, len(new_lines)):
                if search_text and search_text.strip() in new_lines[index]:
                    op.new_line = index + 1
                    new_cursor = index
                    break
