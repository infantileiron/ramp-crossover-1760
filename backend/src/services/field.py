from fastapi import HTTPException

from src.config.database import connect
from src.constants.domain import EntryKind, EntryStatus
from src.services.audit import record

ENTRY_INSERT = '''
    INSERT INTO collection_entry
        (batch_id, route_code, code, sequence, period1, period2, kind,
         prev_sequence, prev_period1, prev_period2, prev_entry_id, status, actor)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING *
'''


def route_or_error(db, route_code):
    route = db.execute('SELECT * FROM field_route WHERE code=%s', (route_code,)).fetchone()
    if route is None:
        raise HTTPException(404, '未找到路线')
    return route


def routes():
    with connect() as db:
        return db.execute('SELECT * FROM field_route ORDER BY code').fetchall()


def ledger_rows(db, route_code):
    return db.execute('''
        SELECT p.code, p.sequence, p.period1, p.period2, p.batch_id, p.entry_id,
               b.label AS batch_label, e.status AS entry_status
        FROM field_pair AS p
        LEFT JOIN collection_batch AS b ON b.id=p.batch_id
        LEFT JOIN collection_entry AS e ON e.id=p.entry_id
        WHERE p.route_code=%s ORDER BY p.sequence, p.code
    ''', (route_code,)).fetchall()


def pairs(route_code):
    with connect() as db:
        route_or_error(db, route_code)
        return ledger_rows(db, route_code)


def batches(route_code):
    with connect() as db:
        route_or_error(db, route_code)
        return db.execute('''
            SELECT b.*, COALESCE(t.total, 0) AS entries, COALESCE(t.flagged, 0) AS flagged,
                   (COALESCE(t.total, 0) > 0 AND COALESCE(t.flagged, 0) = 0) AS complete
            FROM collection_batch AS b LEFT JOIN (
                SELECT batch_id, count(*) AS total,
                       count(*) FILTER (WHERE status NOT IN ('passed', 'duplicate')) AS flagged
                FROM collection_entry GROUP BY batch_id
            ) AS t ON t.batch_id=b.id
            WHERE b.route_code=%s ORDER BY b.id DESC
        ''', (route_code,)).fetchall()


def create_batch(route_code, data, actor):
    with connect() as db:
        route_or_error(db, route_code)
        batch = db.execute('''
            INSERT INTO collection_batch (route_code, label, source, created_by) VALUES (%s,%s,%s,%s)
            ON CONFLICT (route_code, label) DO NOTHING RETURNING *
        ''', (route_code, data.label, data.source, actor)).fetchone()
        if batch is None:
            raise HTTPException(409, '此路线已有同名采集批次')
        record(db, actor, 'batch_created', f'{route_code}/{batch["id"]}', data.model_dump(mode='json'))
        return batch


def entries(route_code):
    with connect() as db:
        route_or_error(db, route_code)
        return db.execute('''
            SELECT e.*, b.label AS batch_label, b.source AS batch_source
            FROM collection_entry AS e JOIN collection_batch AS b ON b.id=e.batch_id
            WHERE e.route_code=%s ORDER BY e.id DESC
        ''', (route_code,)).fetchall()


def batch_or_error(db, route_code, batch_id):
    batch = db.execute('SELECT * FROM collection_batch WHERE id=%s AND route_code=%s', (batch_id, route_code)).fetchone()
    if batch is None:
        raise HTTPException(404, '未找到采集批次')
    return batch


def save_pair(route_code, code, data, actor):
    with connect() as db:
        route_or_error(db, route_code)
        batch = batch_or_error(db, route_code, data.batch_id)
        current = db.execute('SELECT * FROM field_pair WHERE route_code=%s AND code=%s FOR UPDATE',
                             (route_code, code)).fetchone()
        if current is not None and current['sequence'] != data.sequence:
            entry = db.execute(ENTRY_INSERT, (
                batch['id'], route_code, code, data.sequence, data.period1, data.period2, EntryKind.MODIFY,
                current['sequence'], current['period1'], current['period2'], current['entry_id'],
                EntryStatus.SEQUENCE_CONFLICT, actor,
            )).fetchone()
            record(db, actor, 'pair_saved', f'{route_code}/{code}',
                   {'batch_id': batch['id'], 'kind': EntryKind.MODIFY, 'status': EntryStatus.SEQUENCE_CONFLICT})
            db.commit()
            raise HTTPException(409, '已有受试者的分配顺序不可变更，此次上传已按顺序冲突记入对账台账')
        if current is None:
            kind, status = EntryKind.REGISTER, None
        elif current['period1'] == data.period1 and current['period2'] == data.period2:
            kind, status = EntryKind.REUPLOAD, EntryStatus.DUPLICATE
        else:
            fills_gap = ((current['period1'] is None) != (data.period1 is None)
                         or (current['period2'] is None) != (data.period2 is None))
            keeps_values = all(current[key] is None or current[key] == getattr(data, key) for key in ('period1', 'period2'))
            kind = EntryKind.SUPPLEMENT if fills_gap and keeps_values else EntryKind.MODIFY
            status = None
        if status is None:
            status = EntryStatus.PASSED if data.period1 is not None and data.period2 is not None else EntryStatus.MISSING
        entry = db.execute(ENTRY_INSERT, (
            batch['id'], route_code, code, data.sequence, data.period1, data.period2, kind,
            current['sequence'] if current else None,
            current['period1'] if current else None,
            current['period2'] if current else None,
            current['entry_id'] if current else None,
            status, actor,
        )).fetchone()
        if kind in (EntryKind.REGISTER, EntryKind.SUPPLEMENT, EntryKind.MODIFY):
            if current is not None and current['entry_id'] is not None:
                db.execute("UPDATE collection_entry SET status=%s WHERE id=%s AND status IN ('passed','missing')",
                           (EntryStatus.CONFLICT, current['entry_id']))
            db.execute('''
                INSERT INTO field_pair (route_code, code, sequence, period1, period2, batch_id, entry_id, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (route_code, code) DO UPDATE
                SET period1=excluded.period1, period2=excluded.period2,
                    batch_id=excluded.batch_id, entry_id=excluded.entry_id, updated_at=now()
            ''', (route_code, code, data.sequence, data.period1, data.period2, batch['id'], entry['id']))
        pair = db.execute('SELECT code, sequence, period1, period2, batch_id, entry_id FROM field_pair '
                          'WHERE route_code=%s AND code=%s', (route_code, code)).fetchone()
        record(db, actor, 'pair_saved', f'{route_code}/{code}', {
            'batch_id': batch['id'], 'kind': kind, 'status': status,
            'prev': {'period1': str(current['period1']) if current and current['period1'] is not None else None,
                     'period2': str(current['period2']) if current and current['period2'] is not None else None},
            'value': {'period1': str(data.period1) if data.period1 is not None else None,
                      'period2': str(data.period2) if data.period2 is not None else None},
        })
        return {'pair': pair, 'entry': entry}


def plans(route_code):
    with connect() as db:
        route_or_error(db, route_code)
        return db.execute('SELECT * FROM analysis_plan WHERE route_code=%s ORDER BY id DESC', (route_code,)).fetchall()


def create_plan(data, actor):
    with connect() as db:
        route_or_error(db, data.route_code)
        plan = db.execute('''
            INSERT INTO analysis_plan (route_code, edition, min_pairs, gap_limit, created_by) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (route_code, edition) DO NOTHING RETURNING *
        ''', (data.route_code, data.edition, data.min_pairs, data.gap_limit, actor)).fetchone()
        if plan is None:
            raise HTTPException(409, '此路线已有同名版本')
        record(db, actor, 'plan_created', str(plan['id']), data.model_dump(mode='json'))
        return plan
