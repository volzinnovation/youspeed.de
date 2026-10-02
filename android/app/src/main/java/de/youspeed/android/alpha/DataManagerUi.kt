package de.youspeed.android.alpha

import android.text.format.Formatter
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Delete
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.Normalizer
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private val DownloadableBlue = Color(0xFF2164AB)
private val InstalledGreen = Color(0xFF176B50)
private val UnavailableGray = Color(0xFF59616D)
private val ManagerInk = Color(0xFF142C46)

@Composable
internal fun DataManagerSheet(controller: ConsumerSessionController, onBack: () -> Unit, onDismiss: () -> Unit) {
    val ui = controller.uiState
    val options = ui.bundleDownloadSections.flatMap { it.options }
    val selected = options.firstOrNull { it.id == ui.dataManagerSelectedRegionId }
    var tab by rememberSaveable { mutableStateOf(0) }
    var query by rememberSaveable { mutableStateOf("") }
    val listScroll = rememberLazyListState()
    var showMaintenance by rememberSaveable { mutableStateOf(false) }
    var deleteRegionId by rememberSaveable { mutableStateOf<String?>(null) }
    var deleteScopeKey by rememberSaveable { mutableStateOf<String?>(null) }
    var deleteScopeName by rememberSaveable { mutableStateOf("") }
    var deleteScopeCount by rememberSaveable { mutableStateOf(0) }
    var centerX by rememberSaveable { mutableStateOf(DataManagerViewport.GERMANY.centerX) }
    var centerY by rememberSaveable { mutableStateOf(DataManagerViewport.GERMANY.centerY) }
    var span by rememberSaveable { mutableStateOf(DataManagerViewport.GERMANY.span) }
    val viewport = DataManagerViewport(centerX, centerY, span).safe()
    val setViewport: (DataManagerViewport) -> Unit = { next -> centerX = next.centerX; centerY = next.centerY; span = next.span }
    val context = LocalContext.current
    val geometry by produceState<Result<DataManagerMapCatalog>?>(null, context) {
        value = withContext(Dispatchers.IO) { runCatching {
            context.assets.open(DataManagerMapCatalog.ASSET_PATH).use { DataManagerMapCatalog.decode(it.readBytes()) }
        } }
    }
    val catalog = geometry?.getOrNull()
    val states = options.associate { it.id to dataManagerDisplayState(controller.isBundleDownloaded(it), ui.dataManagerMetadataByRegion[it.id]) }
    val requestDelete: (BundleDownloadOption) -> Unit = { option ->
        val scope = controller.dataManagerInstalledScope(option)
        if (scope != null && ui.dataManagerInventoryAvailable) {
            deleteScopeKey = scope.regionKey
            deleteScopeName = if (scope.isCountryPackage) option.countryName else regionTitle(option)
            deleteScopeCount = controller.installedDataManagerRegion(option)?.versionCount ?: 0
            deleteRegionId = option.id
        }
    }
    LaunchedEffect(selected?.id) { selected?.let { controller.requestDataManagerMetadata(it) } }
    val showOnMap: (BundleDownloadOption) -> Unit = { option ->
        controller.selectDataManagerRegion(option.id)
        catalog?.regions?.firstOrNull { it.id == option.id }?.let { setViewport(DataManagerViewport.fit(it.bounds)) }
        tab = 0
    }
    val operations: @Composable () -> Unit = {
        DataManagerOperationStatus(ui, options)
        if (ui.maintenanceMessage.isNotBlank()) Text(ui.maintenanceMessage, fontSize = 12.sp)
        if (ui.lastError.isNotBlank()) Text(ui.lastError, color = Color(0xFFAA2637), fontSize = 12.sp)
        if (!ui.dataManagerInventoryAvailable) {
            Text(stringResource(R.string.data_manager_inventory_unknown), fontSize = 12.sp)
            TextButton(onClick = controller::refreshDataManagerInventory, enabled = !controller.isBundleMaintenanceBusy()) {
                Text(stringResource(R.string.data_manager_refresh_inventory))
            }
        }
    }
    val maintenance: @Composable () -> Unit = {
        TextButton(onClick = { showMaintenance = !showMaintenance }, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.data_manager_maintenance))
        }
        if (showMaintenance) {
            Text(ui.firstLocationPackStatus, fontSize = 12.sp)
            Text(ui.countryModelPackStatus, fontSize = 12.sp)
            OutlinedButton(onClick = controller::retryFirstLocationSetup, enabled = !controller.isBundleMaintenanceBusy()) {
                Text(stringResource(R.string.ui_retry_location_selection))
            }
            OutlinedButton(onClick = { deleteRegionId = "*" },
                enabled = !controller.isBundleMaintenanceBusy() && ui.dataManagerInventoryAvailable && ui.downloadedBundleCountByRegion.isNotEmpty(),
                modifier = Modifier.testTag("data-manager-delete-all")) {
                Text(stringResource(R.string.ui_delete_downloaded_maps), color = Color(0xFFAA2637))
            }
        }
    }
    SheetScaffold(stringResource(R.string.data_manager_title), onDismiss, "data-manager-sheet", onBack = onBack, contentPadding = 8.dp) {
        Column(Modifier.fillMaxSize().imePadding(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            TabRow(selectedTabIndex = tab, containerColor = Color.Transparent, contentColor = ManagerInk) {
                Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text(stringResource(R.string.data_manager_map_tab)) },
                    modifier = Modifier.testTag("data-manager-map-tab"))
                Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text(stringResource(R.string.data_manager_list_tab)) },
                    modifier = Modifier.testTag("data-manager-list-tab"))
            }
            operations()
            if (tab == 1) {
                OutlinedTextField(query, { query = it }, label = { Text(stringResource(R.string.data_manager_search)) }, singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag("data-manager-search"))
                val filtered = options.filter { dataManagerSearchMatches("${regionTitle(it)} ${it.countryName}", query) }
                LazyColumn(Modifier.weight(1f).testTag("data-manager-region-list"), state = listScroll, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (filtered.isEmpty()) item { Text(stringResource(R.string.data_manager_no_results)) }
                    items(filtered, key = { it.id }) { option ->
                        DataManagerListRow(option, option.id == selected?.id, controller,
                            onSelect = { controller.selectDataManagerRegion(option.id) }, onDelete = { requestDelete(option) })
                        if (option.id == selected?.id) {
                            DataManagerDetails(option, controller, onDelete = { requestDelete(option) })
                            TextButton(onClick = { showOnMap(option) }, modifier = Modifier.fillMaxWidth().testTag("data-manager-show-on-map")) {
                                Text(stringResource(R.string.data_manager_show_on_map))
                            }
                        }
                    }
                    item { Column(verticalArrangement = Arrangement.spacedBy(4.dp)) { maintenance() } }
                }
            } else BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                val map: @Composable () -> Unit = {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(stringResource(R.string.data_manager_map_help), color = ManagerInk, fontSize = 12.sp)
                        if (catalog != null) DataManagerRegionCanvas(catalog, states, selected?.id, viewport, setViewport,
                            controller::selectDataManagerRegion, Modifier.fillMaxWidth().height(if (maxWidth > maxHeight) 200.dp else 230.dp))
                        else Text(stringResource(if (geometry == null) R.string.data_manager_map_loading else R.string.data_manager_map_error),
                            modifier = Modifier.fillMaxWidth().padding(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.CenterVertically) {
                            TextButton(onClick = { setViewport(viewport.copy(span = viewport.span / 1.8).safe()) },
                                modifier = Modifier.size(48.dp).semantics { contentDescription = context.getString(R.string.data_manager_zoom_in) }) { Text("+") }
                            TextButton(onClick = { setViewport(viewport.copy(span = viewport.span * 1.8).safe()) },
                                modifier = Modifier.size(48.dp).semantics { contentDescription = context.getString(R.string.data_manager_zoom_out) }) { Text("−") }
                            TextButton(onClick = { setViewport(DataManagerViewport.GERMANY) },
                                modifier = Modifier.size(48.dp).testTag("data-manager-germany")
                                    .semantics { contentDescription = context.getString(R.string.data_manager_germany) }) { Text("DE") }
                            TextButton(onClick = { setViewport(DataManagerViewport.EUROPE) }, modifier = Modifier.weight(1f).testTag("data-manager-europe")) {
                                Text(stringResource(R.string.data_manager_europe))
                            }
                            val shape = catalog?.regions?.firstOrNull { it.id == selected?.id }
                            TextButton(onClick = { shape?.let { setViewport(DataManagerViewport.fit(it.bounds)) } }, enabled = shape != null,
                                modifier = Modifier.weight(1f).testTag("data-manager-jump")) { Text(stringResource(R.string.data_manager_selected_short)) }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            LegendDot(InstalledGreen, stringResource(R.string.data_manager_installed), modifier = Modifier.weight(1f))
                            LegendDot(DownloadableBlue, stringResource(R.string.data_manager_available), modifier = Modifier.weight(1f))
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            LegendDot(UnavailableGray, stringResource(R.string.data_manager_unavailable), modifier = Modifier.weight(1f))
                            LegendDot(Color.White, stringResource(R.string.data_manager_unknown), outlined = true, modifier = Modifier.weight(1f))
                        }
                        Text(catalog?.attribution ?: "© EuroGeographics for the administrative boundaries", fontSize = 10.sp, color = Color.DarkGray)
                        Text(stringResource(R.string.data_manager_boundaries_help), fontSize = 10.sp, color = Color.DarkGray)
                    }
                }
                val details: @Composable () -> Unit = {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        if (selected == null) Text(stringResource(R.string.data_manager_select_prompt), fontWeight = FontWeight.SemiBold, color = ManagerInk)
                        else DataManagerDetails(selected, controller, onDelete = { requestDelete(selected) })
                        maintenance()
                    }
                }
                if (maxWidth > 600.dp && maxWidth > maxHeight) Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    LazyColumn(Modifier.weight(1.1f).fillMaxSize()) { item { map() } }
                    LazyColumn(Modifier.weight(1f).fillMaxSize()) { item { details() } }
                } else LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxSize()) {
                    item { map() }; item { details() }
                }
            }
        }
    }
    val deleting = options.firstOrNull { it.id == deleteRegionId }
    if (deleteRegionId == "*" || deleting != null) AlertDialog(onDismissRequest = { deleteRegionId = null },
        title = { Text(stringResource(R.string.data_manager_delete_title)) },
        text = { Text(if (deleting == null) stringResource(R.string.data_manager_delete_all_message)
            else stringResource(R.string.data_manager_delete_message, deleteScopeName, deleteScopeCount)) },
        confirmButton = { TextButton(enabled = !controller.isBundleMaintenanceBusy() && ui.dataManagerInventoryAvailable, onClick = {
            if (deleting != null) deleteScopeKey?.let { controller.deleteSelectedBundle(deleting, confirmedRegionKey = it) }
            else controller.deleteDownloadedBundlesKeepingSeed()
            deleteRegionId = null
        }, modifier = Modifier.testTag("data-manager-confirm-delete")) { Text(stringResource(R.string.data_manager_delete)) } },
        dismissButton = { TextButton(onClick = { deleteRegionId = null }) { Text(stringResource(R.string.ui_cancel)) } })
}

@Composable
private fun DataManagerDetails(option: BundleDownloadOption, controller: ConsumerSessionController, onDelete: () -> Unit) {
    val ui = controller.uiState
    val context = LocalContext.current
    val installed = controller.installedDataManagerRegion(option)
    val scope = controller.dataManagerInstalledScope(option)
    val isInstalled = controller.isBundleDownloaded(option)
    val remote = ui.dataManagerMetadataByRegion[option.id] ?: DataManagerMetadataState()
    val metadata = remote.metadata.takeIf { remote.status == DataManagerMetadataStatus.READY }
    val displayState = dataManagerDisplayState(isInstalled, remote)
    val unknown = stringResource(R.string.data_manager_unknown)
    fun bytes(value: Long?) = value?.takeIf { it > 0 }?.let { Formatter.formatFileSize(context, it) } ?: unknown
    fun date(value: String?) = value?.let { runCatching {
        DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM).withLocale(Locale.getDefault())
            .withZone(ZoneId.systemDefault()).format(Instant.parse(it))
    }.getOrNull() } ?: unknown
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), modifier = Modifier.fillMaxWidth().testTag("data-manager-details")) {
        Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(regionTitle(option), color = ManagerInk, fontWeight = FontWeight.Bold, fontSize = 18.sp)
            if (option.id.substringBefore('|') != option.id.substringAfter('|')) Text(option.countryName, color = Color.DarkGray)
            Text(stringResource(displayState.label()), color = displayState.color(), fontWeight = FontWeight.SemiBold)
            if (isInstalled && ui.dataManagerInventoryAvailable) {
                if (scope?.isCountryPackage == true) Text(stringResource(R.string.data_manager_country_package, option.countryName), fontSize = 13.sp)
                Text(stringResource(R.string.data_manager_installed_size, bytes(installed?.totalDatabaseBytes)), fontSize = 13.sp)
                Text(stringResource(R.string.data_manager_installed_date, date(installed?.newestPackage?.createdAtUTC)), fontSize = 13.sp)
                installed?.newestPackage?.bundleVersion?.let { Text(stringResource(R.string.data_manager_version, it), fontSize = 12.sp) }
            }
            Text(stringResource(R.string.data_manager_download_size, bytes(metadata?.bytes)), fontSize = 13.sp)
            Text(stringResource(R.string.data_manager_package_date, date(metadata?.createdAtUTC)), fontSize = 13.sp)
            when (remote.status) {
                DataManagerMetadataStatus.LOADING -> {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Text(stringResource(R.string.data_manager_metadata_loading), fontSize = 12.sp)
                }
                DataManagerMetadataStatus.ERROR -> Text(stringResource(R.string.data_manager_metadata_error), fontSize = 12.sp, color = Color(0xFFAA2637))
                DataManagerMetadataStatus.UNAVAILABLE -> Text(stringResource(R.string.data_manager_unavailable_help), fontSize = 12.sp, color = UnavailableGray)
                DataManagerMetadataStatus.UNKNOWN -> Text(stringResource(R.string.data_manager_metadata_unknown), fontSize = 12.sp)
                DataManagerMetadataStatus.READY -> metadata?.bundleVersion?.let {
                    Text(stringResource(R.string.data_manager_available_version, it), fontSize = 12.sp)
                }
            }
            TextButton(onClick = { controller.requestDataManagerMetadata(option, force = true) },
                enabled = remote.status != DataManagerMetadataStatus.LOADING) { Text(stringResource(R.string.data_manager_refresh)) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { controller.downloadSelectedBundle(option) },
                    enabled = !controller.isBundleMaintenanceBusy() && remote.status != DataManagerMetadataStatus.UNAVAILABLE,
                    modifier = Modifier.weight(1f).testTag("data-manager-download")) {
                    Text(stringResource(if (isInstalled && scope?.isCountryPackage != true) R.string.data_manager_check_update else R.string.data_manager_download))
                }
                if (isInstalled) OutlinedButton(onClick = onDelete, enabled = !controller.isBundleMaintenanceBusy() && ui.dataManagerInventoryAvailable,
                    modifier = Modifier.weight(1f).testTag("data-manager-delete")) {
                    Text(stringResource(R.string.data_manager_delete), color = Color(0xFFAA2637))
                }
            }
        }
    }
}

@Composable
private fun DataManagerListRow(option: BundleDownloadOption, isSelected: Boolean, controller: ConsumerSessionController,
    onSelect: () -> Unit, onDelete: () -> Unit) {
    val ui = controller.uiState
    val context = LocalContext.current
    val installed = controller.isBundleDownloaded(option)
    val remote = ui.dataManagerMetadataByRegion[option.id]
    val state = dataManagerDisplayState(installed, remote)
    val local = controller.installedDataManagerRegion(option)
    val metadata = if (installed) local?.newestPackage
        else remote?.metadata?.takeIf { remote.status == DataManagerMetadataStatus.READY }
    val unknown = stringResource(R.string.data_manager_unknown)
    val size = (if (installed) local?.totalDatabaseBytes else metadata?.bytes)?.takeIf { it > 0 }
        ?.let { Formatter.formatFileSize(context, it) } ?: unknown
    val date = metadata?.createdAtUTC?.let { runCatching {
        DateTimeFormatter.ofLocalizedDate(FormatStyle.SHORT).withLocale(Locale.getDefault())
            .withZone(ZoneId.systemDefault()).format(Instant.parse(it))
    }.getOrNull() } ?: unknown
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
        .background(if (isSelected) Color(0xFFDCE8F4) else Color.White)
        .clickable(role = Role.Button, onClick = onSelect).testTag("data-manager-region-${option.id}")
        .semantics { selected = isSelected }
        .padding(start = 8.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(regionTitle(option), fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = ManagerInk)
            Text("${option.countryName} · ${stringResource(state.label())}", fontSize = 11.sp, color = state.color())
            Text(stringResource(R.string.data_manager_row_details, size, date), fontSize = 11.sp, color = Color.DarkGray)
        }
        IconButton(onClick = { onSelect(); controller.downloadSelectedBundle(option) },
            enabled = !controller.isBundleMaintenanceBusy() && remote?.status != DataManagerMetadataStatus.UNAVAILABLE,
            modifier = Modifier.size(48.dp).testTag("data-manager-row-download-${option.id}")) {
            Icon(Icons.Default.Download,
                contentDescription = "${stringResource(if (installed && controller.dataManagerInstalledScope(option)?.isCountryPackage != true)
                    R.string.data_manager_check_update else R.string.data_manager_download)} ${regionTitle(option)}",
                tint = if (state == DataManagerDisplayState.UNAVAILABLE) UnavailableGray else ManagerInk)
        }
        if (installed) IconButton(onClick = { onSelect(); onDelete() },
            enabled = !controller.isBundleMaintenanceBusy() && ui.dataManagerInventoryAvailable,
            modifier = Modifier.size(48.dp).testTag("data-manager-row-delete-${option.id}")) {
            Icon(Icons.Default.Delete, contentDescription = "${stringResource(R.string.data_manager_delete)} ${regionTitle(option)}", tint = Color(0xFFAA2637))
        }
    }
}

private fun DataManagerDisplayState.color(): Color = when (this) {
    DataManagerDisplayState.INSTALLED -> InstalledGreen
    DataManagerDisplayState.AVAILABLE -> DownloadableBlue
    DataManagerDisplayState.UNAVAILABLE -> UnavailableGray
    DataManagerDisplayState.UNKNOWN -> ManagerInk
}

private fun DataManagerDisplayState.label(): Int = when (this) {
    DataManagerDisplayState.INSTALLED -> R.string.data_manager_installed
    DataManagerDisplayState.AVAILABLE -> R.string.data_manager_available
    DataManagerDisplayState.UNAVAILABLE -> R.string.data_manager_unavailable
    DataManagerDisplayState.UNKNOWN -> R.string.data_manager_unknown
}

@Composable
private fun DataManagerOperationStatus(ui: ConsumerUiState, options: List<BundleDownloadOption>) {
    val context = LocalContext.current
    if (ui.activeBundleDeletionOptionId != null) Text(stringResource(R.string.data_manager_deleting))
    if (ui.syncStatus != "syncing" && ui.syncStatus != "bootstrapping") return
    Column(verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.testTag("data-manager-progress")) {
        options.firstOrNull { it.id == ui.activeDownloadOptionId }?.let { Text(regionTitle(it), fontWeight = FontWeight.SemiBold) }
        Text(ui.syncProgressDetail, fontSize = 13.sp)
        if (ui.syncProgressTotalBytes > 0) {
            LinearProgressIndicator(progress = (ui.syncProgressCompletedBytes.toDouble() / ui.syncProgressTotalBytes).coerceIn(0.0, 1.0).toFloat(),
                modifier = Modifier.fillMaxWidth())
            Text("${Formatter.formatFileSize(context, ui.syncProgressCompletedBytes)} / ${Formatter.formatFileSize(context, ui.syncProgressTotalBytes)}", fontSize = 12.sp)
        } else LinearProgressIndicator(Modifier.fillMaxWidth())
        Text(stringResource(R.string.data_manager_background_help), fontSize = 12.sp)
    }
}

@Composable
private fun DataManagerRegionCanvas(catalog: DataManagerMapCatalog, states: Map<String, DataManagerDisplayState>, selectedId: String?,
    viewport: DataManagerViewport, onViewport: (DataManagerViewport) -> Unit, onSelect: (String) -> Unit, modifier: Modifier) {
    val currentViewport by rememberUpdatedState(viewport)
    val description = stringResource(R.string.data_manager_map_accessibility)
    Canvas(modifier.clip(RoundedCornerShape(18.dp)).background(Color(0xFFE4EEF6))
        .testTag("data-manager-map").semantics { contentDescription = description }
        .pointerInput(catalog, states.keys) {
            detectTapGestures { point ->
                val coordinate = currentViewport.coordinateAt(point.x.toDouble(), point.y.toDouble(), size.width.toDouble(), size.height.toDouble())
                catalog.hit(coordinate.first, coordinate.second, states.keys)?.let(onSelect)
            }
        }.pointerInput(catalog) {
            detectTransformGestures { centroid, pan, zoom, _ ->
                onViewport(currentViewport.transformed(pan.x.toDouble(), pan.y.toDouble(), zoom.toDouble(),
                    centroid.x.toDouble(), centroid.y.toDouble(), size.width.toDouble(), size.height.toDouble()))
            }
        }) {
        val scale = minOf(size.width, size.height) / viewport.span
        fun path(region: DataManagerRegion): Path = Path().apply {
            fillType = PathFillType.EvenOdd
            region.polygons.forEach { polygon -> polygon.forEach { ring ->
                ring.forEachIndexed { i, point ->
                    val x = (size.width / 2 + (DataManagerViewport.projectX(point[0]) - viewport.centerX) * scale).toFloat()
                    val y = (size.height / 2 + (DataManagerViewport.projectY(point[1]) - viewport.centerY) * scale).toFloat()
                    if (i == 0) moveTo(x, y) else lineTo(x, y)
                }
                close()
            } }
        }
        clipRect {
            catalog.regions.filter { it.id in states }.forEach { region ->
                val outline = path(region)
                val state = states.getValue(region.id)
                drawPath(outline, if (state == DataManagerDisplayState.UNKNOWN) Color.White else state.color())
                drawPath(outline, if (state == DataManagerDisplayState.UNKNOWN) ManagerInk else Color.White, style = Stroke(1.dp.toPx()))
            }
            catalog.regions.firstOrNull { it.id == selectedId }?.let { region ->
                val outline = path(region)
                drawPath(outline, Color.White, style = Stroke(5.dp.toPx()))
                drawPath(outline, ManagerInk, style = Stroke(2.5.dp.toPx()))
            }
        }
    }
}

@Composable
private fun LegendDot(color: Color, label: String, outlined: Boolean = false, modifier: Modifier = Modifier) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
        Box(Modifier.size(9.dp).background(color, CircleShape).then(if (outlined) Modifier.border(1.dp, ManagerInk, CircleShape) else Modifier))
        Text(label, modifier = Modifier.weight(1f), fontSize = 11.sp, color = ManagerInk)
    }
}

internal fun regionTitle(option: BundleDownloadOption): String =
    if (option.id.substringBefore('|') == option.id.substringAfter('|')) option.countryName else option.displayName

internal fun dataManagerSearchMatches(label: String, query: String): Boolean {
    fun normalized(value: String) = Normalizer.normalize(value, Normalizer.Form.NFD).replace(Regex("\\p{M}+"), "").lowercase(Locale.ROOT)
    return normalized(query).trim().split(Regex("\\s+")).all { normalized(label).contains(it) }
}
