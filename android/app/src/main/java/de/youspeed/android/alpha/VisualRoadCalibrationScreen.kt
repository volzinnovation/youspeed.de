package de.youspeed.android.alpha

import android.graphics.Bitmap
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

internal data class VisualRoadCalibrationPreview(val bitmap: Bitmap, val sourceWidth: Int, val sourceHeight: Int,
    val orientationKey: String, val receivedAtMs: Long)

@Composable
internal fun VisualRoadCalibrationScreen(controller: ConsumerSessionController) {
    BackHandler { controller.endVisualCalibration() }
    val preview = controller.calibrationPreview
    val geometry = preview?.let { "${it.sourceWidth}:${it.sourceHeight}:${it.orientationKey}" }
    var draft by remember(geometry) { mutableStateOf(preview?.let { p ->
        controller.visualRoadCalibration?.takeIf { it.compatible(p.sourceWidth, p.sourceHeight, p.orientationKey) }
            ?: VisualRoadCalibration.defaults(p.sourceWidth, p.sourceHeight, p.orientationKey)
    }) }
    var index by remember(geometry) { mutableIntStateOf(0) }
    var saveFailed by remember { mutableStateOf(false) }
    val step = VisualRoadCalibrationStep.entries[index]
    val titles = listOf(R.string.calibration_horizon, R.string.calibration_left_lower, R.string.calibration_left_upper,
        R.string.calibration_right_lower, R.string.calibration_right_upper)
    val hints = listOf(R.string.calibration_horizon_hint, R.string.calibration_lower_hint, R.string.calibration_upper_hint,
        R.string.calibration_lower_hint, R.string.calibration_upper_hint)
    val video: @Composable (Modifier) -> Unit = { modifier ->
        Box(modifier.background(Color.Black), contentAlignment = Alignment.Center) {
            if (preview == null) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator()
                    Text(controller.uiState.trafficSignCameraRuntimeDetail, color = Color.White, modifier = Modifier.padding(16.dp))
                }
            } else {
                Image(preview.bitmap.asImageBitmap(), contentDescription = stringResource(R.string.calibration_live_video),
                    contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize().testTag("calibration-live-frame"))
                val reference = draft
                if (reference != null) Canvas(Modifier.fillMaxSize().testTag("calibration-guides")) {
                    val factor = minOf(size.width / reference.imageWidth, size.height / reference.imageHeight)
                    val width = reference.imageWidth * factor; val height = reference.imageHeight * factor
                    val left = (size.width - width) / 2; val top = (size.height - height) / 2
                    fun point(p: LanePoint) = Offset(left + p.x.toFloat() * width, top + p.y.toFloat() * height)
                    fun line(a: LanePoint, b: LanePoint, color: Color) {
                        drawLine(Color.Black, point(a), point(b), 6.dp.toPx())
                        drawLine(color, point(a), point(b), 3.dp.toPx())
                    }
                    val green = Color(0xFF39FF14)
                    line(LanePoint(0.0,reference.horizonY),LanePoint(1.0,reference.horizonY),
                        if (step == VisualRoadCalibrationStep.HORIZON) Color.Yellow else Color.White)
                    line(reference.leftTop,reference.leftBottom,green)
                    line(reference.rightTop,reference.rightBottom,green)
                    drawLine(Color.White.copy(alpha = .8f), point(LanePoint(reference.leftTopX,0.0)),
                        point(LanePoint(reference.leftTopX,1.0)),1.dp.toPx(),
                        pathEffect=PathEffect.dashPathEffect(floatArrayOf(5.dp.toPx(),5.dp.toPx())))
                    val selected = when(step) {
                        VisualRoadCalibrationStep.HORIZON -> LanePoint(0.5, reference.horizonY)
                        VisualRoadCalibrationStep.LEFT_BOTTOM -> reference.leftBottom
                        VisualRoadCalibrationStep.LEFT_TOP -> reference.leftTop
                        VisualRoadCalibrationStep.RIGHT_BOTTOM -> reference.rightBottom
                        VisualRoadCalibrationStep.RIGHT_TOP -> reference.rightTop
                    }
                    for (p in listOf(reference.leftTop,reference.leftBottom,reference.rightTop,reference.rightBottom)) {
                        drawCircle(Color.Black,7.dp.toPx(),point(p));drawCircle(green,5.dp.toPx(),point(p))
                    }
                    drawCircle(Color.Black,11.dp.toPx(),point(selected));drawCircle(Color.Yellow,8.dp.toPx(),point(selected))
                }
            }
        }
    }
    val controls: @Composable (Modifier) -> Unit = { modifier ->
        Column(modifier.verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.calibration_step, index+1),color=Color.White,fontSize=13.sp)
            Text(stringResource(titles[index]),color=Color.White,fontSize=20.sp)
            Text(stringResource(hints[index]),color=Color.White,fontSize=14.sp)
            val lower = step == VisualRoadCalibrationStep.LEFT_BOTTOM || step == VisualRoadCalibrationStep.RIGHT_BOTTOM
            val leftLabel = stringResource(R.string.calibration_left)
            val rightLabel = stringResource(R.string.calibration_right)
            val upLabel = stringResource(R.string.calibration_up)
            val downLabel = stringResource(R.string.calibration_down)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                fun adjust(dx: Int, dy: Int) { draft = draft?.adjust(step,dx,dy); saveFailed=false }
                if (step != VisualRoadCalibrationStep.HORIZON) {
                    OutlinedButton(onClick={adjust(-1,0)},enabled=draft!=null,modifier=Modifier.testTag("calibration-left").semantics { contentDescription=leftLabel }) { Text("←",fontSize=24.sp) }
                    OutlinedButton(onClick={adjust(1,0)},enabled=draft!=null,modifier=Modifier.testTag("calibration-right").semantics { contentDescription=rightLabel }) { Text("→",fontSize=24.sp) }
                }
                if (lower || step == VisualRoadCalibrationStep.HORIZON) {
                    OutlinedButton(onClick={adjust(0,-1)},enabled=draft!=null,modifier=Modifier.testTag("calibration-up").semantics { contentDescription=upLabel }) { Text("↑",fontSize=24.sp) }
                    OutlinedButton(onClick={adjust(0,1)},enabled=draft!=null,modifier=Modifier.testTag("calibration-down").semantics { contentDescription=downLabel }) { Text("↓",fontSize=24.sp) }
                }
            }
            if (saveFailed || (index == 4 && draft?.isValid == false)) Text(stringResource(R.string.calibration_invalid),color=Color.Yellow,fontSize=13.sp)
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                TextButton(onClick={if(index>0)index-- else controller.endVisualCalibration()},modifier=Modifier.testTag("calibration-back")) {
                    Text(stringResource(if(index>0)R.string.calibration_back else R.string.calibration_cancel))
                }
                Button(onClick={
                    if(index<4)index++ else { saveFailed = draft?.let { !controller.saveVisualCalibration(it) } ?: true }
                },enabled=draft!=null && (index<4 || draft?.isValid==true),modifier=Modifier.testTag("calibration-next")) {
                    Text(stringResource(if(index==4)R.string.calibration_save else R.string.calibration_next))
                }
            }
            if(index>0) TextButton(onClick=controller::endVisualCalibration,modifier=Modifier.testTag("calibration-cancel")) {
                Text(stringResource(R.string.calibration_cancel))
            }
            TextButton(onClick={preview?.let { draft=VisualRoadCalibration.defaults(it.sourceWidth,it.sourceHeight,it.orientationKey);index=0;saveFailed=false }},
                enabled=preview!=null,modifier=Modifier.testTag("calibration-defaults")) { Text(stringResource(R.string.calibration_defaults)) }
        }
    }
    Surface(Modifier.fillMaxSize().testTag("visual-road-calibration"),color=Color(0xFF101419)) {
        BoxWithConstraints(Modifier.fillMaxSize().safeDrawingPadding()) {
            if(maxWidth>maxHeight) Row(Modifier.fillMaxSize()) {
                video(Modifier.weight(1f).fillMaxHeight())
                controls(Modifier.width(320.dp).fillMaxHeight())
            } else Column(Modifier.fillMaxSize()) {
                video(Modifier.weight(1f).fillMaxWidth())
                controls(Modifier.fillMaxWidth())
            }
        }
    }
}
