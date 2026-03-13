package de.youspeed.android.alpha

import java.io.IOException
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.RecognitionListener
import org.vosk.android.SpeechService

private const val VOSK_SAMPLE_RATE = 16_000f

class VoskSpeedCaptureSession(
    private val model: Model,
    private val grammarJson: String,
) : AutoCloseable {
    interface Listener {
        fun onPartialTranscript(transcript: String)

        fun onCompleted(transcripts: List<String>, source: String)

        fun onError(message: String)
    }

    private var recognizer: Recognizer? = null
    private var speechService: SpeechService? = null
    private var latestPartialTranscript: String = ""
    private var latestCandidateTranscripts: List<String> = emptyList()
    private var completed = false

    @Throws(IOException::class)
    fun start(timeoutMs: Long, listener: Listener): Boolean {
        val recognizer = createRecognizer()
        recognizer.setMaxAlternatives(5)
        val speechService = SpeechService(recognizer, VOSK_SAMPLE_RATE)
        this.recognizer = recognizer
        this.speechService = speechService
        return speechService.startListening(
            object : RecognitionListener {
                override fun onPartialResult(hypothesis: String) {
                    val transcript = parsePartialTranscript(hypothesis)
                    if (transcript.isNotBlank()) {
                        latestPartialTranscript = transcript
                        listener.onPartialTranscript(transcript)
                    }
                }

                override fun onResult(hypothesis: String) {
                    val transcripts = parseCandidateTranscripts(hypothesis)
                    if (transcripts.isNotEmpty()) {
                        latestCandidateTranscripts = transcripts
                        latestPartialTranscript = transcripts.first()
                        listener.onPartialTranscript(transcripts.first())
                    }
                }

                override fun onFinalResult(hypothesis: String) {
                    val transcripts = parseCandidateTranscripts(hypothesis)
                    val finalTranscripts = transcripts.ifEmpty { fallbackTranscripts() }
                    completeOnce(listener, finalTranscripts, "final_result")
                }

                override fun onError(exception: Exception) {
                    if (completed) {
                        return
                    }
                    completed = true
                    close()
                    listener.onError(exception.message ?: exception.javaClass.simpleName)
                }

                override fun onTimeout() {
                    completeOnce(listener, fallbackTranscripts(), "timeout")
                }
            },
            timeoutMs.toInt(),
        )
    }

    override fun close() {
        runCatching { speechService?.cancel() }
        runCatching { speechService?.shutdown() }
        speechService = null
        runCatching { recognizer?.close() }
        recognizer = null
    }

    private fun fallbackTranscripts(): List<String> {
        return (latestCandidateTranscripts + latestPartialTranscript)
            .map(String::trim)
            .filter(String::isNotEmpty)
            .distinct()
    }

    private fun completeOnce(listener: Listener, transcripts: List<String>, source: String) {
        if (completed) {
            return
        }
        completed = true
        close()
        listener.onCompleted(transcripts, source)
    }

    @Throws(IOException::class)
    private fun createRecognizer(): Recognizer {
        return runCatching {
            Recognizer(model, VOSK_SAMPLE_RATE, grammarJson)
        }.getOrElse {
            Recognizer(model, VOSK_SAMPLE_RATE)
        }
    }

    private fun parsePartialTranscript(hypothesis: String): String {
        return runCatching {
            JSONObject(hypothesis).optString("partial").trim()
        }.getOrDefault("")
    }

    private fun parseCandidateTranscripts(hypothesis: String): List<String> {
        return runCatching {
            val json = JSONObject(hypothesis)
            val alternatives = json.optJSONArray("alternatives")
            if (alternatives != null) {
                buildList {
                    for (index in 0 until alternatives.length()) {
                        val transcript = alternatives.optJSONObject(index)
                            ?.optString("text")
                            ?.trim()
                            .orEmpty()
                        if (transcript.isNotEmpty()) {
                            add(transcript)
                        }
                    }
                }.distinct()
            } else {
                listOf(json.optString("text").trim()).filter(String::isNotEmpty)
            }
        }.getOrDefault(emptyList())
    }
}
