#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>
#include "packed_benchmark.h"

static NSString* argument(NSString* name,NSString* fallback){NSArray* args=NSProcessInfo.processInfo.arguments;NSUInteger index=[args indexOfObject:name];return index!=NSNotFound&&index+1<args.count?args[index+1]:fallback;}
static NSString* resolve(NSString* documents,NSString* path){return path.isAbsolutePath?path:[documents stringByAppendingPathComponent:path];}

@interface PackedBenchmarkDelegate:UIResponder<UIApplicationDelegate>
@property(nonatomic,strong)UIWindow* window;
@property(nonatomic,strong)UILabel* status;
@end

@implementation PackedBenchmarkDelegate
- (BOOL)application:(UIApplication*)application didFinishLaunchingWithOptions:(NSDictionary*)options {
    application.idleTimerDisabled=YES;
    self.window=[[UIWindow alloc]initWithFrame:UIScreen.mainScreen.bounds];UIViewController* controller=[UIViewController new];controller.view.backgroundColor=UIColor.systemBackgroundColor;
    self.status=[[UILabel alloc]initWithFrame:CGRectInset(self.window.bounds,24,64)];self.status.numberOfLines=0;self.status.text=@"YouSpeed packed runtime\nStarting isolated storage benchmark…";[controller.view addSubview:self.status];self.window.rootViewController=controller;[self.window makeKeyAndVisible];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{@autoreleasepool{[self runBenchmark];}});return YES;
}
- (void)progress:(NSString*)stage documents:(NSString*)documents configuration:(NSDictionary*)configuration {
    NSDictionary* progress=@{@"stage":stage,@"run_id":configuration[@"run_id"]?:@"unknown",@"epoch_s":@([NSDate.date timeIntervalSince1970])};
    NSData* bytes=[NSJSONSerialization dataWithJSONObject:progress options:NSJSONWritingPrettyPrinted error:nil];[bytes writeToFile:[documents stringByAppendingPathComponent:@"packed-runtime-progress.json"] options:NSDataWritingAtomic error:nil];
    NSLog(@"Packed runtime benchmark: %@",stage);dispatch_async(dispatch_get_main_queue(),^{self.status.text=[NSString stringWithFormat:@"YouSpeed packed runtime\n%@\n%@",configuration[@"mode"]?:@"unknown",stage];});
}
- (void)runBenchmark {
    NSString* documents=NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject;NSError* error=nil;
    NSData* configBytes=[NSData dataWithContentsOfFile:resolve(documents,argument(@"--config",@"data/packed-benchmark.json")) options:0 error:&error];
    id object=configBytes?[NSJSONSerialization JSONObjectWithData:configBytes options:0 error:&error]:nil;NSDictionary* configuration=[object isKindOfClass:NSDictionary.class]?object:nil;
    [self progress:@"configuration-loaded" documents:documents configuration:configuration?:@{}];
    NSDate* started=NSDate.date;NSProcessInfoThermalState before=NSProcessInfo.processInfo.thermalState;NSMutableDictionary* report=[NSMutableDictionary new];
    if(!configuration){report[@"error"]=error.localizedDescription?:@"Missing configuration";report[@"overall_success"]=@NO;}
    else {
        NSString* database=resolve(documents,configuration[@"database"]?:@"");NSString* geometry=resolve(documents,configuration[@"geometry"]?:@"-");NSString* csvPath=resolve(documents,configuration[@"queries"]?:@"data/queries.csv");
        NSString* csv=[NSString stringWithContentsOfFile:csvPath encoding:NSUTF8StringEncoding error:&error];
        if(!csv){report[@"error"]=error.localizedDescription?:@"Missing query corpus";report[@"overall_success"]=@NO;}
        else {
            [self progress:@"native-running" documents:documents configuration:configuration];
            char* native=ysp_storage_benchmark_json([configuration[@"mode"] UTF8String],database.UTF8String,geometry.UTF8String,csv.UTF8String,[configuration[@"repetitions"]?:@3 intValue],[configuration[@"rss_gate_bytes"]?:@(64*1024*1024) unsignedLongLongValue]);
            NSData* bytes=native?[[NSString stringWithUTF8String:native]dataUsingEncoding:NSUTF8StringEncoding]:nil;id parsed=bytes?[NSJSONSerialization JSONObjectWithData:bytes options:0 error:&error]:nil;
            if([parsed isKindOfClass:NSDictionary.class])[report addEntriesFromDictionary:parsed];else {report[@"error"]=error.localizedDescription?:@"Native report missing/invalid";report[@"overall_success"]=@NO;}
            ysp_storage_benchmark_free(native);
        }
    }
    report[@"configuration"]=configuration?:@{};report[@"platform"]=@"iPhone isolated native packed storage";report[@"system_version"]=UIDevice.currentDevice.systemVersion;report[@"device_model"]=UIDevice.currentDevice.model;report[@"thermal_state_before"]=@(before);report[@"thermal_state_after"]=@(NSProcessInfo.processInfo.thermalState);report[@"started_at_epoch_s"]=@([started timeIntervalSince1970]);report[@"finished_at_epoch_s"]=@([NSDate.date timeIntervalSince1970]);
    NSData* bytes=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:&error];BOOL saved=bytes&&[bytes writeToFile:[documents stringByAppendingPathComponent:@"packed-runtime-report.json"] options:NSDataWritingAtomic error:&error];
    [self progress:saved?([report[@"overall_success"]boolValue]?@"complete":@"failed"):@"report-write-failed" documents:documents configuration:configuration?:@{}];
}
@end

int main(int argc,char** argv){@autoreleasepool{return UIApplicationMain(argc,argv,nil,NSStringFromClass(PackedBenchmarkDelegate.class));}}
