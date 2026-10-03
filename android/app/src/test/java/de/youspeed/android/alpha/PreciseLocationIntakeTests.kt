package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class PreciseLocationIntakeTests {
    @Test
    fun preservedFutureProviderTimesDoNotSuspendGermanyRulesOrPoisonFreshRoadContext() {
        val intake = PreciseLocationIntake()
        val country = PenaltyCountrySelection()
        val catalog = RegionalPackCatalog.decode(File("../../shared/RegionalCoverage/catalog-v1.json").readBytes())
        var latest: TrafficSignPositionSample? = null
        fun consume(sample: PreciseLocationSample, nowMs: Long, elapsedNowMs: Long): PreciseLocationIntakeResult {
            val decision = intake.evaluate(sample, nowMs, nanos(elapsedNowMs))
            if (decision is PreciseLocationIntakeResult.Accepted) {
                latest = TrafficSignPositionSample(decision.timestampMs, sample.latitude, sample.longitude, 90.0, 30.0)
                country.update(catalog, sample.latitude, sample.longitude, sample.horizontalAccuracyMeters!!,
                    decision.timestampMs / 1000.0, nowMs / 1000.0)
            }
            return decision
        }
        // UTC timestamps and coordinate from preserved runtime/GPS logs; both
        // providers share one physical sample. Its receipt age here is 65 ms.
        val gps = PreciseLocationSample(1_790_967_688_496L, nanos(10_000), 48.801185, 8.442425, 9.5)
        val fused = gps.copy(timestampMs = 1_790_967_689_000L)
        val first = accepted(consume(fused, 1_790_967_688_561L, 10_065))
        assertEquals(gps.timestampMs, first.timestampMs)
        assertEquals("DEU", country.countryCode)
        val acceptedLatest = latest

        rejected(PreciseLocationRejection.DUPLICATE_FIX, consume(gps, 1_790_967_688_581L, 10_085))
        rejected(PreciseLocationRejection.FUTURE_WALL_CLOCK_FIX,
            consume(gps.copy(timestampMs = 1_790_967_700_000L, elapsedRealtimeNanos = nanos(10_100)),
                1_790_967_688_596L, 10_100))
        rejected(PreciseLocationRejection.OUT_OF_ORDER_FIX,
            consume(gps.copy(timestampMs = 1_790_967_688_580L, elapsedRealtimeNanos = nanos(9_999)),
                1_790_967_688_601L, 10_105))
        assertSame(acceptedLatest, latest)
        assertEquals("DEU", country.countryCode)

        val nextGps = gps.copy(timestampMs = 1_790_967_689_490L, elapsedRealtimeNanos = nanos(11_000))
        val next = accepted(consume(nextGps.copy(timestampMs = 1_790_967_690_000L), 1_790_967_689_549L, 11_059))
        assertEquals(nextGps.timestampMs, next.timestampMs)
        assertEquals("DEU", country.countryCode)
        assertTrue(country.lastUpdateAcceptedNewFix)
        assertTrue(TrafficSignRoadContextFreshness.accepts(acceptedLatest!!, latest, 1_790_967_689_550L))
        assertFalse(TrafficSignRoadContextFreshness.accepts(acceptedLatest, latest, acceptedLatest.timestampMs + 6_001))
    }

    @Test
    fun fusedFutureUtcUsesActualSampleAgeAndGpsCompanionDoesNotReplaceIt() {
        val intake = PreciseLocationIntake()
        val fused = sample(time = 10_450, elapsedMs = 9_920)
        val accepted = accepted(intake.evaluate(fused, nowMs = 10_000, nowElapsedRealtimeNanos = nanos(10_000)))
        assertEquals(9_920L, accepted.timestampMs)
        assertTrue(accepted.wallClockAdjusted)
        assertTrue(TrafficSignRoadContextFreshness.accepts(
            position(accepted.timestampMs), position(accepted.timestampMs), 10_000,
        ))

        rejected(PreciseLocationRejection.DUPLICATE_FIX,
            intake.evaluate(fused.copy(timestampMs = 9_920), 10_020, nanos(10_020)))
        assertEquals(10_920L, accepted(intake.evaluate(sample(10_920, 10_920), 11_000, nanos(11_000))).timestampMs)
    }

    @Test
    fun gpsFirstAndFutureFusedCompanionProduceOnlyOnePhysicalFix() {
        val intake = PreciseLocationIntake()
        val gps = sample(9_920, 9_920)
        val first = accepted(intake.evaluate(gps, 10_000, nanos(10_000)))
        assertFalse(first.wallClockAdjusted)
        rejected(PreciseLocationRejection.DUPLICATE_FIX,
            intake.evaluate(gps.copy(timestampMs = 10_450), 10_010, nanos(10_010)))
    }

    @Test
    fun stationaryNewFixesAreAcceptedWhileOlderPhysicalSamplesAreRejected() {
        val intake = PreciseLocationIntake()
        accepted(intake.evaluate(sample(10_000, 10_000), 10_050, nanos(10_050)))
        accepted(intake.evaluate(sample(11_000, 11_000), 11_050, nanos(11_050)))
        rejected(PreciseLocationRejection.OUT_OF_ORDER_FIX,
            intake.evaluate(sample(11_030, 10_900), 11_060, nanos(11_060)))
        accepted(intake.evaluate(sample(12_000, 12_000), 12_050, nanos(12_050)))
    }

    @Test
    fun futureWallClockCorrectionRequiresTrustedMonotonicTimeAndSmallSkew() {
        val intake = PreciseLocationIntake()
        rejected(PreciseLocationRejection.FUTURE_WALL_CLOCK_FIX,
            intake.evaluate(sample(10_001, 0), 10_000, nanos(10_000)))
        rejected(PreciseLocationRejection.FUTURE_WALL_CLOCK_FIX,
            intake.evaluate(sample(11_001, 9_920), 10_000, nanos(10_000)))
        rejected(PreciseLocationRejection.FUTURE_MONOTONIC_FIX,
            intake.evaluate(sample(10_450, 10_001), 10_000, nanos(10_000)))
        assertEquals(9_920L, accepted(intake.evaluate(sample(11_000, 9_920), 10_000, nanos(10_000))).timestampMs)
    }

    @Test
    fun cachedAndFutureFixesCannotPoisonChronologyOfValidLatestContext() {
        val intake = PreciseLocationIntake()
        accepted(intake.evaluate(sample(10_000, 10_000), 10_050, nanos(10_050)))
        rejected(PreciseLocationRejection.STALE_MONOTONIC_FIX,
            intake.evaluate(sample(10_040, 4_000), 10_050, nanos(10_050)))
        rejected(PreciseLocationRejection.STALE_WALL_CLOCK_FIX,
            intake.evaluate(sample(4_000, 10_040), 10_050, nanos(10_050)))
        rejected(PreciseLocationRejection.FUTURE_WALL_CLOCK_FIX,
            intake.evaluate(sample(Long.MAX_VALUE, 10_040), 10_050, nanos(10_050)))
        assertEquals(10_100L, accepted(intake.evaluate(sample(10_100, 10_100), 10_150, nanos(10_150))).timestampMs)
    }

    @Test
    fun normalizationDoesNotRelaxTheSixSecondFreshnessBoundary() {
        val atBoundary = accepted(PreciseLocationIntake().evaluate(sample(10_450, 4_000), 10_000, nanos(10_000)))
        assertEquals(4_000L, atBoundary.timestampMs)
        assertTrue(TrafficSignRoadContextFreshness.accepts(position(4_000), position(4_000), 10_000))
        assertFalse(TrafficSignRoadContextFreshness.accepts(position(4_000), position(4_000), 10_001))
        rejected(PreciseLocationRejection.STALE_MONOTONIC_FIX,
            PreciseLocationIntake().evaluate(sample(10_450, 4_000).copy(elapsedRealtimeNanos = nanos(4_000) - 1),
                10_000, nanos(10_000)))
        rejected(PreciseLocationRejection.STALE_WALL_CLOCK_FIX,
            PreciseLocationIntake().evaluate(sample(3_999, 4_000), 10_000, nanos(10_000)))
    }

    @Test
    fun validNonFutureUtcIsPreservedAndAcceptedChronologyCannotRegress() {
        val intake = PreciseLocationIntake()
        val original = accepted(intake.evaluate(sample(9_950, 9_930), 10_000, nanos(10_000)))
        assertEquals(9_950L, original.timestampMs)
        assertFalse(original.wallClockAdjusted)
        rejected(PreciseLocationRejection.NON_INCREASING_WALL_CLOCK,
            intake.evaluate(sample(9_950, 9_940), 10_010, nanos(10_010)))
        rejected(PreciseLocationRejection.NON_INCREASING_WALL_CLOCK,
            intake.evaluate(sample(9_949, 9_945), 10_010, nanos(10_010)))
        assertEquals(10_020L, accepted(intake.evaluate(sample(10_020, 10_000), 10_030, nanos(10_030))).timestampMs)
    }

    @Test
    fun missingMonotonicTimeUsesStrictWallClockChronologyAndResetStartsANewSession() {
        val intake = PreciseLocationIntake()
        accepted(intake.evaluate(sample(10_000, 0), 10_010, nanos(10_010)))
        rejected(PreciseLocationRejection.DUPLICATE_FIX,
            intake.evaluate(sample(10_000, 0), 10_020, nanos(10_020)))
        rejected(PreciseLocationRejection.OUT_OF_ORDER_FIX,
            intake.evaluate(sample(9_999, 0), 10_020, nanos(10_020)))
        intake.reset()
        accepted(intake.evaluate(sample(9_999, 0), 10_020, nanos(10_020)))
    }

    @Test
    fun utcOnlyFallbackDoesNotErasePreviousMonotonicChronology() {
        val intake = PreciseLocationIntake()
        accepted(intake.evaluate(sample(10_000, 10_000), 10_010, nanos(10_010)))
        accepted(intake.evaluate(sample(10_020, 0), 10_030, nanos(10_030)))
        rejected(PreciseLocationRejection.OUT_OF_ORDER_FIX,
            intake.evaluate(sample(10_030, 9_990), 10_040, nanos(10_040)))
        rejected(PreciseLocationRejection.DUPLICATE_FIX,
            intake.evaluate(sample(10_030, 10_000), 10_040, nanos(10_040)))
        accepted(intake.evaluate(sample(10_040, 10_040), 10_050, nanos(10_050)))
    }

    @Test
    fun malformedFieldsAreRejectedWithoutChangingAcceptedHistory() {
        val intake = PreciseLocationIntake()
        val valid = sample(10_000, 10_000)
        accepted(intake.evaluate(valid, 10_010, nanos(10_010)))
        for (invalid in listOf(valid.copy(latitude = Double.NaN), valid.copy(latitude = 90.1),
            valid.copy(longitude = Double.POSITIVE_INFINITY), valid.copy(longitude = -180.1))) {
            rejected(PreciseLocationRejection.INVALID_COORDINATES, intake.evaluate(invalid, 10_010, nanos(10_010)))
        }
        for (accuracy in listOf(Double.NaN, Double.POSITIVE_INFINITY, -1.0)) {
            rejected(PreciseLocationRejection.INVALID_HORIZONTAL_ACCURACY,
                intake.evaluate(valid.copy(horizontalAccuracyMeters = accuracy), 10_010, nanos(10_010)))
        }
        rejected(PreciseLocationRejection.INVALID_TIMESTAMP, intake.evaluate(valid.copy(timestampMs = 0), 10_010, nanos(10_010)))
        rejected(PreciseLocationRejection.INVALID_ELAPSED_REALTIME,
            intake.evaluate(valid.copy(elapsedRealtimeNanos = -1), 10_010, nanos(10_010)))
        rejected(PreciseLocationRejection.INVALID_ELAPSED_REALTIME, intake.evaluate(valid, 10_010, 0))
        accepted(intake.evaluate(sample(10_020, 10_020), 10_030, nanos(10_030)))
    }

    private fun sample(time: Long, elapsedMs: Long) = PreciseLocationSample(time, nanos(elapsedMs), 48.825095, 8.1269333, 5.0)
    private fun nanos(milliseconds: Long) = milliseconds * 1_000_000
    private fun position(timestamp: Long) = TrafficSignPositionSample(timestamp, 48.825095, 8.1269333, 90.0, 30.0)
    private fun accepted(result: PreciseLocationIntakeResult) = result as PreciseLocationIntakeResult.Accepted
    private fun rejected(reason: PreciseLocationRejection, result: PreciseLocationIntakeResult) {
        assertEquals(reason, (result as PreciseLocationIntakeResult.Rejected).reason)
    }
}
