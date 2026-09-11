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
    private val transcripts = SpeedCaptureTranscriptBuffer()
    private var completed = false

    @Throws(IOException::class)
    fun start(timeoutMs: Long, listener: Listener): Boolean {
        if (completed || speechService != null) return false
        val recognizer = createRecognizer()
        val speechService = try {
            recognizer.setMaxAlternatives(5)
            SpeechService(recognizer, VOSK_SAMPLE_RATE)
        } catch (failure: Exception) {
            recognizer.close()
            throw failure
        }
        this.recognizer = recognizer
        this.speechService = speechService
        return speechService.startListening(
            object : RecognitionListener {
                override fun onPartialResult(hypothesis: String) {
                    if (completed) return
                    val transcript = parsePartialTranscript(hypothesis)
                    if (transcript.isNotBlank()) {
                        transcripts.updatePartial(transcript)
                        listener.onPartialTranscript(transcript)
                    }
                }

                override fun onResult(hypothesis: String) {
                    if (completed) return
                    val candidates = parseCandidateTranscripts(hypothesis)
                    if (candidates.isNotEmpty()) {
                        // Vosk's onResult is an endpointed utterance. A partial
                        // hypothesis may still be revised and must not save a correction.
                        completeOnce(listener, transcripts.acceptCompleted(candidates), "utterance_result")
                    }
                }

                override fun onFinalResult(hypothesis: String) {
                    if (completed) return
                    val finalTranscripts = transcripts.acceptCompleted(parseCandidateTranscripts(hypothesis))
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
                    if (completed) return
                    // SpeechService posts timeout after stopping AudioRecord.
                    // Join its worker before asking native Vosk to flush the
                    // final utterance, so no acceptWaveForm call can race it.
                    val candidates = runCatching {
                        this@VoskSpeedCaptureSession.speechService?.stop()
                        this@VoskSpeedCaptureSession.recognizer?.finalResult
                            ?.let(::parseCandidateTranscripts).orEmpty()
                    }.getOrDefault(emptyList())
                    completeOnce(listener, transcripts.acceptCompleted(candidates), "timeout_final_result")
                }
            },
            timeoutMs.toInt(),
        )
    }

    override fun close() {
        completed = true
        runCatching { speechService?.cancel() }
        runCatching { speechService?.shutdown() }
        speechService = null
        runCatching { recognizer?.close() }
        recognizer = null
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
