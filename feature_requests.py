import pathlib
from datetime import datetime, timezone

REQUESTS_PATH = pathlib.Path(__file__).parent / 'feature_requests.txt'


def append_request(user_id: int, username: str, text: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
    line = f'[{timestamp}] {username} ({user_id}): {text}'
    with open(REQUESTS_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def read_requests() -> str:
    try:
        with open(REQUESTS_PATH, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ''
