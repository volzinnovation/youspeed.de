#include "runtime_sign_nodes.h"
#include "packed_nodes.h"
#include "../runtime-storage-prototype/bounded_file.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>
#ifndef YSP_NODES_PACKED_ONLY
#include <sqlite3.h>
#endif
#include <zlib.h>
#ifdef __APPLE__
#include <mach/mach.h>
#endif
#if defined(YSP_WITH_GEODESK) && !defined(YSP_NODES_PACKED_ONLY)
#include "../runtime-storage-geodesk/geodesk_adapter.h"
#endif

namespace {
using Clock=std::chrono::steady_clock;
constexpr double PI=3.14159265358979323846, EARTH=6371008.8;
constexpr uint64_t INITIAL_HASH=14695981039346656037ULL;
#pragma pack(push,1)
struct Node { int64_t id; int32_t lat,lon; uint64_t offset; uint32_t size,rawsize,crc; uint64_t digest; };
#pragma pack(pop)
static_assert(sizeof(Node)==44,"fixed node record size");
struct Bounds {int64_t minlon,minlat,maxlon,maxlat;};
void require(bool ok,const char* error){if(!ok)throw std::runtime_error(error);}
template<class T>T read(const uint8_t* p){T out;std::memcpy(&out,p,sizeof(out));return out;}
uint64_t hash(uint64_t h,const void* data,size_t size){auto bytes=static_cast<const uint8_t*>(data);for(size_t i=0;i<size;++i)h=(h^bytes[i])*1099511628211ULL;return h;}
std::string hex(uint64_t n){std::ostringstream out;out<<std::hex<<std::setfill('0')<<std::setw(16)<<n;return out.str();}
std::string escaped(const std::string& x){std::ostringstream out;out<<'"';for(unsigned char c:x){if(c=='"'||c=='\\')out<<'\\'<<c;else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;else out<<c;}out<<'"';return out.str();}
char* copy(const std::string& text){auto p=static_cast<char*>(std::malloc(text.size()+1));if(p)std::memcpy(p,text.c_str(),text.size()+1);return p;}
template<class F>char* safe(F f){try{return copy(f());}catch(const std::exception& e){return copy("{\"error\":"+escaped(e.what())+"}");}catch(...){return copy("{\"error\":\"unknown native failure\"}");}}
Bounds bounds(double lat,double lon,double radius){require(std::isfinite(lat)&&std::isfinite(lon)&&std::isfinite(radius)&&std::abs(lat)<85&&std::abs(lon)<=179.999&&radius>0&&radius<=10000,"invalid node query");double dy=radius/(EARTH*PI/180),dx=dy/std::cos(lat*PI/180);return {int64_t(std::floor((lon-dx)*1e7)),int64_t(std::floor((lat-dy)*1e7)),int64_t(std::ceil((lon+dx)*1e7)),int64_t(std::ceil((lat+dy)*1e7))};}
bool inside(const Node& n,const Bounds& b){return n.lat>=b.minlat&&n.lat<=b.maxlat&&n.lon>=b.minlon&&n.lon<=b.maxlon;}
double distance(double lat,double lon,const Node& n){double x=(n.lat/1e7-lat)*PI/180,y=(n.lon/1e7-lon)*PI/180,v=std::sin(x/2)*std::sin(x/2)+std::cos(lat*PI/180)*std::cos(n.lat/1e7*PI/180)*std::sin(y/2)*std::sin(y/2);return 2*EARTH*std::asin(std::sqrt(std::min(1.0,v)));}
std::string inflate(const Node& n,const void* encoded){require(n.rawsize>0&&n.rawsize<=1024*1024&&n.size<=1024*1024,"invalid metadata length");std::string raw(n.rawsize,'\0');uLongf size=n.rawsize;require(uncompress(reinterpret_cast<Bytef*>(&raw[0]),&size,static_cast<const Bytef*>(encoded),n.size)==Z_OK&&size==n.rawsize,"node metadata decompression failed");require(crc32(0,reinterpret_cast<const Bytef*>(raw.data()),raw.size())==n.crc,"node semantic CRC mismatch");require(hash(INITIAL_HASH,raw.data(),raw.size())==n.digest,"node semantic digest mismatch");return raw;}
class Reader {
public:
    virtual ~Reader()=default;
    virtual uint64_t count()const=0;
    virtual std::string ioStats()const{return "{}";}
    virtual std::vector<Node> candidates(const Bounds&)=0;
    virtual bool get(int64_t,Node&,std::string&)=0;
    virtual std::string semantic(const Node&)=0;
    virtual std::vector<int64_t> allIDs()=0;
};
class Packed final:public Reader {
    mutable ysp_storage::BoundedFile file;
    uint64_t size=0,n=0,ro=0,oo=0,bo=0;
    Node at(uint64_t i)const {require(i<n,"node directory index outside file");auto out=file.value<Node>(ro+i*sizeof(Node));require(out.id>0&&std::abs(int64_t(out.lat))<=900000000&&std::abs(int64_t(out.lon))<=1800000000,"invalid node identity/coordinate");require(out.offset<=size-bo&&out.size<=size-bo-out.offset,"node metadata outside file");return out;}
public:
    explicit Packed(const std::string& path,size_t cacheBytes=512*1024):file(path,cacheBytes){
        size=file.size();require(size>=128,"truncated node pack");std::array<uint8_t,128> header{};file.direct(0,header.data(),header.size());const auto* data=header.data();
        require(std::memcmp(data,"YSPNODE1",8)==0&&read<uint32_t>(data+8)==1&&read<uint32_t>(data+12)==0x01020304,"unsupported node pack format");require(crc32(0,data,64)==read<uint32_t>(data+64),"node pack header checksum");n=read<uint64_t>(data+16);ro=read<uint64_t>(data+24);oo=read<uint64_t>(data+32);bo=read<uint64_t>(data+40);require(n<=10000000&&ro==128&&oo==ro+n*sizeof(Node)&&bo==oo+n*4&&bo<=size&&read<uint64_t>(data+48)==size,"invalid node pack sections");require(file.crc(ro,n*sizeof(Node))==read<uint32_t>(data+56)&&file.crc(oo,n*4)==read<uint32_t>(data+60),"node directory checksum");int32_t lastLat=INT32_MIN;for(uint64_t i=0;i<n;++i){auto node=at(i);require(node.lat>=lastLat,"node latitude ordering invalid");lastLat=node.lat;}int64_t lastID=0;for(uint64_t i=0;i<n;++i){auto node=at(file.value<uint32_t>(oo+i*4));require(node.id>lastID,"node ID ordering invalid");lastID=node.id;}
    }
    uint64_t count()const override{return n;}
    std::string ioStats()const override{return file.statsJSON();}
    std::string semantic(const Node& node)override{require(node.rawsize>0&&node.rawsize<=1024*1024&&node.size<=1024*1024,"invalid metadata length");auto bytes=file.blob(bo+node.offset,node.size);return inflate(node,bytes.data());}
    std::vector<int64_t> allIDs()override{std::vector<int64_t> ids;ids.reserve(n);for(uint64_t i=0;i<n;++i)ids.push_back(at(file.value<uint32_t>(oo+i*4)).id);return ids;}
    bool get(int64_t id,Node& node,std::string& raw)override{uint64_t lo=0,hi=n;while(lo<hi){auto m=lo+(hi-lo)/2;auto item=at(file.value<uint32_t>(oo+m*4));if(item.id<id)lo=m+1;else hi=m;}if(lo>=n)return false;node=at(file.value<uint32_t>(oo+lo*4));if(node.id!=id)return false;raw=semantic(node);return true;}
    std::vector<Node> candidates(const Bounds& b)override{uint64_t lo=0,hi=n;while(lo<hi){auto m=lo+(hi-lo)/2;if(at(m).lat<b.minlat)lo=m+1;else hi=m;}std::vector<Node> out;for(uint64_t i=lo;i<n;++i){auto node=at(i);if(node.lat>b.maxlat)break;if(inside(node,b))out.push_back(node);}std::sort(out.begin(),out.end(),[](const Node& a,const Node& z){return a.id<z.id;});return out;}
};

#ifndef YSP_NODES_PACKED_ONLY
class Sql:public Reader {
protected:
    sqlite3* db=nullptr;sqlite3_stmt* one=nullptr;sqlite3_stmt* record=nullptr;sqlite3_stmt* spatial=nullptr;uint64_t n=0;
    void prep(const char* sql,sqlite3_stmt** statement){require(sqlite3_prepare_v2(db,sql,-1,statement,nullptr)==SQLITE_OK,"invalid nodes SQLite schema");}
    Node readRow(sqlite3_stmt* s,bool encodedColumn=true){Node node{};node.id=sqlite3_column_int64(s,0);node.lat=sqlite3_column_int(s,1);node.lon=sqlite3_column_int(s,2);node.rawsize=sqlite3_column_int(s,3);node.crc=sqlite3_column_int64(s,4);auto text=reinterpret_cast<const char*>(sqlite3_column_text(s,5));require(text&&std::strlen(text)==16,"invalid node digest");node.digest=std::stoull(text,nullptr,16);node.size=encodedColumn?sqlite3_column_bytes(s,6):sqlite3_column_int(s,6);return node;}
    bool recordOnly(int64_t id,Node& node){sqlite3_reset(record);sqlite3_bind_int64(record,1,id);int rc=sqlite3_step(record);if(rc==SQLITE_DONE)return false;require(rc==SQLITE_ROW,"canonical node record lookup failed");node=readRow(record,false);require(node.id==id,"canonical node identity mismatch");return true;}
public:
    explicit Sql(const std::string& path){auto uri="file:"+path+"?mode=ro&immutable=1";if(sqlite3_open_v2(uri.c_str(),&db,SQLITE_OPEN_READONLY|SQLITE_OPEN_URI|SQLITE_OPEN_NOMUTEX,nullptr)!=SQLITE_OK){if(db)sqlite3_close(db);db=nullptr;throw std::runtime_error("cannot open nodes SQLite");}try{sqlite3_exec(db,"PRAGMA cache_size=-4096;PRAGMA mmap_size=0;PRAGMA query_only=ON",nullptr,nullptr,nullptr);prep("SELECT node_id,latitude_e7,longitude_e7,raw_size,crc,digest,data FROM node WHERE node_id=?",&one);prep("SELECT node_id,latitude_e7,longitude_e7,raw_size,crc,digest,length(data) FROM node WHERE node_id=?",&record);prep("SELECT n.node_id,n.latitude_e7,n.longitude_e7,n.raw_size,n.crc,n.digest,n.data FROM spatial s JOIN node n ON n.node_id=s.node_id WHERE s.min_lon<=? AND s.max_lon>=? AND s.min_lat<=? AND s.max_lat>=? ORDER BY n.node_id",&spatial);sqlite3_stmt* c=nullptr;prep("SELECT value FROM metadata WHERE key='node_count'",&c);const bool hasCount=sqlite3_step(c)==SQLITE_ROW;const auto value=hasCount?sqlite3_column_int64(c,0):int64_t(-1);sqlite3_finalize(c);require(hasCount&&value>=0,"node count metadata missing or invalid");n=static_cast<uint64_t>(value);}catch(...){sqlite3_finalize(one);sqlite3_finalize(record);sqlite3_finalize(spatial);sqlite3_close(db);db=nullptr;throw;}}
    ~Sql(){sqlite3_finalize(one);sqlite3_finalize(record);sqlite3_finalize(spatial);if(db)sqlite3_close(db);}
    uint64_t count()const override{return n;}
    std::vector<int64_t> allIDs()override{sqlite3_stmt* all=nullptr;prep("SELECT node_id FROM node ORDER BY node_id",&all);std::vector<int64_t> ids;int rc;while((rc=sqlite3_step(all))==SQLITE_ROW)ids.push_back(sqlite3_column_int64(all,0));sqlite3_finalize(all);require(rc==SQLITE_DONE,"node ID iteration failed");return ids;}
    bool get(int64_t id,Node& node,std::string& raw)override{sqlite3_reset(one);sqlite3_bind_int64(one,1,id);int rc=sqlite3_step(one);if(rc==SQLITE_DONE)return false;require(rc==SQLITE_ROW,"node lookup failed");node=readRow(one);require(node.id==id,"node identity mismatch");raw=inflate(node,sqlite3_column_blob(one,6));return true;}
    std::string semantic(const Node& node)override{Node actual{};std::string raw;require(get(node.id,actual,raw),"node missing");require(actual.crc==node.crc&&actual.digest==node.digest,"node changed");return raw;}
    std::vector<Node> candidates(const Bounds& b)override{sqlite3_reset(spatial);sqlite3_bind_int64(spatial,1,b.maxlon);sqlite3_bind_int64(spatial,2,b.minlon);sqlite3_bind_int64(spatial,3,b.maxlat);sqlite3_bind_int64(spatial,4,b.minlat);std::vector<Node> out;int rc;while((rc=sqlite3_step(spatial))==SQLITE_ROW)out.push_back(readRow(spatial));require(rc==SQLITE_DONE,"nodes RTree query failed");return out;}
};
#if defined(YSP_WITH_GEODESK) && !defined(YSP_NODES_PACKED_ONLY)
class Geo final:public Sql {
    void* gol=nullptr;
public:
    explicit Geo(const std::string& path):Sql(path.substr(path.find('|')+1)){auto split=path.find('|');require(split!=std::string::npos,"GeoDesk nodes path requires GOL|SQLITE");char error[1024]{};gol=storage_geodesk_open(path.substr(0,split).c_str(),error,sizeof error);if(!gol)throw std::runtime_error(error);}
    ~Geo(){storage_geodesk_close(gol);}
    std::vector<Node> candidates(const Bounds& b)override{int64_t* ids=nullptr;size_t count=0;require(storage_geodesk_node_candidates(gol,b.minlon/1e7,b.minlat/1e7,b.maxlon/1e7,b.maxlat/1e7,&ids,&count)==0,"GeoDesk node candidates failed");std::vector<Node> out;try{for(size_t i=0;i<count;++i){Node node{};if(recordOnly(ids[i],node)&&inside(node,b))out.push_back(node);}}catch(...){storage_geodesk_free_ids(ids);throw;}storage_geodesk_free_ids(ids);std::sort(out.begin(),out.end(),[](const Node& a,const Node& z){return a.id<z.id;});out.erase(std::unique(out.begin(),out.end(),[](const Node& a,const Node& z){return a.id==z.id;}),out.end());return out;}
};
#endif
#endif // !YSP_NODES_PACKED_ONLY
std::unique_ptr<Reader> openReader(const std::string& kind,const std::string& path){if(kind=="packed")return std::make_unique<Packed>(path);
#ifndef YSP_NODES_PACKED_ONLY
if(kind=="sqlite")return std::make_unique<Sql>(path);
#endif
#if defined(YSP_WITH_GEODESK) && !defined(YSP_NODES_PACKED_ONLY)
if(kind=="geodesk")return std::make_unique<Geo>(path);
#endif
throw std::runtime_error("unsupported nodes backend");}
std::string query(Reader& reader,double lat,double lon,double radius){auto nodes=reader.candidates(bounds(lat,lon,radius));std::ostringstream out;out<<'[';bool first=true;for(const auto& node:nodes){if(distance(lat,lon,node)>radius)continue;auto raw=reader.semantic(node);(void)raw;if(!first)out<<',';first=false;out<<"{\"node_id\":"<<escaped(std::to_string(node.id))<<",\"latitude_e7\":"<<node.lat<<",\"longitude_e7\":"<<node.lon<<",\"semantic_crc32\":"<<node.crc<<",\"semantic_fnv1a64\":\""<<hex(node.digest)<<"\"}";}out<<']';return out.str();}
struct Memory {uint64_t rss=0,highwater=0,footprint=0,pss=0,private_clean=0,private_dirty=0,shared_clean=0,shared_dirty=0,pss_anon=0,pss_file=0;bool footprint_available=false,smaps_available=false;std::string rss_source="unavailable";};
Memory memory(){Memory out;struct rusage ru{};getrusage(RUSAGE_SELF,&ru);
#ifdef __APPLE__
out.highwater=ru.ru_maxrss;mach_task_basic_info_data_t basic{};mach_msg_type_number_t n=MACH_TASK_BASIC_INFO_COUNT;if(task_info(mach_task_self(),MACH_TASK_BASIC_INFO,reinterpret_cast<task_info_t>(&basic),&n)==KERN_SUCCESS){out.rss=basic.resident_size;out.rss_source="mach_task_basic_info";}task_vm_info_data_t vm{};n=TASK_VM_INFO_COUNT;if(task_info(mach_task_self(),TASK_VM_INFO,reinterpret_cast<task_info_t>(&vm),&n)==KERN_SUCCESS){out.footprint=vm.phys_footprint;out.footprint_available=true;}
#else
out.highwater=uint64_t(ru.ru_maxrss)*1024;std::ifstream stat("/proc/self/statm");uint64_t total=0,pages=0;if(stat>>total>>pages){out.rss=pages*sysconf(_SC_PAGESIZE);out.rss_source="proc_statm";}std::ifstream smaps("/proc/self/smaps_rollup");std::string line;while(std::getline(smaps,line)){std::istringstream input(line);std::string key,unit;uint64_t kb=0;if(!(input>>key>>kb>>unit)||unit!="kB")continue;uint64_t bytes=kb*1024;if(key=="Rss:"){out.rss=bytes;out.rss_source="proc_smaps_rollup";}else if(key=="Pss:"){out.pss=bytes;out.smaps_available=true;}else if(key=="Private_Clean:")out.private_clean=bytes;else if(key=="Private_Dirty:")out.private_dirty=bytes;else if(key=="Shared_Clean:")out.shared_clean=bytes;else if(key=="Shared_Dirty:")out.shared_dirty=bytes;else if(key=="Pss_Anon:")out.pss_anon=bytes;else if(key=="Pss_File:")out.pss_file=bytes;}
#endif
return out;}
std::string memjson(Memory m){auto linuxValue=[&](uint64_t value){return m.smaps_available?std::to_string(value):std::string("null");};return "{\"rss_bytes\":"+std::to_string(m.rss)+",\"rss_source\":"+escaped(m.rss_source)+",\"highwater_rss_bytes\":"+std::to_string(m.highwater)+",\"highwater_rss_source\":\"getrusage_ru_maxrss\",\"physical_footprint_bytes\":"+(m.footprint_available?std::to_string(m.footprint):"null")+",\"pss_bytes\":"+linuxValue(m.pss)+",\"private_resident_bytes\":"+linuxValue(m.private_clean+m.private_dirty)+",\"private_clean_bytes\":"+linuxValue(m.private_clean)+",\"private_dirty_bytes\":"+linuxValue(m.private_dirty)+",\"shared_resident_bytes\":"+linuxValue(m.shared_clean+m.shared_dirty)+",\"pss_anonymous_bytes\":"+linuxValue(m.pss_anon)+",\"pss_file_bytes\":"+linuxValue(m.pss_file)+"}";}
std::string stats(std::vector<double> x){if(x.empty())return "{}";std::sort(x.begin(),x.end());auto p=[&](double q){return x[size_t(std::ceil(q*(x.size()-1)))];};std::ostringstream out;out<<"{\"count\":"<<x.size()<<",\"p50_us\":"<<p(.5)<<",\"p95_us\":"<<p(.95)<<",\"p99_us\":"<<p(.99)<<",\"max_us\":"<<x.back()<<'}';return out.str();}
std::vector<std::array<double,3>> parse(const char* csv){std::istringstream input(csv?csv:"");std::string line;std::vector<std::array<double,3>> queries;while(std::getline(input,line)){if(line.empty()||line[0]=='#'||line.rfind("lat,",0)==0)continue;std::replace(line.begin(),line.end(),',',' ');std::istringstream row(line);std::array<double,3> q{};require(bool(row>>q[0]>>q[1]>>q[2]),"invalid nodes query CSV");bounds(q[0],q[1],q[2]);queries.push_back(q);}require(!queries.empty()&&queries.size()<=1000000,"empty/oversized nodes corpus");return queries;}
}
extern "C" char* storage_nodes_benchmark_json(const char* kind,const char* path,const char* csv,int repetitions){return safe([&](){require(repetitions>=1&&repetitions<=100,"invalid repetitions");auto queries=parse(csv);auto before=memory();auto start=Clock::now();auto reader=openReader(kind?kind:"",path?path:"");double init=std::chrono::duration<double,std::milli>(Clock::now()-start).count();auto opened=memory();std::vector<double> first,warm;std::vector<uint64_t> expected;uint64_t digest=INITIAL_HASH;uint64_t hitQueries=0;for(auto q:queries){start=Clock::now();auto value=query(*reader,q[0],q[1],q[2]);first.push_back(std::chrono::duration<double,std::micro>(Clock::now()-start).count());digest=hash(digest,value.data(),value.size());expected.push_back(hash(INITIAL_HASH,value.data(),value.size()));if(value!="[]")++hitQueries;}auto firstmem=memory();for(int rep=0;rep<repetitions;++rep){for(size_t i=0;i<queries.size();++i){auto q=queries[i];start=Clock::now();auto value=query(*reader,q[0],q[1],q[2]);warm.push_back(std::chrono::duration<double,std::micro>(Clock::now()-start).count());require(hash(INITIAL_HASH,value.data(),value.size())==expected[i],"nondeterministic nodes query");}}auto after=memory();std::ostringstream out;out<<"{\"backend\":"<<escaped(kind?kind:"")<<",\"nodes\":"<<reader->count()<<",\"query_count\":"<<queries.size()<<",\"queries_with_hits\":"<<hitQueries<<",\"repetitions\":"<<repetitions<<",\"result_fnv1a64\":\""<<hex(digest)<<"\",\"init_ms\":"<<init<<",\"first_pass\":"<<stats(first)<<",\"warm\":"<<stats(warm)<<",\"memory_before\":"<<memjson(before)<<",\"memory_opened\":"<<memjson(opened)<<",\"memory_first_pass\":"<<memjson(firstmem)<<",\"memory_after\":"<<memjson(after)<<",\"incremental_rss_bytes\":"<<int64_t(after.rss)-int64_t(before.rss)<<",\"io_stats\":"<<reader->ioStats()<<",\"notes\":\"Process-first, not OS-cold. Kernel-reported highwater is unadjusted; Linux kernel accounting may lag current smaps_rollup RSS. Full source metadata is decompressed and CRC/FNV validated on every returned node. Source membership is not a verified directed applicability binding.\"}";return out.str();});}
extern "C" char* storage_nodes_query_json(const char* kind,const char* path,double lat,double lon,double radius){return safe([&](){auto reader=openReader(kind?kind:"",path?path:"");return query(*reader,lat,lon,radius);});}
extern "C" char* storage_node_json(const char* kind,const char* path,long long id){return safe([&](){auto reader=openReader(kind?kind:"",path?path:"");Node node{};std::string raw;if(!reader->get(id,node,raw))return std::string("null");return raw;});}
extern "C" char* storage_nodes_roundtrip_json(const char* kind,const char* path){return safe([&](){auto reader=openReader(kind?kind:"",path?path:"");auto ids=reader->allIDs();require(ids.size()==reader->count(),"all-node count mismatch");uint64_t digest=INITIAL_HASH;for(auto id:ids){Node node{};std::string raw;require(reader->get(id,node,raw),"source node missing");digest=hash(digest,raw.data(),raw.size());}return "{\"nodes\":"+std::to_string(ids.size())+",\"semantic_fnv1a64\":\""+hex(digest)+"\",\"full_metadata_validated\":true}";});}
extern "C" char* storage_nodes_compare_json(const char* firstKind,const char* firstPath,const char* secondKind,const char* secondPath,const char* csv){return safe([&](){auto first=openReader(firstKind?firstKind:"",firstPath?firstPath:"");auto second=openReader(secondKind?secondKind:"",secondPath?secondPath:"");auto ids=first->allIDs();require(ids==second->allIDs(),"backend source node ID lists differ");for(auto id:ids){Node a{},b{};std::string ar,br;require(first->get(id,a,ar)&&second->get(id,b,br),"backend source node missing");require(ar==br&&a.lat==b.lat&&a.lon==b.lon,"backend full node records differ");}auto queries=parse(csv);for(size_t i=0;i<queries.size();++i){auto q=queries[i];auto a=query(*first,q[0],q[1],q[2]),b=query(*second,q[0],q[1],q[2]);if(a!=b)throw std::runtime_error("node lookup differs at query "+std::to_string(i));}return "{\"nodes\":"+std::to_string(ids.size())+",\"queries\":"+std::to_string(queries.size())+",\"full_records_byte_identical\":true,\"all_queries_byte_identical\":true}";});}
extern "C" void storage_nodes_free(void* value){std::free(value);}


namespace {
struct PersistentNodes {std::mutex mutex;Packed reader;PersistentNodes(const char* path,size_t cache):reader(path?path:"",cache){}};
void nodeError(char* error,size_t size,const char* text){if(error&&size){const auto length=std::min(size-1,std::strlen(text));std::memcpy(error,text,length);error[length]=0;}}
template<class R,class F>R nodeGuard(char* error,size_t size,R failure,F function){if(error&&size)error[0]=0;try{return function();}catch(const std::exception& exception){nodeError(error,size,exception.what());return failure;}catch(...){nodeError(error,size,"unknown packed node failure");return failure;}}
int64_t nodeIdentity(const char* text){require(text&&*text,"missing node identity");uint64_t id=0;for(const char* p=text;*p;++p){require(*p>='0'&&*p<='9',"node identity must be positive decimal Int64");const uint64_t digit=static_cast<unsigned>(*p-'0');require(id<=(uint64_t(INT64_MAX)-digit)/10,"node identity exceeds Int64");id=id*10+digit;}require(id>0,"node identity must be positive");return static_cast<int64_t>(id);}
}
extern "C" void* ysp_nodes_open(const char* path,uint64_t cache,char* error,size_t size){return nodeGuard(error,size,static_cast<void*>(nullptr),[&](){const uint64_t requested=cache?cache:512*1024;require(requested>=4096&&requested<=8*1024*1024,"node cache must be between 4 KiB and 8 MiB");return static_cast<void*>(new PersistentNodes(path,static_cast<size_t>(requested)));});}
extern "C" char* ysp_nodes_json(void* value,const char* id,char* error,size_t size){return nodeGuard(error,size,static_cast<char*>(nullptr),[&](){require(value,"null node handle");auto& handle=*static_cast<PersistentNodes*>(value);std::lock_guard<std::mutex> lock(handle.mutex);Node node{};std::string raw;if(!handle.reader.get(nodeIdentity(id),node,raw))return copy("null");return copy(raw);});}
extern "C" char* ysp_nodes_query_json(void* value,double lat,double lon,double radius,char* error,size_t size){return nodeGuard(error,size,static_cast<char*>(nullptr),[&](){require(value,"null node handle");auto& handle=*static_cast<PersistentNodes*>(value);std::lock_guard<std::mutex> lock(handle.mutex);const auto nodes=handle.reader.candidates(bounds(lat,lon,radius));std::string out="[";bool first=true;for(const auto& node:nodes){if(distance(lat,lon,node)>radius)continue;if(!first)out+=',';first=false;out+=handle.reader.semantic(node);}out+=']';return copy(out);});}
extern "C" char* ysp_nodes_stats_json(void* value){return nodeGuard(nullptr,0,static_cast<char*>(nullptr),[&](){require(value,"null node handle");auto& handle=*static_cast<PersistentNodes*>(value);std::lock_guard<std::mutex> lock(handle.mutex);return copy("{\"nodes\":"+std::to_string(handle.reader.count())+",\"file\":"+handle.reader.ioStats()+"}");});}
extern "C" void ysp_nodes_close(void* value){delete static_cast<PersistentNodes*>(value);}
extern "C" void ysp_nodes_free(void* value){std::free(value);}
