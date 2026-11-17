import SwiftUI

struct MapillaryAccountSection: View {
    @ObservedObject var model: MapillaryUploadModel
    @State private var token = ""
    var body: some View {
        Section(mly("account")) {
            if let username = model.username {
                LabeledContent(mly("account"), value: username)
                Button(mly("disconnect"), role: .destructive) { model.disconnect() }
                    .disabled(model.isBusy || model.isUploading)
            } else {
                SecureField(mly("token"), text: $token)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .accessibilityIdentifier("mapillary.account.token")
                Text(mly("token_help")).font(.footnote).foregroundStyle(.secondary)
                Link(mly("token_link"), destination: URL(string: "https://www.mapillary.com/developer")!)
                Button(mly("connect")) {
                    model.connect(token: token)
                    token = ""
                }
                .accessibilityIdentifier("mapillary.account.connect")
                .disabled(token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isBusy || model.isUploading)
            }
            if model.isBusy { ProgressView() }
            if !model.status.isEmpty { Text(model.status).font(.caption) }
        }
    }
}

struct MapillaryUploadView: View {
    @ObservedObject var model: MapillaryUploadModel
    let photos: [MapillaryPhoto]
    let allowed: @MainActor @Sendable () -> Bool
    var body: some View {
        List {
            Section {
                Text(String(format: mly("selected"), photos.count))
                Text(mly("scope")).font(.footnote).foregroundStyle(.secondary)
                if !model.isConnected { Text(mly("account_required")) }
                if !allowed() { Text(mly("paused")).foregroundStyle(.orange) }
                if model.isUploading {
                    ProgressView(value: Double(model.completed), total: Double(max(1, model.total)))
                    Text("\(model.completed) / \(model.total)").monospacedDigit()
                    Button(mly("stop"), role: .destructive) { model.stop() }
                        .accessibilityIdentifier("mapillary.upload.stop")
                } else {
                    Button(mly("upload")) { model.start(photos: photos, allowed: { @MainActor @Sendable in allowed() }) }
                        .accessibilityIdentifier("mapillary.upload.start")
                        .disabled(photos.isEmpty || !model.isConnected || model.isBusy || !allowed())
                }
                if !model.status.isEmpty { Text(model.status).accessibilityIdentifier("mapillary.upload.status") }
            }
            if !model.pending.isEmpty {
                Section(mly("pending")) {
                    ForEach(model.pending) { job in
                        Button(String(format: mly("resume_count"), job.images.count)) {
                            model.start(resume: job, allowed: { @MainActor @Sendable in allowed() })
                        }.disabled(model.isUploading || model.isBusy || !allowed() || !model.isConnected)
                    }
                }
            }
        }
        .navigationTitle("Mapillary")
        .navigationBarTitleDisplayMode(.inline)
        .subscreenCloseButton()
        .task { await model.refresh() }
    }
}
