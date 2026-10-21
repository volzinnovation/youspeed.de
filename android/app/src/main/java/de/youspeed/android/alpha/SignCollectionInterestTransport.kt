package de.youspeed.android.alpha

import java.net.HttpURLConnection
import java.net.URI

/** A separate connection from uploads, with no identifiers, cookies or redirect following. */
internal class SignCollectionInterestHTTP {
    data class Response(val status: Int, val data: ByteArray, val retryAfter: String?)
    @Volatile private var active: HttpURLConnection? = null
    fun cancel() { active?.disconnect() }
    fun fetch(etag: String?): Response {
        val connection = URI(SignCollectionHTTPClient.defaultBaseURL + "/crop-interest").toURL().openConnection() as HttpURLConnection
        active = connection
        try {
            connection.instanceFollowRedirects=false; connection.connectTimeout=15000; connection.readTimeout=15000
            connection.setRequestProperty("Accept","application/json"); connection.setRequestProperty("Accept-Encoding","identity")
            if(etag != null) connection.setRequestProperty("If-None-Match",etag)
            val status=connection.responseCode
            require(connection.contentLengthLong <= SignCollectionInterestPlan.MAXIMUM_BYTES)
            val data=if(status == 200) {
                require(connection.contentType?.substringBefore(';')?.trim() == "application/json")
                connection.inputStream.use { input ->
                    val output=java.io.ByteArrayOutputStream(); val buffer=ByteArray(8192)
                    while(output.size() <= SignCollectionInterestPlan.MAXIMUM_BYTES) {
                        if(Thread.currentThread().isInterrupted) throw java.io.InterruptedIOException()
                        val count=input.read(buffer,0,minOf(buffer.size,SignCollectionInterestPlan.MAXIMUM_BYTES+1-output.size()))
                        if(count<0) break
                        output.write(buffer,0,count)
                    }
                    require(output.size() <= SignCollectionInterestPlan.MAXIMUM_BYTES);output.toByteArray()
                }
            } else ByteArray(0)
            return Response(status,data,connection.getHeaderField("Retry-After"))
        } finally { connection.disconnect();active=null }
    }
}
