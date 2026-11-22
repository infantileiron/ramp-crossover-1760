import json

from src.config.database import connect
from src.utils.passwords import hash_password

ACCOUNTS = (
    ('reviewer', '程岚', 'reviewer', 'Review5215!'),
    ('analyst', '沈栩', 'analyst', 'Analyze5215!'),
    ('viewer', '陶桥', 'viewer', 'View5215!'),
)
ROUTE = (
    'R07', '北门连廊坡道', '北门入口', '连廊平台', 86,
    '由入口经过花坛岔口至连廊平台。两轮走同一条路线，期间更换岔口的指引。',
    '文字箭头牌', '坡道图标牌',
)
BATCH = ('现场手记初录', '计时员手记表一')
PAIRS = (
    ('AB01', 'AB', 60, 42), ('AB02', 'AB', 64, 52), ('AB03', 'AB', 75, 51),
    ('AB04', 'AB', 70, 50), ('AB05', 'AB', 65, 49), ('AB06', 'AB', 68, 50),
    ('AB07', 'AB', 72, None),
    ('BA01', 'BA', 65, 69), ('BA02', 'BA', 76, 76), ('BA03', 'BA', 70, 74),
    ('BA04', 'BA', 73, 73), ('BA05', 'BA', None, 79),
)


def seed():
    with connect() as db, db.cursor() as cursor:
        cursor.executemany(
            'INSERT INTO app_user (username, display_name, role, password_hash) VALUES (%s,%s,%s,%s) '
            'ON CONFLICT (username) DO NOTHING',
            [(username, name, role, hash_password(password)) for username, name, role, password in ACCOUNTS],
        )
        cursor.execute('INSERT INTO field_route VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING', ROUTE)
        has_pairs = cursor.execute('SELECT 1 FROM field_pair WHERE route_code=%s LIMIT 1', (ROUTE[0],)).fetchone()
        if not has_pairs:
            cursor.execute(
                'INSERT INTO collection_batch (route_code, label, source, created_by) VALUES (%s,%s,%s,%s) '
                'ON CONFLICT (route_code, label) DO NOTHING RETURNING id',
                (ROUTE[0], *BATCH, 'analyst'),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute('SELECT id FROM collection_batch WHERE route_code=%s AND label=%s', (ROUTE[0], BATCH[0]))
                batch_id = cursor.fetchone()['id']
            else:
                batch_id = row['id']
            cursor.executemany(
                'INSERT INTO field_pair (route_code, code, sequence, period1, period2, batch_id) VALUES (%s,%s,%s,%s,%s,%s) '
                'ON CONFLICT (route_code, code) DO NOTHING',
                [(ROUTE[0], code, sequence, period1, period2, batch_id) for code, sequence, period1, period2 in PAIRS],
            )
            cursor.executemany(
                'INSERT INTO collection_entry (batch_id, route_code, code, sequence, period1, period2, kind, status, actor) '
                "SELECT %s, p.route_code, p.code, p.sequence, p.period1, p.period2, 'register', "
                "CASE WHEN p.period1 IS NOT NULL AND p.period2 IS NOT NULL THEN 'passed' ELSE 'missing' END, 'analyst' "
                'FROM field_pair AS p WHERE p.route_code=%s AND p.code=%s AND p.entry_id IS NULL',
                [(batch_id, ROUTE[0], code) for code, _, _, _ in PAIRS],
            )
            cursor.execute(
                'UPDATE field_pair AS p SET entry_id=e.id FROM collection_entry AS e '
                'WHERE e.batch_id=%s AND e.route_code=p.route_code AND e.code=p.code '
                'AND p.route_code=%s AND p.entry_id IS NULL',
                (batch_id, ROUTE[0]),
            )
        cursor.execute(
            'INSERT INTO analysis_plan (route_code, edition, min_pairs, gap_limit, created_by) '
            "VALUES (%s,'现场初核',3,8,'analyst') ON CONFLICT (route_code, edition) DO NOTHING", (ROUTE[0],),
        )
        keys = {
            'users': [row['username'] for row in db.execute('SELECT username FROM app_user ORDER BY username')],
            'routes': [row['code'] for row in db.execute('SELECT code FROM field_route ORDER BY code')],
            'pairs': [list(row.values()) for row in db.execute('SELECT route_code, code FROM field_pair ORDER BY route_code, code')],
            'plans': [list(row.values()) for row in db.execute('SELECT route_code, edition FROM analysis_plan ORDER BY route_code, edition')],
            'batches': [list(row.values()) for row in db.execute('SELECT route_code, label FROM collection_batch ORDER BY route_code, label')],
        }
    print(json.dumps(keys, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    seed()
