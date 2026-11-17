"""Conservative dataset admission after frozen teacher proposal mining."""
from mine_full_pseudo_labels import positions
import hashlib
import json
from pathlib import Path

_AUDIT_BYTES=Path(__file__).with_name('manual_scope_exclusions.json').read_bytes()
assert hashlib.sha256(_AUDIT_BYTES).hexdigest()=='bb7b34097631ea15cff8082f6cdfb657b979c0e1073c67d9b311da1c52c6f60a'
_VISUAL_EXCLUSIONS=json.loads(_AUDIT_BYTES)['excluded_frames']


def touches_internal_tile_boundary(box, width, height, tolerance=2):
    """Reject possible tile-truncated faces; true outer image edges are allowed.

    The raw mining records did not retain the proposal's source window. Testing
    every internal boundary can conservatively exclude a coincident full-view
    box. It cannot recover a full box suppressed by a higher-scoring fragment.
    """
    if max(width, height) <= 1536:
        return False
    for length, lower, upper in ((width, box[0], box[2]), (height, box[1], box[3])):
        for start in positions(length):
            end = min(start+1536, length)
            if start > 0 and abs(lower-start) <= tolerance:
                return True
            if end < length and abs(upper-end) <= tolerance:
                return True
    return False


def exclusion_reason(pseudo):
    if pseudo['status'] not in ('pseudo_positive', 'pseudo_negative'):
        return pseudo['status']
    if pseudo.get('picture_id') in _VISUAL_EXCLUSIONS:
        return 'visual_scope_or_localization_audit'
    if any(row['class_label']=='lanes' for row in pseudo['accepted_boxes']):
        return 'excluded_direction_or_lane_layout_board'
    if any(touches_internal_tile_boundary(row['box'], pseudo['width'], pseudo['height'])
           for row in pseudo['accepted_boxes']):
        return 'possible_tile_truncated_sign_box'
    return None
