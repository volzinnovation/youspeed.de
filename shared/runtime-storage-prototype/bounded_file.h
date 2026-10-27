#pragma once

// Immutable, fd-only storage. Callers serialize access to a persistent handle.
// The cache holds a fixed number of pages; payloads are read directly into
// caller-owned bounded/validated buffers. No file section is memory mapped.
#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <list>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <unordered_map>
#include <vector>
#include <zlib.h>

namespace ysp_storage {

class BoundedFile {
    struct Page {
        std::vector<uint8_t> bytes;
        std::list<uint64_t>::iterator recent;
    };
    int descriptor_=-1;
    uint64_t size_=0;
    size_t capacity_=0;
    std::unordered_map<uint64_t,Page> pages_;
    std::list<uint64_t> recent_;
    uint64_t resident_=0,peak_=0,hits_=0,misses_=0,calls_=0,bytes_=0,maxRequest_=0;
    static constexpr size_t PAGE=4096;

    static void check(bool ok,const char* message) {
        if(!ok) throw std::runtime_error(message);
    }
public:
    explicit BoundedFile(const std::string& path,size_t cacheBytes=512*1024):capacity_(cacheBytes/PAGE) {
        check(capacity_>0,"file page cache must hold a page");
        descriptor_=::open(path.c_str(),O_RDONLY|O_CLOEXEC);
        check(descriptor_>=0,"cannot open immutable packed file");
#if defined(__ANDROID__)
        struct stat64 info{};
        const int status=::fstat64(descriptor_,&info);
#else
        struct stat info{};
        const int status=::fstat(descriptor_,&info);
#endif
        if(status!=0||info.st_size<0) {
            ::close(descriptor_);descriptor_=-1;
            throw std::runtime_error("cannot stat immutable packed file");
        }
        size_=static_cast<uint64_t>(info.st_size);
    }
    ~BoundedFile(){if(descriptor_>=0)::close(descriptor_);}
    BoundedFile(const BoundedFile&)=delete;
    BoundedFile& operator=(const BoundedFile&)=delete;
    uint64_t size()const{return size_;}
    size_t cacheCapacity()const{return capacity_*PAGE;}
    uint64_t cacheResident()const{return resident_;}
    uint64_t cachePeak()const{return peak_;}
    void range(uint64_t offset,uint64_t length)const {
        check(offset<=size_&&length<=size_-offset,"packed read outside file");
        check(offset<=static_cast<uint64_t>(std::numeric_limits<int64_t>::max()),"packed offset exceeds signed 64-bit range");
    }
    void direct(uint64_t offset,void* destination,size_t length) {
        range(offset,length);
        auto output=static_cast<uint8_t*>(destination);
        while(length) {
            const size_t request=std::min<size_t>(length,1024*1024);
            maxRequest_=std::max<uint64_t>(maxRequest_,request);
#if defined(__ANDROID__)
            const ssize_t count=::pread64(descriptor_,output,request,static_cast<off64_t>(offset));
#else
            static_assert(sizeof(off_t)>=8,"packed storage requires 64-bit file offsets");
            const ssize_t count=::pread(descriptor_,output,request,static_cast<off_t>(offset));
#endif
            ++calls_;
            if(count<0&&errno==EINTR)continue;
            check(count>0,"short or failed packed pread");
            bytes_+=static_cast<uint64_t>(count);
            offset+=static_cast<uint64_t>(count);output+=count;length-=static_cast<size_t>(count);
        }
    }
    void cached(uint64_t offset,void* destination,size_t length) {
        range(offset,length);
        auto output=static_cast<uint8_t*>(destination);
        while(length) {
            const uint64_t pageID=offset/PAGE;
            const size_t in=static_cast<size_t>(offset%PAGE);
            auto found=pages_.find(pageID);
            if(found==pages_.end()) {
                ++misses_;
                // Evict before allocation: even the transient cache contents
                // never exceed the declared page budget.
                if(pages_.size()>=capacity_) {
                    const auto victim=recent_.back();recent_.pop_back();
                    resident_-=pages_.at(victim).bytes.size();pages_.erase(victim);
                }
                const size_t size=static_cast<size_t>(std::min<uint64_t>(PAGE,size_-pageID*PAGE));
                std::vector<uint8_t> page(size);
                direct(pageID*PAGE,page.data(),page.size());
                recent_.push_front(pageID);
                found=pages_.emplace(pageID,Page{std::move(page),recent_.begin()}).first;
                resident_+=size;peak_=std::max(peak_,resident_);
            } else {
                ++hits_;recent_.erase(found->second.recent);recent_.push_front(pageID);
                found->second.recent=recent_.begin();
            }
            const auto& page=found->second.bytes;
            check(in<page.size(),"invalid cached packed offset");
            const size_t count=std::min(length,page.size()-in);
            std::memcpy(output,page.data()+in,count);
            output+=count;offset+=count;length-=count;
        }
    }
    template<typename T>T value(uint64_t offset) {
        T result{};cached(offset,&result,sizeof(result));return result;
    }
    std::vector<uint8_t> blob(uint64_t offset,uint32_t length) {
        range(offset,length);std::vector<uint8_t> result(length);
        if(length)direct(offset,result.data(),length);return result;
    }
    uint32_t crc(uint64_t offset,uint64_t length) {
        range(offset,length);std::array<uint8_t,64*1024> scratch{};uint32_t result=0;
        while(length) {
            const size_t count=static_cast<size_t>(std::min<uint64_t>(length,scratch.size()));
            direct(offset,scratch.data(),count);
            result=static_cast<uint32_t>(crc32(result,scratch.data(),static_cast<uInt>(count)));offset+=count;length-=count;
        }
        return result;
    }
    std::string statsJSON()const {
        std::ostringstream output;
        output<<"{\"mode\":\"bounded_pread\",\"mapped_bytes\":0,\"page_bytes\":"<<PAGE
              <<",\"page_cache_capacity_bytes\":"<<cacheCapacity()<<",\"page_cache_resident_bytes\":"<<resident_
              <<",\"page_cache_peak_bytes\":"<<peak_<<",\"page_cache_hits\":"<<hits_
              <<",\"page_cache_misses\":"<<misses_<<",\"pread_calls\":"<<calls_
              <<",\"pread_bytes\":"<<bytes_<<",\"largest_pread_request_bytes\":"<<maxRequest_<<"}";
        return output.str();
    }
};

} // namespace ysp_storage
