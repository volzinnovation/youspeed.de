package de.youspeed.android.alpha

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp

@Composable
internal fun MapillaryAccountSection(model: MapillaryUploadModel) {
    val state=model.state
    var token by remember { mutableStateOf("") }
    val uri=LocalUriHandler.current
    Column(Modifier.fillMaxWidth().padding(vertical=8.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
        Text(stringResource(R.string.mapillary_account),style=MaterialTheme.typography.titleMedium)
        if (state.username != null) {
            Text(state.username)
            OutlinedButton(model::disconnect,enabled=!state.busy && !state.uploading) { Text(stringResource(R.string.mapillary_disconnect)) }
        } else {
            OutlinedTextField(token,{token=it},label={Text(stringResource(R.string.mapillary_token))},
                visualTransformation=PasswordVisualTransformation(),singleLine=true,
                keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Password,autoCorrect=false),
                modifier=Modifier.fillMaxWidth().testTag("mapillary-account-token"))
            Text(stringResource(R.string.mapillary_token_help),style=MaterialTheme.typography.bodySmall)
            TextButton({uri.openUri("https://www.mapillary.com/developer")}) { Text(stringResource(R.string.mapillary_token_link)) }
            Button({model.connect(token);token=""},enabled=token.isNotBlank() && !state.busy && !state.uploading,
                modifier=Modifier.testTag("mapillary-account-connect")) { Text(stringResource(R.string.mapillary_connect)) }
        }
        if (state.busy) CircularProgressIndicator()
        if (state.status.isNotBlank()) Text(state.status,style=MaterialTheme.typography.bodySmall)
    }
}

@Composable
internal fun MapillaryUploadDialog(model: MapillaryUploadModel, photos: List<MapillaryPhoto>, allowed: () -> Boolean,
                                  onDismiss: () -> Unit) {
    val state=model.state
    AlertDialog(onDismissRequest=onDismiss,title={Text("Mapillary")},text={
        Column(Modifier.verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.mapillary_selected,photos.size))
            Text(stringResource(R.string.mapillary_scope),style=MaterialTheme.typography.bodySmall)
            if (state.username==null) Text(stringResource(R.string.mapillary_account_required))
            if (!allowed()) Text(stringResource(R.string.mapillary_paused))
            if (state.uploading) {
                LinearProgressIndicator(progress={state.completed.toFloat()/maxOf(1,state.total)},modifier=Modifier.fillMaxWidth())
                Text("${state.completed} / ${state.total}")
            }
            if (state.status.isNotBlank()) Text(state.status,modifier=Modifier.testTag("mapillary-upload-status"))
            if (state.pending.isNotEmpty()) Text(stringResource(R.string.mapillary_pending))
            state.pending.forEach { job ->
                OutlinedButton({model.start(resume=job)},enabled=!state.uploading && !state.busy && allowed() && state.username!=null) {
                    Text(stringResource(R.string.mapillary_resume_count,job.images.size))
                }
            }
        }
    },confirmButton={
        if (state.uploading) TextButton(model::stop,modifier=Modifier.testTag("mapillary-upload-stop")) { Text(stringResource(R.string.mapillary_stop)) }
        else TextButton({model.start(photos)},enabled=photos.isNotEmpty() && state.username!=null && !state.busy && allowed(),
            modifier=Modifier.testTag("mapillary-upload-start")) { Text(stringResource(R.string.mapillary_upload)) }
    },dismissButton={TextButton(onDismiss) {Text(stringResource(R.string.mapillary_close))}})
}
