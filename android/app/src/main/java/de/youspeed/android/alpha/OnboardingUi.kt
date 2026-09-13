package de.youspeed.android.alpha

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.BiasAlignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

private val SetupRed = Color(0xFFD21B24)
private val SetupMuted = Color(0xFFB9B9C0)

/** Stateless surface: granting permission, downloading and capture stay explicit controller actions. */
@Composable
internal fun OnboardingScreen(
    ui: ConsumerUiState,
    hasUsableMap: Boolean,
    isSyncing: Boolean,
    onNext: () -> Unit,
    onBack: () -> Unit,
    onUseLocation: () -> Unit,
    onOpenLocationSettings: () -> Unit,
    onSelectMap: (String) -> Unit,
    onDownloadMap: () -> Unit,
    onAudioEnabled: (Boolean) -> Unit,
    onAudioThreshold: (Int) -> Unit,
    onRecognitionEnabled: (Boolean) -> Unit,
    onIndependentRecognitionEnabled: (Boolean) -> Unit,
    onPanoramaxEnabled: (Boolean) -> Unit,
) {
    val step = OnboardingPolicy.resumedStep(ui.onboardingStep, hasUsableMap)
    val decreaseThreshold = stringResource(R.string.onboarding_threshold_decrease_label)
    val increaseThreshold = stringResource(R.string.onboarding_threshold_increase_label)
    val title = when (step) {
        0 -> R.string.onboarding_map_title
        1 -> R.string.onboarding_driving_title
        2 -> R.string.onboarding_dashcam_title
        3 -> R.string.onboarding_sources_title
        else -> R.string.onboarding_panoramax_title
    }
    val icon = when (step) {
        0 -> Icons.Default.LocationOn
        1 -> Icons.Default.Settings
        2 -> Icons.Default.CameraAlt
        3 -> Icons.Default.CheckCircle
        else -> Icons.Default.PhotoLibrary
    }
    Column(
        Modifier.fillMaxSize().background(Color.Black).safeDrawingPadding()
            .testTag("onboarding-root").padding(horizontal = 24.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(Modifier.widthIn(max = 560.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween) {
                Text("YouSpeed", color = Color.White, fontSize = 25.sp, fontWeight = FontWeight.Bold)
                Text(stringResource(R.string.onboarding_step, step + 1), color = SetupMuted,
                    fontSize = 14.sp, modifier = Modifier.testTag("onboarding-step"))
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                repeat(5) { index ->
                    Box(Modifier.weight(1f).height(3.dp).background(if (index <= step) SetupRed else Color(0xFF303036)))
                }
            }
        }
        key(step) {
            Column(
                Modifier.weight(1f).widthIn(max = 560.dp).fillMaxWidth()
                    .verticalScroll(rememberScrollState()).testTag("onboarding-content").padding(vertical = 24.dp),
                verticalArrangement = Arrangement.spacedBy(20.dp),
            ) {
                Icon(icon, contentDescription = null, tint = SetupRed, modifier = Modifier.size(40.dp))
                Text(stringResource(title), color = Color.White, fontSize = 32.sp, lineHeight = 36.sp,
                    fontWeight = FontWeight.Bold, modifier = Modifier.testTag("onboarding-title"))
                when (step) {
                    0 -> OnboardingMap(ui, hasUsableMap, isSyncing, onUseLocation, onSelectMap, onDownloadMap)
                    1 -> {
                        SetupBody(R.string.onboarding_driving_body)
                        if (ui.preciseLocationGranted) {
                            Text(stringResource(R.string.onboarding_location_ready), color = Color(0xFF8CE5A8),
                                modifier = Modifier.testTag("onboarding-location-ready"))
                        } else {
                            SetupAction(R.string.onboarding_allow_location, "onboarding-use-location-button", onUseLocation)
                            if (ui.onboardingLocationRequested) {
                                SetupBody(R.string.onboarding_location_denied)
                                OutlinedButton(onClick = onOpenLocationSettings,
                                    modifier = Modifier.testTag("onboarding-location-settings-button")) {
                                    Text(stringResource(R.string.onboarding_open_settings), color = Color.White)
                                }
                            }
                        }
                        SetupToggle(R.string.onboarding_audio, ui.audioAlertsEnabled, onAudioEnabled, "onboarding-audio-toggle")
                        SetupBody(R.string.onboarding_audio_body)
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            OutlinedButton(onClick = { onAudioThreshold((ui.audioAlertThresholdKmh - 1).coerceAtLeast(0)) },
                                enabled = ui.audioAlertsEnabled && ui.audioAlertThresholdKmh > 0,
                                modifier = Modifier.testTag("onboarding-threshold-decrease").semantics { contentDescription = decreaseThreshold }) { Text("−", color = Color.White) }
                            Text(stringResource(R.string.onboarding_threshold, ui.audioAlertThresholdKmh),
                                color = Color.White, modifier = Modifier.weight(1f))
                            OutlinedButton(onClick = { onAudioThreshold((ui.audioAlertThresholdKmh + 1).coerceAtMost(80)) },
                                enabled = ui.audioAlertsEnabled && ui.audioAlertThresholdKmh < 80,
                                modifier = Modifier.testTag("onboarding-threshold-increase").semantics { contentDescription = increaseThreshold }) { Text("+", color = Color.White) }
                        }
                    }
                    2 -> {
                        SetupBody(R.string.onboarding_dashcam_body)
                        SetupScreenshot(R.drawable.onboarding_video_library, R.string.onboarding_video_screenshot)
                        SetupInfo(R.string.onboarding_dashcam_control_title, R.string.onboarding_dashcam_control_body)
                        SetupInfo(R.string.onboarding_dashcam_library_title, R.string.onboarding_dashcam_library_body)
                        SetupInfo(R.string.onboarding_dashcam_permission_title, R.string.onboarding_dashcam_permission_body)
                    }
                    3 -> {
                        SetupBody(R.string.onboarding_sources_body)
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            SetupScreenshot(R.drawable.onboarding_limit_map, R.string.onboarding_normal_limit_caption, Modifier.weight(1f))
                            SetupScreenshot(R.drawable.onboarding_limit_camera, R.string.onboarding_camera_limit_caption, Modifier.weight(1f))
                        }
                        SetupInfo(R.string.onboarding_source_map_title, R.string.onboarding_source_map_body)
                        SetupInfo(R.string.onboarding_source_correction_title, R.string.onboarding_source_correction_body)
                        SetupInfo(R.string.onboarding_source_camera_title, R.string.onboarding_source_camera_body)
                        SetupToggle(R.string.onboarding_recognition, ui.trafficSignRecognitionEnabled,
                            onRecognitionEnabled, "onboarding-recognition-toggle")
                        SetupToggle(R.string.onboarding_independent, ui.trafficSignRecognitionIndependentEnabled,
                            onIndependentRecognitionEnabled, "onboarding-independent-toggle", ui.trafficSignRecognitionEnabled)
                        SetupBody(R.string.onboarding_independent_body)
                    }
                    else -> {
                        SetupBody(R.string.onboarding_panoramax_body)
                        SetupScreenshot(R.drawable.onboarding_photo_review, R.string.onboarding_review_screenshot)
                        SetupToggle(R.string.onboarding_panoramax_capture, ui.panoramaxCaptureEnabled,
                            onPanoramaxEnabled, "onboarding-panoramax-toggle")
                        SetupInfo(R.string.onboarding_panoramax_review_title, R.string.onboarding_panoramax_review_body)
                        SetupScreenshot(R.drawable.onboarding_photo_upload, R.string.onboarding_upload_screenshot)
                        SetupInfo(R.string.onboarding_panoramax_upload_title, R.string.onboarding_panoramax_upload_body)
                        SetupBody(R.string.onboarding_finish_body)
                    }
                }
            }
        }
        Row(Modifier.widthIn(max = 560.dp).fillMaxWidth().padding(top = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            if (step > 0) {
                OutlinedButton(onClick = onBack, modifier = Modifier.heightIn(min = 52.dp).testTag("onboarding-back-button")) {
                    Text(stringResource(R.string.onboarding_back), color = Color.White)
                }
            }
            Button(onClick = onNext, enabled = OnboardingPolicy.canAdvance(step, hasUsableMap, ui.preciseLocationGranted),
                colors = ButtonDefaults.buttonColors(containerColor = SetupRed, disabledContainerColor = Color(0xFF36363B),
                    disabledContentColor = Color(0xFFAAAAAF)),
                modifier = Modifier.weight(1f).heightIn(min = 52.dp).testTag("onboarding-next-button")) {
                Text(stringResource(if (step == 4) R.string.onboarding_finish else R.string.onboarding_next), fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
private fun OnboardingMap(ui: ConsumerUiState, hasUsableMap: Boolean, isSyncing: Boolean,
    onUseLocation: () -> Unit, onSelectMap: (String) -> Unit, onDownloadMap: () -> Unit) {
    var choosingMap by rememberSaveable { mutableStateOf(false) }
    val selected = ui.bundleDownloadSections.flatMap { it.options }.firstOrNull { it.id == ui.onboardingSelectedMapId }
    SetupBody(R.string.onboarding_map_body)
    OutlinedButton(onClick = onUseLocation, enabled = !isSyncing && !ui.onboardingLocating,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag("onboarding-use-location-button")) {
        Text(stringResource(R.string.onboarding_use_location), color = Color.White)
    }
    if (ui.onboardingLocating) {
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth(), color = SetupRed)
        Text(stringResource(R.string.onboarding_locating), color = SetupMuted)
    } else if (ui.onboardingLocationRequested && ui.firstLocationPackStatus.isNotBlank()) {
        Text(ui.firstLocationPackStatus, color = SetupMuted, modifier = Modifier.testTag("onboarding-map-suggestion"))
    }
    OutlinedButton(onClick = { choosingMap = !choosingMap }, enabled = !isSyncing,
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag("onboarding-choose-map-button")) {
        Text(stringResource(R.string.onboarding_choose_map), color = Color.White)
    }
    if (choosingMap) {
        ui.bundleDownloadSections.forEach { section ->
            Text(section.countryName, color = SetupMuted, fontWeight = FontWeight.SemiBold)
            section.options.forEach { option ->
                Row(Modifier.fillMaxWidth().heightIn(min = 48.dp)
                    .selectable(selected = option.id == selected?.id, role = Role.RadioButton) {
                        onSelectMap(option.id); choosingMap = false
                    }.testTag("onboarding-map-choice-${option.id}"), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = option.id == selected?.id, onClick = null,
                        colors = RadioButtonDefaults.colors(selectedColor = SetupRed, unselectedColor = SetupMuted))
                    Text(option.displayName, color = Color.White, modifier = Modifier.padding(start = 8.dp))
                }
            }
        }
    }
    if (selected != null) {
        Card(colors = CardDefaults.cardColors(containerColor = Color(0xFF202025)), shape = RoundedCornerShape(16.dp)) {
            Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(selected.displayName, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp,
                    modifier = Modifier.testTag("onboarding-selected-map"))
                if (isSyncing) {
                    if (ui.syncProgressTotalBytes > 0) {
                        LinearProgressIndicator(progress = { (ui.syncProgressCompletedBytes.toFloat() / ui.syncProgressTotalBytes).coerceIn(0f, 1f) },
                            modifier = Modifier.fillMaxWidth().testTag("onboarding-download-progress"), color = SetupRed)
                    } else {
                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth().testTag("onboarding-download-progress"), color = SetupRed)
                    }
                    Text(ui.syncProgressDetail, color = SetupMuted)
                } else {
                    Button(onClick = onDownloadMap, colors = ButtonDefaults.buttonColors(containerColor = SetupRed),
                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag("onboarding-map-download-button")) {
                        Text(stringResource(if (ui.syncStatus == "sync_failed") R.string.onboarding_retry_download else R.string.onboarding_download))
                    }
                }
            }
        }
    }
    if (hasUsableMap) {
        Text(stringResource(R.string.onboarding_map_ready), color = Color(0xFF8CE5A8), modifier = Modifier.testTag("onboarding-map-ready"))
    } else {
        Text(stringResource(R.string.onboarding_map_required), color = SetupMuted)
    }
    if (ui.lastError.isNotBlank()) Text(ui.lastError, color = Color(0xFFFF999F), modifier = Modifier.testTag("onboarding-download-error"))
    SetupBody(R.string.onboarding_map_network)
}

@Composable
private fun SetupBody(resource: Int) {
    Text(stringResource(resource), color = SetupMuted, fontSize = 16.sp, lineHeight = 24.sp)
}

@Composable
private fun SetupInfo(title: Int, body: Int) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(stringResource(title), color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        SetupBody(body)
    }
}

@Composable
private fun SetupAction(label: Int, tag: String, onClick: () -> Unit) {
    Button(onClick = onClick, colors = ButtonDefaults.buttonColors(containerColor = SetupRed),
        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag(tag)) {
        Text(stringResource(label))
    }
}

@Composable
private fun SetupToggle(label: Int, checked: Boolean, onChange: (Boolean) -> Unit, tag: String, enabled: Boolean = true) {
    val description = stringResource(label)
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(stringResource(label), color = if (enabled) Color.White else SetupMuted,
            modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
        Switch(checked = checked, onCheckedChange = onChange, enabled = enabled, modifier = Modifier.testTag(tag).semantics { contentDescription = description },
            colors = SwitchDefaults.colors(checkedTrackColor = SetupRed, checkedThumbColor = Color.White))
    }
}

@Composable
private fun SetupScreenshot(resource: Int, caption: Int, modifier: Modifier = Modifier) {
    val painter = painterResource(resource)
    val enlargeLabel = stringResource(R.string.onboarding_expand_screenshot)
    var expanded by remember { mutableStateOf(false) }
    val showsFullComparison = resource == R.drawable.onboarding_limit_map || resource == R.drawable.onboarding_limit_camera
    val previewSize = if (showsFullComparison) {
        Modifier.aspectRatio(painter.intrinsicSize.width / painter.intrinsicSize.height)
    } else {
        Modifier.height(280.dp)
    }
    // Focus library previews on their controls; the original full screenshot remains available on tap.
    val previewAlignment = if (resource == R.drawable.onboarding_video_library) BiasAlignment(0f, -0.4f) else Alignment.Center
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Image(painter, contentDescription = stringResource(caption),
            contentScale = if (showsFullComparison) ContentScale.Fit else ContentScale.Crop,
            alignment = previewAlignment,
            modifier = Modifier.fillMaxWidth().then(previewSize)
                .clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClickLabel = enlargeLabel) { expanded = true })
        Text(stringResource(caption), color = SetupMuted, fontSize = 13.sp, lineHeight = 18.sp)
        Text(stringResource(R.string.onboarding_screenshot_hint), color = SetupMuted, fontSize = 12.sp)
    }
    if (expanded) {
        var scale by remember { mutableStateOf(1f) }
        var offset by remember { mutableStateOf(Offset.Zero) }
        Dialog(onDismissRequest = { expanded = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Column(Modifier.fillMaxSize().background(Color.Black).safeDrawingPadding().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(stringResource(caption), color = Color.White, fontWeight = FontWeight.SemiBold)
                Box(Modifier.weight(1f).fillMaxWidth().clipToBounds().pointerInput(Unit) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        scale = (scale * zoom).coerceIn(1f, 5f)
                        offset = if (scale == 1f) Offset.Zero else offset + pan
                    }
                }, contentAlignment = Alignment.Center) {
                    Image(painter, contentDescription = stringResource(caption), contentScale = ContentScale.Fit,
                        modifier = Modifier.fillMaxSize().graphicsLayer {
                            scaleX = scale; scaleY = scale; translationX = offset.x; translationY = offset.y
                        })
                }
                Button(onClick = { expanded = false }, colors = ButtonDefaults.buttonColors(containerColor = SetupRed),
                    modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
                    Text(stringResource(R.string.onboarding_close_example))
                }
            }
        }
    }
}
