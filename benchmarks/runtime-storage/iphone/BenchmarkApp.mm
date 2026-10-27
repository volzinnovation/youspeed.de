#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>

extern "C" char *storage_benchmark_json(const char *, const char *, const char *, int);
extern "C" void storage_free(void *);
extern "C" char *storage_query_batch_json(const char *, const char *, const char *);
extern "C" const char *ysp_corrections_selftest_json(void);
extern "C" const char *ysp_corrections_persistence_selftest_json(const char *);
extern "C" const char *ysp_corrections_source_node_probe_json(const char *, const char *);
extern "C" char *storage_nodes_benchmark_json(const char *, const char *, const char *, int);
extern "C" char *storage_node_json(const char *, const char *, long long);
extern "C" void storage_nodes_free(void *);

static void progress(NSString *phase) {
    NSString *documents = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
    NSDictionary *value = @{@"phase": phase, @"epoch_s": @([[NSDate date] timeIntervalSince1970]),
                            @"pid": @(NSProcessInfo.processInfo.processIdentifier),
                            @"arguments": NSProcessInfo.processInfo.arguments};
    NSData *bytes = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    [bytes writeToFile:[documents stringByAppendingPathComponent:@"benchmark-progress.json"] options:NSDataWritingAtomic error:nil];
    NSLog(@"YSP_BENCH %@", phase);
}

static NSString *argument(NSString *key, NSString *fallback) {
    NSArray<NSString *> *args = NSProcessInfo.processInfo.arguments;
    NSUInteger i = [args indexOfObject:key];
    return i != NSNotFound && i + 1 < args.count ? args[i + 1] : fallback;
}

static NSString *resolvePaths(NSString *root, NSString *path) {
    NSMutableArray *parts = [NSMutableArray new];
    for (NSString *part in [path componentsSeparatedByString:@"|"])
        [parts addObject:part.isAbsolutePath ? part : [root stringByAppendingPathComponent:part]];
    return [parts componentsJoinedByString:@"|"];
}

static id parseNative(const char *text) {
    if (!text) return nil;
    NSData *bytes = [[NSString stringWithUTF8String:text] dataUsingEncoding:NSUTF8StringEncoding];
    return bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:nil] : nil;
}

@interface BenchmarkDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@property(nonatomic, strong) UILabel *status;
@end

@implementation BenchmarkDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    application.idleTimerDisabled = YES;
    progress(@"application_did_finish_launching");
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller = [UIViewController new];
    controller.view.backgroundColor = UIColor.systemBackgroundColor;
    self.status = [[UILabel alloc] initWithFrame:CGRectInset(self.window.bounds, 24, 70)];
    self.status.numberOfLines = 0;
    self.status.text = @"YouSpeed storage prototype\nPreparing benchmark…";
    [controller.view addSubview:self.status];
    self.window.rootViewController = controller;
    [self.window makeKeyAndVisible];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        @autoreleasepool {
            [self runBenchmark];
        }
    });
    return YES;
}

- (void)runBenchmark {
    progress(@"worker_started");
    NSString *documents = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
    NSString *configName = argument(@"--config", @"data/sqlite.json");
    NSString *configPath = [documents stringByAppendingPathComponent:configName];
    NSError *error = nil;
    NSData *configData = [NSData dataWithContentsOfFile:configPath options:0 error:&error];
    id loadedConfig = configData ? [NSJSONSerialization JSONObjectWithData:configData options:0 error:&error] : nil;
    NSDictionary *config = [loadedConfig isKindOfClass:NSDictionary.class] ? loadedConfig : nil;
    NSMutableDictionary *report = [NSMutableDictionary new];
    NSString *backend = config[@"backend"] ?: @"unknown";
    NSDate *started = [NSDate date];
    NSProcessInfoThermalState thermalBefore = NSProcessInfo.processInfo.thermalState;
    if (![config isKindOfClass:NSDictionary.class]) {
        report[@"error"] = error.localizedDescription ?: @"Missing benchmark configuration";
    } else {
        NSString *root = [documents stringByAppendingPathComponent:config[@"directory"] ?: @"data"];
        NSString *path = resolvePaths(root, config[@"path"] ?: @"");
        NSString *queriesPath = [root stringByAppendingPathComponent:config[@"queries"] ?: @"queries.csv"];
        NSString *queries = [NSString stringWithContentsOfFile:queriesPath encoding:NSUTF8StringEncoding error:&error];
        if (!queries) {
            report[@"error"] = error.localizedDescription ?: @"Missing query corpus";
        } else {
            progress(@"road_benchmark_started");
            char *result = storage_benchmark_json(backend.UTF8String, path.UTF8String, queries.UTF8String,
                                                  [config[@"repetitions"] ?: @3 intValue]);
            if (result) {
                NSData *resultData = [[NSString stringWithUTF8String:result] dataUsingEncoding:NSUTF8StringEncoding];
                id object = resultData ? [NSJSONSerialization JSONObjectWithData:resultData options:0 error:&error] : nil;
                if ([object isKindOfClass:NSDictionary.class]) [report addEntriesFromDictionary:object];
                else report[@"error"] = error.localizedDescription ?: @"Native benchmark returned invalid JSON";
                storage_free(result);
            } else report[@"error"] = @"Native benchmark returned no result";
            progress(@"road_benchmark_finished");
        }
        if (config[@"node_path"]) {
            NSString *nodePath = resolvePaths(root, config[@"node_path"]);
            NSString *nodeCSVPath = [root stringByAppendingPathComponent:config[@"node_queries"] ?: @"node-queries.csv"];
            NSString *nodeCSV = [NSString stringWithContentsOfFile:nodeCSVPath encoding:NSUTF8StringEncoding error:&error];
            if (nodeCSV) {
                progress(@"node_benchmark_started");
                char *nodes = storage_nodes_benchmark_json(backend.UTF8String, nodePath.UTF8String, nodeCSV.UTF8String,
                                                          [config[@"repetitions"] ?: @3 intValue]);
                id nodeReport = parseNative(nodes);
                if (nodeReport) report[@"generic_speed_nodes"] = nodeReport;
                if (nodes) storage_nodes_free(nodes);
                progress(@"node_benchmark_finished");
            } else report[@"node_error"] = error.localizedDescription ?: @"Missing node corpus";
        }
    }
    const char *overlay = ysp_corrections_selftest_json();
    if (overlay) {
        NSData *bytes = [[NSString stringWithUTF8String:overlay] dataUsingEncoding:NSUTF8StringEncoding];
        id object = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:nil] : nil;
        if (object) report[@"correction_overlay_selftest"] = object;
    }
    NSString *journal = [NSTemporaryDirectory() stringByAppendingPathComponent:@"storage-corrections-test.journal"];
    id persistence = parseNative(ysp_corrections_persistence_selftest_json(journal.UTF8String));
    if (persistence) report[@"correction_persistence_selftest"] = persistence;
    if (config[@"node_path"]) {
        NSString *root = [documents stringByAppendingPathComponent:config[@"directory"] ?: @"data"];
        NSString *nodePath = resolvePaths(root, config[@"node_path"]);
        char *source = storage_node_json(backend.UTF8String, nodePath.UTF8String, 2532969814LL);
        id amendment = parseNative(ysp_corrections_source_node_probe_json(source, [journal stringByAppendingString:@".source-node"].UTF8String));
        if (amendment) report[@"source_amendment_probe"] = amendment;
        storage_nodes_free(source);
    }
    NSDictionary *nodeReport = report[@"generic_speed_nodes"];
    NSDictionary *correctionReport = report[@"correction_overlay_selftest"];
    NSDictionary *diskReport = report[@"correction_persistence_selftest"];
    NSDictionary *amendment = report[@"source_amendment_probe"];
    BOOL passed = !report[@"error"] && [report[@"query_count"] unsignedLongLongValue] > 0
        && [nodeReport isKindOfClass:NSDictionary.class] && !nodeReport[@"error"]
        && [nodeReport[@"query_count"] unsignedLongLongValue] > 0 && !report[@"node_error"]
        && [correctionReport isKindOfClass:NSDictionary.class] && correctionReport[@"failed"]
        && [correctionReport[@"failed"] intValue] == 0 && [correctionReport[@"tests"] intValue] > 0
        && [diskReport[@"created_reopened"] boolValue] && [diskReport[@"amended_reopened"] boolValue]
        && [diskReport[@"tombstoned_reopened"] boolValue] && [diskReport[@"history_preserved"] boolValue]
        && [amendment isKindOfClass:NSDictionary.class] && amendment[@"failed"]
        && [amendment[@"failed"] intValue] == 0 && [amendment[@"tests"] intValue] > 0
        && [amendment[@"error"] isEqual:@""];
    report[@"overall_success"] = @(passed);
    if (!passed && !report[@"error"]) report[@"error"] = @"A storage, generic-node, or correction check failed";
    report[@"platform"] = @"iPhone native isolated benchmark";
    report[@"system_version"] = UIDevice.currentDevice.systemVersion;
    report[@"device_model"] = UIDevice.currentDevice.model;
    report[@"physical_memory_bytes"] = @(NSProcessInfo.processInfo.physicalMemory);
    report[@"thermal_state_before"] = @(thermalBefore);
    report[@"thermal_state_after"] = @(NSProcessInfo.processInfo.thermalState);
    report[@"started_at_epoch_s"] = @([started timeIntervalSince1970]);
    report[@"finished_at_epoch_s"] = @([[NSDate date] timeIntervalSince1970]);
    progress(@"correction_checks_finished");
    // Export after both timed/memory phases, so cross-phone parity does not alter measurements.
    if (passed && [config[@"write_road_results"] boolValue]) {
        NSString *root = [documents stringByAppendingPathComponent:config[@"directory"] ?: @"data"];
        NSString *path = resolvePaths(root, config[@"path"] ?: @"");
        NSString *csv = [NSString stringWithContentsOfFile:[root stringByAppendingPathComponent:config[@"queries"] ?: @"queries.csv"]
                                                  encoding:NSUTF8StringEncoding error:&error];
        char *nativeResults = csv ? storage_query_batch_json(backend.UTF8String, path.UTF8String, csv.UTF8String) : nullptr;
        id results = parseNative(nativeResults);
        NSString *resultsPath = [documents stringByAppendingPathComponent:[NSString stringWithFormat:@"road-results-%@.json", backend]];
        NSData *resultBytes = nativeResults ? [[NSString stringWithUTF8String:nativeResults] dataUsingEncoding:NSUTF8StringEncoding] : nil;
        BOOL exported = [results isKindOfClass:NSArray.class] && [results count] == [report[@"query_count"] unsignedLongLongValue]
            && [resultBytes writeToFile:resultsPath options:NSDataWritingAtomic error:&error];
        storage_free(nativeResults);
        report[@"road_results_exported"] = @(exported);
        if (!exported) {report[@"overall_success"]=@NO;report[@"error"]=@"Cross-phone road result export failed";}
    }
    if (config) report[@"configuration"] = config;
    NSString *output = [documents stringByAppendingPathComponent:[NSString stringWithFormat:@"report-%@.json", backend]];
    NSData *bytes = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:&error];
    BOOL saved = bytes && [bytes writeToFile:output options:NSDataWritingAtomic error:&error];
    progress(saved ? @"report_written" : @"report_write_failed");
    dispatch_async(dispatch_get_main_queue(), ^{
        self.status.text = [NSString stringWithFormat:@"YouSpeed storage prototype\n%@\n%@\n%@", backend,
                            report[@"error"] ?: (saved ? @"Complete" : @"Report write failed"), output];
    });
}
@end

int main(int argc, char **argv) {
    @autoreleasepool {
        progress(@"main_entered");
        return UIApplicationMain(argc, argv, nil, NSStringFromClass(BenchmarkDelegate.class));
    }
}
