package de.youspeed.android.alpha

/** SemVer precedence, allowing omitted minor/patch components in app version names. */
internal object BundleAppVersion {
    private data class Version(val core: List<Long>, val prerelease: List<String>)
    private val pattern = Regex("^(0|[1-9][0-9]*)(?:\\.(0|[1-9][0-9]*))?(?:\\.(0|[1-9][0-9]*))?(?:-([0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?(?:\\+([0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?$")

    private fun parse(raw: String): Version? {
        val match = pattern.matchEntire(raw.trim()) ?: return null
        val core = (1..3).map { index ->
            match.groupValues[index].takeIf { it.isNotEmpty() }?.toLongOrNull()
                ?: if (match.groupValues[index].isEmpty()) 0L else return null
        }
        val prerelease = match.groupValues[4].takeIf { it.isNotEmpty() }?.split('.').orEmpty()
        if (prerelease.any { it.all(Char::isDigit) && it.length > 1 && it.startsWith('0') }) return null
        return Version(core, prerelease)
    }

    fun isAtLeast(current: String, minimum: String): Boolean {
        val a = parse(current) ?: return false
        val b = parse(minimum) ?: return false
        for (index in 0..2) if (a.core[index] != b.core[index]) return a.core[index] > b.core[index]
        if (a.prerelease.isEmpty() || b.prerelease.isEmpty()) return b.prerelease.isNotEmpty() || a.prerelease.isEmpty()
        for (index in 0 until minOf(a.prerelease.size, b.prerelease.size)) {
            val left = a.prerelease[index]
            val right = b.prerelease[index]
            if (left == right) continue
            val leftNumeric = left.all(Char::isDigit)
            val rightNumeric = right.all(Char::isDigit)
            return when {
                leftNumeric && rightNumeric -> if (left.length != right.length) left.length > right.length else left > right
                leftNumeric != rightNumeric -> !leftNumeric
                else -> left > right
            }
        }
        return a.prerelease.size >= b.prerelease.size
    }
}
