@file:OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class)

package de.youspeed.android.alpha

import android.content.Context
import android.graphics.Paint as AndroidPaint
import android.graphics.Typeface
import android.text.format.Formatter
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.systemBars
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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material.icons.filled.WifiOff
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
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
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
private val CameraEvidenceAccent = Color(0xFF7B0E17)
private val BrightYellow = Color(0xFFF9D950)
private val SoftOrange = Color(0xFFF39A24)
private val SoftRed = Color(0xFFC5212E)
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
private val GPS_BADGE_MIN_HEIGHT = 58.dp
private val LOCATION_SLOT_MIN_HEIGHT = 84.dp
private val CONTROL_BUTTON_DIAMETER = 44.dp
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
    var dismissedWelcomeThisSession by rememberSaveable { mutableStateOf(false) }
    var openSettings by rememberSaveable { mutableStateOf(false) }
    var openLegal by rememberSaveable { mutableStateOf(false) }
    var openDebug by rememberSaveable { mutableStateOf(false) }
    var openLocalRecordings by rememberSaveable { mutableStateOf(false) }

    LaunchedEffect(ui.startupDataState, ui.appScreenshotState) {
        if (ui.appScreenshotState == null && ui.startupDataState == StartupDataState.READY && ui.driveStatus == "stopped") {
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
                        ui = ui,
                        onOpenSettings = { openSettings = true },
                        onOpenLegal = { openLegal = true },
                        onOpenDebug = { openDebug = true },
                        onOpenLocalRecordings = { openLocalRecordings = true },
                        onCapture = controller::beginSpeedCapture,
                    )
                }

                controller.shouldPresentWelcome(Instant.now()) && !dismissedWelcomeThisSession -> {
                    WelcomeScreen(
                        ui = ui,
                        onOpenSettings = {
                            dismissedWelcomeThisSession = true
                            openSettings = true
                        },
                        onContinue = {
                            dismissedWelcomeThisSession = true
                        },
                        onHideWelcomeChanged = controller::setHideWelcomeScreen,
                    )
                }

                ui.startupDataState == StartupDataState.READY -> {
                    MainScreen(
                        ui = ui,
                        onOpenSettings = { openSettings = true },
                        onOpenLegal = { openLegal = true },
                        onOpenDebug = { openDebug = true },
                        onOpenLocalRecordings = { openLocalRecordings = true },
                        onCapture = controller::beginSpeedCapture,
                    )
                }

                else -> {
                    StartupScreen(
                        ui = ui,
                        onRetry = controller::retryStartupDataPreparation,
                    )
                }
            }

            if (openSettings) {
                SettingsSheet(
                    controller = controller,
                    onDismiss = { openSettings = false },
                    onOpenDebug = { openDebug = true },
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
        }
    }
}

@Composable
private fun StartupScreen(
    ui: ConsumerUiState,
    onRetry: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .testTag("startup-root")
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(18.dp),
            modifier = Modifier.widthIn(max = 420.dp),
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
                    modifier = Modifier.testTag("startup-retry-button"),
                ) {
                    Text(stringResource(R.string.startup_retry), style = roundedUiTextStyle(size = 17.sp, weight = FontWeight.Bold))
                }
            }
        }
    }
}

@Composable
private fun WelcomeScreen(
    ui: ConsumerUiState,
    onOpenSettings: () -> Unit,
    onContinue: () -> Unit,
    onHideWelcomeChanged: (Boolean) -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .testTag("welcome-root"),
    ) {
        Column(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 24.dp)
                .widthIn(max = 560.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            Text(
                stringResource(R.string.welcome_title),
                color = Color.White,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
                style = roundedUiTextStyle(size = 34.sp, weight = FontWeight.Bold),
            )
            Text(
                stringResource(R.string.welcome_copy),
                color = Color.White.copy(alpha = 0.92f),
                textAlign = TextAlign.Center,
                style = roundedUiTextStyle(size = 18.sp, weight = FontWeight.SemiBold),
            )
            CoverageCard(activeBundleVersion = ui.activeBundleVersion)
            Text(
                if (ui.activeBundleVersion == "seed" || ui.activeBundleVersion == "none") {
                    stringResource(R.string.welcome_scope_seed)
                } else {
                    stringResource(R.string.welcome_scope_active, ui.activeBundleVersion)
                },
                color = Color.White.copy(alpha = 0.88f),
                textAlign = TextAlign.Center,
                style = roundedUiTextStyle(size = 15.sp, weight = FontWeight.Medium),
            )
            Card(colors = CardDefaults.cardColors(containerColor = Color(0x33FFD54F))) {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        stringResource(R.string.welcome_legal_heading),
                        color = Color.Yellow,
                        style = roundedUiTextStyle(size = 14.sp, weight = FontWeight.Bold),
                    )
                    Text(
                        stringResource(R.string.legal_disclaimer_short),
                        color = Color.White.copy(alpha = 0.86f),
                        style = roundedUiTextStyle(size = 13.sp, weight = FontWeight.Normal),
                    )
                }
            }
            Card(colors = CardDefaults.cardColors(containerColor = Color.White.copy(alpha = 0.08f))) {
                Text(
                    stringResource(R.string.welcome_osm_credit),
                    color = Color.White.copy(alpha = 0.76f),
                    modifier = Modifier.padding(12.dp),
                    style = roundedUiTextStyle(size = 13.sp, weight = FontWeight.Normal),
                )
            }
            Button(
                onClick = onOpenSettings,
                colors = ButtonDefaults.buttonColors(containerColor = SoftRed),
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("welcome-open-settings-button"),
            ) { Text(stringResource(R.string.welcome_open_settings), style = roundedUiTextStyle(size = 17.sp, weight = FontWeight.Bold)) }
            OutlinedButton(
                onClick = onContinue,
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("welcome-continue-button"),
            ) {
                Text(
                    stringResource(R.string.welcome_continue),
                    color = Color.White,
                    style = roundedUiTextStyle(size = 17.sp, weight = FontWeight.Bold),
                )
            }
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onHideWelcomeChanged(!ui.hideWelcomeScreen) }
                    .testTag("welcome-hide-toggle"),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                androidx.compose.material3.Checkbox(checked = ui.hideWelcomeScreen, onCheckedChange = onHideWelcomeChanged)
                Text(
                    stringResource(R.string.welcome_hide),
                    color = Color.White.copy(alpha = 0.92f),
                    style = roundedUiTextStyle(size = 15.sp, weight = FontWeight.SemiBold),
                )
            }
        }
    }
}

@Composable
private fun CoverageCard(activeBundleVersion: String) {
    val hasGermanyDataset = activeBundleVersion != "seed" && activeBundleVersion != "none"
    Card(colors = CardDefaults.cardColors(containerColor = Color.White.copy(alpha = 0.08f))) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Canvas(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(180.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .background(Color.White.copy(alpha = 0.06f)),
            ) {
                val germanyColor = if (hasGermanyDataset) Color(0xFF2F66CC) else Color.White.copy(alpha = 0.92f)
                val outline = if (hasGermanyDataset) Color.White else Color.Black.copy(alpha = 0.75f)
                drawRoundRect(
                    color = germanyColor,
                    topLeft = Offset(size.width * 0.24f, size.height * 0.10f),
                    size = Size(size.width * 0.44f, size.height * 0.78f),
                    cornerRadius = CornerRadius(26f, 26f),
                )
                if (hasGermanyDataset) {
                    val badgePath = Path().apply {
                        addRoundRect(
                            androidx.compose.ui.geometry.RoundRect(
                                left = size.width * 0.36f,
                                top = size.height * 0.34f,
                                right = size.width * 0.48f,
                                bottom = size.height * 0.48f,
                                cornerRadius = CornerRadius(16f, 16f),
                            ),
                        )
                    }
                    drawPath(badgePath, color = Color.White, style = Stroke(width = 6f))
                }
                drawRoundRect(
                    color = outline,
                    topLeft = Offset(size.width * 0.24f, size.height * 0.10f),
                    size = Size(size.width * 0.44f, size.height * 0.78f),
                    cornerRadius = CornerRadius(26f, 26f),
                    style = Stroke(width = 3f),
                )
            }
            Text(
                "Deutschland",
                color = Color.White.copy(alpha = 0.84f),
                style = roundedUiTextStyle(size = 11.sp, weight = FontWeight.SemiBold),
            )
            Text(
                stringResource(
                    if (hasGermanyDataset) R.string.welcome_coverage_active else R.string.welcome_coverage_none,
                ),
                color = if (hasGermanyDataset) Color(0xFF6FB0FF) else Color.White.copy(alpha = 0.72f),
                style = roundedUiTextStyle(size = 11.sp, weight = FontWeight.SemiBold),
            )
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
    ui: ConsumerUiState,
    onOpenSettings: () -> Unit,
    onOpenLegal: () -> Unit,
    onOpenDebug: () -> Unit,
    onOpenLocalRecordings: () -> Unit,
    onCapture: () -> Unit,
) {
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
    val usesDarkForeground = ConsumerMainScreenLogic.usesDarkForeground(ui)
    val foreground = if (usesDarkForeground) Color.Black else Color.White
    val buttonBg = if (usesDarkForeground) Color.Black.copy(alpha = 0.08f) else Color.White.copy(alpha = 0.14f)
    val buttonBorder = foreground.copy(alpha = 0.95f)
    val insets = WindowInsets.systemBars.asPaddingValues()
    val primaryMetric = ConsumerMainScreenLogic.primaryMetricText(ui)
    val secondaryMetric = ConsumerMainScreenLogic.secondaryMetricText(ui)
    val limitText = ConsumerMainScreenLogic.limitText(ui)
    val runtimeBanner = runtimeBanner(ui)
    val showsPedestrianZoneSign = ConsumerMainScreenLogic.showsPedestrianZoneSign(ui)

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(background)
            .testTag("main-root")
            .padding(top = insets.calculateTopPadding(), bottom = insets.calculateBottomPadding()),
    ) {
        val minDimensionDp = min(maxWidth.value, maxHeight.value).dp
        val compactPhoneLayout = maxHeight.value < 780f
        val screenInset = (minDimensionDp.value * 0.02f).dp
        val signWidthFactor = if (compactPhoneLayout) 0.62f else 0.74f
        val signSize = min(maxWidth.value * signWidthFactor, maxWidth.value - (screenInset.value * 2f)).dp
        val primaryMetricScale = if (compactPhoneLayout) 0.42f else SPEED_LIMIT_NUMBER_SCALE
        val primaryMetricFont = (signSize.value * primaryMetricScale).sp
        val secondaryScale = sharedSecondaryScale(
            baseSecondaryFontSp = primaryMetricFont.value * SECONDARY_TEXT_RATIO,
            availableWidthSp = maxWidth.value - (max(12f, maxWidth.value * 0.04f) * 2f),
        )
        val secondaryFont = primaryMetricFont * (SECONDARY_TEXT_RATIO * secondaryScale)
        val debugFont = secondaryFont * 0.6f
        val metricDebugGap = max(12f, minDimensionDp.value * 0.024f).dp
        val debugSpacing = max(2f, minDimensionDp.value * 0.004f).dp
        val metricSlotMinHeight = with(LocalDensity.current) {
            (primaryMetricFont.toDp() * 1.05f) + (secondaryFont.toDp() * 1.2f)
        }
        val locationSlotMinHeight = if (ConsumerMainScreenLogic.isInSpeedCaptureMode(ui)) {
            0.dp
        } else {
            max(LOCATION_SLOT_MIN_HEIGHT.value, minDimensionDp.value * 0.225f).dp
        }
        val contentHorizontalPadding = max(12f, maxWidth.value * 0.04f).dp
        val bottomButtonGapWidth = max(
            0f,
            maxWidth.value - (screenInset.value * 2f) - (CONTROL_BUTTON_DIAMETER.value * 2f),
        ).dp

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(top = screenInset, bottom = CONTROL_BUTTON_DIAMETER + 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            TopCornerButtons(
                screenInset = screenInset,
                foreground = foreground,
                buttonBg = buttonBg,
                buttonBorder = buttonBorder,
                gpsSignalBars = ui.gpsSignalBars,
                gpsHorizontalAccuracyM = ui.gpsHorizontalAccuracyM,
                onOpenLocalRecordings = onOpenLocalRecordings,
            )

            Spacer(modifier = Modifier.weight(1f))

            val showsActiveCameraLimitIndicator = CameraSpeedLimitUsePresentation.isVisible(
                isInSpeedCaptureMode = ConsumerMainScreenLogic.isInSpeedCaptureMode(ui),
                source = ui.effectiveSpeedLimitSource,
                hasResolvedValue = ui.speedLimitKmh != null || ui.speedLimitDisplayText != null ||
                    ui.isUnlimitedSpeedLimitActive,
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(signSize),
                contentAlignment = Alignment.Center,
            ) {
                if (showsActiveCameraLimitIndicator) {
                    ActiveCameraSpeedLimitEye(
                        signSize = signSize,
                        screenInset = screenInset,
                    )
                }
                SpeedLimitSign(
                    limitText = limitText,
                    signSize = signSize,
                    numberFontSize = primaryMetricFont,
                    showsUnlimitedIcon = !showsPedestrianZoneSign &&
                        ui.isUnlimitedSpeedLimitActive &&
                        !ConsumerMainScreenLogic.isInSpeedCaptureMode(ui),
                    showsPedestrianZoneIcon = showsPedestrianZoneSign,
                    showsActiveCameraLimitIndicator = showsActiveCameraLimitIndicator,
                    cameraSourceStateDescription = when {
                        ui.isUnlimitedSpeedLimitActive -> "Durch Kamera erkannt: keine Geschwindigkeitsbegrenzung"
                        ui.speedLimitDisplayText == "Schritt" -> "Durch Kamera erkannt: Schrittgeschwindigkeit"
                        ui.speedLimitKmh != null -> "Tempolimit ${ui.speedLimitKmh}, durch Kamera erkannt"
                        else -> "Durch Kamera erkanntes Verkehrszeichen"
                    },
                    onDoubleTap = onCapture,
                )
            }

            Spacer(modifier = Modifier.weight(1f))

            MetricStatusBlock(
                displayedPrimaryMetric = primaryMetric,
                secondaryMetric = secondaryMetric,
                foreground = foreground,
                ui = ui,
                primaryMetricFont = primaryMetricFont,
                secondaryFont = secondaryFont,
                metricSlotMinHeight = metricSlotMinHeight,
            )

            Spacer(modifier = Modifier.weight(1f))

            LocationStatusBlock(
                ui = ui,
                foreground = foreground,
                debugFont = debugFont,
                debugSpacing = debugSpacing,
                metricDebugGap = metricDebugGap,
                locationSlotMinHeight = locationSlotMinHeight,
                contentHorizontalPadding = contentHorizontalPadding,
                locationBadgeWidth = bottomButtonGapWidth,
                runtimeBanner = runtimeBanner,
                onOpenDebug = onOpenDebug,
            )
        }

        BottomCornerButtons(
            horizontalPadding = screenInset,
            foreground = foreground,
            buttonBg = buttonBg,
            buttonBorder = buttonBorder,
            onOpenLegal = onOpenLegal,
            onOpenSettings = onOpenSettings,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .padding(bottom = 12.dp),
        )
    }
}

@Composable
private fun TopCornerButtons(
    screenInset: androidx.compose.ui.unit.Dp,
    foreground: Color,
    buttonBg: Color,
    buttonBorder: Color,
    gpsSignalBars: Int,
    gpsHorizontalAccuracyM: Double?,
    onOpenLocalRecordings: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = screenInset),
        verticalAlignment = Alignment.Top,
    ) {
        LocalRecordingsButton(
            onClick = onOpenLocalRecordings,
            foreground = foreground,
            buttonBg = buttonBg,
            buttonBorder = buttonBorder,
        )
        Spacer(modifier = Modifier.weight(1f))
        GpsSignalBadge(
            bars = gpsSignalBars,
            accuracyM = gpsHorizontalAccuracyM,
            foreground = foreground,
        )
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
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = horizontalPadding),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        PillIconButton(
            onClick = onOpenLegal,
            background = buttonBg,
            border = buttonBorder,
            modifier = Modifier.testTag("legal-button"),
        ) {
            Icon(Icons.Default.Info, contentDescription = "Rechtliche Hinweise", tint = foreground)
        }
        PillIconButton(
            onClick = onOpenSettings,
            background = buttonBg,
            border = buttonBorder,
            modifier = Modifier.testTag("settings-button"),
        ) {
            Icon(Icons.Default.Settings, contentDescription = "Einstellungen", tint = foreground)
        }
    }
}

@Composable
private fun LocalRecordingsButton(
    onClick: () -> Unit,
    foreground: Color,
    buttonBg: Color,
    buttonBorder: Color,
) {
    PillIconButton(
        onClick = onClick,
        background = buttonBg,
        border = buttonBorder,
        modifier = Modifier.testTag("local-recordings-button"),
    ) {
        Icon(Icons.Default.BugReport, contentDescription = "Lokale Erfassungen", tint = foreground)
    }
}

@Composable
private fun PillIconButton(
    onClick: () -> Unit,
    background: Color,
    border: Color,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Surface(
        modifier = modifier,
        shape = CircleShape,
        color = background,
        border = androidx.compose.foundation.BorderStroke(1.5.dp, border),
    ) {
        IconButton(onClick = onClick, modifier = Modifier.size(CONTROL_BUTTON_DIAMETER)) {
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
    cameraSourceStateDescription: String?,
    onDoubleTap: () -> Unit,
) {
    val density = LocalDensity.current
    val numberFontPx = with(density) { numberFontSize.toPx() }
    val trafficSignTypeface = rememberTrafficSignTypeface()
    Box(
        modifier = Modifier
            .then(modifier)
            .size(signSize)
            .pointerInput(Unit) { detectTapGestures(onDoubleTap = { onDoubleTap() }) }
            .semantics {
                contentDescription = if (showsActiveCameraLimitIndicator) {
                    cameraSourceStateDescription ?: "Tempolimit $limitText, durch Kamera erkannt"
                } else {
                    "Tempolimit $limitText"
                }
            }
            .testTag("speed-sign"),
        contentAlignment = Alignment.Center,
    ) {
        if (showsPedestrianZoneIcon) {
            Image(
                painter = painterResource(id = R.drawable.ic_pedestrian_zone_sign),
                contentDescription = "Fussgaengerzone",
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Canvas(modifier = Modifier.fillMaxSize()) {
                if (showsUnlimitedIcon) {
                    drawCircle(color = Color.White)
                    drawCircle(color = Color.Black.copy(alpha = 0.82f), style = Stroke(width = size.minDimension * 0.028f))
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
                    drawCircle(color = Color.White)
                    drawCircle(
                        color = if (showsActiveCameraLimitIndicator) Color.White else Color.Black.copy(alpha = 0.75f),
                        style = Stroke(width = size.minDimension * 0.018f),
                    )
                    drawCircle(
                        color = SpeedSignBorderRed,
                        style = Stroke(width = size.minDimension * 0.134f),
                    )
                    val standardBlackBorderWidth = size.minDimension * 0.018f
                    val standardRedBandWidth = size.minDimension * 0.134f
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
        val tipLeftX = inset + controlRadius
        val tipRightX = size.width - inset - controlRadius
        val attachmentYOffset = radius * 0.58f
        val attachmentXOffset = sqrt(max(0f, (radius * radius) - (attachmentYOffset * attachmentYOffset)))
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
                width = max(4f, radius * 0.032f),
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
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = metricSlotMinHeight)
            .padding(horizontal = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
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
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = contentHorizontalPadding),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(debugSpacing),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = locationSlotMinHeight),
            contentAlignment = Alignment.Center,
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
                    horizontal = CITY_BADGE_HORIZONTAL_PADDING,
                    vertical = CITY_BADGE_VERTICAL_PADDING,
                ),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(CITY_BADGE_LINE_SPACING),
        ) {
            CityBadgeLine(
                text = streetName,
                color = if (highlighted) Color.Black else foreground,
                fontWeight = FontWeight.Bold,
                fontSize = CITY_BADGE_STREET_TEXT_SIZE,
            )
            CityBadgeLine(
                text = placeName,
                color = if (highlighted) Color.Black else foreground,
                fontWeight = FontWeight.Bold,
                fontSize = CITY_BADGE_PLACE_TEXT_SIZE,
            )
            CityBadgeLine(
                text = districtName,
                color = if (highlighted) Color.Black else foreground,
                fontWeight = FontWeight.SemiBold,
                fontSize = CITY_BADGE_DISTRICT_TEXT_SIZE,
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
private fun GpsSignalBadge(
    bars: Int,
    accuracyM: Double?,
    foreground: Color,
) {
    val accuracyText = accuracyM?.let { String.format(Locale.US, "%.0f m", it) }
    Column(
        modifier = Modifier
            .heightIn(min = GPS_BADGE_MIN_HEIGHT)
            .testTag("gps-badge"),
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(
                imageVector = if (bars >= 2) Icons.Default.Wifi else Icons.Default.WifiOff,
                contentDescription = null,
                tint = foreground,
                modifier = Modifier.size(44.dp),
            )
            if (bars == 2) {
                Text(
                    "!",
                    color = foreground,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Black,
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            }
        }
        Text(
            accuracyText ?: " ",
            color = foreground.copy(alpha = if (accuracyText == null) 0f else 0.82f),
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
        )
    }
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
    SheetScaffold(title = "Einstellungen", onDismiss = onDismiss, testTag = "settings-sheet") {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(16.dp), modifier = Modifier.fillMaxSize()) {
            item {
                SectionCard("Verkehrszeichenerkennung") {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Live-Kamera (TSR)", modifier = Modifier.weight(1f), color = Color.Black)
                        Switch(
                            checked = ui.trafficSignRecognitionEnabled,
                            onCheckedChange = controller::setTrafficSignRecognitionEnabled,
                            modifier = Modifier.testTag("traffic-sign-recognition-toggle"),
                        )
                    }
                    Text(
                        if (ui.trafficSignRecognitionEnabled) {
                            "Erkannte Schilder werden erst nach dem Vorbeifahren wirksam. Ein verifiziertes Android-Modell muss separat bereitgestellt sein."
                        } else {
                            "Die Kamera-Erkennung ist ausgeschaltet; TSR-Ereignisse werden nicht verarbeitet."
                        },
                        color = Color(0xFF555555),
                        fontSize = 13.sp,
                    )
                }
            }
            item {
                SectionCard("Akustische Hinweise") {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Sprachausgabe", modifier = Modifier.weight(1f), color = Color.Black)
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
                        label = { Text("Warnung ab (km/h)") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        enabled = ui.audioAlertsEnabled,
                    )
                    Text(
                        text = if (!ui.audioAlertsEnabled) {
                            "Sprachausgabe ist deaktiviert."
                        } else if (ui.audioAlertThresholdKmh == 0) {
                            "Akustische Hinweise sind deaktiviert."
                        } else {
                            "Sprachwarnung startet bei ${ui.audioAlertThresholdKmh} km/h ueber dem erkannten Tempolimit."
                        },
                        color = Color(0xFF555555),
                        fontSize = 13.sp,
                    )
                }
            }
            item {
                SectionCard("Offline-Spracherkennung") {
                    DebugLabel("Plattform", "Vosk (gebuendelt)")
                    DebugLabel("Status", speechModelStateLabel(ui.germanSpeechModelState))
                    Text(
                        ui.germanSpeechModelStatus,
                        color = if (ui.germanSpeechModelState == GermanSpeechModelState.READY) Color(0xFF555555) else SignalOrange,
                        fontSize = 13.sp,
                    )
                    Button(
                        onClick = controller::prepareGermanSpeechModel,
                        colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                        modifier = Modifier.testTag("speech-model-install-button"),
                    ) {
                        Text("Offline-Modell neu laden")
                    }
                }
            }
            item {
                SectionCard("Kartendaten-Download") {
                    DebugLabel("Status", controller.formattedSyncStatus())
                    DebugLabel("Bundle", ui.activeBundleVersion)
                    syncMessageLine(ui)?.let { (text, color) ->
                        Text(text, color = color, fontSize = 13.sp)
                    }
                    Text(
                        "Top-10 Laender (A-Z). Bundles koennen einzeln geladen oder geloescht werden.",
                        color = Color(0xFF555555),
                        fontSize = 13.sp,
                    )
                    if (ui.bundleDownloadSections.isEmpty()) {
                        Text(
                            "Keine Downloadliste verfuegbar.",
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
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(
                            onClick = controller::fetchFirstGermanyManifest,
                            colors = ButtonDefaults.buttonColors(containerColor = SignalOrange),
                            modifier = Modifier.testTag("settings-manifest-button"),
                        ) {
                            Text("Manifest testen")
                        }
                        Button(
                            onClick = controller::bootstrapAndSync,
                            colors = ButtonDefaults.buttonColors(containerColor = SoftRed),
                            modifier = Modifier.testTag("settings-sync-button"),
                        ) {
                            Text("Sync starten")
                        }
                    }
                    OutlinedButton(
                        onClick = { confirmDeleteDownloaded = true },
                        modifier = Modifier.testTag("settings-delete-bundles-button"),
                    ) {
                        Text("Heruntergeladene Datenbanken loeschen")
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
                SectionCard("Bussgeldregeln") {
                    DebugLabel("Aktive Datei", ui.activePenaltyRules.fileName)
                    DebugLabel("Land", "${ui.activePenaltyRules.countryName} (${ui.activePenaltyRules.countryCode})")
                    DebugLabel("Stufen", ui.activePenaltyRules.bandCount.toString())
                }
            }
            item {
                SectionCard("Startbildschirm") {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Nicht mehr anzeigen", modifier = Modifier.weight(1f), color = Color.Black)
                        Switch(
                            checked = ui.hideWelcomeScreen,
                            onCheckedChange = controller::setHideWelcomeScreen,
                            modifier = Modifier.testTag("hide-welcome-toggle"),
                        )
                    }
                    Text(
                        if (ui.hideWelcomeScreen) {
                            "Der Startbildschirm wird nicht mehr automatisch angezeigt."
                        } else {
                            "Der Startbildschirm wird bei Seed-Daten oder veralteten Deutschland-Daten angezeigt."
                        },
                        color = Color(0xFF555555),
                        fontSize = 13.sp,
                    )
                }
            }
            item {
                SectionCard("Debug") {
                    Button(
                        onClick = onOpenDebug,
                        colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                        modifier = Modifier.testTag("open-debug-button"),
                    ) {
                        Text("Debug-Informationen oeffnen")
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
                        Text("Loeschen")
                    }
                },
                dismissButton = {
                    OutlinedButton(onClick = { confirmDeleteDownloaded = false }) { Text("Abbrechen") }
                },
                title = { Text("Heruntergeladene Datenbanken loeschen?") },
                text = { Text("Alle heruntergeladenen Bundle-Daten werden entfernt. Der Seed-Datensatz bleibt erhalten.") },
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
    SheetScaffold(title = "Debug", onDismiss = onDismiss, testTag = "debug-sheet") {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(16.dp), modifier = Modifier.fillMaxSize()) {
            item {
                SectionCard("Letzter Fix") {
                    controller.debugRows().forEach { (key, value) -> DebugLabel(key, value) }
                }
            }
            item {
                SectionCard("Matcher") {
                    DebugLabel("Aktiv", ui.matcherDebugProfile.debugLabel)
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
                        DebugLabel("Way", ui.limitWayId ?: "n/a")
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
                            Text("Im Browser oeffnen")
                        }
                    }
                }
            }
            item {
                SectionCard("Logs") {
                    if (ui.gpsLogPath.isBlank() && ui.matchLogPath.isBlank()) {
                        Text("Noch keine Logdateien vorhanden.", color = Color(0xFF555555))
                    }
                    if (ui.gpsLogPath.isNotBlank()) {
                        DebugLabel("GPS-CSV", ui.gpsLogPath)
                        Button(
                            onClick = controller::shareGpsLog,
                            colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                            modifier = Modifier.testTag("debug-share-gps-log-button"),
                        ) {
                            Text("GPS-CSV teilen")
                        }
                    }
                    if (ui.matchLogPath.isNotBlank()) {
                        DebugLabel("Matcher-Log", ui.matchLogPath)
                        OutlinedButton(
                            onClick = controller::shareMatchLog,
                            modifier = Modifier.testTag("debug-share-match-log-button"),
                        ) {
                            Text("Matcher-Log teilen")
                        }
                    }
                    if (ui.runtimeDiagnosticsLogPath.isNotBlank()) {
                        DebugLabel("Diagnose-Log", ui.runtimeDiagnosticsLogPath)
                        OutlinedButton(
                            onClick = controller::shareRuntimeDiagnosticsLog,
                            modifier = Modifier.testTag("debug-share-runtime-diagnostics-log-button"),
                        ) {
                            Text("Diagnose-Log teilen")
                        }
                        OutlinedButton(
                            onClick = controller::clearRuntimeDiagnosticsLog,
                            modifier = Modifier.testTag("debug-clear-runtime-diagnostics-log-button"),
                        ) {
                            Text("Diagnose-Log leeren")
                        }
                    }
                    OutlinedButton(
                        onClick = controller::clearDrivingLogs,
                        modifier = Modifier.testTag("debug-clear-logs-button"),
                    ) {
                        Text("Fahrlog leeren")
                    }
                }
            }
            if (ui.lastError.isNotBlank()) {
                item {
                    SectionCard("Fehler") {
                        Text(ui.lastError, color = SignalRed)
                    }
                }
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun LocalRecordingsSheet(
    controller: ConsumerSessionController,
    onDismiss: () -> Unit,
) {
    val ui = controller.uiState
    SheetScaffold(title = "Lokale Erfassungen", onDismiss = onDismiss, testTag = "local-recordings-sheet") {
        Column(modifier = Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(
                "Zur Erfassung von Korrekturen Schild doppelklicken. Android bestaetigt mit \"Korrektur\", anschliessend die korrekte Geschwindigkeit sprechen.",
                color = Color(0xFF555555),
                fontSize = 13.sp,
            )
            if (ui.localObservations.isEmpty()) {
                SectionCard("Status") {
                    Text("Keine lokalen Erfassungen vorhanden.", color = Color(0xFF555555))
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
                                        Text(observation.streetName, color = Color.Black, fontWeight = FontWeight.SemiBold)
                                        if (observation.modality == LocalObservationModality.COMPUTER_VISION) {
                                            Text(
                                                "Kamera-Erkennung${observation.evidenceSummary?.let { " • $it" }.orEmpty()}",
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
                                            "alt ${observation.oldSpeedKmh ?: "n/a"} • neu ${observation.newSpeedValue?.let(::formatObservationValue).orEmpty().ifBlank { observation.newSpeedKmh?.toString() ?: "n/a" }}",
                                            color = Color.Black,
                                        )
                                        observation.wayId?.let { Text("way $it", color = Color(0xFF777777), fontSize = 12.sp) }
                                    }
                                    IconButton(onClick = { controller.deleteLocalObservation(observation.id) }) {
                                        Icon(Icons.Default.Delete, contentDescription = "Eintrag loeschen")
                                    }
                                }
                                when (observation.state) {
                                    LocalObservationState.LOCAL_ONLY,
                                    LocalObservationState.NEEDS_REVIEW -> {
                                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                            OutlinedButton(onClick = { controller.approveLocalObservation(observation.id) }) {
                                                Text("Freigeben")
                                            }
                                            OutlinedButton(onClick = { controller.discardLocalObservation(observation.id) }) {
                                                Text("Verwerfen")
                                            }
                                        }
                                    }

                                    LocalObservationState.APPROVED_FOR_EXPORT -> {
                                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                            Button(
                                                onClick = { controller.exportLocalObservation(observation.id) },
                                                colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                                            ) {
                                                Text("Exportieren")
                                            }
                                            OutlinedButton(onClick = { controller.discardLocalObservation(observation.id) }) {
                                                Text("Verwerfen")
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
                Text("Export: ${ui.lastExportDirectoryPath}", color = Color(0xFF555555), fontSize = 12.sp)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Button(
                    onClick = controller::exportAllLocalObservations,
                    colors = ButtonDefaults.buttonColors(containerColor = SignalGreen),
                    modifier = Modifier.testTag("local-export-button"),
                ) {
                    Icon(Icons.Default.Download, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("changes.osc exportieren")
                }
                OutlinedButton(
                    onClick = controller::deleteAllLocalObservations,
                    modifier = Modifier.testTag("local-delete-all-button"),
                ) {
                    Icon(Icons.Default.Delete, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Alle loeschen")
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
    SheetScaffold(title = "Rechtliche Hinweise", onDismiss = onDismiss, testTag = "legal-sheet") {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            SectionCard("Rechtlicher Hinweis") {
                Text(stringResource(R.string.legal_disclaimer_long), color = Color.Black)
            }
            Text(ui.legalText.ifBlank { "Keine rechtlichen Hinweise gebuendelt." }, color = Color.Black, lineHeight = 22.sp)
        }
    }
}

private data class RuntimeBanner(
    val text: String,
    val background: Color,
    val foreground: Color,
)

private fun formatObservationValue(value: String): String {
    return if (value == "walk") "Fussgaengerzone" else value
}

private fun observationStateLabel(state: LocalObservationState): String {
    return when (state) {
        LocalObservationState.LOCAL_ONLY -> "Lokal"
        LocalObservationState.NEEDS_REVIEW -> "Pruefen"
        LocalObservationState.APPROVED_FOR_EXPORT -> "Freigegeben"
        LocalObservationState.EXPORTED_OSC -> "Exportiert"
        LocalObservationState.DISCARDED -> "Verworfen"
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

private fun runtimeBanner(ui: ConsumerUiState): RuntimeBanner? {
    return when (ui.driveStatus) {
        "requesting_location" -> RuntimeBanner(
            text = "Standortfreigabe wird angefragt.",
            background = Color(0xFFFFF3D8),
            foreground = Color(0xFF6B5200),
        )
        "location_denied" -> RuntimeBanner(
            text = "Standortzugriff verweigert. Bitte in Android erlauben.",
            background = Color(0xFFF7D9D6),
            foreground = SignalRed,
        )
        "location_error" -> RuntimeBanner(
            text = "Standortfehler. Debug pruefen oder GPS erneut aktivieren.",
            background = Color(0xFFF7D9D6),
            foreground = SignalRed,
        )
        else -> if (ui.activeDBPath.isBlank()) {
            RuntimeBanner(
                text = "Noch kein lokales Bundle aktiv. Seed oder Sync in den Einstellungen vorbereiten.",
                background = Color(0xFFFFF3D8),
                foreground = Color(0xFF6B5200),
            )
        } else {
            null
        }
    }
}

private fun speechModelStateLabel(state: GermanSpeechModelState): String = when (state) {
    GermanSpeechModelState.CHECKING -> "prueft"
    GermanSpeechModelState.DOWNLOADING -> "entpackt"
    GermanSpeechModelState.PENDING -> "wartet"
    GermanSpeechModelState.READY -> "bereit"
    GermanSpeechModelState.UNAVAILABLE -> "nicht verfuegbar"
}

@Composable
private fun SheetScaffold(
    title: String,
    onDismiss: () -> Unit,
    testTag: String,
    content: @Composable BoxScope.() -> Unit,
) {
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier
                .fillMaxSize()
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
                        .padding(horizontal = 18.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(title, fontWeight = FontWeight.Bold, fontSize = 22.sp, color = Color.Black, modifier = Modifier.weight(1f))
                    IconButton(onClick = onDismiss) {
                        Icon(Icons.Default.Close, contentDescription = "Fertig", tint = Color.Black)
                    }
                }
                HorizontalDivider()
                Box(
                    modifier = Modifier
                        .fillMaxSize()
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
                        contentDescription = "Bundle loeschen",
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
            contentDescription = if (onClick != null) "Bundle laden" else null,
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

private fun syncMessageLine(ui: ConsumerUiState): Pair<String, Color>? {
    return when (ui.syncStatus) {
        "ready_upToDate" -> "Daten sind verfuegbar und aktuell." to SignalGreen
        "ready_fullDownload", "ready_deltaPatch" -> "Datensynchronisierung abgeschlossen. Lokale Daten sind aktuell." to SignalGreen
        "ready_bootstrap" -> "Seed-Daten sind lokal verfuegbar." to SignalOrange
        "sync_failed" -> {
            if (ui.activeDBPath.isNotBlank()) {
                "Synchronisierung fehlgeschlagen, lokale Daten sind aber weiterhin verfuegbar." to SignalOrange
            } else {
                "Synchronisierung fehlgeschlagen. Kein aktives Daten-Bundle verfuegbar." to SignalRed
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
