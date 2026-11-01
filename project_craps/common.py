import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
SPORTS = ('NFL', 'NCAAF')


def now():
    return datetime.now(UTC)


def stamp(value):
    return value.astimezone(UTC).isoformat()


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result.astimezone(UTC)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def bytes_hash(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def create(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(canonical(value) + '\n')


def envelope(value):
    return {'sha256': digest(value), 'payload': value}


def unwrap(value):
    if set(value) != {'sha256', 'payload'} or digest(value['payload']) != value['sha256']:
        raise ValueError('hash mismatch')
    return value['payload']


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite number required')
    return value


def fresh(timestamp, issued, seconds, label):
    time = instant(timestamp)
    if time > issued or (issued - time).total_seconds() > seconds:
        raise ValueError(label + ': future or stale timestamp')


def code_fingerprint():
    package = Path(__file__).parent
    paths = list(package.glob('*.py')) + [package.parent / 'models' / 'probability.py']
    return digest({str(p.relative_to(package.parent)): bytes_hash(p.read_bytes()) for p in sorted(paths)})
