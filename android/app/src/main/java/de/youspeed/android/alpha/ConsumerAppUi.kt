@file:OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class)

package de.youspeed.android.alpha

import androidx.compose.material3.RadioButton
import androidx.compose.material3.Checkbox

import android.content.Context
import android.graphics.BitmapFactory
import android.graphics.Paint as AndroidPaint
import android.graphics.Typeface
import android.text.format.Formatter
import android.view.WindowManager
import androidx.core.content.res.ResourcesCompat
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredHeight
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.WifiOff
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.DialogWindowProvider
import java.time.Instant
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

private val Paper = Color(0xFFFDF8F0)
private val SoftCard = Color(0xCCFFFFFF)
private val NightRed = Color(0xFF6B0E16)
private val NightRedDark = Color(0xFF42040B)
private val HighwayBlue = Color(0xFF0B54C9)
private val SignalGreen = Color(0xFF1D7A4A)
private val SignalOrange = Color(0xFFD46A1D)
private val SignalRed = Color(0xFF9A1D28)
private val SpeedSignBorderRed = Color(0xFFD21B24)
private val SpeedSignBorderGray = Color(0xFF7B7F86)
private val CameraEvidenceAccent = Color(0xFF7B0E17)
private val BrightYellow = Color(0xFFF9D950)
private val SoftOrange = Color(0xFFF39A24)
private val SoftRed = Color(0xFFC5212E)

private fun trafficSignBugButtonTint(ui: ConsumerUiState, foreground: Color): Color {
    if (!ui.trafficSignRecognitionEnabled) return foreground
    val runtimeUnhealthy = ui.trafficSignRecognitionUnavailable ||
        ui.trafficSignDebugRuntimeUnhealthy ||
        ui.trafficSignCameraRuntimeState in setOf(
            TrafficSignCameraRuntimeState.DENIED,
            TrafficSignCameraRuntimeState.UNAVAILABLE,
            TrafficSignCameraRuntimeState.FAILED,
        )
    if (runtimeUnhealthy) return SoftRed
    if (ui.trafficSignDebugRoadContextInvalid || ui.trafficSignDebugGenerationSessionContextMismatch) {
        return BrightYellow
    }
    return foreground
}
private const val DRIVING_BAN_PULSE_CYCLE_SECONDS = 2.2f
private const val SPEED_LIMIT_NUMBER_SCALE = 0.5f
private const val SECONDARY_TEXT_RATIO = 9f / 16f
private const val DEBUG_WIDTH_REFERENCE = "N00.0000 O000.0000"
private val CITY_BADGE_STREET_TEXT_SIZE = 18.sp
private val CITY_BADGE_PLACE_TEXT_SIZE = 17.sp
private val CITY_BADGE_DISTRICT_TEXT_SIZE = 16.sp
private val CITY_BADGE_LINE_SPACING = 2.dp
private val CITY_BADGE_HORIZONTAL_PADDING = 12.dp
private val CITY_BADGE_VERTICAL_PADDING = 8.dp
private val LOCATION_SLOT_MIN_HEIGHT = 84.dp
private val CONTROL_BUTTON_DIAMETER = 48.dp
private val TrafficSignFontFamily = FontFamily(
    Font(R.font.u_din_1451_mittelschrift_regular, weight = FontWeight.Normal),
)

internal object CameraSpeedLimitUsePresentation {
    fun isVisible(
        isInSpeedCaptureMode: Boolean,
        source: EffectiveSpeedLimitSource,
        hasResolvedValue: Boolean,
    ): Boolean = !isInSpeedCaptureMode && source == EffectiveSpeedLimitSource.CAMERA && hasResolvedValue
}

@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun ConsumerApp(controller: ConsumerSessionController) {
    val ui = controller.uiState
    var openSettings by rememberSaveable { mutableStateOf(false) }
    var openLegal by rememberSaveable { mutableStateOf(false) }
    var openDebug by rememberSaveable { mutableStateOf(false) }
    var openLocalRecordings by rememberSaveable { mutableStateOf(false) }
    var openPanoramaxGallery by rememberSaveable { mutableStateOf(false) }

    val showingOnboarding = controller.shouldPresentOnboarding()
    LaunchedEffect(ui.startupDataState, ui.appScreenshotState, showingOnboarding) {
        if (showingOnboarding) {
            controller.pauseDrivingForOnboarding()
        } else if (ui.appScreenshotState == null && ui.startupDataState == StartupDataState.READY && ui.driveStatus == "stopped") {
            controller.startDriving()
        }
    }

    MaterialTheme {
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .semantics { testTagsAsResourceId = true },
            color = Color.Black,
        ) {
            when {
                ui.appScreenshotState != null -> {
                    MainScreen(
                        controller = controller,
                        ui = ui,
                        onOpenSettings = { controller.performButtonAction { openSettings = true } },
                        onOpenLegal = { controller.performButtonAction { openLegal = true } },
                        onOpenDebug = { controller.performButtonAction { openDebug = true } },
                        onOpenLocalRecordings = { controller.performButtonAction { openLocalRecordings = true } },
                        onOpenPanoramaxGallery = { controller.performButtonAction { openPanoramaxGallery = true } },
                        onToggleDriveRecorder = controller::toggleDriveRecorder,
                        onCapture = { controller.performButtonAction(controller::beginSpeedCapture) },
                    )
                }

                showingOnboarding -> {
                    OnboardingScreen(
                        ui = ui,
                        hasUsableMap = controller.hasUsableOnboardingMap(),
                        isSyncing = controller.isSyncingNow(),
                        onNext = controller::advanceOnboarding,
                        onBack = controller::goBackInOnboarding,
                        onUseLocation = {
                            if (ui.onboardingStep == 0) controller.useLocationForOnboarding()
                            else controller.requestOnboardingLocationPermission()
                        },
                        onOpenLocationSettings = controller::openOnboardingLocationSettings,
                        onSelectMap = controller::selectOnboardingMap,
                        onDownloadMap = controller::downloadOnboardingMap,
                        onAudioEnabled = controller::setAudioAlertsEnabled,
                        onAudioThreshold = controller::setAudioAlertThresholdKmh,
                        onRecognitionEnabled = controller::setTrafficSignRecognitionEnabled,
                        onIndependentRecognitionEnabled = controller::setTrafficSignRecognitionIndependentEnabled,
                        onPanoramaxEnabled = controller::setPanoramaxCaptureEnabled,
                    )
                }

                ui.startupDataState == StartupDataState.READY -> {
                    MainScreen(
                        controller = controller,
                        ui = ui,
                        onOpenSettings = { controller.performButtonAction { openSettings = true } },
                        onOpenLegal = { controller.performButtonAction { openLegal = true } },
                        onOpenDebug = { controller.performButtonAction { openDebug = true } },
                        onOpenLocalRecordings = { controller.performButtonAction { openLocalRecordings = true } },
                        onOpenPanoramaxGallery = { controller.performButtonAction { openPanoramaxGallery = true } },
                        onToggleDriveRecorder = controller::toggleDriveRecorder,
                        onCapture = { controller.performButtonAction(controller::beginSpeedCapture) },
                    )
                }

                else -> {
                    StartupScreen(
                        ui = ui,
                        onRetry = controller::retryStartupDataPreparation,
                    )
                }
            }

            if (ui.dashcamButtonActionPending) {
                AlertDialog(onDismissRequest = {}, confirmButton = {},
                    title = { Text(stringResource(R.string.ui_video_saving)) },
                    text = { LinearProgressIndicator(Modifier.fillMaxWidth()) })
            }
            ui.dashcamButtonActionError?.let { error ->
                AlertDialog(onDismissRequest = controller::dismissDashcamButtonActionError,
                    title = { Text(stringResource(R.string.ui_video_save_failed)) },
                    text = { Text(error) },
                    confirmButton = { Button(onClick = controller::dismissDashcamButtonActionError) {
                        Text(stringResource(R.string.ui_done))
                    } })
            }

            if (openSettings) {
                SettingsSheet(
                    controller = controller,
                    onDismiss = { openSettings = false },
                    onOpenDebug = { controller.performButtonAction { openDebug = true } },
                )
            }
            if (openLegal) {
                LegalSheet(ui = ui, onDismiss = { openLegal = false })
            }
            if (openDebug) {
                DebugSheet(controller = controller, onDismiss = { openDebug = false })
            }
            if (openLocalRecordings) {
                LocalRecordingsSheet(controller = controller, onDismiss = { openLocalRecordings = false })
            }
            if (openPanoramaxGallery) {
                PanoramaxGallerySheet(controller = controller, onDismiss = { openPanoramaxGallery = false })
            }
        }
    }
}

@Composable
internal fun StartupScreen(
    ui: ConsumerUiState,
    onRetry: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .testTag("startup-root")
            .safeDrawingPadding()
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(18.dp),
            modifier = Modifier.widthIn(max = 420.dp)
                .verticalScroll(rememberScrollState())
                .testTag("startup-content"),
        ) {
            Text("YouSpeed", color = Color.White, style = roundedUiTextStyle(size = 42.sp, weight = FontWeight.Bold))
            Text(stringResource(R.string.startup_loading_map_data), color = Color.White, style = roundedUiTextStyle(size = 20.sp, weight = FontWeight.SemiBold))
            LinearProgress(ui.startupProgress)
            Text(
                "${(ui.startupProgress.coerceIn(0.0, 1.0) * 100).toInt()}%",
                color = Color.White.copy(alpha = 0.92f),
                style = roundedUiTextStyle(size = 18.sp, weight = FontWeight.Bold),
            )
            Text(
                ui.startupDetail,
                color = Color.White.copy(alpha = 0.85f),
                textAlign = TextAlign.Center,
                style = roundedUiTextStyle(size = 16.sp, weight = FontWeight.Medium),
            )
            if (ui.startupDataState == StartupDataState.FAILED && ui.lastError.isNotBlank()) {
                Text(
                    ui.lastError,
                    color = Color.White.copy(alpha = 0.75f),
                    textAlign = TextAlign.Center,
                    style = roundedUiTextStyle(size = 14.sp, weight = FontWeight.Normal),
                )
                Button(
                    onClick = onRetry,
                    colors = ButtonDefaults.buttonColors(containerColor = SoftRed),
                    modifier = Modifier.heightIn(min = 48.dp).testTag("startup-retry-button"),
                ) {
                    Text(stringResource(R.string.startup_retry), style = roundedUiTextStyle(size = 17.sp, weight = FontWeight.Bold))
                }
            }
        }
    }
}

private fun roundedUiTextStyle(
    size: androidx.compose.ui.unit.TextUnit,
    weight: FontWeight,
): TextStyle = TextStyle(
    fontSize = size,
    fontWeight = weight,
    fontFamily = FontFamily.SansSerif,
)

private fun trafficSignTextStyle(size: androidx.compose.ui.unit.TextUnit): TextStyle = TextStyle(
    fontSize = size,
    fontWeight = FontWeight.Normal,
    fontFamily = TrafficSignFontFamily,
    letterSpacing = (-0.01f * size.value).sp,
)

private fun primaryMetricTextStyle(
    ui: ConsumerUiState,
    baseSize: androidx.compose.ui.unit.TextUnit,
): TextStyle = when {
    ConsumerMainScreenLogic.isInSpeedCaptureMode(ui) -> roundedUiTextStyle(size = baseSize * 0.42f, weight = FontWeight.Bold)
    else -> trafficSignTextStyle(baseSize)
}

private fun sharedSecondaryScale(
    baseSecondaryFontSp: Float,
    availableWidthSp: Float,
): Float {
    val estimatedWidth = DEBUG_WIDTH_REFERENCE.length * baseSecondaryFontSp * 0.58f
    if (estimatedWidth <= 0f) {
        return 0.45f
    }
    val adaptive = availableWidthSp / estimatedWidth
    return min(0.5f, max(0.35f, adaptive))
}

@Composable
private fun rememberTrafficSignTypeface(): Typeface {
    val context = LocalContext.current
    return remember(context) {
        ResourcesCompat.getFont(context, R.font.u_din_1451_mittelschrift_regular)
            ?: Typeface.create("sans-serif-condensed", Typeface.NORMAL)
            ?: Typeface.SANS_SERIF
    }
}

@Composable
private fun MainScreen(
    controller: ConsumerSessionController,
    ui: ConsumerUiState,
    onOpenSettings: () -> Unit,
    onOpenLegal: () -> Unit,
    onOpenDebug: () -> Unit,
    onOpenLocalRecordings: () -> Unit,
    onOpenPanoramaxGallery: () -> Unit,
    onToggleDriveRecorder: () -> Unit,
    onCapture: () -> Unit,
) {
    var previewSelected by rememberSaveable { mutableStateOf(true) }
    val recorderVisible = ui.driveRecorderState != DriveRecorderState.DISABLED
    LaunchedEffect(ui.driveRecorderState, ui.driveRecorderDashcamActive) {
        if (ui.driveRecorderDashcamActive) previewSelected = true
    }
    val previewPresentation = DriveRecorderPreviewPresentation.resolve(
        sessionAvailable = recorderVisible,
        selection = if (previewSelected) DriveRecorderWorkspaceSelection.PREVIEW
        else DriveRecorderWorkspaceSelection.TELEMETRY,
        previewAvailable = DriveRecorderPolicy.canShowPreview(
            ui.driveRecorderState,
            ui.driveRecorderDashcamActive,
            ConsumerMainScreenLogic.isInSpeedCaptureMode(ui),
        ),
    )
    val previewVisible = previewPresentation.isVisible
    val pulseTransition = rememberInfiniteTransition(label = "driving-ban-pulse")
    val pulseFraction by pulseTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = (DRIVING_BAN_PULSE_CYCLE_SECONDS * 1000).toInt(), easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "driving-ban-pulse-value",
    )
    val background = mainBackgroundColor(ui, if (ui.appScreenshotState != null) 0f else pulseFraction)
    // Choose the higher-contrast text color from the rendered warning background.
    val usesDarkForeground = background.luminance() > 0.179f
    val foreground = if (usesDarkForeground) Color.Black else Color.White
    val buttonBg = if (usesDarkForeground) Color.Black.copy(alpha = 0.08f) else Color.White.copy(alpha = 0.14f)
    val buttonBorder = foreground.copy(alpha = 0.95f)
    val primaryMetric = ConsumerMainScreenLogic.primaryMetricText(ui)
    val secondaryMetric = ConsumerMainScreenLogic.secondaryMetricText(ui)
    val limitText = ConsumerMainScreenLogic.limitText(ui)
    val banner = runtimeBanner(ui)
    val showsPedestrianZoneSign = ConsumerMainScreenLogic.showsPedestrianZoneSign(ui)

    BoxWithConstraints(
        Modifier.fillMaxSize().background(background).testTag("main-root").safeDrawingPadding(),
    ) {
        val landscape = ui.manualOrientation.isLandscape && maxWidth > maxHeight
        // Portrait uses the full display width for the sign pane so the sign
        // and its camera eye are centered on the screen. Landscape keeps the
        // two fixed panes side by side.
        val signPaneWidth = if (landscape) maxWidth * 0.45f else maxWidth
        val workspaceWidth = if (landscape) maxWidth - signPaneWidth else maxWidth
        val minDimension = min(maxWidth.value, maxHeight.value)
        val screenInset = max(8f, minDimension * 0.02f).dp
        val compact = maxHeight.value < 780f
        // Keep the Android sign close to the iPhone's visual weight. The
        // previous limits made the circle noticeably smaller, especially in
        // portrait where the height cap won over the width budget.
        val preferredSignSize = signPaneWidth * when {
            // Landscape has the same generous sign scale as the iPhone
            // dashboard. The old compact-width branch kept this device at
            // roughly 58% of the pane height.
            landscape -> 0.72f
            compact -> 0.64f
            else -> 0.76f
        }
        val signSize = min(preferredSignSize.value,
            if (landscape) max(48f, maxHeight.value - 104f)
            else maxHeight.value * 0.42f).dp
        val portraitTopHeight = min(maxHeight.value * 0.57f,
            signSize.value + CONTROL_BUTTON_DIAMETER.value + screenInset.value + 28f).dp
        val primaryMetricFont = (signSize.value * if (compact) 0.42f else SPEED_LIMIT_NUMBER_SCALE).sp
        val secondaryScale = sharedSecondaryScale(
            primaryMetricFont.value * SECONDARY_TEXT_RATIO,
            workspaceWidth.value - max(12f, workspaceWidth.value * 0.04f) * 2f,
        )
        val secondaryFont = primaryMetricFont * (SECONDARY_TEXT_RATIO * secondaryScale)
        val debugFont = secondaryFont * 0.6f
        val metricSlotMinHeight = with(LocalDensity.current) {
            primaryMetricFont.toDp() * 1.05f + secondaryFont.toDp() * 1.2f
        }
        val horizontalPadding = max(12f, workspaceWidth.value * 0.04f).dp
        val locationHeight = if (landscape) 72.dp else max(LOCATION_SLOT_MIN_HEIGHT.value, minDimension * 0.225f).dp
        val locationBadgeWidth = if (landscape) {
            (workspaceWidth.value * 0.78f).coerceAtLeast(180f).dp
        } else {
            max(0f, workspaceWidth.value - screenInset.value * 2f - CONTROL_BUTTON_DIAMETER.value * 2f).dp
        }
        // The sign is centered in the upper pane after its top/bottom inset.
        // Landscape telemetry is anchored to that same circle-height frame so
        // the metric slot starts at the circle's top and the location badge
        // finishes at its bottom, like the iPhone layout.
        val landscapeSignTopInWorkspace = max(
            0f,
            (maxHeight.value - screenInset.value - 8f - signSize.value) / 2f,
        ).dp
        // safeDrawingPadding() removes the landscape navigation inset from
        // the content. On this device the remaining content is vertically
        // displaced because the left navigation inset is much larger than
        // the opposite edge inset. Counter that half-difference so the
        // visible dashboard is symmetric against the physical screen edges.
        val landscapeVerticalCenterCorrection = if (landscape) {
            val systemBars = WindowInsets.systemBars.asPaddingValues()
            ((systemBars.calculateBottomPadding().value - systemBars.calculateTopPadding().value) / 2f).dp
        } else {
            0.dp
        }

        // Keep both subtrees mounted. Only their measured size and placement
        // change, so the live PreviewView and its surface provider survive.
        Layout(
            modifier = Modifier.fillMaxSize(),
            content = {
                Box(
                    Modifier.fillMaxSize().padding(top = screenInset, bottom = 8.dp).testTag("main-sign-pane"),
                ) {
                    TopCornerButtons(
                        screenInset, foreground, buttonBg, buttonBorder,
                        trafficSignBugButtonTint(ui, foreground),
                        showLocalRecordings = false,
                        onOpenLocalRecordings = onOpenLocalRecordings,
                        modifier = Modifier.align(Alignment.TopStart),
                    )
                    val showsActiveCameraLimitIndicator = CameraSpeedLimitUsePresentation.isVisible(
                        ConsumerMainScreenLogic.isInSpeedCaptureMode(ui), ui.effectiveSpeedLimitSource,
                        ui.speedLimitKmh != null || ui.speedLimitDisplayText != null || ui.isUnlimitedSpeedLimitActive,
                    )
                    // Keep the sign square inside a full-width eye canvas. The
                    // eye tips use the canvas edges (with screen/control insets)
                    // and would otherwise collapse onto the circle border.
                    Box(
                        Modifier.align(Alignment.Center)
                            .fillMaxWidth()
                            .height(signSize)
                            .offset(y = landscapeVerticalCenterCorrection),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (showsActiveCameraLimitIndicator) ActiveCameraSpeedLimitEye(
                            signSize = signSize,
                            screenInset = screenInset,
                            landscape = landscape,
                        )
                        SpeedLimitSign(
                            limitText = limitText, signSize = signSize, numberFontSize = primaryMetricFont,
                            showsUnlimitedIcon = !showsPedestrianZoneSign && ui.isUnlimitedSpeedLimitActive &&
                                !ConsumerMainScreenLogic.isInSpeedCaptureMode(ui),
                            showsPedestrianZoneIcon = showsPedestrianZoneSign,
                            showsActiveCameraLimitIndicator = showsActiveCameraLimitIndicator,
                            showsStaleBundleLimitIndicator = ui.effectiveSpeedLimitSource == EffectiveSpeedLimitSource.STALE_BUNDLE,
                            cameraSourceStateDescription = when {
                                ui.isUnlimitedSpeedLimitActive -> stringResource(R.string.ui_camera_unlimited)
                                ui.speedLimitDisplayText == "Schritt" -> stringResource(R.string.ui_camera_walking)
                                ui.speedLimitKmh != null -> stringResource(R.string.ui_camera_speed_limit, ui.speedLimitKmh.toString())
                                else -> stringResource(R.string.ui_camera_sign)
                            },
                            onDoubleTap = onCapture,
                        )
                        if (ui.isTrafficSignEndOverlayVisible) EndOfSpeedLimitSign(
                            modifier = Modifier.offset(y = -(signSize * 0.42f)).testTag("speed-limit-end-overlay"),
                            signSize = signSize * 0.34f,
                        )
                        // Draw the recognized secondary sign after the speed
                        // sign. This is intentionally the same z-order as the
                        // iPhone implementation: it remains at the eye tip,
                        // but its artwork is in front of the speed-limit ring.
                        if (ui.otherTrafficSignDisplayEnabled) {
                            ui.lastTrafficSignPictogram?.let { pictogram ->
                                val eyeTipInset = if (landscape) {
                                    max(10f, (signPaneWidth.value - signSize.value) / 4f).dp
                                } else {
                                    screenInset + CONTROL_BUTTON_DIAMETER / 2
                                }
                                RecognizedTrafficSignPictogram(
                                    pictogram = pictogram,
                                    modifier = Modifier
                                        .align(Alignment.TopStart)
                                        .offset(x = eyeTipInset),
                                )
                            }
                        }
                    }
                }
                Column(
                    Modifier.fillMaxSize().padding(top = if (landscape) screenInset else 0.dp, bottom = 12.dp)
                        .testTag("main-workspace-pane"),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    if (recorderVisible && landscape) RecorderModuleStrip(
                        controller,
                        Modifier.padding(horizontal = horizontalPadding, vertical = 6.dp)
                            .testTag("drive-recorder-status"),
                        compact = true,
                        onPreviewRequested = { previewSelected = true },
                    )
                    BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                        val fittedMetricHeight = min(metricSlotMinHeight.value, maxHeight.value * 0.58f).dp
                        val metricScale = (fittedMetricHeight.value / metricSlotMinHeight.value).coerceIn(0.1f, 1f)
                        val fittedLocationHeight = min(locationHeight.value, maxHeight.value * 0.30f).dp
                        if (landscape) {
                            Column(
                                Modifier
                                    .fillMaxWidth()
                                    .requiredHeight(signSize)
                                    .offset(y = landscapeSignTopInWorkspace + landscapeVerticalCenterCorrection)
                                    .padding(horizontal = horizontalPadding)
                                    .alpha(if (previewVisible) 0f else 1f),
                                verticalArrangement = Arrangement.SpaceBetween,
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                MetricStatusBlock(
                                    primaryMetric, secondaryMetric, foreground, ui,
                                    primaryMetricFont, secondaryFont, metricSlotMinHeight,
                                    alignContentToTop = true,
                                )
                                LocationStatusBlock(
                                    ui, foreground, debugFont, max(2f, minDimension * 0.004f).dp,
                                    max(12f, minDimension * 0.024f).dp, locationHeight, horizontalPadding,
                                    locationBadgeWidth, banner, onOpenDebug, compact = true,
                                    alignContentToBottom = true,
                                )
                            }
                        } else {
                            Column(
                                Modifier
                                    .fillMaxSize()
                                    .alpha(if (previewVisible) 0f else 1f),
                                verticalArrangement = Arrangement.SpaceEvenly,
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                MetricStatusBlock(primaryMetric, secondaryMetric, foreground, ui,
                                    primaryMetricFont * metricScale, secondaryFont * metricScale, fittedMetricHeight)
                                Spacer(Modifier.height(4.dp))
                                Box(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                                    LocationStatusBlock(ui, foreground, debugFont, max(2f, minDimension * 0.004f).dp,
                                        max(12f, minDimension * 0.024f).dp, fittedLocationHeight, horizontalPadding,
                                        locationBadgeWidth, banner, onOpenDebug, compact = false)
                                }
                            }
                        }
                        if (previewPresentation.isAttached) RecorderPreviewWorkspace(
                            controller, Modifier.fillMaxSize().padding(horizontal = horizontalPadding),
                            visible = previewVisible,
                            onDismiss = { previewSelected = false },
                        )
                    }
                    if (recorderVisible && !landscape) RecorderModuleStrip(
                        controller, Modifier.padding(top = 6.dp).testTag("drive-recorder-status"),
                        onPreviewRequested = { previewSelected = true },
                    )
                    if (landscape) BottomCornerButtons(
                        horizontalPadding = screenInset, foreground = foreground,
                        buttonBg = buttonBg, buttonBorder = buttonBorder,
                        onOpenLegal = onOpenLegal, onOpenSettings = onOpenSettings,
                        onOpenPanoramaxGallery = onOpenPanoramaxGallery,
                        onToggleDriveRecorder = onToggleDriveRecorder,
                        onOpenLocalRecordings = onOpenLocalRecordings,
                        localRecordingsTint = trafficSignBugButtonTint(ui, foreground),
                        driveRecorderState = ui.driveRecorderState, panoramaxCaptureCount = ui.panoramaxCaptureCount,
                        modifier = Modifier.padding(top = if (recorderVisible) 8.dp else 16.dp),
                    )
                }
            },
        ) { measurables, constraints ->
            val width = constraints.maxWidth
            val height = constraints.maxHeight
            val upperWidth = if (landscape) (width * 0.45f).toInt() else width
            val upperHeight = if (landscape) height else portraitTopHeight.roundToPx().coerceIn(0, height)
            val upper = measurables[0].measure(Constraints.fixed(upperWidth, upperHeight))
            val lower = measurables[1].measure(Constraints.fixed(
                if (landscape) width - upperWidth else width,
                if (landscape) height else height - upperHeight,
            ))
            layout(width, height) {
                upper.place(0, 0)
                // Absolute placement makes the requested left/right invariant
                // independent of interface language and mounting direction.
                lower.place(if (landscape) upperWidth else 0, if (landscape) 0 else upperHeight)
            }
        }
        if (!landscape) BottomCornerButtons(
            horizontalPadding = screenInset, foreground = foreground,
            buttonBg = buttonBg, buttonBorder = buttonBorder,
            onOpenLegal = onOpenLegal, onOpenSettings = onOpenSettings,
            onOpenPanoramaxGallery = onOpenPanoramaxGallery,
            onToggleDriveRecorder = onToggleDriveRecorder,
            onOpenLocalRecordings = onOpenLocalRecordings,
            localRecordingsTint = trafficSignBugButtonTint(ui, foreground),
            driveRecorderState = ui.driveRecorderState, panoramaxCaptureCount = ui.panoramaxCaptureCount,
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 8.dp),
        )
    }
}

@Composable
private fun TopCornerButtons(
    screenInset: androidx.compose.ui.unit.Dp,
    foreground: Color,
    buttonBg: Color,
    buttonBorder: Color,
    bugTint: Color,
    showLocalRecordings: Boolean,
    onOpenLocalRecordings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (!showLocalRecordings) return
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = screenInset),
        verticalAlignment = Alignment.Top,
    ) {
        if (showLocalRecordings) {
            LocalRecordingsButton(
                onClick = onOpenLocalRecordings,
                foreground = foreground,
                buttonBg = buttonBg,
                buttonBorder = buttonBorder,
                tint = bugTint,
            )
        }
        if (showLocalRecordings) Spacer(modifier = Modifier.weight(1f))
    }
}

@Composable
private fun RecognizedTrafficSignPictogram(
    pictogram: TrafficSignPictogram,
    modifier: Modifier = Modifier,
) {
    val pictogramModifier = modifier
        .size(72.dp)
        .padding(5.dp)
        .testTag("last-traffic-sign-pictogram")
    val context = LocalContext.current
    val bitmap = remember(pictogram.imagePath) {
        pictogram.imagePath?.let { path ->
            runCatching { context.assets.open(path).use(BitmapFactory::decodeStream)?.asImageBitmap() }.getOrNull()
        }
    }
    if (bitmap != null) {
        Image(
            bitmap = bitmap,
            contentDescription = stringResource(R.string.ui_last_recognized_sign, pictogram.label()),
            modifier = pictogramModifier,
        )
    }
}

@Composable
private fun EndOfSpeedLimitSign(modifier: Modifier = Modifier, signSize: androidx.compose.ui.unit.Dp) {
    val description = stringResource(R.string.ui_camera_speed_limit_end)
    Canvas(
        modifier = modifier
            .size(signSize)
            .semantics { contentDescription = description },
    ) {
        val borderWidth = size.minDimension * 0.028f
        drawCircle(Color.White)
        clipPath(Path().apply { addOval(androidx.compose.ui.geometry.Rect(0f, 0f, size.width, size.height)) }) {
            repeat(5) { index ->
                rotate(degrees = -51f, pivot = center) {
                    val stripeWidth = size.minDimension * 0.035f
                    val stripeHeight = size.minDimension * 1.7f
                    val offsetX = (index - 2) * size.minDimension * 0.12f
                    drawRect(
                        color = Color.Black.copy(alpha = 0.42f),
                        topLeft = Offset(center.x + offsetX - stripeWidth / 2f, center.y - stripeHeight / 2f),
                        size = Size(stripeWidth, stripeHeight),
                    )
                }
            }
        }
        drawCircle(Color.Black.copy(alpha = 0.82f), radius = (size.minDimension - borderWidth) / 2f, style = Stroke(width = borderWidth))
    }
}

@Composable
private fun BottomCornerButtons(
    horizontalPadding: androidx.compose.ui.unit.Dp,
    foreground: Color,
    buttonBg: Color,
    buttonBorder: Color,
    onOpenLegal: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenPanoramaxGallery: () -> Unit,
    onToggleDriveRecorder: () -> Unit,
    onOpenLocalRecordings: (() -> Unit)?,
    localRecordingsTint: Color,
    driveRecorderState: DriveRecorderState,
    panoramaxCaptureCount: Int,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = horizontalPadding)
            .testTag("dashboard-bottom-controls"),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        PillIconButton(
            onClick = { if (driveRecorderState != DriveRecorderState.STOPPING) onToggleDriveRecorder() },
            background = if (driveRecorderState == DriveRecorderState.RECORDING) Color(0x3321C55D) else buttonBg,
            border = if (driveRecorderState == DriveRecorderState.RECORDING) Color(0xFFEF4444) else buttonBorder,
            modifier = Modifier.testTag("drive-recorder-toggle-button"),
        ) {
            Icon(
                imageVector = if (DriveRecorderPolicy.isActive(driveRecorderState)) Icons.Default.Stop else Icons.Default.RadioButtonUnchecked,
                contentDescription = stringResource(
                    if (DriveRecorderPolicy.isActive(driveRecorderState)) R.string.ui_drive_recorder_stop else R.string.ui_drive_recorder_start,
                ),
                tint = Color(0xFFEF4444),
            )
        }
        if (onOpenLocalRecordings != null) {
            LocalRecordingsButton(
                onClick = onOpenLocalRecordings,
                foreground = foreground,
                buttonBg = buttonBg,
                buttonBorder = buttonBorder,
                tint = localRecordingsTint,
            )
        }
        PillIconButton(
            onClick = { if (DriveRecorderPolicy.canProcessPanoramaxUploads(driveRecorderState)) onOpenPanoramaxGallery() },
            enabled = DriveRecorderPolicy.canProcessPanoramaxUploads(driveRecorderState),
            background = buttonBg,
            border = buttonBorder,
            modifier = Modifier.testTag("panoramax-gallery-button"),
        ) {
            Box {
                Icon(
                    Icons.Default.PhotoLibrary,
                    contentDescription = stringResource(R.string.ui_panoramax_gallery),
                    tint = foreground,
                )
                if (panoramaxCaptureCount > 0) {
                    Text(
                        panoramaxCaptureCount.toString(),
                        color = Color.White,
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .background(Color(0xFFEF4444), CircleShape)
                            .padding(horizontal = 4.dp, vertical = 1.dp),
                    )
                }
            }
        }
        PillIconButton(
            onClick = onOpenLegal,
            background = buttonBg,
            border = buttonBorder,
            modifier = Modifier.testTag("legal-button"),
        ) {
            Icon(Icons.Default.Info, contentDescription = stringResource(R.string.ui_legal_title), tint = foreground)
        }
        PillIconButton(
            onClick = onOpenSettings,
            background = buttonBg,
            border = buttonBorder,
            modifier = Modifier.testTag("settings-button"),
        ) {
            Icon(Icons.Default.Settings, contentDescription = stringResource(R.string.ui_settings_title), tint = foreground)
        }
    }
}

@Composable
private fun LocalRecordingsButton(
    onClick: () -> Unit,
    foreground: Color,
    buttonBg: Color,
    buttonBorder: Color,
    tint: Color = foreground,
) {
    PillIconButton(
        onClick = onClick,
        background = buttonBg,
        border = if (tint == foreground) buttonBorder else tint,
        modifier = Modifier.testTag("local-recordings-button"),
    ) {
        Icon(Icons.Default.BugReport, contentDescription = stringResource(R.string.ui_recordings_title), tint = tint)
    }
}

@Composable
private fun PillIconButton(
    onClick: () -> Unit,
    background: Color,
    border: Color,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    content: @Composable () -> Unit,
) {
    Surface(
        modifier = modifier.alpha(if (enabled) 1f else 0.38f),
        shape = CircleShape,
        color = background,
        border = androidx.compose.foundation.BorderStroke(1.5.dp, border),
    ) {
        IconButton(onClick = onClick, enabled = enabled, modifier = Modifier.size(CONTROL_BUTTON_DIAMETER)) {
            content()
        }
    }
}

@Composable
private fun SpeedLimitSign(
    limitText: String,
    modifier: Modifier = Modifier,
    signSize: androidx.compose.ui.unit.Dp,
    numberFontSize: androidx.compose.ui.unit.TextUnit,
    showsUnlimitedIcon: Boolean,
    showsPedestrianZoneIcon: Boolean,
    showsActiveCameraLimitIndicator: Boolean,
    showsStaleBundleLimitIndicator: Boolean,
    cameraSourceStateDescription: String?,
    onDoubleTap: () -> Unit,
) {
    val currentCaptureAction by rememberUpdatedState(onDoubleTap)
    val captureLabel = stringResource(R.string.ui_correct_speed_limit)
    val density = LocalDensity.current
    val numberFontPx = with(density) { numberFontSize.toPx() }
    val trafficSignTypeface = rememberTrafficSignTypeface()
    val signDescription = if (showsActiveCameraLimitIndicator) {
        cameraSourceStateDescription ?: stringResource(R.string.ui_camera_speed_limit, limitText)
    } else {
        stringResource(R.string.ui_speed_limit_description, limitText)
    }
    Box(
        modifier = Modifier
            .then(modifier)
            .size(signSize)
            .pointerInput(Unit) { detectTapGestures(onDoubleTap = { currentCaptureAction() }) }
            .semantics {
                contentDescription = signDescription
                onClick(label = captureLabel) { currentCaptureAction(); true }
            }
            .testTag("speed-sign"),
        contentAlignment = Alignment.Center,
    ) {
        if (showsPedestrianZoneIcon) {
            Image(
                painter = painterResource(id = R.drawable.ic_pedestrian_zone_sign),
                contentDescription = stringResource(R.string.ui_pedestrian_zone),
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Canvas(modifier = Modifier.fillMaxSize().clip(CircleShape)) {
                if (showsUnlimitedIcon) {
                    val borderWidth = size.minDimension * 0.028f
                    drawCircle(color = Color.White)
                    drawCircle(color = Color.Black.copy(alpha = 0.82f),
                        radius = (size.minDimension - borderWidth) / 2f, style = Stroke(width = borderWidth))
                    repeat(5) { index ->
                        rotate(degrees = 51f, pivot = center) {
                            val stripeWidth = size.minDimension * 0.028f
                            val stripeHeight = size.minDimension * 1.5f
                            val offsetX = (index - 2) * size.minDimension * 0.07f
                            drawRect(
                                color = Color.Black.copy(alpha = 0.34f),
                                topLeft = Offset(center.x + offsetX - stripeWidth / 2f, center.y - stripeHeight / 2f),
                                size = Size(stripeWidth, stripeHeight),
                            )
                        }
                    }
                } else {
                    val standardBlackBorderWidth = size.minDimension * 0.0175f
                    val standardRedBandWidth = size.minDimension * 0.134f
                    drawCircle(color = Color.White)
                    // Match iPhone's strokeBorder: both rings stay inside the measured sign.
                    drawCircle(
                        color = if (showsActiveCameraLimitIndicator) Color.White else Color.Black.copy(alpha = 0.75f),
                        radius = (size.minDimension - standardBlackBorderWidth) / 2f,
                        style = Stroke(width = standardBlackBorderWidth),
                    )
                    drawCircle(
                        color = if (showsStaleBundleLimitIndicator) SpeedSignBorderGray else SpeedSignBorderRed,
                        radius = size.minDimension / 2f - standardBlackBorderWidth - standardRedBandWidth / 2f,
                        style = Stroke(width = standardRedBandWidth),
                    )
                    val standardInnerDiameter = max(1f, size.minDimension - (2f * (standardBlackBorderWidth + standardRedBandWidth)))
                    val targetWidth = standardInnerDiameter * 0.86f
                    val textPaint = AndroidPaint(AndroidPaint.ANTI_ALIAS_FLAG).apply {
                        color = android.graphics.Color.BLACK
                        textAlign = AndroidPaint.Align.CENTER
                        textSize = numberFontPx
                        typeface = trafficSignTypeface
                        isFakeBoldText = false
                        style = AndroidPaint.Style.FILL
                    }
                    val measuredWidth = textPaint.measureText(limitText)
                    if (measuredWidth > targetWidth && measuredWidth > 0f) {
                        textPaint.textSize *= targetWidth / measuredWidth
                    }
                    val metrics = textPaint.fontMetrics
                    val baseline = center.y - ((metrics.ascent + metrics.descent) / 2f)
                    drawContext.canvas.nativeCanvas.drawText(limitText, center.x, baseline, textPaint)
                }
            }
        }
    }
}

@Composable
private fun ActiveCameraSpeedLimitEye(
    signSize: androidx.compose.ui.unit.Dp,
    screenInset: androidx.compose.ui.unit.Dp,
    landscape: Boolean = false,
) {
    val density = LocalDensity.current
    Canvas(
        modifier = Modifier
            .fillMaxSize()
            .testTag("camera-speed-source-marker"),
    ) {
        val radius = with(density) { signSize.toPx() } / 2f
        val controlRadius = with(density) { CONTROL_BUTTON_DIAMETER.toPx() } / 2f
        val inset = with(density) { screenInset.toPx() }
        val center = Offset(size.width / 2f, size.height / 2f)
        // In landscape, use the midpoint between each canvas edge and the
        // circle border. The shorter span produces the steeper eye geometry
        // used by the iPhone layout while retaining a small portrait inset.
        val tipInset = if (landscape) {
            max(10f, (size.width - radius * 2f) / 4f)
        } else {
            inset + controlRadius
        }
        val tipLeftX = tipInset
        val tipRightX = size.width - tipInset
        // Extend the eye stroke underneath the circle by half its width so
        // antialiasing cannot leave a seam where the white shapes meet.
        val strokeWidth = max(4f, radius * 0.032f)
        val attachmentRadius = max(0f, radius - strokeWidth / 2f)
        val attachmentYOffset = attachmentRadius * 0.58f
        val attachmentXOffset = sqrt(max(0f,
            (attachmentRadius * attachmentRadius) - (attachmentYOffset * attachmentYOffset)))
        val path = Path().apply {
            moveTo(center.x - attachmentXOffset, center.y - attachmentYOffset)
            lineTo(tipLeftX, center.y)
            lineTo(center.x - attachmentXOffset, center.y + attachmentYOffset)
            moveTo(center.x + attachmentXOffset, center.y - attachmentYOffset)
            lineTo(tipRightX, center.y)
            lineTo(center.x + attachmentXOffset, center.y + attachmentYOffset)
        }
        drawPath(
            path = path,
            color = Color.White,
            style = Stroke(
                width = strokeWidth,
                cap = StrokeCap.Round,
            ),
        )
    }
}

@Composable
private fun MetricStatusBlock(
    displayedPrimaryMetric: String,
    secondaryMetric: String,
    foreground: Color,
    ui: ConsumerUiState,
    primaryMetricFont: androidx.compose.ui.unit.TextUnit,
    secondaryFont: androidx.compose.ui.unit.TextUnit,
    metricSlotMinHeight: androidx.compose.ui.unit.Dp,
    alignContentToTop: Boolean = false,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = metricSlotMinHeight)
            .padding(horizontal = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = if (alignContentToTop) Arrangement.Top else Arrangement.Center,
    ) {
        Text(
            displayedPrimaryMetric,
            color = foreground,
            style = primaryMetricTextStyle(ui = ui, baseSize = primaryMetricFont),
            textAlign = TextAlign.Center,
            modifier = Modifier.testTag("primary-metric"),
            maxLines = if (ConsumerMainScreenLogic.isInSpeedCaptureMode(ui)) 2 else 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            if (secondaryMetric.isBlank()) " " else secondaryMetric,
            color = foreground.copy(alpha = if (secondaryMetric.isBlank()) 0f else 1f),
            style = roundedUiTextStyle(size = secondaryFont, weight = FontWeight.Bold),
            textAlign = TextAlign.Center,
            modifier = Modifier.testTag("secondary-metric"),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun LocationStatusBlock(
    ui: ConsumerUiState,
    foreground: Color,
    debugFont: androidx.compose.ui.unit.TextUnit,
    debugSpacing: androidx.compose.ui.unit.Dp,
    metricDebugGap: androidx.compose.ui.unit.Dp,
    locationSlotMinHeight: androidx.compose.ui.unit.Dp,
    contentHorizontalPadding: androidx.compose.ui.unit.Dp,
    locationBadgeWidth: androidx.compose.ui.unit.Dp,
    runtimeBanner: RuntimeBanner?,
    onOpenDebug: () -> Unit,
    compact: Boolean = false,
    alignContentToBottom: Boolean = false,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = contentHorizontalPadding),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(debugSpacing),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = locationSlotMinHeight),
            contentAlignment = if (alignContentToBottom) Alignment.BottomCenter else Alignment.Center,
        ) {
            if (ConsumerMainScreenLogic.shouldShowCityBadge(ui)) {
                CityBadge(
                    streetName = ConsumerMainScreenLogic.cityBadgeStreetText(ui).orEmpty(),
                    placeName = ConsumerMainScreenLogic.cityBadgePlaceText(ui).orEmpty(),
                    districtName = ConsumerMainScreenLogic.cityBadgeDistrictText(ui).orEmpty(),
                    highlighted = ConsumerMainScreenLogic.shouldHighlightCityBadge(ui),
                badgeWidth = locationBadgeWidth,
                foreground = foreground,
                onOpenDebug = onOpenDebug,
                compact = compact,
            )
            } else {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(debugSpacing),
                    modifier = Modifier.testTag("debug-fix-summary"),
                ) {
                    Text(
                        ConsumerMainScreenLogic.debugCoordinateText(ui),
                        color = foreground.copy(alpha = 0.92f),
                        fontSize = debugFont,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                    )
                    Text(
                        ConsumerMainScreenLogic.debugWayIdText(ui),
                        color = foreground.copy(alpha = 0.82f),
                        fontSize = debugFont,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }
        }
        Spacer(modifier = Modifier.height(metricDebugGap))
        if (runtimeBanner != null) {
            ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = runtimeBanner.background)) {
                Text(
                    runtimeBanner.text,
                    color = runtimeBanner.foreground,
                    modifier = Modifier.padding(14.dp),
                    textAlign = TextAlign.Center,
                )
            }
        }
        if (ui.maintenanceMessage.isNotBlank()) {
            ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = SoftCard)) {
                Text(
                    ui.maintenanceMessage,
                    color = Color.Black,
                    modifier = Modifier.padding(14.dp),
                    textAlign = TextAlign.Center,
                )
            }
        }
        if (ui.lastError.isNotBlank()) {
            ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = Color(0xFFF7D9D6))) {
                Text(
                    ui.lastError,
                    color = SignalRed,
                    modifier = Modifier.padding(14.dp),
                    textAlign = TextAlign.Center,
                )
            }
        }
    }
}

@Composable
private fun CityBadge(
    streetName: String,
    placeName: String,
    districtName: String,
    highlighted: Boolean,
    badgeWidth: androidx.compose.ui.unit.Dp,
    foreground: Color,
    onOpenDebug: () -> Unit,
    compact: Boolean = false,
) {
    Card(
        modifier = Modifier
            .width(badgeWidth)
            .clickable { onOpenDebug() }
            .testTag("city-badge"),
        colors = CardDefaults.cardColors(
            containerColor = if (highlighted) BrightYellow else Color.Transparent,
        ),
        border = androidx.compose.foundation.BorderStroke(
            width = if (highlighted) 2.dp else 0.dp,
            color = if (highlighted) Color.Black.copy(alpha = 0.9f) else Color.Transparent,
        ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    horizontal = if (compact) 8.dp else CITY_BADGE_HORIZONTAL_PADDING,
                    vertical = if (compact) 5.dp else CITY_BADGE_VERTICAL_PADDING,
                ),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(CITY_BADGE_LINE_SPACING),
        ) {
            CityBadgeLine(
                text = streetName,
                color = if (highlighted) Color.Black else foreground,
                fontWeight = FontWeight.Bold,
                fontSize = if (compact) 15.sp else CITY_BADGE_STREET_TEXT_SIZE,
            )
            CityBadgeLine(
                text = placeName,
                color = if (highlighted) Color.Black else foreground,
                fontWeight = FontWeight.Bold,
                fontSize = if (compact) 14.sp else CITY_BADGE_PLACE_TEXT_SIZE,
            )
            CityBadgeLine(
                text = districtName,
                color = if (highlighted) Color.Black else foreground,
                fontWeight = FontWeight.SemiBold,
                fontSize = if (compact) 13.sp else CITY_BADGE_DISTRICT_TEXT_SIZE,
            )
        }
    }
}

@Composable
private fun CityBadgeLine(
    text: String,
    color: Color,
    fontWeight: FontWeight,
    fontSize: androidx.compose.ui.unit.TextUnit,
) {
    val hasText = text.isNotBlank()
    Text(
        text = if (hasText) text else " ",
        color = color.copy(alpha = if (hasText) 1f else 0f),
        fontWeight = fontWeight,
        fontSize = fontSize,
        textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth(),
        maxLines = 1,
        minLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
private fun SettingsSheet(
    controller: ConsumerSessionController,
    onDismiss: () -> Unit,
    onOpenDebug: () -> Unit,
) {
    val ui = controller.uiState
    val thresholdInputState = remember(ui.audioAlertThresholdKmh) {
        mutableStateOf(ui.audioAlertThresholdKmh.toString())
    }
    var confirmDeleteDownloaded by rememberSaveable { mutableStateOf(false) }
    SheetScaffold(title = stringResource(R.string.ui_settings_title), onDismiss = onDismiss, testTag = "settings-sheet") {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(16.dp), modifier = Modifier.fillMaxSize()) {
            item {
                SectionCard(stringResource(R.string.ui_screen_orientation)) {
                    Text(stringResource(R.string.ui_screen_orientation_help), color = Color(0xFF555555), fontSize = 13.sp)
                    ManualOrientation.entries.forEach { orientation ->
                        val label = stringResource(when (orientation) {
                            ManualOrientation.PORTRAIT -> R.string.ui_orientation_portrait
                            ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT -> R.string.ui_orientation_landscape_lower_right
                            ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT -> R.string.ui_orientation_landscape_upper_left
                        })
                        Row(
                            Modifier.fillMaxWidth().testTag("orientation-${orientation.storageValue}")
                                .clickable { controller.setManualOrientation(orientation) }.padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = ui.manualOrientation == orientation,
                                onClick = { controller.setManualOrientation(orientation) })
                            Text(label, color = Color.Black)
                        }
                    }
                }
            }
            item { RecorderParitySettings(controller) }
            item {
                SectionCard(stringResource(R.string.ui_audio_alerts)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(stringResource(R.string.ui_spoken_alerts), modifier = Modifier.weight(1f), color = Color.Black)
                        Switch(
                            checked = ui.audioAlertsEnabled,
                            onCheckedChange = controller::setAudioAlertsEnabled,
                            modifier = Modifier.testTag("audio-alert-toggle"),
                        )
                    }
                    OutlinedTextField(
                        value = thresholdInputState.value,
                        onValueChange = {
                            val filtered = it.filter(Char::isDigit).take(2)
                            thresholdInputState.value = filtered
                            controller.setAudioAlertThresholdKmh(filtered.toIntOrNull() ?: 0)
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("audio-alert-threshold"),
                        label = { Text(stringResource(R.string.ui_alert_threshold)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        enabled = ui.audioAlertsEnabled,
                    )
                    Text(
                        text = if (!ui.audioAlertsEnabled) {
                            stringResource(R.string.ui_spoken_alerts_disabled)
                        } else if (ui.audioAlertThresholdKmh == 0) {
                            stringResource(R.string.ui_audio_alerts_disabled)
                        } else {
                            stringResource(R.string.ui_spoken_alert_threshold_detail, ui.audioAlertThresholdKmh)
                        },
                        color = Color(0xFF555555),
                        fontSize = 13.sp,
                    )
                }
            }
            item {
                SectionCard(stringResource(R.string.ui_map_downloads)) {
                    Text(ui.firstLocationPackStatus, fontSize = 13.sp)
                    Text(ui.countryModelPackStatus, fontSize = 13.sp)
                    OutlinedButton(onClick = controller::retryFirstLocationSetup) { Text(stringResource(R.string.ui_retry_location_selection)) }
                    DebugLabel(stringResource(R.string.ui_status), controller.formattedSyncStatus())
                    DebugLabel(stringResource(R.string.ui_map_bundle), ui.activeBundleVersion)
                    syncMessageLine(ui)?.let { (text, color) ->
                        Text(text, color = color, fontSize = 13.sp)
                    }
                    Text(
                        stringResource(R.string.ui_map_downloads_help),
                        color = Color(0xFF555555),
                        fontSize = 13.sp,
                    )
                    if (ui.bundleDownloadSections.isEmpty()) {
                        Text(
                            stringResource(R.string.ui_downloads_unavailable),
                            color = Color(0xFF555555),
                            fontSize = 13.sp,
                        )
                    } else {
                        ui.bundleDownloadSections.forEach { section: BundleDownloadCountrySection ->
                            if (section.options.size == 1) {
                                BundleDownloadOptionRow(
                                    title = section.countryName,
                                    option = section.options.first(),
                                    controller = controller,
                                    ui = ui,
                                )
                            } else {
                                Column(
                                    modifier = Modifier.padding(vertical = 2.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Text(
                                        section.countryName,
                                        color = Color.Black,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                    section.options.forEach { option: BundleDownloadOption ->
                                        BundleDownloadOptionRow(
                                            title = option.displayName,
                                            option = option,
                                            controller = controller,
                                            ui = ui,
                                        )
                                    }
                                }
                            }
                        }
                    }
                    OutlinedButton(
                        onClick = { confirmDeleteDownloaded = true },
                        modifier = Modifier.testTag("settings-delete-bundles-button"),
                    ) {
                        Text(stringResource(R.string.ui_delete_downloaded_maps))
                    }
                    if (ui.maintenanceMessage.isNotBlank()) {
                        Text(ui.maintenanceMessage, color = Color(0xFF555555), fontSize = 13.sp)
                    }
                    if (ui.lastError.isNotBlank()) {
                        Text(ui.lastError, color = SignalRed, fontSize = 13.sp)
                    }
                    if (controller.isSyncingNow() && ui.activeDownloadOptionId == null) {
                        BundleSyncProgressBlock(ui = ui)
                    }
                }
            }
            item {
                SectionCard(stringResource(R.string.ui_penalty_rules)) {
                    DebugLabel(stringResource(R.string.ui_active_file), ui.activePenaltyRules.fileName)
                    DebugLabel(stringResource(R.string.ui_country), "${ui.activePenaltyRules.countryName} (${ui.activePenaltyRules.countryCode})")
                    DebugLabel(stringResource(R.string.ui_penalty_bands), ui.activePenaltyRules.bandCount.toString())
                }
            }
            item {
                SectionCard(stringResource(R.string.onboarding_setup)) {
                    OutlinedButton(
                        onClick = { if (controller.replayOnboarding()) onDismiss() },
                        enabled = controller.canReplayOnboarding(),
                        modifier = Modifier.testTag("settings-replay-onboarding-button"),
                    ) { Text(stringResource(R.string.onboarding_replay)) }
                    Text(stringResource(R.string.onboarding_replay_detail), color = Color(0xFF555555), fontSize = 13.sp)
                }
            }
            item {
                SectionCard(stringResource(R.string.ui_diagnostics)) {
                    Button(
                        onClick = onOpenDebug,
                        colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                        modifier = Modifier.testTag("open-debug-button"),
                    ) {
                        Text(stringResource(R.string.ui_open_diagnostics))
                    }
                }
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }
        }
        if (confirmDeleteDownloaded) {
            AlertDialog(
                onDismissRequest = { confirmDeleteDownloaded = false },
                confirmButton = {
                    Button(onClick = {
                        controller.deleteDownloadedBundlesKeepingSeed()
                        confirmDeleteDownloaded = false
                    }) {
                        Text(stringResource(R.string.ui_delete))
                    }
                },
                dismissButton = {
                    OutlinedButton(onClick = { confirmDeleteDownloaded = false }) { Text(stringResource(R.string.ui_cancel)) }
                },
                title = { Text(stringResource(R.string.ui_delete_maps_title)) },
                text = { Text(stringResource(R.string.ui_delete_maps_message)) },
            )
        }
    }
}

@Composable
private fun DebugSheet(
    controller: ConsumerSessionController,
    onDismiss: () -> Unit,
) {
    val ui = controller.uiState
    SheetScaffold(title = stringResource(R.string.ui_diagnostics), onDismiss = onDismiss, testTag = "debug-sheet") {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(16.dp), modifier = Modifier.fillMaxSize()) {
            item {
                SectionCard(stringResource(R.string.ui_latest_location)) {
                    controller.debugRows().forEach { (key, value) -> DebugLabel(key, value) }
                }
            }
            item {
                SectionCard(stringResource(R.string.ui_map_matcher)) {
                    DebugLabel(stringResource(R.string.ui_active), ui.matcherDebugProfile.debugLabel)
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        MatcherDebugProfile.entries.forEach { profile ->
                            val selected = profile == ui.matcherDebugProfile
                            val colors = if (selected) {
                                ButtonDefaults.buttonColors(containerColor = SignalGreen)
                            } else {
                                ButtonDefaults.outlinedButtonColors()
                            }
                            val buttonModifier = Modifier.fillMaxWidth()
                            if (selected) {
                                Button(
                                    onClick = { controller.setMatcherDebugProfile(profile) },
                                    colors = colors,
                                    modifier = buttonModifier,
                                ) {
                                    Text(profile.debugLabel)
                                }
                            } else {
                                OutlinedButton(
                                    onClick = { controller.setMatcherDebugProfile(profile) },
                                    modifier = buttonModifier,
                                ) {
                                    Text(profile.debugLabel)
                                }
                            }
                        }
                    }
                }
            }
            controller.currentOsmUrl()?.let { osmUrl ->
                item {
                    SectionCard("OSM") {
                        DebugLabel(stringResource(R.string.ui_osm_way), ui.limitWayId ?: "n/a")
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.AutoMirrored.Filled.OpenInNew, contentDescription = null, tint = Color(0xFF555555))
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(osmUrl, color = Color(0xFF555555), fontSize = 12.sp)
                        }
                        Button(
                            onClick = controller::openCurrentOsmUrl,
                            colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                            modifier = Modifier.testTag("debug-open-osm-button"),
                        ) {
                            Text(stringResource(R.string.ui_open_browser))
                        }
                    }
                }
            }
            item {
                SectionCard(stringResource(R.string.ui_logs)) {
                    if (ui.gpsLogPath.isBlank() && ui.matchLogPath.isBlank()) {
                        Text(stringResource(R.string.ui_no_logs), color = Color(0xFF555555))
                    }
                    if (ui.gpsLogPath.isNotBlank()) {
                        DebugLabel("GPS-CSV", ui.gpsLogPath)
                        Button(
                            onClick = controller::shareGpsLog,
                            colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                            modifier = Modifier.testTag("debug-share-gps-log-button"),
                        ) {
                            Text(stringResource(R.string.ui_share_gps))
                        }
                    }
                    if (ui.matchLogPath.isNotBlank()) {
                        DebugLabel(stringResource(R.string.ui_matcher_log), ui.matchLogPath)
                        OutlinedButton(
                            onClick = controller::shareMatchLog,
                            modifier = Modifier.testTag("debug-share-match-log-button"),
                        ) {
                            Text(stringResource(R.string.ui_share_matcher_log))
                        }
                    }
                    if (ui.runtimeDiagnosticsLogPath.isNotBlank()) {
                        DebugLabel(stringResource(R.string.ui_diagnostics_log), ui.runtimeDiagnosticsLogPath)
                        OutlinedButton(
                            onClick = controller::shareRuntimeDiagnosticsLog,
                            modifier = Modifier.testTag("debug-share-runtime-diagnostics-log-button"),
                        ) {
                            Text(stringResource(R.string.ui_share_diagnostics_log))
                        }
                        OutlinedButton(
                            onClick = controller::clearRuntimeDiagnosticsLog,
                            modifier = Modifier.testTag("debug-clear-runtime-diagnostics-log-button"),
                        ) {
                            Text(stringResource(R.string.ui_clear_diagnostics_log))
                        }
                    }
                    OutlinedButton(
                        onClick = controller::clearDrivingLogs,
                        modifier = Modifier.testTag("debug-clear-logs-button"),
                    ) {
                        Text(stringResource(R.string.ui_clear_driving_log))
                    }
                }
            }
            if (ui.lastError.isNotBlank()) {
                item {
                    SectionCard(stringResource(R.string.ui_error)) {
                        Text(ui.lastError, color = SignalRed)
                    }
                }
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LocalRecordingsSheet(
    controller: ConsumerSessionController,
    onDismiss: () -> Unit,
) {
    val ui = controller.uiState
    SheetScaffold(title = stringResource(R.string.ui_recordings_title), onDismiss = onDismiss, testTag = "local-recordings-sheet") {
        Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(
                stringResource(R.string.ui_capture_help),
                color = Color(0xFF555555),
                fontSize = 13.sp,
            )
            var showVideos by rememberSaveable { mutableStateOf(false) }
            OutlinedButton(onClick = { showVideos = true }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.ui_dashcam_title) + " (${ui.dashcamRecordings.size})")
            }
            if (showVideos) SheetScaffold(title = stringResource(R.string.ui_dashcam_title), onDismiss = { showVideos = false }, testTag = "dashcam-library-sheet") {
                DashcamLibraryContent(controller)
            }
            if (ui.localObservations.isEmpty()) {
                SectionCard(stringResource(R.string.ui_status)) {
                    Text(stringResource(R.string.ui_no_observations), color = Color(0xFF555555))
                }
            } else {
                LazyColumn(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(
                        items = ui.localObservations,
                        key = { observation: LocalObservation -> observation.id },
                    ) { observation: LocalObservation ->
                        ElevatedCard(
                            colors = CardDefaults.elevatedCardColors(containerColor = Paper),
                            modifier = Modifier.testTag("local-observation-row"),
                        ) {
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(16.dp),
                                verticalArrangement = Arrangement.spacedBy(10.dp),
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                        Text(observation.capturedAtUTC, color = Color(0xFF777777), fontSize = 12.sp)
                                        Text(observation.streetContext?.trim().orEmpty().ifBlank { stringResource(R.string.ui_street_unknown) }, color = Color.Black, fontWeight = FontWeight.SemiBold)
                                        if (observation.modality == LocalObservationModality.COMPUTER_VISION) {
                                            Text(
                                                stringResource(R.string.ui_camera_observation, observation.evidenceSummary?.let { " • $it" }.orEmpty()),
                                                color = CameraEvidenceAccent,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.SemiBold,
                                            )
                                        }
                                        Text(
                                            observationStateLabel(observation.state),
                                            color = observationStateForeground(observation.state),
                                            fontSize = 12.sp,
                                            fontWeight = FontWeight.Bold,
                                            modifier = Modifier
                                                .clip(RoundedCornerShape(999.dp))
                                                .background(observationStateBackground(observation.state))
                                                .padding(horizontal = 10.dp, vertical = 4.dp),
                                        )
                                        Text(
                                            stringResource(
                                                R.string.ui_observation_values,
                                                observation.oldSpeedKmh?.toString() ?: "–",
                                                observation.newSpeedValue?.let { formatObservationValue(it) }.orEmpty().ifBlank { observation.newSpeedKmh?.toString() ?: "–" },
                                            ),
                                            color = Color.Black,
                                        )
                                        observation.wayId?.let { Text(stringResource(R.string.ui_observation_way, it), color = Color(0xFF777777), fontSize = 12.sp) }
                                    }
                                    IconButton(onClick = { controller.deleteLocalObservation(observation.id) }) {
                                        Icon(Icons.Default.Delete, contentDescription = stringResource(R.string.ui_delete_observation))
                                    }
                                }
                                when (observation.state) {
                                    LocalObservationState.LOCAL_ONLY,
                                    LocalObservationState.NEEDS_REVIEW -> {
                                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
                                            verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                            OutlinedButton(onClick = { controller.approveLocalObservation(observation.id) }) {
                                                Text(stringResource(R.string.ui_approve))
                                            }
                                            OutlinedButton(onClick = { controller.discardLocalObservation(observation.id) }) {
                                                Text(stringResource(R.string.ui_discard))
                                            }
                                        }
                                    }

                                    LocalObservationState.APPROVED_FOR_EXPORT -> {
                                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp),
                                            verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                            Button(
                                                onClick = { controller.exportLocalObservation(observation.id) },
                                                colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                                            ) {
                                                Text(stringResource(R.string.ui_export))
                                            }
                                            OutlinedButton(onClick = { controller.discardLocalObservation(observation.id) }) {
                                                Text(stringResource(R.string.ui_discard))
                                            }
                                        }
                                    }

                                    else -> Unit
                                }
                            }
                        }
                    }
                }
            }
            if (ui.localObservationStatus.isNotBlank()) {
                Text(ui.localObservationStatus, color = Color(0xFF555555), fontSize = 13.sp)
            }
            if (ui.lastExportDirectoryPath.isNotBlank()) {
                Text(stringResource(R.string.ui_export_directory, ui.lastExportDirectoryPath), color = Color(0xFF555555), fontSize = 12.sp)
            }
            FlowRow(
                modifier = Modifier.fillMaxWidth().testTag("local-recordings-actions"),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Button(
                    onClick = controller::exportAllLocalObservations,
                    colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                    modifier = Modifier.heightIn(min = 48.dp).testTag("local-export-button"),
                ) {
                    Icon(Icons.Default.Download, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(stringResource(R.string.ui_export_osc))
                }
                OutlinedButton(
                    onClick = controller::deleteAllLocalObservations,
                    modifier = Modifier.heightIn(min = 48.dp).testTag("local-delete-all-button"),
                ) {
                    Icon(Icons.Default.Delete, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(stringResource(R.string.ui_delete_all))
                }
            }
        }
    }
}

@Composable
private fun LegalSheet(
    ui: ConsumerUiState,
    onDismiss: () -> Unit,
) {
    var openAttributions by rememberSaveable { mutableStateOf(false) }
    SheetScaffold(title = stringResource(R.string.ui_legal_title), onDismiss = onDismiss, testTag = "legal-sheet") {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            OutlinedButton(onClick = { openAttributions = true }, modifier = Modifier.fillMaxWidth().testTag("attribution-button")) {
                Text(stringResource(R.string.credits_title))
            }
            SectionCard(stringResource(R.string.ui_legal_notice)) {
                Text(stringResource(R.string.legal_disclaimer_long), color = Color.Black)
            }
            Text(ui.legalText.ifBlank { stringResource(R.string.ui_legal_missing) }, color = Color.Black, lineHeight = 22.sp)
        }
    }
    if (openAttributions) AttributionSheet(onDismiss = { openAttributions = false })
}

private data class RuntimeBanner(
    val text: String,
    val background: Color,
    val foreground: Color,
)

@Composable
private fun formatObservationValue(value: String): String {
    return if (value == "walk") stringResource(R.string.ui_pedestrian_zone) else value
}

@Composable
private fun observationStateLabel(state: LocalObservationState): String {
    return when (state) {
        LocalObservationState.LOCAL_ONLY -> stringResource(R.string.ui_observation_local)
        LocalObservationState.NEEDS_REVIEW -> stringResource(R.string.ui_observation_review)
        LocalObservationState.APPROVED_FOR_EXPORT -> stringResource(R.string.ui_observation_approved)
        LocalObservationState.EXPORTED_OSC -> stringResource(R.string.ui_observation_exported)
        LocalObservationState.DISCARDED -> stringResource(R.string.ui_observation_discarded)
    }
}

private fun observationStateBackground(state: LocalObservationState): Color {
    return when (state) {
        LocalObservationState.LOCAL_ONLY -> Color(0xFFFFF0D2)
        LocalObservationState.NEEDS_REVIEW -> Color(0xFFFDE1D7)
        LocalObservationState.APPROVED_FOR_EXPORT -> Color(0xFFDDF1E4)
        LocalObservationState.EXPORTED_OSC -> Color(0xFFDCEAF9)
        LocalObservationState.DISCARDED -> Color(0xFFE8E8E8)
    }
}

private fun observationStateForeground(state: LocalObservationState): Color {
    return when (state) {
        LocalObservationState.LOCAL_ONLY -> Color(0xFF7B5600)
        LocalObservationState.NEEDS_REVIEW -> SignalRed
        LocalObservationState.APPROVED_FOR_EXPORT -> SignalGreen
        LocalObservationState.EXPORTED_OSC -> HighwayBlue
        LocalObservationState.DISCARDED -> Color(0xFF606060)
    }
}

@Composable
private fun runtimeBanner(ui: ConsumerUiState): RuntimeBanner? {
    return when (ui.driveStatus) {
        "requesting_location" -> RuntimeBanner(
            text = stringResource(R.string.ui_location_permission_requested),
            background = Color(0xFFFFF3D8),
            foreground = Color(0xFF6B5200),
        )
        "location_denied" -> RuntimeBanner(
            text = stringResource(R.string.ui_location_permission_denied),
            background = Color(0xFFF7D9D6),
            foreground = SignalRed,
        )
        "location_error" -> RuntimeBanner(
            text = stringResource(R.string.ui_location_error),
            background = Color(0xFFF7D9D6),
            foreground = SignalRed,
        )
        else -> if (ui.activeDBPath.isBlank()) {
            RuntimeBanner(
                text = stringResource(R.string.ui_no_active_map),
                background = Color(0xFFFFF3D8),
                foreground = Color(0xFF6B5200),
            )
        } else {
            null
        }
    }
}

@Composable
private fun speechModelStateLabel(state: GermanSpeechModelState): String = when (state) {
    GermanSpeechModelState.CHECKING -> stringResource(R.string.ui_speech_checking)
    GermanSpeechModelState.DOWNLOADING -> stringResource(R.string.ui_speech_unpacking)
    GermanSpeechModelState.PENDING -> stringResource(R.string.ui_speech_pending)
    GermanSpeechModelState.READY -> stringResource(R.string.ui_speech_ready)
    GermanSpeechModelState.UNAVAILABLE -> stringResource(R.string.ui_speech_unavailable)
}

@Composable
internal fun SheetScaffold(
    title: String,
    onDismiss: () -> Unit,
    testTag: String,
    content: @Composable BoxScope.() -> Unit,
) {
    Dialog(
        onDismissRequest = onDismiss,
        // Compose 1.6's non-default width mode ignores the window's measure limits
        // and fixes its size from a retained themed context. Let WindowManager
        // resize the dialog instead, including when this open sheet rotates.
        properties = DialogProperties(usePlatformDefaultWidth = true, decorFitsSystemWindows = false),
    ) {
        val window = (LocalView.current.parent as DialogWindowProvider).window
        SideEffect {
            if (window.attributes.width != WindowManager.LayoutParams.MATCH_PARENT ||
                window.attributes.height != WindowManager.LayoutParams.MATCH_PARENT) {
                window.setLayout(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT)
            }
        }
        Surface(
            modifier = Modifier
                .fillMaxSize()
                .safeDrawingPadding()
                .padding(12.dp)
                .semantics { testTagsAsResourceId = true }
                .testTag(testTag),
            shape = RoundedCornerShape(28.dp),
            color = Paper,
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("$testTag-header")
                        .padding(horizontal = 18.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(onClick = onDismiss, modifier = Modifier.size(48.dp).testTag("$testTag-close")) {
                        Icon(Icons.Default.Close, contentDescription = stringResource(R.string.ui_done), tint = Color.Black)
                    }
                    Spacer(Modifier.width(8.dp))
                    Text(title, fontWeight = FontWeight.Bold, fontSize = 22.sp, color = Color.Black,
                        maxLines = 2, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f).testTag("$testTag-title"))
                }
                HorizontalDivider()
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .testTag("$testTag-content")
                        .padding(16.dp),
                    content = content,
                )
            }
        }
    }
}

@Composable
private fun SectionCard(
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    ElevatedCard(colors = CardDefaults.elevatedCardColors(containerColor = SoftCard)) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(title, color = Color.Black, fontWeight = FontWeight.Bold)
            content()
        }
    }
}

@Composable
private fun DebugLabel(key: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(key, color = Color(0xFF666666), modifier = Modifier.weight(1f))
        Spacer(modifier = Modifier.width(12.dp))
        Text(value, color = Color.Black, textAlign = TextAlign.End, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun LinearProgress(progress: Double) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(10.dp)
            .clip(RoundedCornerShape(999.dp))
            .background(Color.White.copy(alpha = 0.12f)),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(progress.coerceIn(0.0, 1.0).toFloat())
                .height(10.dp)
                .background(SoftRed),
        )
    }
}

@Composable
private fun BundleDownloadOptionRow(
    title: String,
    option: BundleDownloadOption,
    controller: ConsumerSessionController,
    ui: ConsumerUiState,
) {
    val context = LocalContext.current
    val downloaded = controller.isBundleDownloaded(option)
    val isActiveDownload = controller.isActiveBundleDownload(option)
    val progress = controller.activeBundleDownloadProgress(option)
    val statusText = controller.downloadedBundleStatusText(option)
    val progressText = if (isActiveDownload) {
        progressBytesText(
            context = context,
            completedBytes = ui.syncProgressCompletedBytes,
            totalBytes = ui.syncProgressTotalBytes,
        )
    } else {
        ""
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 42.dp)
            .padding(vertical = 1.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(
                text = title,
                color = Color.Black,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )

            if (statusText.isNotBlank()) {
                Text(
                    text = statusText,
                    color = if (downloaded) SignalGreen else Color(0xFF666666),
                    fontSize = 12.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            if (isActiveDownload) {
                if (progress != null) {
                    LinearProgress(progress)
                } else {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
                if (progressText.isNotBlank()) {
                    Text(
                        text = progressText,
                        color = Color(0xFF666666),
                        fontSize = 12.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }

        Spacer(modifier = Modifier.width(8.dp))

        when {
            downloaded -> {
                IconButton(
                    onClick = { controller.deleteSelectedBundle(option) },
                    enabled = !controller.isSyncingNow(),
                    modifier = Modifier.size(30.dp),
                ) {
                    Icon(
                        imageVector = Icons.Default.Delete,
                        contentDescription = stringResource(R.string.ui_delete_bundle),
                        tint = SignalRed,
                    )
                }
            }
            isActiveDownload -> {
                DownloadActionIcon(
                    tint = Color(0xFF777777),
                    enabled = false,
                    onClick = null,
                )
            }
            else -> {
                DownloadActionIcon(
                    tint = Color.Black,
                    enabled = !controller.isSyncingNow() && !controller.hasActiveBundleDownload(),
                    onClick = { controller.downloadSelectedBundle(option) },
                )
            }
        }
    }
}

@Composable
private fun PanoramaxGallerySheet(controller: ConsumerSessionController, onDismiss: () -> Unit) {
    var videos by rememberSaveable { mutableStateOf(false) }
    SheetScaffold(title = stringResource(R.string.ui_panoramax_gallery), onDismiss = onDismiss, testTag = "panoramax-gallery-sheet") {
        Column(Modifier.fillMaxSize()) {
            Box(Modifier.weight(1f)) {
                if (videos) DashcamLibraryContent(controller) else PanoramaxGalleryContent(controller)
            }
            NavigationBar {
                NavigationBarItem(
                    selected = !videos,
                    onClick = { videos = false },
                    icon = { Icon(Icons.Default.PhotoLibrary, contentDescription = null) },
                    label = { Text(ConsumerUiStrings.text("Pictures", "Bilder", "Photos", "Foto’s")) },
                )
                NavigationBarItem(
                    selected = videos,
                    onClick = { videos = true },
                    icon = { Icon(Icons.Default.VideoLibrary, contentDescription = null) },
                    label = { Text(ConsumerUiStrings.text("Videos", "Videos", "Vidéos", "Video’s")) },
                )
            }
        }
    }
}

@Composable
private fun DownloadActionIcon(
    tint: Color,
    enabled: Boolean,
    onClick: (() -> Unit)?,
) {
    val alpha = if (enabled || onClick == null) 1f else 0.45f
    val modifier = Modifier
        .size(30.dp)
        .clip(CircleShape)
        .border(width = 1.25.dp, color = tint.copy(alpha = alpha), shape = CircleShape)
        .let { baseModifier ->
            if (onClick != null) {
                baseModifier.clickable(enabled = enabled, onClick = onClick)
            } else {
                baseModifier
            }
        }

    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = Icons.Default.Download,
            contentDescription = if (onClick != null) stringResource(R.string.ui_download_bundle) else null,
            tint = tint.copy(alpha = alpha),
            modifier = Modifier.size(16.dp),
        )
    }
}

@Composable
private fun BundleSyncProgressBlock(ui: ConsumerUiState) {
    val context = LocalContext.current
    val progress = syncProgressValue(ui)
    val bytesText = progressBytesText(
        context = context,
        completedBytes = ui.syncProgressCompletedBytes,
        totalBytes = ui.syncProgressTotalBytes,
    )

    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (ui.syncProgressDetail.isNotBlank()) {
            Text(ui.syncProgressDetail, color = Color.Black, fontSize = 13.sp)
        }
        if (progress != null) {
            LinearProgress(progress)
        } else {
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
        if (bytesText.isNotBlank()) {
            Text(bytesText, color = Color(0xFF666666), fontSize = 12.sp)
        }
    }
}

private fun syncProgressValue(ui: ConsumerUiState): Double? {
    val total = ui.syncProgressTotalBytes.coerceAtLeast(0L)
    if (total <= 0L) {
        return null
    }
    val completed = ui.syncProgressCompletedBytes.coerceAtLeast(0L).coerceAtMost(total)
    return completed.toDouble() / total.toDouble()
}

private fun progressBytesText(
    context: Context,
    completedBytes: Long,
    totalBytes: Long,
): String {
    val normalizedCompletedBytes = completedBytes.coerceAtLeast(0L)
    val normalizedTotalBytes = totalBytes.coerceAtLeast(0L)
    return when {
        normalizedTotalBytes > 0L -> {
            "${Formatter.formatShortFileSize(context, normalizedCompletedBytes.coerceAtMost(normalizedTotalBytes))} / ${Formatter.formatShortFileSize(context, normalizedTotalBytes)}"
        }
        normalizedCompletedBytes > 0L -> Formatter.formatShortFileSize(context, normalizedCompletedBytes)
        else -> ""
    }
}

@Composable
private fun syncMessageLine(ui: ConsumerUiState): Pair<String, Color>? {
    return when (ui.syncStatus) {
        "ready_upToDate", "ready_up_to_date" -> stringResource(R.string.ui_sync_current) to SignalGreen
        "ready_fullDownload", "ready_full_download", "ready_deltaPatch", "ready_delta_patch" -> stringResource(R.string.ui_sync_complete) to SignalGreen
        "ready_bootstrap" -> stringResource(R.string.ui_sync_seed) to SignalOrange
        "sync_failed" -> {
            if (ui.activeDBPath.isNotBlank()) {
                stringResource(R.string.ui_sync_failed_local) to SignalOrange
            } else {
                stringResource(R.string.ui_sync_failed_no_map) to SignalRed
            }
        }
        else -> null
    }
}

private fun mainBackgroundColor(ui: ConsumerUiState, pulseFraction: Float): Color {
    if (ConsumerMainScreenLogic.isInSpeedCaptureMode(ui)) {
        return Paper
    }
    if (ui.isUnlimitedSpeedLimitActive) {
        return HighwayBlue
    }
    if (ConsumerMainScreenLogic.isDrivingBanWarningActive(ui)) {
        return lerp(NightRed, NightRedDark, 0.25f + (pulseFraction * 0.75f))
    }
    val progress = ConsumerMainScreenLogic.overspeedBackgroundProgress(ui) ?: return Color.Black
    return when {
        progress < 0.6 -> lerp(BrightYellow, SoftOrange, (progress / 0.6).toFloat())
        else -> lerp(SoftOrange, SoftRed, ((progress - 0.6) / 0.4).toFloat())
    }
}
