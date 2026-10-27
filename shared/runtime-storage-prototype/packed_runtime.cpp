#include "packed_runtime.h"
#include "bounded_file.h"
#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <list>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#define ZSTD_STATIC_LINKING_ONLY
#if defined(__GNUC__) || defined(__clang__)
#define ZSTDLIB_VISIBLE __attribute__((visibility("hidden")))
#endif
#include "../packed-runtime/vendor/zstd/zstd.h"

namespace {
constexpr uint64_t HEADER_BYTES=128,BLOCK_BYTES=262144;
constexpr uint64_t CONTEXT_CACHE=YSP_CONTEXT_CACHE_DEFAULT_BYTES,GEOMETRY_CACHE=YSP_GEOMETRY_CACHE_DEFAULT_BYTES;
constexpr uint32_t MAX_GEOMETRY_RECORD=16*1024*1024;
#pragma pack(push,1)
struct BlockEntry {uint64_t offset;uint32_t encoded,raw,crc,reserved;};
struct GeometryEntry {int64_t way;uint64_t offset;uint32_t bytes,crc;};
#pragma pack(pop)
static_assert(sizeof(BlockEntry)==24&&sizeof(GeometryEntry)==24,"packed runtime record layout");
void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
template<class T>T field(const uint8_t* p){T result;std::memcpy(&result,p,sizeof result);return result;}
void setError(char* out,size_t size,const char* message){if(out&&size){const size_t count=std::min(size-1,std::strlen(message));std::memcpy(out,message,count);out[count]=0;}}
void clearError(char* out,size_t size){if(out&&size)out[0]=0;}
char* copied(const std::string& value){auto out=static_cast<char*>(std::malloc(value.size()+1));check(out!=nullptr,"packed result allocation failed");std::memcpy(out,value.data(),value.size());out[value.size()]=0;return out;}

class BlockPack {
    struct CachedBlock {std::vector<uint8_t> bytes;std::list<uint64_t>::iterator recent;};
    ysp_storage::BoundedFile file_;
    uint64_t logical_=0,count_=0,directory_=0,data_=0,indexCount_=0,index_=0;
    uint64_t capacity_=0,resident_=0,peak_=0,hits_=0,misses_=0,largestResult_=0;
    bool geometry_=false;
    uint32_t codec_=1;
    std::unique_ptr<ZSTD_DCtx,decltype(&ZSTD_freeDCtx)> zstd_{nullptr,&ZSTD_freeDCtx};
    std::array<uint8_t,32> source_{};
    std::unordered_map<uint64_t,CachedBlock> cache_;
    std::list<uint64_t> recent_;
    std::vector<uint8_t> encodedScratch_;

    BlockEntry entry(uint64_t id){check(id<count_,"packed block outside directory");return file_.value<BlockEntry>(directory_+id*sizeof(BlockEntry));}
    GeometryEntry geometryEntry(uint64_t id){check(id<indexCount_,"geometry index outside directory");return file_.value<GeometryEntry>(index_+id*sizeof(GeometryEntry));}
    const std::vector<uint8_t>& block(uint64_t id){
        auto found=cache_.find(id);
        if(found!=cache_.end()){++hits_;recent_.splice(recent_.begin(),recent_,found->second.recent);return found->second.bytes;}
        ++misses_;const auto descriptor=entry(id);
        std::vector<uint8_t> raw;
        if(cache_.size()>=capacity_/BLOCK_BYTES){const auto victim=recent_.back();recent_.pop_back();raw=std::move(cache_.at(victim).bytes);resident_-=raw.size();cache_.erase(victim);}
        // Reuse fixed allocated slots, including for a short final block.
        // This caps real vector storage and avoids allocator/quarantine growth
        // from repeatedly freeing and allocating 256 KiB on random reads.
        raw.resize(BLOCK_BYTES);
        if(encodedScratch_.empty())encodedScratch_.resize(BLOCK_BYTES+1024);
        file_.direct(data_+descriptor.offset,encodedScratch_.data(),descriptor.encoded);
        const auto* encoded=encodedScratch_.data();
        if(codec_==1){
            z_stream stream{};stream.next_in=const_cast<Bytef*>(encoded);stream.avail_in=descriptor.encoded;stream.next_out=raw.data();stream.avail_out=descriptor.raw;
            check(inflateInit(&stream)==Z_OK,"packed zlib initialization failed");const int result=inflate(&stream,Z_FINISH);const bool valid=result==Z_STREAM_END&&stream.total_out==descriptor.raw&&stream.avail_in==0;inflateEnd(&stream);check(valid,"packed zlib block decompression failed");
        }else{
            ZSTD_frameHeader frame{};const auto header=ZSTD_getFrameHeader(&frame,encoded,descriptor.encoded);
            check(!ZSTD_isError(header)&&header==0&&frame.frameType==ZSTD_frame&&frame.frameContentSize==descriptor.raw&&frame.windowSize<=BLOCK_BYTES&&frame.dictID==0,"invalid zstd frame size/window/dictionary");
            const auto frameBytes=ZSTD_findFrameCompressedSize(encoded,descriptor.encoded);check(!ZSTD_isError(frameBytes)&&frameBytes==descriptor.encoded,"zstd block must contain exactly one frame");
            const auto result=ZSTD_decompressDCtx(zstd_.get(),raw.data(),descriptor.raw,encoded,descriptor.encoded);check(!ZSTD_isError(result)&&result==descriptor.raw,"packed zstd block decompression failed");
        }
        check(crc32(0,raw.data(),descriptor.raw)==descriptor.crc,"packed block CRC mismatch");
        recent_.push_front(id);resident_+=raw.size();peak_=std::max(peak_,resident_);
        return cache_.emplace(id,CachedBlock{std::move(raw),recent_.begin()}).first->second.bytes;
    }
public:
    explicit BlockPack(const char* path,bool geometry,uint64_t cacheBytes):file_(path?path:""),geometry_(geometry){
        const uint16_t hostEndian=1;check(*reinterpret_cast<const uint8_t*>(&hostEndian)==1,"packed runtime requires little-endian host");
        check(file_.size()>=HEADER_BYTES,"truncated packed runtime header");std::array<uint8_t,HEADER_BYTES> h{};file_.direct(0,h.data(),h.size());
        check(std::memcmp(h.data(),geometry?"YSPGEO1\0":"YSPCTX1\0",8)==0,"unsupported packed runtime magic");
        check(field<uint32_t>(&h[8])==1&&field<uint32_t>(&h[12])==0x01020304&&field<uint32_t>(&h[16])==HEADER_BYTES,"unsupported packed runtime version/endian/header");
        codec_=field<uint32_t>(&h[92]);check(field<uint32_t>(&h[20])==BLOCK_BYTES&&(codec_==1||codec_==2),"unsupported packed block size/codec");
        check(crc32(0,h.data(),88)==field<uint32_t>(&h[88]),"packed header CRC mismatch");
        logical_=field<uint64_t>(&h[24]);count_=field<uint64_t>(&h[32]);directory_=field<uint64_t>(&h[40]);data_=field<uint64_t>(&h[48]);
        indexCount_=field<uint64_t>(&h[64]);index_=field<uint64_t>(&h[72]);std::memcpy(source_.data(),h.data()+96,source_.size());
        check(field<uint64_t>(&h[56])==file_.size(),"packed physical size mismatch");
        check(logical_<=uint64_t(std::numeric_limits<int64_t>::max()),"packed logical size exceeds signed 64-bit range");
        check(count_==logical_/BLOCK_BYTES+(logical_%BLOCK_BYTES!=0),"packed logical block count mismatch");
        check(count_<=(file_.size()-HEADER_BYTES)/sizeof(BlockEntry),"packed directory count overflow");
        check(directory_>=HEADER_BYTES&&directory_<=file_.size()&&count_<=(file_.size()-directory_)/sizeof(BlockEntry),"packed directory outside file");
        check(data_>=directory_&&count_*sizeof(BlockEntry)<=data_-directory_&&data_<=file_.size(),"packed data overlaps directory");
        if(geometry){
            check(index_==HEADER_BYTES&&indexCount_<=(file_.size()-index_)/sizeof(GeometryEntry),"geometry index outside file");
            check(index_<=directory_&&indexCount_*sizeof(GeometryEntry)<=directory_-index_,"geometry index overlaps block directory");
            check(file_.crc(index_,indexCount_*sizeof(GeometryEntry))==field<uint32_t>(&h[84]),"geometry index CRC mismatch");
        }else check(logical_>0&&indexCount_==0&&index_==0&&field<uint32_t>(&h[84])==0,"invalid packed context image/index");
        check(file_.crc(directory_,count_*sizeof(BlockEntry))==field<uint32_t>(&h[80]),"packed block directory CRC mismatch");
        uint64_t end=0;
        for(uint64_t i=0;i<count_;++i){const auto b=entry(i);const auto raw=std::min<uint64_t>(BLOCK_BYTES,logical_-i*BLOCK_BYTES);check(b.reserved==0&&b.raw==raw&&b.encoded>0&&b.encoded<=BLOCK_BYTES+1024,"invalid packed block descriptor");check(b.offset>=end&&b.offset<=file_.size()-data_&&b.encoded<=file_.size()-data_-b.offset,"overlapping/out-of-bounds packed blocks");end=b.offset+b.encoded;}
        if(geometry){int64_t previous=0;uint64_t payloadEnd=0;for(uint64_t i=0;i<indexCount_;++i){const auto row=geometryEntry(i);check(row.way>previous&&row.bytes>0&&row.bytes<=MAX_GEOMETRY_RECORD&&row.offset==payloadEnd&&row.offset<=logical_&&row.bytes<=logical_-row.offset,"invalid geometry identity/payload ordering");previous=row.way;payloadEnd=row.offset+row.bytes;}check(payloadEnd==logical_,"unindexed geometry payload");}
        const uint64_t requested=cacheBytes?cacheBytes:(geometry?GEOMETRY_CACHE:CONTEXT_CACHE);
        check(requested>=BLOCK_BYTES&&requested<=64*1024*1024,"packed block cache must be between 256 KiB and 64 MiB");capacity_=(requested/BLOCK_BYTES)*BLOCK_BYTES;
        if(codec_==2){zstd_.reset(ZSTD_createDCtx());check(zstd_!=nullptr,"zstd decoder allocation failed");check(!ZSTD_isError(ZSTD_DCtx_setParameter(zstd_.get(),ZSTD_d_windowLogMax,18)),"zstd decoder window limit failed");}
        if(!geometry){std::array<uint8_t,16> signature{};check(read(0,signature.data(),signature.size())==signature.size()&&std::memcmp(signature.data(),"SQLite format 3\0",16)==0,"context payload is not a SQLite page image");}
    }
    uint64_t size()const{return logical_;}
    size_t read(uint64_t offset,void* output,size_t length){
        if(offset>=logical_||!length)return 0;
        check(output!=nullptr,"null packed read destination");const uint64_t available=logical_-offset;
        const size_t wanted=static_cast<size_t>(std::min<uint64_t>(available,length));size_t left=wanted;auto destination=static_cast<uint8_t*>(output);
        while(left){const auto id=offset/BLOCK_BYTES;const size_t in=static_cast<size_t>(offset%BLOCK_BYTES);const auto& raw=block(id);check(in<raw.size(),"packed logical read outside block");const size_t bytes=std::min(left,raw.size()-in);std::memcpy(destination,raw.data()+in,bytes);destination+=bytes;offset+=bytes;left-=bytes;}
        return wanted;
    }
    char* geometry(const char* decimal){
        check(geometry_,"not a geometry handle");check(decimal&&*decimal,"missing geometry source ID");uint64_t id=0;
        for(const char* p=decimal;*p;++p){check(*p>='0'&&*p<='9',"geometry source ID must be positive decimal Int64");const uint64_t digit=static_cast<unsigned>(*p-'0');check(id<=(uint64_t(std::numeric_limits<int64_t>::max())-digit)/10,"geometry source ID exceeds Int64");id=id*10+digit;}
        check(id>0,"geometry source ID must be positive");uint64_t low=0,high=indexCount_;
        while(low<high){const auto middle=low+(high-low)/2;const auto row=geometryEntry(middle);if(row.way<static_cast<int64_t>(id))low=middle+1;else high=middle;}
        check(low<indexCount_,"geometry source ID absent from companion");const auto row=geometryEntry(low);check(row.way==static_cast<int64_t>(id),"geometry source ID absent from companion");
        // A record is copied once for the SQLite scalar result. It is caller
        // owned and is not retained in either of the bounded native caches.
        largestResult_=std::max<uint64_t>(largestResult_,row.bytes);std::unique_ptr<char,decltype(&std::free)> result(static_cast<char*>(std::malloc(static_cast<size_t>(row.bytes)+1)),&std::free);check(result!=nullptr,"geometry result allocation failed");
        check(read(row.offset,result.get(),row.bytes)==row.bytes,"short geometry record read");check(std::memchr(result.get(),0,row.bytes)==nullptr,"geometry JSON contains embedded NUL");
        check(crc32(0,reinterpret_cast<const Bytef*>(result.get()),row.bytes)==row.crc,"geometry record CRC mismatch");result.get()[row.bytes]=0;return result.release();
    }
    std::string stats()const{
        std::string source;source.reserve(64);constexpr const char* digits="0123456789abcdef";for(auto byte:source_){source+=digits[byte>>4];source+=digits[byte&15];}
        std::ostringstream output;output<<"{\"format\":\""<<(geometry_?"YSPGEO1":"YSPCTX1")<<"\",\"codec\":"<<codec_<<",\"source_sqlite_sha256\":\""<<source<<"\",\"decoder_workspace_bytes\":"<<(zstd_?ZSTD_sizeof_DCtx(zstd_.get()):0)<<",\"encoded_scratch_capacity_bytes\":"<<encodedScratch_.capacity()<<",\"logical_bytes\":"<<logical_<<",\"block_cache_capacity_bytes\":"<<capacity_<<",\"block_cache_resident_bytes\":"<<resident_<<",\"block_cache_peak_bytes\":"<<peak_<<",\"block_cache_hits\":"<<hits_<<",\"block_cache_misses\":"<<misses_<<",\"largest_caller_result_bytes\":"<<largestResult_<<",\"file\":"<<file_.statsJSON()<<"}";return output.str();
    }
};
struct Handle {std::mutex mutex;BlockPack pack;Handle(const char* path,bool geometry,uint64_t cache):pack(path,geometry,cache){}};
template<class F,class R>R guarded(char* error,size_t size,R failure,F action){clearError(error,size);try{return action();}catch(const std::exception& exception){setError(error,size,exception.what());return failure;}catch(...){setError(error,size,"unknown packed runtime failure");return failure;}}
}

extern "C" void* ysp_context_open(const char* path,uint64_t cache,char* error,size_t size){return guarded(error,size,static_cast<void*>(nullptr),[&](){return static_cast<void*>(new Handle(path,false,cache));});}
extern "C" uint64_t ysp_context_size(void* value){if(!value)return 0;auto& handle=*static_cast<Handle*>(value);std::lock_guard<std::mutex> lock(handle.mutex);return handle.pack.size();}
extern "C" int64_t ysp_context_read(void* value,uint64_t offset,void* output,size_t bytes,char* error,size_t size){return guarded(error,size,int64_t(-1),[&](){check(value!=nullptr,"null context handle");check(bytes<=static_cast<uint64_t>(std::numeric_limits<int64_t>::max()),"packed read request exceeds signed 64-bit range");auto& handle=*static_cast<Handle*>(value);std::lock_guard<std::mutex> lock(handle.mutex);return static_cast<int64_t>(handle.pack.read(offset,output,bytes));});}
extern "C" void ysp_context_close(void* value){delete static_cast<Handle*>(value);}
extern "C" void* ysp_geometry_open(const char* path,uint64_t cache,char* error,size_t size){return guarded(error,size,static_cast<void*>(nullptr),[&](){return static_cast<void*>(new Handle(path,true,cache));});}
extern "C" char* ysp_geometry_json(void* value,const char* id,char* error,size_t size){return guarded(error,size,static_cast<char*>(nullptr),[&](){check(value!=nullptr,"null geometry handle");auto& handle=*static_cast<Handle*>(value);std::lock_guard<std::mutex> lock(handle.mutex);return handle.pack.geometry(id);});}
extern "C" void ysp_geometry_close(void* value){delete static_cast<Handle*>(value);}
extern "C" void ysp_packed_free(void* memory){std::free(memory);}
extern "C" int ysp_sqlite_cache_kib(void){return YSP_SQLITE_CACHE_DEFAULT_KIB;}
extern "C" char* ysp_context_stats_json(void* value){return guarded(nullptr,0,static_cast<char*>(nullptr),[&](){check(value!=nullptr,"null context handle");auto& handle=*static_cast<Handle*>(value);std::lock_guard<std::mutex> lock(handle.mutex);return copied(handle.pack.stats());});}
extern "C" char* ysp_geometry_stats_json(void* value){return ysp_context_stats_json(value);}
