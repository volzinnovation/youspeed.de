package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class DriveEvidencePresentationTests {
    @Test fun mobiDataContourRequiresExactProviderAndInventoryOrigin() {
        for (kind in listOf("inventory_sign", "inventory_town_context", "inventory_reset_context")) {
            val origin = BundleSpeedProvenance(kind, sourceId = "mobidata-bw-vzk")
            assertTrue(MobiDataSignSourcePresentation.showsLimitContour(EffectiveSpeedLimitSource.BUNDLE, true, origin, false, false, false))
            for (other in listOf(null, "", "osm-settlement", "actual-source", "mobidata-bw-vzk-copy")) {
                assertFalse(MobiDataSignSourcePresentation.isMobiData(other))
                assertFalse(MobiDataSignSourcePresentation.showsLimitContour(EffectiveSpeedLimitSource.BUNDLE, true,
                    origin.copy(sourceId = other), false, false, false))
            }
        }
        for (kind in listOf("osm_tag", "road_default", "unknown")) assertFalse(
            MobiDataSignSourcePresentation.showsLimitContour(EffectiveSpeedLimitSource.BUNDLE, true,
                BundleSpeedProvenance(kind, sourceId = "mobidata-bw-vzk"), false, false, false))
        assertFalse(MobiDataSignSourcePresentation.showsLimitContour(EffectiveSpeedLimitSource.BUNDLE, true, null, false, false, false))
    }
    @Test fun cameraOverridesStaleValuesAndTransientScreensCannotRetainMobiDataContour() {
        val origin = BundleSpeedProvenance("inventory_sign", sourceId = "mobidata-bw-vzk")
        for (source in EffectiveSpeedLimitSource.entries.filter { it != EffectiveSpeedLimitSource.BUNDLE }) {
            assertFalse(source.name, MobiDataSignSourcePresentation.showsLimitContour(source, true, origin, false, false, false))
        }
        for (flags in listOf(listOf(false,false,false,false), listOf(true,true,false,false),
            listOf(true,false,true,false), listOf(true,false,false,true))) {
            assertFalse(MobiDataSignSourcePresentation.showsLimitContour(EffectiveSpeedLimitSource.BUNDLE,
                flags[0], origin, flags[1], flags[2], flags[3]))
        }
        assertTrue(CameraSpeedLimitUsePresentation.isVisible(false, EffectiveSpeedLimitSource.CAMERA, true))
    }
    @Test fun secondarySurvivesCameraAndGpsGapsButResetsWithDriveOrBundle() {
        for (reason in listOf("application_lifecycle","independent_recognition_changed","recognition_unavailable","tsr_enabled","tsr_disabled","night_paused","route_changed"))
            assertTrue(reason,DriveEvidencePresentation.retainSecondary(reason))
        for (reason in listOf("drive_started","drive_stopped","bundle_country_switch","bundle_removed"))
            assertFalse(reason,DriveEvidencePresentation.retainSecondary(reason))
    }
    @Test fun selectedRecognitionAtNightIsPausedEvenWithActivePhotoCamera() {
        assertEquals(TrafficSignRuntimeStatus.PAUSED_NIGHT,DriveEvidencePresentation.recognitionStatus(
            true,false,true,true,TrafficSignCameraRuntimeState.ACTIVE))
        assertEquals(TrafficSignRuntimeStatus.WAITING_LOCATION,DriveEvidencePresentation.recognitionStatus(
            true,false,false,true,TrafficSignCameraRuntimeState.ACTIVE))
    }
    @Test fun disabledSessionUnavailableAndActiveStayDistinct() {
        assertEquals(TrafficSignRuntimeStatus.DISABLED,DriveEvidencePresentation.recognitionStatus(false,true,true,true,TrafficSignCameraRuntimeState.ACTIVE))
        assertEquals(TrafficSignRuntimeStatus.PAUSED_SESSION,DriveEvidencePresentation.recognitionStatus(true,true,true,false,TrafficSignCameraRuntimeState.ACTIVE))
        assertEquals(TrafficSignRuntimeStatus.UNAVAILABLE,DriveEvidencePresentation.recognitionStatus(true,true,true,true,TrafficSignCameraRuntimeState.DENIED))
        assertEquals(TrafficSignRuntimeStatus.WAITING_CAMERA,DriveEvidencePresentation.recognitionStatus(true,true,true,true,TrafficSignCameraRuntimeState.STARTING))
        assertEquals(TrafficSignRuntimeStatus.ACTIVE,DriveEvidencePresentation.recognitionStatus(true,true,true,true,TrafficSignCameraRuntimeState.ACTIVE))
    }
    @Test fun cameraLocalAndStaleAuthorityOverrideRetainedInventoryOrigin() {
        val origin=BundleSpeedProvenance("inventory_sign",sourceId="mobidata-bw-vzk",signId="one")
        assertEquals("camera",DriveEvidencePresentation.sourceKind(EffectiveSpeedLimitSource.CAMERA,true,origin))
        assertEquals("local_correction",DriveEvidencePresentation.sourceKind(EffectiveSpeedLimitSource.LOCAL_CORRECTION,true,origin))
        assertEquals("stale_bundle",DriveEvidencePresentation.sourceKind(EffectiveSpeedLimitSource.STALE_BUNDLE,true,origin))
        assertEquals("last_known",DriveEvidencePresentation.sourceKind(EffectiveSpeedLimitSource.LAST_KNOWN,true,origin))
        assertEquals("unknown",DriveEvidencePresentation.sourceKind(EffectiveSpeedLimitSource.BUNDLE,false,origin))
        assertEquals("inventory_sign",DriveEvidencePresentation.sourceKind(EffectiveSpeedLimitSource.BUNDLE,true,origin))
    }
    @Test fun oldBundlesAndUnknownEvidenceDoNotAcquireInventoryIdentity() {
        assertEquals("bundle",DriveEvidencePresentation.sourceKind(EffectiveSpeedLimitSource.BUNDLE,true,null))
        val osm=DriveEvidencePresentation.mapProvenance(DerivedSpeedSource.EXPLICIT_TAG,"42",TrafficSignTravelDirection.REVERSE)
        assertEquals("osm_tag",osm?.kind);assertEquals(-1,osm?.direction);assertNull(osm?.sourceId);assertNull(osm?.signId)
        assertEquals("road_default",DriveEvidencePresentation.mapProvenance(DerivedSpeedSource.HIGHWAY_CLASS,"42",TrafficSignTravelDirection.UNKNOWN)?.kind)
        assertNull(DriveEvidencePresentation.mapProvenance(DerivedSpeedSource.DIRECTIONAL_UNRESOLVED,"42",TrafficSignTravelDirection.UNKNOWN))
    }
    @Test fun unknownLatchedOriginNeverInventsAProviderOrSign() {
        val context=DriveEvidencePresentation.inventoryProvenance("inventory_town_context",null)
        assertEquals("inventory_town_context",context.kind);assertNull(context.sourceId);assertNull(context.signId);assertNull(context.snapshotSha256)
    }
}
