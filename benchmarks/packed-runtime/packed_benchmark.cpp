#include "packed_benchmark.h"
#include "packed_runtime.h"
#include "runtime_storage.h"
#include <sqlite3.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <unistd.h>
#include <vector>
#ifdef __APPLE__
#include <mach/mach.h>
#endif

namespace {
using Clock=std::chrono::steady_clock;
constexpr uint64_t HASH=14695981039346656037ull;
void check(bool ok,const char* error){if(!ok)throw std::runtime_error(error);}
uint64_t hash(uint64_t value,const void* input,size_t size){const auto bytes=static_cast<const unsigned char*>(input);for(size_t i=0;i<size;++i)value=(value^bytes[i])*1099511628211ull;return value;}
std::string hex(uint64_t value){std::ostringstream out;out<<std::hex<<std::setw(16)<<std::setfill('0')<<value;return out.str();}
std::string quoted(const std::string& value){std::ostringstream out;out<<'"';for(unsigned char c:value){if(c=='"'||c=='\\')out<<'\\'<<c;else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<unsigned(c)<<std::dec;else out<<c;}out<<'"';return out.str();}
char* copy(const std::string& value){auto result=static_cast<char*>(std::malloc(value.size()+1));check(result,"benchmark allocation failed");std::memcpy(result,value.c_str(),value.size()+1);return result;}
struct Memory {uint64_t rss=0,kernelPeak=0,footprint=0,pss=0,anonymous=0,file=0,privateDirty=0;bool mach=false,smaps=false;const char* source="unavailable";};
Memory memory(){Memory result;struct rusage usage{};getrusage(RUSAGE_SELF,&usage);
#ifdef __APPLE__
    result.kernelPeak=usage.ru_maxrss;mach_task_basic_info_data_t info{};mach_msg_type_number_t count=MACH_TASK_BASIC_INFO_COUNT;if(task_info(mach_task_self(),MACH_TASK_BASIC_INFO,reinterpret_cast<task_info_t>(&info),&count)==KERN_SUCCESS){result.rss=info.resident_size;result.source="mach_task_basic_info";}task_vm_info_data_t vm{};count=TASK_VM_INFO_COUNT;if(task_info(mach_task_self(),TASK_VM_INFO,reinterpret_cast<task_info_t>(&vm),&count)==KERN_SUCCESS){result.footprint=vm.phys_footprint;result.mach=true;}
#else
    result.kernelPeak=uint64_t(usage.ru_maxrss)*1024;std::ifstream stat("/proc/self/statm");uint64_t total=0,resident=0;if(stat>>total>>resident){result.rss=resident*sysconf(_SC_PAGESIZE);result.source="proc_statm";}std::ifstream smaps("/proc/self/smaps_rollup");std::string line;while(std::getline(smaps,line)){std::istringstream input(line);std::string key,unit;uint64_t value=0;if(!(input>>key>>value>>unit)||unit!="kB")continue;value*=1024;if(key=="Rss:"){result.rss=value;result.source="proc_smaps_rollup";}else if(key=="Pss:"){result.pss=value;result.smaps=true;}else if(key=="Pss_Anon:")result.anonymous=value;else if(key=="Pss_File:")result.file=value;else if(key=="Private_Dirty:")result.privateDirty=value;}
#endif
    return result;
}
std::string memoryJSON(Memory value){std::ostringstream out;out<<"{\"rss_bytes\":"<<value.rss<<",\"rss_source\":"<<quoted(value.source)<<",\"kernel_highwater_rss_bytes\":"<<value.kernelPeak<<",\"physical_footprint_bytes\":"<<(value.mach?std::to_string(value.footprint):"null")<<",\"pss_bytes\":"<<(value.smaps?std::to_string(value.pss):"null")<<",\"pss_anonymous_bytes\":"<<(value.smaps?std::to_string(value.anonymous):"null")<<",\"pss_file_bytes\":"<<(value.smaps?std::to_string(value.file):"null")<<",\"private_dirty_bytes\":"<<(value.smaps?std::to_string(value.privateDirty):"null")<<"}";return out.str();}
std::string stats(std::vector<double> values){std::sort(values.begin(),values.end());if(values.empty())return "{}";auto at=[&](double p){return values[static_cast<size_t>(std::ceil(p*(values.size()-1)))];};std::ostringstream out;out<<std::setprecision(10)<<"{\"count\":"<<values.size()<<",\"p50_us\":"<<at(.5)<<",\"p95_us\":"<<at(.95)<<",\"p99_us\":"<<at(.99)<<",\"max_us\":"<<values.back()<<"}";return out.str();}
std::vector<std::array<double,3>> queries(const char* csv){std::istringstream input(csv?csv:"");std::string line;std::vector<std::array<double,3>> result;while(std::getline(input,line)){if(line.empty()||line[0]=='#'||line.rfind("lat,",0)==0)continue;std::replace(line.begin(),line.end(),',',' ');std::istringstream row(line);std::array<double,3> value{};check(bool(row>>value[0]>>value[1]>>value[2]),"invalid benchmark CSV");check(std::isfinite(value[0])&&std::isfinite(value[1])&&std::isfinite(value[2])&&std::abs(value[0])<85&&std::abs(value[1])<180&&value[2]>0&&value[2]<=10000,"benchmark coordinate/radius outside scope");result.push_back(value);}check(!result.empty()&&result.size()<=100000,"empty/oversized benchmark corpus");return result;}
int64_t integerField(const std::string& json,const std::string& name){const auto found=json.find("\""+name+"\":");check(found!=std::string::npos,"missing benchmark diagnostic field");return std::stoll(json.substr(json.find(':',found)+1));}
std::string owned(char* value){if(!value)return "null";std::string result(value);ysp_packed_free(value);return result;}
bool cacheWithin(const std::string& value){if(value=="null")return true;return integerField(value,"block_cache_peak_bytes")<=integerField(value,"block_cache_capacity_bytes")&&integerField(value,"page_cache_peak_bytes")<=integerField(value,"page_cache_capacity_bytes")&&integerField(value,"mapped_bytes")==0;}
std::string sqliteConfiguration(){return "PRAGMA mmap_size=0;PRAGMA cache_size=-"+std::to_string(ysp_sqlite_cache_kib())+";PRAGMA query_only=ON;";}
void geometryScalar(sqlite3_context* context,int argc,sqlite3_value** argv){if(argc!=1||sqlite3_value_type(argv[0])==SQLITE_NULL){sqlite3_result_null(context);return;}char error[512]{};char* value=ysp_geometry_json(sqlite3_user_data(context),reinterpret_cast<const char*>(sqlite3_value_text(argv[0])),error,sizeof error);if(!value){sqlite3_result_error(context,error,-1);return;}sqlite3_result_text(context,value,-1,&ysp_packed_free);}
uint64_t rowHash(uint64_t digest,sqlite3_stmt* statement){for(int column=0;column<sqlite3_column_count(statement);++column){const uint8_t type=sqlite3_column_type(statement,column);digest=hash(digest,&type,sizeof type);if(type==SQLITE_INTEGER){const auto value=sqlite3_column_int64(statement,column);digest=hash(digest,&value,sizeof value);}else if(type==SQLITE_FLOAT){const auto value=sqlite3_column_double(statement,column);digest=hash(digest,&value,sizeof value);}else if(type==SQLITE_TEXT||type==SQLITE_BLOB){const uint64_t size=sqlite3_column_bytes(statement,column);digest=hash(digest,&size,sizeof size);const auto value=type==SQLITE_TEXT?sqlite3_column_text(statement,column):static_cast<const unsigned char*>(sqlite3_column_blob(statement,column));digest=hash(digest,value,size);}}return digest;}

std::string poolStress(const char* path,const char* geometry,const char* csv,uint64_t gate,size_t count){
    // Independent connections reproduce per-handle cache multiplication even
    // when their immutable generation bytes happen to be identical.
    struct Connection {
        std::unique_ptr<void,decltype(&ysp_geometry_close)> geometry{nullptr,&ysp_geometry_close};
        std::unique_ptr<sqlite3,decltype(&sqlite3_close)> database{nullptr,&sqlite3_close};
        std::unique_ptr<sqlite3_stmt,decltype(&sqlite3_finalize)> statement{nullptr,&sqlite3_finalize};
    };
    check(count>0&&count<=30,"invalid stress connection count");const auto corpus=queries(csv);const auto before=memory();uint64_t observed=before.rss;
    check(ysp_register_context_vfs()==SQLITE_OK,"context VFS registration failed");
    std::vector<std::unique_ptr<Connection>> connections;std::vector<std::string> snapshots,contexts,geometries,latencies;
    std::vector<std::array<uint64_t,2>> expected;std::vector<uint64_t> digests;bool caches=true;
    for(size_t i=0;i<count;++i){
        auto connection=std::make_unique<Connection>();char error[512]{};
        connection->geometry.reset(ysp_geometry_open(geometry,0,error,sizeof error));check(connection->geometry!=nullptr,error);
        sqlite3* pointer=nullptr;const int code=sqlite3_open_v2(path,&pointer,SQLITE_OPEN_READONLY|SQLITE_OPEN_NOMUTEX,"ysp-packed-v1");connection->database.reset(pointer);check(code==SQLITE_OK,pointer?sqlite3_errmsg(pointer):"pool database open failed");
        int flags=SQLITE_UTF8|SQLITE_DETERMINISTIC;
#ifdef SQLITE_INNOCUOUS
        flags|=SQLITE_INNOCUOUS;
#endif
        check(sqlite3_create_function_v2(pointer,"ysp_way_points_json",1,flags,connection->geometry.get(),geometryScalar,nullptr,nullptr,nullptr)==SQLITE_OK,sqlite3_errmsg(pointer));
        check(sqlite3_exec(pointer,sqliteConfiguration().c_str(),nullptr,nullptr,nullptr)==SQLITE_OK,sqlite3_errmsg(pointer));
        const char* sql="SELECT w.*,g.points_json FROM ways_rtree r JOIN ways w ON w.way_id=r.way_id LEFT JOIN way_geom g ON g.way_id=w.way_id WHERE r.min_lon<=?1 AND r.max_lon>=?2 AND r.min_lat<=?3 AND r.max_lat>=?4 ORDER BY CAST(w.way_id AS TEXT) COLLATE BINARY";
        sqlite3_stmt* statement=nullptr;check(sqlite3_prepare_v2(pointer,sql,-1,&statement,nullptr)==SQLITE_OK,sqlite3_errmsg(pointer));connection->statement.reset(statement);
        uint64_t digest=HASH;size_t queryIndex=0;std::vector<double> times;
        for(const auto& query:corpus){const auto started=Clock::now();const double dy=query[2]/(6371008.8*3.14159265358979323846/180),dx=dy/std::cos(query[0]*3.14159265358979323846/180);sqlite3_reset(statement);sqlite3_bind_double(statement,1,query[1]+dx);sqlite3_bind_double(statement,2,query[1]-dx);sqlite3_bind_double(statement,3,query[0]+dy);sqlite3_bind_double(statement,4,query[0]-dy);uint64_t rowDigest=HASH,rows=0;int step=0;while((step=sqlite3_step(statement))==SQLITE_ROW){rowDigest=rowHash(rowDigest,statement);++rows;}check(step==SQLITE_DONE,sqlite3_errmsg(pointer));const std::array<uint64_t,2> result{rowDigest,rows};if(i==0)expected.push_back(result);else check(result==expected[queryIndex],"pool lookup results differ between connections");digest=hash(digest,result.data(),sizeof result);++queryIndex;times.push_back(std::chrono::duration<double,std::micro>(Clock::now()-started).count());}
        latencies.push_back(stats(times));digests.push_back(digest);connections.push_back(std::move(connection));const auto snapshot=memory();observed=std::max(observed,snapshot.rss);snapshots.push_back(memoryJSON(snapshot));
    }
    for(auto& connection:connections){contexts.push_back(owned(ysp_context_vfs_stats_json(connection->database.get())));geometries.push_back(owned(ysp_geometry_stats_json(connection->geometry.get())));caches=caches&&cacheWithin(contexts.back())&&cacheWithin(geometries.back());}
    const auto after=memory();observed=std::max(observed,after.rss);const auto delta=observed-before.rss;
    std::ostringstream output;output<<"{\"schema\":1,\"mode\":\"pool-context-packed\",\"measurement_valid\":true,\"connection_count\":"<<count<<",\"sqlite_page_cache_kib\":"<<ysp_sqlite_cache_kib()<<",\"queries_per_connection\":"<<corpus.size()<<",\"all_connection_results_identical\":true,\"observed_snapshot_incremental_rss_bytes\":"<<delta<<",\"rss_gate_bytes\":"<<gate<<",\"memory_gate_pass\":"<<(delta<gate?"true":"false")<<",\"cache_bounds_pass\":"<<(caches?"true":"false")<<",\"overall_success\":"<<(delta<gate&&caches?"true":"false")<<",\"memory_before\":"<<memoryJSON(before)<<",\"memory_after\":"<<memoryJSON(after)<<",\"connections\":[";
    for(size_t i=0;i<count;++i){if(i)output<<',';output<<"{\"connection_index\":"<<i<<",\"result_fnv1a64\":"<<quoted(hex(digests[i]))<<",\"lookup_latency\":"<<latencies[i]<<",\"memory_after_fill\":"<<snapshots[i]<<",\"context_io_stats\":"<<contexts[i]<<",\"geometry_io_stats\":"<<geometries[i]<<'}';}
    output<<"],\"result_fnv1a64\":"<<quoted(hex(digests.front()))<<",\"query_results\":[";
    for(size_t i=0;i<expected.size();++i){if(i)output<<',';output<<"{\"query_index\":"<<i<<",\"rows\":"<<expected[i][1]<<",\"result_fnv1a64\":"<<quoted(hex(expected[i][0]))<<'}';}
    output<<"],\"notes\":\"Independent SQLite connections and geometry handles are retained simultaneously after each runs the entire corpus. Native default caches and SQLite page caches multiply per connection. This stress does not include platform decoded-geometry caches or other driving-app allocations. It is not an app-wide memory guarantee or OS-cold benchmark.\"}";return output.str();
}

std::string run(const char* mode,const char* path,const char* geometry,const char* csv,int repetitions,uint64_t gate){
    const std::string kind=mode?mode:"";check(repetitions>=1&&repetitions<=30,"invalid benchmark repetitions");check(gate>0,"invalid RSS gate");
    if(kind=="pool-context-packed")return poolStress(path,geometry,csv,gate,static_cast<size_t>(repetitions));
    if(kind=="legacy-packed"||kind=="legacy-sqlite"){
        char* result=storage_benchmark_json(kind=="legacy-packed"?"packed":"sqlite",path,csv,repetitions);check(result,"legacy benchmark returned no data");std::string value(result);storage_free(result);check(value.find("\"error\":")==std::string::npos,value.c_str());const auto delta=integerField(value,"incremental_rss_bytes");auto snapshot=[&](const std::string& label){const auto start=value.find("\""+label+"\":");check(start!=std::string::npos,"missing legacy RSS snapshot");return integerField(value.substr(start,value.find('}',start)-start+1),"rss_bytes");};const auto baseline=snapshot("memory_before");const auto observed=std::max({baseline,snapshot("memory_opened"),snapshot("memory_first_pass"),snapshot("memory_after")})-baseline;const bool caches=integerField(value,"decoded_semantic_cache_peak_bytes")<=4194304&&(kind!="legacy-packed"||(integerField(value,"page_cache_peak_bytes")<=integerField(value,"page_cache_capacity_bytes")&&integerField(value,"mapped_bytes")==0));const bool passed=observed<static_cast<int64_t>(gate)&&caches;return "{\"schema\":1,\"mode\":"+quoted(kind)+",\"overall_success\":"+(passed?"true":"false")+",\"rss_gate_bytes\":"+std::to_string(gate)+",\"incremental_rss_bytes\":"+std::to_string(delta)+",\"observed_snapshot_incremental_rss_bytes\":"+std::to_string(observed)+",\"memory_gate_pass\":"+(passed?"true":"false")+",\"cache_bounds_pass\":"+(caches?"true":"false")+",\"legacy_result\":"+value+"}";
    }
    check(kind=="context-packed"||kind=="source-sqlite","unknown benchmark mode");auto corpus=queries(csv);const auto before=memory();auto started=Clock::now();
    std::unique_ptr<void,decltype(&ysp_geometry_close)> companion(nullptr,&ysp_geometry_close);char error[512]{};
    if(kind=="context-packed"){companion.reset(ysp_geometry_open(geometry,0,error,sizeof error));check(companion!=nullptr,error);check(ysp_register_context_vfs()==SQLITE_OK,"context VFS registration failed");}
    sqlite3* pointer=nullptr;const int opened=sqlite3_open_v2(path,&pointer,SQLITE_OPEN_READONLY|SQLITE_OPEN_NOMUTEX,kind=="context-packed"?"ysp-packed-v1":nullptr);std::unique_ptr<sqlite3,decltype(&sqlite3_close)> database(pointer,&sqlite3_close);check(opened==SQLITE_OK,pointer?sqlite3_errmsg(pointer):"database open failed");
    if(companion){int flags=SQLITE_UTF8|SQLITE_DETERMINISTIC;
#ifdef SQLITE_INNOCUOUS
        flags|=SQLITE_INNOCUOUS;
#endif
        check(sqlite3_create_function_v2(pointer,"ysp_way_points_json",1,flags,companion.get(),geometryScalar,nullptr,nullptr,nullptr)==SQLITE_OK,sqlite3_errmsg(pointer));}
    check(sqlite3_exec(pointer,sqliteConfiguration().c_str(),nullptr,nullptr,nullptr)==SQLITE_OK,sqlite3_errmsg(pointer));
    const char* sql="SELECT w.*,g.points_json FROM ways_rtree r JOIN ways w ON w.way_id=r.way_id LEFT JOIN way_geom g ON g.way_id=w.way_id WHERE r.min_lon<=?1 AND r.max_lon>=?2 AND r.min_lat<=?3 AND r.max_lat>=?4 ORDER BY CAST(w.way_id AS TEXT) COLLATE BINARY";
    sqlite3_stmt* raw=nullptr;check(sqlite3_prepare_v2(pointer,sql,-1,&raw,nullptr)==SQLITE_OK,sqlite3_errmsg(pointer));std::unique_ptr<sqlite3_stmt,decltype(&sqlite3_finalize)> statement(raw,&sqlite3_finalize);const auto openedMemory=memory();const double opening=std::chrono::duration<double,std::milli>(Clock::now()-started).count();
    auto lookup=[&](const std::array<double,3>& q){const double dy=q[2]/(6371008.8*3.14159265358979323846/180),dx=dy/std::cos(q[0]*3.14159265358979323846/180);sqlite3_reset(raw);sqlite3_bind_double(raw,1,q[1]+dx);sqlite3_bind_double(raw,2,q[1]-dx);sqlite3_bind_double(raw,3,q[0]+dy);sqlite3_bind_double(raw,4,q[0]-dy);uint64_t digest=HASH,count=0;int code=0;while((code=sqlite3_step(raw))==SQLITE_ROW){digest=rowHash(digest,raw);++count;}check(code==SQLITE_DONE,sqlite3_errmsg(pointer));return std::array<uint64_t,2>{digest,count};};
    std::vector<std::array<uint64_t,2>> expected;std::vector<double> first,warm;uint64_t digest=HASH,rows=0;
    for(auto query:corpus){started=Clock::now();const auto result=lookup(query);first.push_back(std::chrono::duration<double,std::micro>(Clock::now()-started).count());expected.push_back(result);rows+=result[1];digest=hash(digest,result.data(),sizeof result);}
    const auto firstMemory=memory();for(int repetition=0;repetition<repetitions;++repetition)for(size_t i=0;i<corpus.size();++i){started=Clock::now();const auto result=lookup(corpus[i]);warm.push_back(std::chrono::duration<double,std::micro>(Clock::now()-started).count());check(result==expected[i],"non-deterministic SQL result");}
    const auto after=memory();const int64_t delta=static_cast<int64_t>(after.rss)-static_cast<int64_t>(before.rss);const uint64_t observed=std::max({before.rss,openedMemory.rss,firstMemory.rss,after.rss});const auto observedDelta=static_cast<int64_t>(observed)-static_cast<int64_t>(before.rss);
    const auto contextStats=owned(ysp_context_vfs_stats_json(pointer));const auto geometryStats=companion?owned(ysp_geometry_stats_json(companion.get())):"null";const bool caches=cacheWithin(contextStats)&&cacheWithin(geometryStats),passed=observedDelta<static_cast<int64_t>(gate)&&caches;
    std::ostringstream output;output<<std::setprecision(10)<<"{\"schema\":1,\"mode\":"<<quoted(kind)<<",\"sqlite_version\":"<<quoted(sqlite3_libversion())<<",\"sqlite_page_cache_kib\":"<<ysp_sqlite_cache_kib()<<",\"overall_success\":"<<(passed?"true":"false")<<",\"query_count\":"<<corpus.size()<<",\"candidate_rows\":"<<rows<<",\"repetitions\":"<<repetitions<<",\"result_fnv1a64\":"<<quoted(hex(digest))<<",\"init_ms\":"<<opening<<",\"first_pass\":"<<stats(first)<<",\"warm\":"<<stats(warm)<<",\"memory_before\":"<<memoryJSON(before)<<",\"memory_opened\":"<<memoryJSON(openedMemory)<<",\"memory_first_pass\":"<<memoryJSON(firstMemory)<<",\"memory_after\":"<<memoryJSON(after)<<",\"incremental_rss_bytes\":"<<delta<<",\"observed_snapshot_incremental_rss_bytes\":"<<observedDelta<<",\"rss_gate_bytes\":"<<gate<<",\"memory_gate_pass\":"<<(observedDelta<static_cast<int64_t>(gate)?"true":"false")<<",\"cache_bounds_pass\":"<<(caches?"true":"false")<<",\"context_io_stats\":"<<contextStats<<",\"geometry_io_stats\":"<<geometryStats<<",\"query_results\":[";
    for(size_t i=0;i<expected.size();++i){if(i)output<<',';output<<"{\"query_index\":"<<i<<",\"rows\":"<<expected[i][1]<<",\"result_fnv1a64\":"<<quoted(hex(expected[i][0]))<<'}';}
    output<<"],\"workload\":\"Source ways bbox query plus exact source way_geom text, lexical source-ID ordering. Typed SQLite column bytes are hashed. This is a storage SQL workload, not full driving matcher/state policy.\",\"notes\":\"First pass is process-first, not OS-cold. RSS gate uses observed snapshots, not an asserted process peak. Kernel highwater is unadjusted and can lag Linux smaps_rollup. Caches are explicit, caller/SQLite allocations are measured separately.\"}";return output.str();
}
}
extern "C" char* ysp_storage_benchmark_json(const char* mode,const char* path,const char* geometry,const char* csv,int repetitions,uint64_t gate){try{return copy(run(mode,path,geometry,csv,repetitions,gate));}catch(const std::exception& error){return copy("{\"overall_success\":false,\"error\":"+quoted(error.what())+"}");}}
extern "C" void ysp_storage_benchmark_free(void* memory){std::free(memory);}
