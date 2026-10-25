package de.youspeed.android.alpha

import kotlin.math.ceil
import kotlin.math.floor

/** Native pixel measurements made by the same owned-frame scan and OCR read.
 * No caller-supplied "verified" switch grants runtime authority. */
class TrafficSignConditionalAssemblyEvidence internal constructor(
    internal val physicalSignId:String,
    internal val sourceFrameId:String,
    internal val capturedAt:java.time.Instant,
    internal val sourceWidth:Int,
    internal val sourceHeight:Int,
    internal val contextRect:TrafficSignSupplementaryPixelRect,
    internal val primaryBox:NormalizedTrafficSignBoundingBox,
    internal val plateRects:List<TrafficSignPlateRect>,
    internal val scanStatus:String,
    internal val decision:String,
    internal val lowerLumaStd:Double,
    internal val lowerEdgeFraction:Double,
    internal val passes:List<TrafficSignOCRPass>,
    internal val otherPrimaryBoxes:List<NormalizedTrafficSignBoundingBox>,
    internal val sourceContentRect:TrafficSignSupplementaryPixelRect=TrafficSignSupplementaryPixelRect(0,0,sourceWidth,sourceHeight),
    internal val backgroundVerified:Boolean=false,
) {
    val revision="live-assembly-pixels-v1"
    internal enum class Kind { PLAIN, CONDITIONAL, UNRESOLVED }
    internal data class Validation(val kind:Kind,val reason:String,val plateCount:Int=0)
    internal fun validate(box:NormalizedTrafficSignBoundingBox,rawText:String?,frameId:String=sourceFrameId,at:java.time.Instant=capturedAt,parentId:String=physicalSignId):Validation {
        fun unknown(reason:String)=Validation(Kind.UNRESOLVED,reason)
        if(parentId!=physicalSignId || frameId!=sourceFrameId || at!=capturedAt || sourceWidth<=0 || sourceHeight<=0 || primaryBox!=box ||
            supplementaryOCRContextPixelRect(box,sourceWidth,sourceHeight)!=contextRect) return unknown("context_provenance_mismatch")
        val pLeft=floor(box.x*sourceWidth).toInt();val pTop=floor(box.y*sourceHeight).toInt()
        val pWidth=ceil(box.width*sourceWidth).toInt();val pHeight=ceil(box.height*sourceHeight).toInt()
        val content=sourceContentRect
        if(content.x<0 || content.y<0 || content.x+content.width>sourceWidth || content.y+content.height>sourceHeight ||
            pLeft<content.x+2 || pTop<content.y+2 || pLeft+pWidth>content.x+content.width-2 || pTop+pHeight>content.y+content.height-2 ||
            contextRect.x<content.x || contextRect.y<content.y || contextRect.x+contextRect.width>content.x+content.width ||
            contextRect.y+contextRect.height>content.y+content.height-2) return unknown("context_outside_native_pixels")
        if(pLeft<2 || pTop<2 || pLeft+pWidth>sourceWidth-2 || pTop+pHeight>sourceHeight-2 ||
            contextRect.y+contextRect.height>sourceHeight-2 || contextRect.width<48 || contextRect.height<64) return unknown("truncated_parent_or_context")
        val lowerTop=box.y+box.height;val contextRight=(contextRect.x+contextRect.width).toDouble()/sourceWidth
        val contextBottom=(contextRect.y+contextRect.height).toDouble()/sourceHeight
        if(otherPrimaryBoxes.any {it.x<contextRight && it.x+it.width>box.x && it.y<contextBottom && it.y+it.height>lowerTop})
            return unknown("another_primary_in_lower_context")
        if(scanStatus=="plain") {
            val quiet=decision=="quiet_lower_context" && lowerLumaStd.isFinite() && lowerLumaStd in 0.0..18.0 && lowerEdgeFraction.isFinite() && lowerEdgeFraction in 0.0..0.015
            val background=decision=="natural_background_without_panel" && backgroundVerified && contextRect.width>=80 && contextRect.height>=128
            return if(plateRects.isEmpty() && rawText.isNullOrBlank() && (quiet || background))
                Validation(Kind.PLAIN,"measured_clear_lower_region") else unknown("plain_pixels_not_proven")
        }
        if(scanStatus!="complete" || plateRects.isEmpty() || plateRects.size>3) return unknown("assembly_scan_unresolved")
        if(plateRects.any {it.x<2 || it.y<contextRect.height/2 || it.width<48 || it.height<32 ||
                it.x+it.width>contextRect.width-2 || it.y+it.height>contextRect.height-2}) return unknown("small_or_truncated_plate")
        val ordered=plateRects.sortedBy {it.y}
        if(ordered.zipWithNext().any {(a,b)->b.y<a.y+a.height ||
                minOf(a.x+a.width,b.x+b.width)-maxOf(a.x,b.x)<.8*minOf(a.width,b.width)}) return unknown("ambiguous_plate_association")
        val plateTop=(contextRect.y+plateRects.minOf {it.y}).toDouble()/sourceHeight
        val plateLeft=(contextRect.x+plateRects.minOf {it.x}).toDouble()/sourceWidth
        val plateRight=(contextRect.x+plateRects.maxOf {it.x+it.width}).toDouble()/sourceWidth
        val ownGap=plateTop-(box.y+box.height)
        if(otherPrimaryBoxes.any {other ->
            val gap=plateTop-(other.y+other.height)
            val overlap=minOf(other.x+other.width,plateRight)-maxOf(other.x,plateLeft)
            gap>=-.03 && gap<=.18 && gap<=ownGap+.03 && overlap>=.25*minOf(other.width,plateRight-plateLeft)
        }) return unknown("ambiguous_parent_association")
        val unionWidth=plateRects.maxOf {it.x+it.width}-plateRects.minOf {it.x}
        if(decision!="accepted" || TrafficSignOCRQuality.decision(passes,unionWidth)!="accepted" ||
            passes.map {it.scale}.toSet().containsAll(setOf(1,2)).not() ||
            rawText.isNullOrBlank() || TrafficSignOCRQuality.selected(passes)?.text?.trim()!=rawText.trim()) return unknown("full_plate_read_not_accepted")
        return Validation(Kind.CONDITIONAL,"complete_native_assembly_read",plateRects.size)
    }
}
