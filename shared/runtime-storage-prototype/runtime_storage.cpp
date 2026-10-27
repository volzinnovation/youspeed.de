#include "runtime_storage.h"
#include "bounded_file.h"
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
#include <limits>
#include <list>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>
#include <unordered_map>
#include <vector>
#include <sqlite3.h>
#include <zlib.h>
#ifdef __APPLE__
#include <mach/mach.h>
#endif
#ifdef YSP_WITH_GEODESK
#include "geodesk_adapter.h"
#endif

namespace {
using Clock=std::chrono::steady_clock;
constexpr double PI=3.14159265358979323846, EARTH=6371008.8;
constexpr uint64_t HEADER=160, BLOCK_SIZE=262144;
#pragma pack(push,1)
struct Road { int64_t id; int32_t minlon,minlat,maxlon,maxlat; uint64_t geometry,metadata; uint32_t geomsize,metasize,points; int16_t speed,forward,backward; uint16_t flags; uint64_t metacrc; uint32_t geomcrc; };
struct Node { int32_t minlon,minlat,maxlon,maxlat; uint32_t a,b,leaf,reserved; };
struct Block { uint64_t offset; uint32_t size,rawsize,crc; };
#pragma pack(pop)
static_assert(sizeof(Road)==72 && sizeof(Node)==32 && sizeof(Block)==20,"format layout");
struct Point { double lat,lon; };
struct Bounds { int64_t minlon,minlat,maxlon,maxlat; };
uint64_t hash(uint64_t h,const void* data,size_t size) { auto p=(const uint8_t*)data; for(size_t i=0;i<size;++i) h=(h^p[i])*1099511628211ull; return h; }
std::string hex(uint64_t n) { std::ostringstream s;s<<std::hex<<std::setfill('0')<<std::setw(16)<<n;return s.str(); }
std::string escaped(const std::string& x) { std::ostringstream s;s<<'"'; for(unsigned char c:x) {if(c=='"'||c=='\\')s<<'\\'<<c;else if(c<32)s<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c);else s<<c;}s<<'"';return s.str(); }
void require(bool condition,const char* message) { if(!condition)throw std::runtime_error(message); }
template<typename T>T read(const uint8_t* p) { T value;std::memcpy(&value,p,sizeof(T));return value; }
uint64_t varint(const std::vector<uint8_t>& b,size_t& pos) { uint64_t v=0;for(unsigned s=0;s<=63;s+=7){require(pos<b.size(),"truncated geometry varint");uint8_t c=b[pos++];require(s<63||(c&0xfe)==0,"geometry varint overflow");v|=uint64_t(c&127)<<s;if(!(c&128))return v;}throw std::runtime_error("invalid geometry varint"); }
std::vector<Point> decode(const std::vector<uint8_t>& b,uint32_t expected) {
    require(!b.empty()&&b[0]<=1,"unsupported geometry codec");size_t pos=1;auto n=varint(b,pos);require(n==expected&&n<=10000000,"invalid point count");std::vector<Point> points;points.reserve(n);
    int64_t lat=0,lon=0;
    for(uint64_t i=0;i<n;++i) {if(b[0]==1){require(b.size()-pos>=16,"truncated doubles");points.push_back({read<double>(&b[pos]),read<double>(&b[pos+8])});pos+=16;}else{auto a=varint(b,pos),c=varint(b,pos);int64_t dla=int64_t(a>>1)^-int64_t(a&1),dlo=int64_t(c>>1)^-int64_t(c&1);require(dla>=-1800000000ll&&dla<=1800000000ll&&dlo>=-3600000000ll&&dlo<=3600000000ll,"geometry delta outside coordinate domain");lat+=dla;lon+=dlo;points.push_back({lat/1e7,lon/1e7});}auto p=points.back();require(std::isfinite(p.lat)&&std::isfinite(p.lon)&&std::abs(p.lat)<=90&&std::abs(p.lon)<=180,"invalid coordinate");}
    require(pos==b.size(),"trailing geometry bytes");return points;
}
bool overlap(const Road& r,const Bounds& b) {return r.minlon<=b.maxlon&&r.maxlon>=b.minlon&&r.minlat<=b.maxlat&&r.maxlat>=b.minlat;}
bool overlap(const Node& r,const Bounds& b) {return r.minlon<=b.maxlon&&r.maxlon>=b.minlon&&r.minlat<=b.maxlat&&r.maxlat>=b.minlat;}

class Reader {
protected:
    struct Cached {std::vector<uint8_t> raw;std::list<uint64_t>::iterator lru;};
    std::unordered_map<uint64_t,Cached> cache;
    std::list<uint64_t> lru;
    uint64_t semanticResident=0,semanticPeak=0,largestSemanticRecord=0;
    virtual std::vector<uint8_t> loadBlock(uint64_t)=0;
public:
    virtual ~Reader()=default;
    virtual std::vector<int64_t> candidates(const Bounds&)=0;
    virtual bool road(int64_t,Road&,std::vector<uint8_t>&)=0;
    virtual uint64_t count()const=0;
    virtual std::string ioStats()const{return "{}";}
    std::string diagnostics()const{return "{\"file\":"+ioStats()+",\"decoded_semantic_cache_capacity_bytes\":4194304,\"decoded_semantic_cache_resident_bytes\":"+std::to_string(semanticResident)+",\"decoded_semantic_cache_peak_bytes\":"+std::to_string(semanticPeak)+",\"largest_semantic_record_bytes\":"+std::to_string(largestSemanticRecord)+"}";}
    std::string metadata(const Road& r) {
        require(r.metasize<=64*1024*1024,"oversized semantic record");largestSemanticRecord=std::max<uint64_t>(largestSemanticRecord,r.metasize);std::string out;out.reserve(r.metasize);uint64_t offset=r.metadata;size_t left=r.metasize;
        while(left){uint64_t id=offset/BLOCK_SIZE;size_t in=offset%BLOCK_SIZE;auto it=cache.find(id);if(it==cache.end()){if(cache.size()>=16){auto victim=lru.back();lru.pop_back();semanticResident-=cache.at(victim).raw.size();cache.erase(victim);}auto raw=loadBlock(id);semanticResident+=raw.size();semanticPeak=std::max(semanticPeak,semanticResident);lru.push_front(id);it=cache.emplace(id,Cached{std::move(raw),lru.begin()}).first;}else{lru.erase(it->second.lru);lru.push_front(id);it->second.lru=lru.begin();}auto& raw=it->second.raw;require(in<raw.size(),"semantic offset out of range");size_t n=std::min(left,raw.size()-in);out.append((const char*)raw.data()+in,n);left-=n;offset+=n;}
        require(crc32(0,(const Bytef*)out.data(),out.size())==r.metacrc,"semantic record checksum mismatch");return out;
    }
};
std::vector<uint8_t> inflateBlock(const uint8_t* encoded,uint32_t size,uint32_t rawsize,uint32_t crc) {require(rawsize<=BLOCK_SIZE&&rawsize>0&&size<=BLOCK_SIZE+1024,"invalid compressed block size");std::vector<uint8_t> raw(rawsize);uLongf n=rawsize;require(uncompress(raw.data(),&n,encoded,size)==Z_OK&&n==rawsize,"corrupt compressed block");require(crc32(0,raw.data(),raw.size())==crc,"block checksum mismatch");return raw;}

class Packed final:public Reader {
    mutable ysp_storage::BoundedFile file;
    uint64_t bytes=0,n=0,nodes=0,orders=0,blocks=0,ro=0,go=0,gs=0,no=0,oo=0,bo=0,bd=0,logical=0;
    void range(uint64_t off,uint64_t len)const {require(off<=bytes&&len<=bytes-off,"pack section outside file");}
    Road at(uint64_t idx)const {require(idx<n,"road index outside file");auto r=file.value<Road>(ro+idx*sizeof(Road));require(r.geometry<=gs&&r.geomsize<=gs-r.geometry,"geometry outside section");require(r.metadata<=logical&&r.metasize<=logical-r.metadata,"metadata outside section");return r;}
protected:
    std::vector<uint8_t> loadBlock(uint64_t i)override {require(i<blocks,"block index outside file");auto b=file.value<Block>(bo+i*sizeof(Block));require(b.offset<=bytes-bd&&b.size<=bytes-bd-b.offset,"block outside data section");require(b.size<=BLOCK_SIZE+1024,"invalid compressed block size");auto encoded=file.blob(bd+b.offset,b.size);return inflateBlock(encoded.data(),b.size,b.rawsize,b.crc);}
public:
    explicit Packed(const std::string& path):file(path) {
        bytes=file.size();require(bytes>=HEADER,"truncated pack header");std::array<uint8_t,HEADER> header{};file.direct(0,header.data(),header.size());const auto* data=header.data();
        require(std::memcmp(data,"YSPACK1\0",8)==0,"unsupported pack magic");require(read<uint32_t>(data+8)==1&&read<uint32_t>(data+12)==0x01020304,"unsupported pack version/endian");require(crc32(0,data,128)==read<uint32_t>(data+128),"pack header checksum mismatch");
        uint64_t f[14];std::memcpy(f,data+16,sizeof f);n=f[0];nodes=f[1];orders=f[2];blocks=f[3];ro=f[4];go=f[5];gs=f[6];no=f[7];oo=f[8];bo=f[9];bd=f[10];logical=f[13];require(f[11]==bytes&&f[12]==BLOCK_SIZE,"pack size/block mismatch");require(n<=100000000&&nodes<=2*n+1&&orders==n&&blocks<=1000000,"invalid section counts");
        require(ro==HEADER&&go==ro+n*sizeof(Road)&&no==go+gs&&oo==no+nodes*sizeof(Node)&&bo==oo+orders*4&&bd==bo+blocks*sizeof(Block),"overlapping pack sections");range(ro,n*sizeof(Road));range(go,gs);range(no,nodes*sizeof(Node));range(oo,orders*4);range(bo,blocks*sizeof(Block));require(bd<=bytes,"bad block section");
        require(read<uint32_t>(data+148)==0x43524331,"missing section integrity directory");
        require(file.crc(ro,n*sizeof(Road))==read<uint32_t>(data+132)&&file.crc(no,nodes*sizeof(Node))==read<uint32_t>(data+136)&&file.crc(oo,orders*4)==read<uint32_t>(data+140)&&file.crc(bo,blocks*sizeof(Block))==read<uint32_t>(data+144),"pack index checksum mismatch");
        if(n){auto first=at(0),last=at(n-1);require(first.id<=last.id&&nodes>0,"bad road ordering");}
    }
    uint64_t count()const override{return n;}
    std::string ioStats()const override{return file.statsJSON();}
    bool road(int64_t id,Road& result,std::vector<uint8_t>& geometry)override {uint64_t lo=0,hi=n;while(lo<hi){auto m=lo+(hi-lo)/2;auto r=at(m);if(r.id<id)lo=m+1;else hi=m;}if(lo>=n)return false;result=at(lo);if(result.id!=id)return false;geometry=file.blob(go+result.geometry,result.geomsize);require(crc32(0,geometry.data(),geometry.size())==result.geomcrc,"geometry checksum mismatch");return true;}
    std::vector<int64_t> candidates(const Bounds& b)override {std::vector<int64_t> out;if(!n)return out;std::vector<uint32_t> stack{0};size_t visited=0;while(!stack.empty()){auto i=stack.back();stack.pop_back();require(i<nodes&&++visited<=nodes,"corrupt or cyclic spatial index");auto node=file.value<Node>(no+i*sizeof(Node));if(!overlap(node,b))continue;if(node.leaf==1){require(node.a<=orders&&node.b<=orders-node.a&&node.b<=32,"corrupt spatial leaf");for(uint64_t j=node.a;j<uint64_t(node.a)+node.b;++j){auto r=at(file.value<uint32_t>(oo+j*4));if(overlap(r,b))out.push_back(r.id);}}else{require(node.leaf==0&&node.a>i&&node.b>i,"corrupt spatial branch");stack.push_back(node.a);stack.push_back(node.b);}}std::sort(out.begin(),out.end());out.erase(std::unique(out.begin(),out.end()),out.end());return out;}
};

class Sql:public Reader {
protected:
    sqlite3* db=nullptr;sqlite3_stmt *get=nullptr,*spatial=nullptr,*block=nullptr,*getrecord=nullptr;uint64_t n=0;
    void prep(const char* text,sqlite3_stmt** stmt){require(sqlite3_prepare_v2(db,text,-1,stmt,nullptr)==SQLITE_OK,"invalid prototype SQLite schema");}
    bool recordOnly(int64_t id,Road& r){sqlite3_reset(getrecord);sqlite3_bind_int64(getrecord,1,id);int rc=sqlite3_step(getrecord);if(rc==SQLITE_DONE)return false;require(rc==SQLITE_ROW&&sqlite3_column_bytes(getrecord,0)==sizeof(Road),"invalid road record");std::memcpy(&r,sqlite3_column_blob(getrecord,0),sizeof(Road));require(r.id==id,"road identity mismatch");return true;}
    std::vector<uint8_t> loadBlock(uint64_t id)override {sqlite3_reset(block);sqlite3_bind_int64(block,1,id);require(sqlite3_step(block)==SQLITE_ROW,"missing semantic block");uint32_t raw=sqlite3_column_int(block,0),crc=sqlite3_column_int64(block,1);auto p=(const uint8_t*)sqlite3_column_blob(block,2);uint32_t size=sqlite3_column_bytes(block,2);return inflateBlock(p,size,raw,crc);}
public:
    explicit Sql(const std::string& path) {
        std::string uri="file:"+path+"?mode=ro&immutable=1";require(sqlite3_open_v2(uri.c_str(),&db,SQLITE_OPEN_READONLY|SQLITE_OPEN_URI|SQLITE_OPEN_NOMUTEX,nullptr)==SQLITE_OK,"cannot open prototype SQLite");
        try{sqlite3_exec(db,"PRAGMA cache_size=-8192;PRAGMA mmap_size=0;PRAGMA query_only=ON",nullptr,nullptr,nullptr);prep("SELECT record,geometry FROM road WHERE way_id=?",&get);prep("SELECT record FROM road WHERE way_id=?",&getrecord);prep("SELECT way_id FROM spatial WHERE min_lon<=? AND max_lon>=? AND min_lat<=? AND max_lat>=? ORDER BY way_id",&spatial);prep("SELECT raw_size,crc,data FROM block WHERE block_id=?",&block);sqlite3_stmt* c=nullptr;prep("SELECT value FROM metadata WHERE key='way_count'",&c);if(sqlite3_step(c)==SQLITE_ROW)n=sqlite3_column_int64(c,0);sqlite3_finalize(c);require(n>0,"missing SQLite way_count metadata");}catch(...){sqlite3_finalize(get);sqlite3_finalize(getrecord);sqlite3_finalize(spatial);sqlite3_finalize(block);sqlite3_close(db);db=nullptr;throw;}
    }
    ~Sql(){sqlite3_finalize(get);sqlite3_finalize(getrecord);sqlite3_finalize(spatial);sqlite3_finalize(block);if(db)sqlite3_close(db);}
    uint64_t count()const override{return n;}
    bool road(int64_t id,Road& r,std::vector<uint8_t>& geometry)override {sqlite3_reset(get);sqlite3_bind_int64(get,1,id);int rc=sqlite3_step(get);if(rc==SQLITE_DONE)return false;require(rc==SQLITE_ROW&&sqlite3_column_bytes(get,0)==sizeof(Road),"invalid road record");std::memcpy(&r,sqlite3_column_blob(get,0),sizeof(Road));require(r.id==id,"road identity mismatch");auto p=(const uint8_t*)sqlite3_column_blob(get,1);int size=sqlite3_column_bytes(get,1);require(size>=0&&uint32_t(size)==r.geomsize,"geometry size mismatch");geometry.assign(p,p+size);require(crc32(0,geometry.data(),geometry.size())==r.geomcrc,"geometry checksum mismatch");return true;}
    std::vector<int64_t> candidates(const Bounds& b)override {sqlite3_reset(spatial);sqlite3_bind_int64(spatial,1,b.maxlon);sqlite3_bind_int64(spatial,2,b.minlon);sqlite3_bind_int64(spatial,3,b.maxlat);sqlite3_bind_int64(spatial,4,b.minlat);std::vector<int64_t> out;int rc;while((rc=sqlite3_step(spatial))==SQLITE_ROW)out.push_back(sqlite3_column_int64(spatial,0));require(rc==SQLITE_DONE,"SQLite spatial query failed");return out;}
};
#ifdef YSP_WITH_GEODESK
class Geo final:public Sql {
    void* gol=nullptr;
public:
    explicit Geo(const std::string& path):Sql(path.substr(path.find('|')+1)){auto split=path.find('|');require(split!=std::string::npos,"GeoDesk path requires GOL|SQLITE");char error[1024]{};gol=storage_geodesk_open(path.substr(0,split).c_str(),error,sizeof error);if(!gol)throw std::runtime_error(error);}
    ~Geo(){storage_geodesk_close(gol);}
    std::vector<int64_t> candidates(const Bounds& b)override {int64_t* ids=nullptr;size_t count=0;require(storage_geodesk_candidates(gol,b.minlon/1e7,b.minlat/1e7,b.maxlon/1e7,b.maxlat/1e7,&ids,&count)==0,"GeoDesk query failed");std::unique_ptr<int64_t,decltype(&storage_geodesk_free_ids)> owned(ids,&storage_geodesk_free_ids);std::vector<int64_t> out;for(size_t i=0;i<count;++i){Road r{};if(recordOnly(ids[i],r)&&overlap(r,b))out.push_back(r.id);}std::sort(out.begin(),out.end());out.erase(std::unique(out.begin(),out.end()),out.end());return out;}
};
#endif
std::unique_ptr<Reader> openReader(const std::string& kind,const std::string& path) {if(kind=="packed")return std::make_unique<Packed>(path);if(kind=="sqlite")return std::make_unique<Sql>(path);
#ifdef YSP_WITH_GEODESK
if(kind=="geodesk")return std::make_unique<Geo>(path);
#endif
throw std::runtime_error("unsupported backend (GeoDesk requires optional native build)");}
double haversine(Point a,Point b) {double x=(b.lat-a.lat)*PI/180,y=(b.lon-a.lon)*PI/180,v=std::sin(x/2)*std::sin(x/2)+std::cos(a.lat*PI/180)*std::cos(b.lat*PI/180)*std::sin(y/2)*std::sin(y/2);return 2*EARTH*std::asin(std::sqrt(std::min(1.0,v)));}
struct Projection {double distance=std::numeric_limits<double>::infinity(),chainage=0,lat=0,lon=0;};
Projection project(Point q,const std::vector<Point>& points) {Projection best;double chain=0,c=std::cos(q.lat*PI/180),scale=EARTH*PI/180;if(points.size()==1){best={haversine(q,points[0]),0,points[0].lat,points[0].lon};return best;}for(size_t i=1;i<points.size();++i){auto a=points[i-1],b=points[i];double ax=(a.lon-q.lon)*c*scale,ay=(a.lat-q.lat)*scale,bx=(b.lon-q.lon)*c*scale,by=(b.lat-q.lat)*scale,dx=bx-ax,dy=by-ay,den=dx*dx+dy*dy,t=den?std::max(0.0,std::min(1.0,-(ax*dx+ay*dy)/den)):0;double dist=std::hypot(ax+t*dx,ay+t*dy),length=haversine(a,b);if(dist<best.distance)best={dist,chain+t*length,a.lat+t*(b.lat-a.lat),a.lon+t*(b.lon-a.lon)};chain+=length;}return best;}
Bounds bounds(double lat,double lon,double radius){require(std::isfinite(lat)&&std::isfinite(lon)&&std::isfinite(radius)&&std::abs(lat)<89&&std::abs(lon)<=180&&radius>0&&radius<=10000,"invalid query coordinate/radius");double dy=radius/(EARTH*PI/180),dx=dy/std::cos(lat*PI/180);return {(int64_t)std::floor((lon-dx)*1e7),(int64_t)std::floor((lat-dy)*1e7),(int64_t)std::ceil((lon+dx)*1e7),(int64_t)std::ceil((lat+dy)*1e7)};}
std::string query(Reader& reader,double lat,double lon,double radius) {auto ids=reader.candidates(bounds(lat,lon,radius));std::ostringstream out;out<<std::setprecision(17)<<"[";bool first=true;for(auto id:ids){Road r{};std::vector<uint8_t> bytes;require(reader.road(id,r,bytes),"spatial road missing");auto points=decode(bytes,r.points);auto p=project({lat,lon},points);if(p.distance>radius)continue;auto semantic=reader.metadata(r);if(!first)out<<',';first=false;out<<"{\"way_id\":"<<id<<",\"distance_m\":"<<p.distance<<",\"chainage_m\":"<<p.chainage<<",\"lat\":"<<p.lat<<",\"lon\":"<<p.lon<<",\"speed_code\":"<<r.speed<<",\"forward_speed_code\":"<<r.forward<<",\"backward_speed_code\":"<<r.backward<<",\"points\":"<<r.points<<",\"geometry_crc32\":"<<r.geomcrc<<",\"semantic_crc32\":"<<r.metacrc<<"}";}out<<']';return out.str();}
struct Memory {uint64_t rss=0,highwater=0,footprint=0,pss=0,private_clean=0,private_dirty=0,shared_clean=0,shared_dirty=0,pss_anon=0,pss_file=0;bool footprint_available=false,smaps_available=false;const char* rss_source="unavailable";};
Memory memory(){Memory m;struct rusage ru{};getrusage(RUSAGE_SELF,&ru);
#ifdef __APPLE__
m.highwater=ru.ru_maxrss;mach_task_basic_info_data_t basic{};mach_msg_type_number_t count=MACH_TASK_BASIC_INFO_COUNT;if(task_info(mach_task_self(),MACH_TASK_BASIC_INFO,(task_info_t)&basic,&count)==KERN_SUCCESS){m.rss=basic.resident_size;m.rss_source="mach_task_basic_info";}task_vm_info_data_t vm{};count=TASK_VM_INFO_COUNT;if(task_info(mach_task_self(),TASK_VM_INFO,(task_info_t)&vm,&count)==KERN_SUCCESS){m.footprint=vm.phys_footprint;m.footprint_available=true;}
#else
m.highwater=uint64_t(ru.ru_maxrss)*1024;std::ifstream f("/proc/self/statm");uint64_t total=0,pages=0;if(f>>total>>pages){m.rss=pages*sysconf(_SC_PAGESIZE);m.rss_source="proc_statm";}std::ifstream smaps("/proc/self/smaps_rollup");std::string line;while(std::getline(smaps,line)){std::istringstream input(line);std::string key,unit;uint64_t kb=0;if(!(input>>key>>kb>>unit)||unit!="kB")continue;uint64_t bytes=kb*1024;if(key=="Rss:"){m.rss=bytes;m.rss_source="proc_smaps_rollup";}else if(key=="Pss:"){m.pss=bytes;m.smaps_available=true;}else if(key=="Private_Clean:")m.private_clean=bytes;else if(key=="Private_Dirty:")m.private_dirty=bytes;else if(key=="Shared_Clean:")m.shared_clean=bytes;else if(key=="Shared_Dirty:")m.shared_dirty=bytes;else if(key=="Pss_Anon:")m.pss_anon=bytes;else if(key=="Pss_File:")m.pss_file=bytes;}
#endif
return m;}
std::string memjson(Memory m){auto linuxValue=[&](uint64_t value){return m.smaps_available?std::to_string(value):std::string("null");};return "{\"rss_bytes\":"+std::to_string(m.rss)+",\"rss_source\":"+escaped(m.rss_source)+",\"highwater_rss_source\":\"getrusage_ru_maxrss\",\"highwater_rss_bytes\":"+std::to_string(m.highwater)+",\"physical_footprint_bytes\":"+(m.footprint_available?std::to_string(m.footprint):"null")+",\"pss_bytes\":"+linuxValue(m.pss)+",\"private_resident_bytes\":"+linuxValue(m.private_clean+m.private_dirty)+",\"private_clean_bytes\":"+linuxValue(m.private_clean)+",\"private_dirty_bytes\":"+linuxValue(m.private_dirty)+",\"shared_resident_bytes\":"+linuxValue(m.shared_clean+m.shared_dirty)+",\"pss_anonymous_bytes\":"+linuxValue(m.pss_anon)+",\"pss_file_bytes\":"+linuxValue(m.pss_file)+"}";}
std::string stats(std::vector<double> v){if(v.empty())return "{}";std::sort(v.begin(),v.end());auto q=[&](double p){return v[(size_t)std::ceil(p*(v.size()-1))];};std::ostringstream s;s<<std::setprecision(9)<<"{\"count\":"<<v.size()<<",\"p50_us\":"<<q(.5)<<",\"p95_us\":"<<q(.95)<<",\"p99_us\":"<<q(.99)<<",\"max_us\":"<<v.back()<<"}";return s.str();}
std::vector<std::array<double,3>> parseCSV(const char* csv){std::istringstream input(csv?csv:"");std::string line;std::vector<std::array<double,3>> rows;while(std::getline(input,line)){if(line.empty()||line[0]=='#'||line.rfind("lat,",0)==0)continue;std::replace(line.begin(),line.end(),',',' ');std::istringstream row(line);std::array<double,3> q{};require(bool(row>>q[0]>>q[1]>>q[2]),"invalid query CSV");bounds(q[0],q[1],q[2]);rows.push_back(q);}require(!rows.empty()&&rows.size()<=1000000,"empty/oversized query corpus");return rows;}
char* result(const std::string& text){auto p=(char*)std::malloc(text.size()+1);if(p)std::memcpy(p,text.c_str(),text.size()+1);return p;}
template<class F>char* safe(F f){try{return result(f());}catch(const std::exception& e){return result("{\"error\":"+escaped(e.what())+"}");}catch(...){return result("{\"error\":\"unknown native failure\"}");}}
}
extern "C" char* storage_query_json(const char* kind,const char* path,double lat,double lon,double radius){return safe([&](){auto r=openReader(kind?kind:"",path?path:"");return query(*r,lat,lon,radius);});}
extern "C" char* storage_query_batch_json(const char* kind,const char* path,const char* csv){return safe([&](){auto queries=parseCSV(csv);auto r=openReader(kind?kind:"",path?path:"");std::ostringstream s;s<<'[';bool first=true;for(auto q:queries){if(!first)s<<',';first=false;s<<query(*r,q[0],q[1],q[2]);}s<<']';return s.str();});}
extern "C" char* storage_way_json(const char* kind,const char* path,long long id){return safe([&](){auto reader=openReader(kind?kind:"",path?path:"");Road r{};std::vector<uint8_t> bytes;if(!reader->road(id,r,bytes))return std::string("null");auto points=decode(bytes,r.points);auto semantic=reader->metadata(r);std::ostringstream s;s<<std::setprecision(17)<<"{\"way_id\":"<<id<<",\"geometry\":[";bool first=true;for(auto p:points){if(!first)s<<',';first=false;s<<'['<<p.lat<<','<<p.lon<<']';}s<<"],\"semantic\":"<<semantic<<'}';return s.str();});}
extern "C" char* storage_benchmark_json(const char* kind,const char* path,const char* csv,int repetitions){return safe([&](){require(repetitions>=1&&repetitions<=100,"invalid repetitions");auto queries=parseCSV(csv);auto before=memory();auto t=Clock::now();auto reader=openReader(kind?kind:"",path?path:"");double init=std::chrono::duration<double,std::milli>(Clock::now()-t).count();auto opened=memory();std::vector<double> first,warm;uint64_t digest=14695981039346656037ull;std::vector<std::string> expected;for(auto q:queries){t=Clock::now();auto value=query(*reader,q[0],q[1],q[2]);first.push_back(std::chrono::duration<double,std::micro>(Clock::now()-t).count());digest=hash(digest,value.data(),value.size());expected.push_back(std::move(value));}auto firstmem=memory();for(int rep=0;rep<repetitions;++rep){for(size_t i=0;i<queries.size();++i){auto q=queries[i];t=Clock::now();auto value=query(*reader,q[0],q[1],q[2]);warm.push_back(std::chrono::duration<double,std::micro>(Clock::now()-t).count());require(value==expected[i],"nondeterministic lookup result");}}auto after=memory();std::ostringstream s;s<<std::setprecision(9)<<"{\"backend\":"<<escaped(kind?kind:"")<<",\"sqlite_version\":"<<escaped(sqlite3_libversion())<<",\"ways\":"<<reader->count()<<",\"query_count\":"<<queries.size()<<",\"repetitions\":"<<repetitions<<",\"result_fnv1a64\":\""<<hex(digest)<<"\",\"init_ms\":"<<init<<",\"first_pass\":"<<stats(first)<<",\"warm\":"<<stats(warm)<<",\"memory_before\":"<<memjson(before)<<",\"memory_opened\":"<<memjson(opened)<<",\"memory_first_pass\":"<<memjson(firstmem)<<",\"memory_after\":"<<memjson(after)<<",\"incremental_rss_bytes\":"<<int64_t(after.rss)-int64_t(before.rss)<<",\"cache_capacity_bytes\":4194304,\"io_stats\":"<<reader->diagnostics()<<",\"notes\":\"First pass is process-first, not OS-cold. Query validates exact geometry and full per-way semantic record; production matching/conditional evaluation is outside this kernel. Process RSS/highwater include host harness and allocator. Kernel-reported highwater is unadjusted; Linux kernel accounting may lag current smaps_rollup RSS.\"}";return s.str();});}
extern "C" void storage_free(void* p){std::free(p);}
