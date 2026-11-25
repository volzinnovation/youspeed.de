"""Keep vehicle-scoped sign assemblies in the inventory without a car speed rule."""

PLATE_CODES = ('DE:1052-30', 'DE:1052-31')


def restricted_inventory_signs(db):
    columns = {row[1] for row in db.execute('PRAGMA table_info(traffic_sign_inventory)')}
    restricted = {}
    if {'group_id', 'location_id'}.issubset(columns):
        marks = ','.join('?' for _ in PLATE_CODES)
        # MobiData gives a sign assembly one group ID. Group order distinguishes
        # different assemblies on the same support and is not a plate position.
        query = f'''SELECT p.source_id, p.record_key, z.sign_code
            FROM traffic_sign_inventory z JOIN traffic_sign_inventory p
              ON p.source_id=z.source_id AND p.group_id=z.group_id AND p.location_id=z.location_id
            WHERE z.sign_code IN ({marks}) AND (p.sign_code GLOB 'DE:274-*' OR p.sign_code GLOB 'DE:274[[]*')
              AND (SELECT count(*) FROM traffic_sign_inventory member
                   WHERE member.source_id=p.source_id AND member.group_id=p.group_id
                     AND member.location_id=p.location_id
                     AND (member.sign_code GLOB 'DE:274-*' OR member.sign_code GLOB 'DE:274[[]*'))=1
            ORDER BY p.source_id,p.record_key,z.sign_code'''
        for source, key, plate in db.execute(query, PLATE_CODES):
            restricted[f'{source}:{key}'] = plate
    return restricted


def suppress_inventory_rules(db, restricted):
    for sign, plate in restricted.items():
        # Remove successors first. The source record and associated placement remain auditable.
        db.execute('''DELETE FROM traffic_sign_rule_path WHERE rule_id IN
                      (SELECT rule_id FROM traffic_sign_way_rule WHERE sign_id=?)''', (sign,))
        db.execute('DELETE FROM traffic_sign_way_rule WHERE sign_id=?', (sign,))
        db.execute('''UPDATE traffic_sign_association SET status='vehicle_restricted',
            evidence_json=json_set(evidence_json, '$.vehicle_plate', ?) WHERE sign_id=?''', (plate, sign))
