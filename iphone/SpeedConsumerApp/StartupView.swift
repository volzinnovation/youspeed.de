import SwiftUI

struct StartupView: View {
    @ObservedObject var viewModel: DriveSessionViewModel

    var body: some View {
        ZStack {
            Color.black
                .ignoresSafeArea()

            VStack(spacing: 18) {
                Text("YouSpeed")
                    .font(.system(size: 42, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)

                Text("Lade lokale Kartendaten")
                    .font(.system(size: 20, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)

                ProgressView(value: clampedProgress, total: 1)
                    .tint(.red)
                    .padding(.top, 10)

                Text("\(Int(clampedProgress * 100))%")
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.92))
                    .monospacedDigit()

                Text(viewModel.startupDetail)
                    .font(.system(size: 16, weight: .medium, design: .rounded))
                    .foregroundStyle(.white.opacity(0.85))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 16)

                if viewModel.startupDataState == .failed {
                    if !viewModel.lastError.isEmpty {
                        Text(viewModel.lastError)
                            .font(.system(size: 14, weight: .regular, design: .rounded))
                            .foregroundStyle(.white.opacity(0.75))
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 16)
                    }

                    Button("Erneut versuchen") {
                        viewModel.retryStartupDataPreparation()
                    }
                    .font(.system(size: 17, weight: .bold, design: .rounded))
                    .buttonStyle(.borderedProminent)
                    .tint(.red)
                }
            }
            .padding(.horizontal, 24)
            .frame(maxWidth: 420)
        }
    }

    private var clampedProgress: Double {
        min(1, max(0, viewModel.startupProgress))
    }
}
