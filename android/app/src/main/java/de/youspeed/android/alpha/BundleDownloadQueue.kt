package de.youspeed.android.alpha

/** Main-lane FIFO; closing a sheet does not cancel requested downloads. */
internal class BundleDownloadQueue<T>(private val id: (T) -> String) {
    private val entries = mutableListOf<T>()
    val ids: List<String> get() = entries.map(id)

    fun enqueue(entry: T, activeId: String?) {
        if (id(entry) != activeId && id(entry) !in ids) entries += entry
    }

    fun remove(entryId: String) { entries.removeAll { id(it) == entryId } }

    fun next(isBusy: Boolean): T? = if (isBusy || entries.isEmpty()) null else entries.removeAt(0)
}
