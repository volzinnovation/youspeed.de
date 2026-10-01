import unittest
from audit_drive_stability import continuity, visible
from compare_replay_cadence import continuity as replay_continuity


def frame(t, x, published=True):
    return ('time', dict(sourceTimestampSeconds=t,capturedAtSeconds=t,frameId=str(t),
        analysisWidth=101,overlayPublished=published,
        boundaries=[dict(points=[[x,.5],[x,.9]],cue='paint',provenance='fresh')],
        lanePresentation=dict(visibleBoundaryIndices=[0],items=[dict(trackId=1,boundaryIndex=0)])))


class DriveStabilityTests(unittest.TestCase):
    def test_suppressed_output_is_not_visible(self):
        self.assertEqual(visible(frame(1,.3,False)[1]),{})
        report=continuity([frame(1,.3),frame(1.5,.3,False)])
        self.assertEqual(report['availabilityTransitions'],1)
        self.assertEqual(report['sameIdSteps'],0)

    def test_displacement_uses_shared_rows_and_excludes_long_gaps(self):
        report=continuity([frame(1,.3),frame(1.5,.4),frame(3,.6)])
        self.assertEqual(report['sameIdSteps'],1)
        self.assertAlmostEqual(report['sameIdMaxDisplacementPixels']['p50'],10)
        self.assertEqual(report['gapsOver750ms'],1)

    def test_replay_ids_are_scoped_to_sequences(self):
        rows=[dict(sequenceId=seq,time=t,visibleIDs=[1]) for seq in ['a','b'] for t in [0,.5]]
        report=replay_continuity(rows)
        self.assertEqual(report['uniqueVisibleIds'],2)
        self.assertEqual(report['identitySetTransitions'],0)
        self.assertEqual(report['observedSpanSeconds'],1)


if __name__=='__main__':unittest.main()
