package de.youspeed.android.alpha

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** Bundled Latin model, reused for the process lifetime; startup warm-up never publishes evidence. */
internal object AndroidTrafficSignSupplementaryOCR {
    private val executor = ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS, ArrayBlockingQueue(1),
        { task -> Thread(task, "supplementary-sign-ocr") })
    private val warming = AtomicBoolean(false)
    private val recognitionScheduled = AtomicBoolean(false)
    @Volatile private var recognizer: TextRecognizer? = null
    @Volatile var ready = false
        private set
    private fun client(): TextRecognizer = recognizer ?: TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        .also { recognizer = it }
    private val zoneReadInFlight = AtomicBoolean(false)
    private val zoneRecognizer by lazy { TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS) }

    /** Primary-panel proof, separate from supplementary text and its presentation. */
    fun verifiesZone(bitmap: Bitmap, candidate: TrafficSignCandidate): Boolean {
        if (!zoneReadInFlight.compareAndSet(false, true)) return false
        var launched = false
        return try { verifiesZonePanel(bitmap, candidate) { launched = true } }
        catch (_: Exception) { false }
        finally { if (!launched) zoneReadInFlight.set(false) }
    }

    private fun verifiesZonePanel(bitmap: Bitmap, candidate: TrafficSignCandidate, launched: () -> Unit): Boolean {
        if (candidate.semantic.kind != TrafficSignSemanticKind.ZONE_START) return false
        val speed = candidate.semantic.value ?: return false
        val box = candidate.boundingBox
        val x = kotlin.math.floor(box.x * bitmap.width).toInt()
        val y = kotlin.math.floor(box.y * bitmap.height).toInt()
        val width = kotlin.math.ceil(box.width * bitmap.width).toInt()
        val height = kotlin.math.ceil(box.height * bitmap.height).toInt()
        if (width < 48 || height < 48 || width.toLong()*height > 1_000_000 ||
            x+width > bitmap.width || y+height > bitmap.height) return false
        val region = Bitmap.createBitmap(bitmap, x, y, width, height)
        val crop = if (region === bitmap) bitmap.copy(Bitmap.Config.ARGB_8888, false) else region
        val task = try { zoneRecognizer.process(InputImage.fromBitmap(crop, 0)) }
        catch (_: Exception) { crop.recycle(); return false }
        launched()
        task.addOnCompleteListener(java.util.concurrent.Executor { it.run() }) { zoneReadInFlight.set(false) }
        try {
            val text = Tasks.await(task, 500, TimeUnit.MILLISECONDS).text
            return TSRLiveSignAdmission.verifiesZoneText(text, speed)
        } catch (_: Exception) { return false }
        finally {
            // A timed-out native read still owns its pixels until completion.
            if (task.isComplete) crop.recycle()
            else task.addOnCompleteListener(java.util.concurrent.Executor { it.run() }) { crop.recycle() }
        }
    }

    fun warmUp(context: Context, completion: (Boolean) -> Unit = {}) {
        if (ready) { completion(true); return }
        if (!warming.compareAndSet(false, true)) { completion(false); return }
        try { executor.execute {
            val bitmap = Bitmap.createBitmap(192, 64, Bitmap.Config.ARGB_8888).apply {
                eraseColor(Color.WHITE)
                Canvas(this).drawText("12-13 h", 8f, 46f,
                    Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.BLACK; textSize = 36f })
            }
            try {
                context.applicationContext
                Tasks.await(client().process(InputImage.fromBitmap(bitmap, 0)))
                TrafficSignOCRLanguageContext.warmUp()
                ready = true
            } catch (_: Exception) { ready = false }
            finally { bitmap.recycle(); warming.set(false); completion(ready) }
        } } catch (_: RuntimeException) { warming.set(false); completion(false) }
    }

    internal data class Read(val raw: String?, val rect: TrafficSignPlateRect? = null,
        val decision: String, val passes: List<TrafficSignOCRPass> = emptyList(), val failed: Boolean = false,
        val scan:TrafficSignPlateDetector.Scan?=null)

    /** Owns one admitted primary-plus-lower crop; only a separate lower plate reaches ML Kit. */
    fun recognize(bitmap: Bitmap, completion: (Read) -> Unit): Boolean {
        if (!recognitionScheduled.compareAndSet(false, true)) return false
        return try {
            executor.execute {
                val read = try { readPlate(bitmap) }
                    catch (_: Exception) { Read(null, decision = "engine_failure", failed = true) }
                finally { bitmap.recycle(); recognitionScheduled.set(false) }
                completion(read)
            }; true
        } catch (_: RuntimeException) { recognitionScheduled.set(false); false }
    }

    private fun pixels(bitmap: Bitmap): IntArray = IntArray(bitmap.width*bitmap.height).also {
        bitmap.getPixels(it, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
    }
    private fun readPlate(bitmap: Bitmap): Read {
        val scan=TrafficSignPlateDetector.scan(bitmap.width,bitmap.height,pixels(bitmap))
        val rect=scan.rect ?: return Read(null,decision=scan.decision,scan=scan)
        val plate = Bitmap.createBitmap(bitmap, rect.x, rect.y, rect.width, rect.height)
        try {
            if (TrafficSignPlateDetector.isPrimaryGraphic(plate.width, plate.height, pixels(plate)))
                return Read(null, rect, "primary_graphic",scan=scan)
            val platePixels = pixels(plate)
            fun pass(input: Bitmap, scale: Int): TrafficSignOCRPass {
                val result = Tasks.await(client().process(InputImage.fromBitmap(input, 0)))
                ready = true
                val lines = result.textBlocks.flatMap { it.lines }.sortedWith(compareBy({ it.boundingBox?.top ?: 0 }, { it.boundingBox?.left ?: 0 }))
                val rows = lines.flatMap { line -> line.boundingBox?.let { ((it.top/scale-2).coerceAtLeast(0)..(it.bottom/scale+2).coerceAtMost(plate.height-1)).toList() } ?: emptyList() }.toSet()
                return TrafficSignOCRPass(lines.joinToString("\n") { it.text },
                    lines.minOfOrNull { it.confidence.toDouble() } ?: 0.0, scale,
                    TrafficSignPlateDetector.hasUncoveredInk(plate.width, plate.height, platePixels, rows) ||
                        TrafficSignPlateDetector.hasUncoveredAssemblyInk(plate.width,plate.height,platePixels,rows,
                            scan.plates.map {TrafficSignPlateRect(it.x-rect.x,it.y-rect.y,it.width,it.height)}))
            }
            val passes = mutableListOf(pass(plate, 1))
            val scaled = Bitmap.createScaledBitmap(plate, plate.width*2, plate.height*2, true)
            try { passes += pass(scaled, 2) } finally { if (scaled !== plate) scaled.recycle() }
            val chosen = requireNotNull(TrafficSignOCRQuality.selected(passes)).text.ifBlank { passes.first().text }.ifBlank { null }
            val decision = TrafficSignOCRQuality.decision(passes, rect.width)
            if (decision == "accepted" && chosen != null) TrafficSignOCRLanguageContext.prepare(chosen)
            return Read(chosen, rect, decision, passes,scan=scan)
        } finally { if (plate !== bitmap) plate.recycle() }
    }

    /** Copy primary context before returning; the camera owns and recycles its source. */
    fun fromBitmap(bitmap: Bitmap, sourceContentRect:TrafficSignSupplementaryPixelRect=TrafficSignSupplementaryPixelRect(0,0,bitmap.width,bitmap.height)): TrafficSignSupplementaryTextRecognition = TrafficSignSupplementaryTextRecognition { request, completion ->
        val sourceWidth = bitmap.width; val sourceHeight = bitmap.height
        val context = supplementaryOCRContextPixelRect(request.candidate.boundingBox, sourceWidth, sourceHeight)
        if (context == null)
            completion(request.annotation(null, failed = true))
        else {
            val (x, y, w, h) = context
            val crop = try { Bitmap.createBitmap(bitmap, x, y, w, h) } catch (_: RuntimeException) { null }
            val owned = crop?.let { if (it === bitmap) it.copy(Bitmap.Config.ARGB_8888, false) else it }
            if (owned == null) completion(request.annotation(null, failed = true))
            else if (!recognize(owned) { read ->
                val roi = read.rect?.let { NormalizedTrafficSignBoundingBox((x+it.x).toDouble()/sourceWidth,
                    (y+it.y).toDouble()/sourceHeight, it.width.toDouble()/sourceWidth, it.height.toDouble()/sourceHeight) }
                val evidence=read.scan?.let {scan -> TrafficSignConditionalAssemblyEvidence(request.physicalSignId,request.frameId,request.observedAt,sourceWidth,sourceHeight,context,
                    request.candidate.boundingBox,scan.plates,scan.status,read.decision,scan.lowerLumaStd,scan.lowerEdgeFraction,
                    read.passes,request.otherPrimaryBoxes,sourceContentRect)}
                completion(request.annotation(read.raw, failed = read.failed, ocrBox = roi,
                    admitted = read.decision == "accepted", decision = read.decision, passes = read.passes,assemblyEvidence=evidence))
            }) { owned.recycle(); completion(request.annotation(null, failed = true)) }
        }
    }
}
