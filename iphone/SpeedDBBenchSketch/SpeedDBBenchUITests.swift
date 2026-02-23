import XCTest

final class SpeedDBBenchUITests: XCTestCase {
    func testRunBenchmarkFlow() {
        let app = XCUIApplication()
        app.launchArguments.append("--uitest-benchmark")
        app.launch()

        let runButton = app.buttons["runBenchmarkButton"]
        XCTAssertTrue(runButton.waitForExistence(timeout: 10))
        runButton.tap()

        let status = app.staticTexts["benchmarkStatus"]
        XCTAssertTrue(status.waitForExistence(timeout: 10))

        let donePredicate = NSPredicate(format: "label CONTAINS 'benchmark_finished' OR label CONTAINS 'error_'")
        expectation(for: donePredicate, evaluatedWith: status)
        waitForExpectations(timeout: 1800)
        XCTAssertTrue(
            status.label.contains("benchmark_finished"),
            "Expected benchmark to finish, got status: \(status.label)"
        )
    }
}
