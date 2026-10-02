package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import kotlin.math.abs

/** User's image-space mounting reference; it does not assert metric calibration or a detected road. */
data class VisualRoadCalibration(
    val revision: String,
    val imageWidth: Int,
    val imageHeight: Int,
    val orientationKey: String,
    val horizonY: Double,
    val leftBottom: LanePoint,
    val leftTopX: Double,
    val rightBottom: LanePoint,
    val rightTopX: Double,
) {
    val leftTop get() = LanePoint(leftTopX, horizonY)
    val rightTop get() = LanePoint(rightTopX, horizonY)
    val isValid: Boolean get() = revision.isNotBlank() && imageWidth > 0 && imageHeight > 0 &&
        orientationKey.isNotBlank() && listOf(horizonY, leftBottom.x, leftBottom.y, leftTopX,
            rightBottom.x, rightBottom.y, rightTopX).all { it.isFinite() && it in 0.0..1.0 } &&
        horizonY in 0.05..0.80 && leftBottom.y >= horizonY + 0.05 && rightBottom.y >= horizonY + 0.05 &&
        leftBottom.x + 0.02 < rightBottom.x && leftTopX <= rightTopX && leftTopX <= 0.95

    fun compatible(width: Int, height: Int, orientationKey: String): Boolean = isValid && width > 0 && height > 0 &&
        this.orientationKey == orientationKey && abs(width.toDouble() / height - imageWidth.toDouble() / imageHeight) < 0.015

    /** Actual pixel-aligned ROI. Only its left edge is user-defined; all other edges stay full-frame. */
    fun cropLeftPixels(width: Int): Int = (leftTopX * width).toInt().coerceIn(0, (width - 1).coerceAtLeast(0))

    fun fullFrameBox(box: NormalizedTrafficSignBoundingBox, sourceWidth: Int): NormalizedTrafficSignBoundingBox {
        require(sourceWidth > 0)
        val left = cropLeftPixels(sourceWidth).toDouble() / sourceWidth
        val scale = 1.0 - left
        return NormalizedTrafficSignBoundingBox(left + box.x * scale, box.y, box.width * scale, box.height)
    }

    fun encode(): String = buildJsonObject {
        put("schemaVersion", 1); put("revision", revision); put("imageWidth", imageWidth); put("imageHeight", imageHeight)
        put("orientationKey", orientationKey); put("horizonY", horizonY)
        put("leftTopX", leftTopX); put("rightTopX", rightTopX)
        putJsonObject("leftBottom") { put("x", leftBottom.x); put("y", leftBottom.y) }
        putJsonObject("rightBottom") { put("x", rightBottom.x); put("y", rightBottom.y) }
    }.toString()

    companion object {
        const val PREFERENCE_KEY = "youspeed.visual_road_calibration.v1"
        fun defaults(width: Int, height: Int, orientationKey: String) = VisualRoadCalibration(
            "draft", width, height, orientationKey, 0.42, LanePoint(0.0, 1.0), 0.46, LanePoint(1.0, 1.0), 0.54)
        fun decode(text: String?): VisualRoadCalibration? = runCatching {
            val o = Json.parseToJsonElement(requireNotNull(text)).jsonObject
            require(o.getValue("schemaVersion").jsonPrimitive.int == 1)
            fun number(key: String) = o.getValue(key).jsonPrimitive.double
            fun point(key: String) = o.getValue(key).jsonObject.let {
                LanePoint(it.getValue("x").jsonPrimitive.double, it.getValue("y").jsonPrimitive.double)
            }
            VisualRoadCalibration(o.getValue("revision").jsonPrimitive.content,
                o.getValue("imageWidth").jsonPrimitive.int, o.getValue("imageHeight").jsonPrimitive.int,
                o.getValue("orientationKey").jsonPrimitive.content, number("horizonY"), point("leftBottom"),
                number("leftTopX"), point("rightBottom"), number("rightTopX")).takeIf { it.isValid }
        }.getOrNull()
    }
}

enum class VisualRoadCalibrationStep { HORIZON, LEFT_BOTTOM, LEFT_TOP, RIGHT_BOTTOM, RIGHT_TOP }

/** Pure edit operations shared with the five-step screen; upper points always stay on the horizon. */
fun VisualRoadCalibration.adjust(step: VisualRoadCalibrationStep, dx: Int, dy: Int): VisualRoadCalibration {
    val amount = 0.005
    fun point(p: LanePoint) = LanePoint((p.x + dx * amount).coerceIn(0.0, 1.0),
        (p.y + dy * amount).coerceIn(horizonY + 0.05, 1.0))
    return when (step) {
        VisualRoadCalibrationStep.HORIZON -> copy(horizonY = (horizonY + dy * amount)
            .coerceIn(0.05, minOf(0.80, leftBottom.y - 0.05, rightBottom.y - 0.05)))
        VisualRoadCalibrationStep.LEFT_BOTTOM -> copy(leftBottom = point(leftBottom))
        VisualRoadCalibrationStep.LEFT_TOP -> copy(leftTopX = (leftTopX + dx * amount).coerceIn(0.0, 0.95))
        VisualRoadCalibrationStep.RIGHT_BOTTOM -> copy(rightBottom = point(rightBottom))
        VisualRoadCalibrationStep.RIGHT_TOP -> copy(rightTopX = (rightTopX + dx * amount).coerceIn(0.0, 1.0))
    }
}

/** Preview-only guide trust, verified using fresh paint on independent broad audit frames. */
data class RoadVisualGuideTrustSnapshot(val state: String, val reason: String, val independentAudit: Boolean,
    val matchedSides: Int, val agreementCount: Int, val leftResidual: Double?, val rightResidual: Double?) {
    val diagnosticJson get() = buildJsonObject {
        put("state",state); put("reason",reason); put("independentAudit",independentAudit)
        put("matchedSides",matchedSides); put("agreementCount",agreementCount)
        leftResidual?.let { put("leftResidual",it) }; rightResidual?.let { put("rightResidual",it) }
    }
}
data class RoadVisualGuidePlan(val independentAudit: Boolean, val trusted: Boolean, val reason: String)
class RoadVisualGuideValidator {
    private var key: String? = null
    private var count=0; private var agreements=0
    private var firstAgreement: Double?=null; private var lastAgreement: Double?=null
    private var trusted=false
    private var reason="awaiting_independent_paint"
    var snapshot=RoadVisualGuideTrustSnapshot("unavailable","no_saved_guides",true,0,0,null,null)
        private set
    fun begin(saved: VisualRoadCalibration?, compatible: VisualRoadCalibration?, time: Double, key: String): RoadVisualGuidePlan {
        if(this.key != key) { this.key=key; count=0; agreements=0; firstAgreement=null; lastAgreement=null; trusted=false; reason="awaiting_independent_paint" }
        count++
        if(compatible == null) {
            trusted=false; agreements=0; firstAgreement=null; lastAgreement=null
            reason=if(saved == null) "no_saved_guides" else "incompatible_geometry"
        } else if(lastAgreement?.let { time-it > 1.0 } == true) {
            trusted=false; agreements=0; firstAgreement=null; reason="independent_evidence_expired"
        }
        // Weak guides never affect horizon/projection/ego centre. Broad audits avoid self-confirmation.
        val audit=saved != null && (compatible == null || if(trusted) count%5 == 0 else count%2 == 1)
        return RoadVisualGuidePlan(audit,trusted,reason)
    }
    fun observe(boundaries: List<RoadBoundaryEvidence>, visual: VisualRoadCalibration?, time: Double,
        plan: RoadVisualGuidePlan): RoadVisualGuideTrustSnapshot {
        val residuals=arrayOfNulls<Double>(2)
        var matched=0
        if(plan.independentAudit && visual != null) {
            val candidates=boundaries.filter { it.provenance == RoadBoundaryProvenance.FRESH && it.cue == RoadBoundaryCue.PAINT &&
                it.confidence >= .6 && it.points.size >= 2 && it.points.last().y-it.points.first().y >= .12 }
            for(side in 0..1) {
                val observed=candidates.filter { if(side == 0) it.points.last().x < .5 else it.points.last().x > .5 }
                    .minByOrNull { abs(it.points.last().x-.5) } ?: continue
                val guide=listOf(LanePoint(if(side == 0) visual.leftTopX else visual.rightTopX,visual.horizonY),
                    if(side == 0) visual.leftBottom else visual.rightBottom)
                val low=maxOf(observed.points.first().y,guide[0].y); val high=minOf(observed.points.last().y,guide[1].y)
                if(high-low < .10) continue
                val errors=(0..2).map { i ->
                    val y=low+(high-low)*i/2
                    abs(roadBoundaryXAt(observed.points,y)-roadBoundaryXAt(guide,y))
                }.sorted()
                residuals[side]=errors[1]
                if(errors[1] <= .055 && errors[2] <= .085) matched++
            }
            if(residuals.filterNotNull().any { it > .10 }) {
                trusted=false; agreements=0; firstAgreement=null; lastAgreement=null; reason="observed_border_conflict"
            } else if(matched == 2) {
                if(firstAgreement == null) firstAgreement=time
                agreements++; lastAgreement=time
                trusted=agreements >= 3 && time-(firstAgreement ?: time) >= .2
                reason=if(trusted) "independent_paint_agreement" else "confirming_independent_paint"
            } else {
                agreements=0; firstAgreement=null
                if(!trusted) reason="insufficient_independent_paint"
            }
        }
        snapshot=RoadVisualGuideTrustSnapshot(if(visual == null) "unavailable" else if(trusted) "trusted" else "weak",reason,
            plan.independentAudit,matched,agreements,residuals[0],residuals[1])
        return snapshot
    }
}
