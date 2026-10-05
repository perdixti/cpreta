"""Portable HTML snapshots authenticated for safe in-app rendering."""
import hashlib
import hmac
from pathlib import Path

LIMIT = 2 * 1024 * 1024
PREFIX = b'<!-- CPreta-report-v1: '


def file_identity(path):
    path = Path(path)
    stat = path.stat()
    identity = (str(path.resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    return hashlib.sha256(repr(identity).encode()).hexdigest()


def seal(html, key):
    body = html.encode('utf-8')
    digest = hmac.new(key.encode(), body, hashlib.sha256).hexdigest().encode()
    result = PREFIX + digest + b' -->\n' + body
    if len(result) > LIMIT:
        raise ValueError('O relatório excede 2 MB. Escolha um período menor.')
    return result


def verified(path, key):
    with Path(path).open('rb') as handle:
        raw = handle.read(LIMIT + 1)
    if len(raw) > LIMIT or not raw.startswith(PREFIX):
        return None
    header, separator, body = raw.partition(b'\n')
    expected = PREFIX + hmac.new(key.encode(), body, hashlib.sha256).hexdigest().encode() + b' -->'
    if not separator or not hmac.compare_digest(header, expected):
        return None
    return body
