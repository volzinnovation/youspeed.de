import Foundation
import AVFoundation
import Speech

/// A physical sign gets one short correction opportunity, even when its frame
/// preview subsequently becomes a committed passage. All times are monotonic.
struct VisionDismissalVoiceWindow {
    static let maximumStartDelay: TimeInterval = 3
    static let listeningDuration: TimeInterval = 4
    static let recognitionDrainDuration: TimeInterval = 0.35

    struct Attempt: Equatable {
        let token: UUID
        let evidenceID: String
        let language: String
        let detectedAt: TimeInterval
        var listeningUntil: TimeInterval?
    }

    private(set) var attempt: Attempt?
    private var offeredEvidence: [String] = []

    mutating func offer(evidenceID: String, deduplicationID: String? = nil, language: String, now: TimeInterval) -> Attempt? {
        let identity = deduplicationID ?? evidenceID
        guard !offeredEvidence.contains(identity) else { return nil }
        offeredEvidence.append(identity)
        if offeredEvidence.count > 128 { offeredEvidence.removeFirst() }
        let next = Attempt(token: UUID(), evidenceID: evidenceID, language: language, detectedAt: now)
        attempt = next
        return next
    }

    mutating func start(token: UUID, now: TimeInterval) -> Bool {
        guard var current = attempt, current.token == token,
              current.listeningUntil == nil,
              now >= current.detectedAt,
              now - current.detectedAt <= Self.maximumStartDelay else { return false }
        current.listeningUntil = now + Self.listeningDuration
        attempt = current
        return true
    }

    func accepts(token: UUID, evidenceID: String, transcript: String, now: TimeInterval) -> Bool {
        guard let current = attempt, current.token == token, current.evidenceID == evidenceID,
              let deadline = current.listeningUntil, now < deadline + Self.recognitionDrainDuration,
              now >= deadline - Self.listeningDuration else { return false }
        return Self.matchesCommand(transcript, language: current.language)
    }

    mutating func cancel() { attempt = nil }

    static func command(language: String) -> String {
        switch language.lowercased().split(whereSeparator: { $0 == "-" || $0 == "_" }).first {
        case "de": return "falsch"
        case "fr": return "faux"
        case "nl": return "fout"
        default: return "wrong"
        }
    }

    static func matchesCommand(_ transcript: String, language: String) -> Bool {
        let normalized = transcript.lowercased().trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
        // Whole utterance only: never discard a sign for “not wrong” or a
        // substring in an unrelated sentence.
        return normalized == command(language: language)
    }
}

/// iPhone uses its existing offline Apple recognizer; Android uses bundled
/// Vosk models for the same four command languages. Never fall back to a server.
@MainActor
final class VisionDismissalSpeechListener {
    private var engine: AVAudioEngine?
    private var recognizer: SFSpeechRecognizer?
    private var inputTapInstalled = false
    private var previousAudioConfiguration: (AVAudioSession.Category, AVAudioSession.Mode, AVAudioSession.CategoryOptions)?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var interruptionObserver: NSObjectProtocol?
    private var ownsAudioSession = false

    func start(language: String, onResult: @escaping @MainActor (String?, Bool) -> Void) throws {
        guard SFSpeechRecognizer.authorizationStatus() == .authorized,
              AVAudioApplication.shared.recordPermission == .granted,
              let recognizer = SFSpeechRecognizer(locale: Locale(identifier: language)),
              recognizer.isAvailable, recognizer.supportsOnDeviceRecognition else {
            throw ConsumerAppError.io("On-device dismissal speech recognition is unavailable.")
        }
        self.recognizer = recognizer
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.addsPunctuation = false
        request.taskHint = .confirmation
        request.contextualStrings = [VisionDismissalVoiceWindow.command(language: language)]
        self.request = request
        do {
            let audioSession = AVAudioSession.sharedInstance()
            previousAudioConfiguration = (audioSession.category, audioSession.mode, audioSession.categoryOptions)
            try audioSession.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
            ownsAudioSession = true
            try audioSession.setActive(true)
            guard let microphone = audioSession.availableInputs?.first(where: { $0.portType == .builtInMic }) else {
                throw ConsumerAppError.io("The iPhone microphone is unavailable.")
            }
            try audioSession.setPreferredInput(microphone)
            let engine = AVAudioEngine()
            self.engine = engine
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                throw ConsumerAppError.io("The iPhone microphone has no active audio input.")
            }
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in request.append(buffer) }
            inputTapInstalled = true
            engine.prepare()
            try engine.start()
            task = recognizer.recognitionTask(with: request) { result, error in
                let transcript = result?.isFinal == true ? result?.bestTranscription.formattedString : nil
                let ended = result?.isFinal == true || error != nil
                Task { @MainActor in onResult(transcript, ended) }
            }
            interruptionObserver = NotificationCenter.default.addObserver(
                forName: AVAudioSession.interruptionNotification, object: audioSession, queue: .main
            ) { _ in Task { @MainActor in onResult(nil, true) } }
        } catch {
            stop()
            throw error
        }
    }

    func finishAudio() {
        engine?.stop()
        request?.endAudio()
    }

    func stop() {
        if let interruptionObserver { NotificationCenter.default.removeObserver(interruptionObserver) }
        interruptionObserver = nil
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        recognizer = nil
        if let engine {
            engine.stop()
            if inputTapInstalled { engine.inputNode.removeTap(onBus: 0) }
        }
        inputTapInstalled = false
        engine = nil
        if ownsAudioSession {
            let session = AVAudioSession.sharedInstance()
            try? session.setPreferredInput(nil)
            try? session.setActive(false, options: .notifyOthersOnDeactivation)
            if let (category, mode, options) = previousAudioConfiguration {
                try? session.setCategory(category, mode: mode, options: options)
            }
            ownsAudioSession = false
        }
    }
}
