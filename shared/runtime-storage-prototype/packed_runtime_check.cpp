#include "packed_runtime.h"
#include <sqlite3.h>
#include <zlib.h>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::string quoted(const std::string& value){std::ostringstream out;out<<'"';for(unsigned char c:value){if(c=='"'||c=='\\')out<<'\\'<<c;else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<unsigned(c)<<std::dec;else out<<c;}out<<'"';return out.str();}
void check(bool ok,const char* error){if(!ok)throw std::runtime_error(error);}
using Context=std::unique_ptr<void,decltype(&ysp_context_close)>;
using Geometry=std::unique_ptr<void,decltype(&ysp_geometry_close)>;
Context context(const char* path){char error[512]{};auto handle=ysp_context_open(path,0,error,sizeof error);check(handle,error);return Context(handle,&ysp_context_close);}
Geometry geometry(const char* path){char error[512]{};auto handle=ysp_geometry_open(path,0,error,sizeof error);check(handle,error);return Geometry(handle,&ysp_geometry_close);}
std::string stats(void* context){char* value=ysp_context_stats_json(context);check(value,"native statistics unavailable");std::string copy(value);ysp_packed_free(value);return copy;}
void geometryScalar(sqlite3_context* result,int argc,sqlite3_value** values){
    if(argc!=1||sqlite3_value_type(values[0])==SQLITE_NULL){sqlite3_result_null(result);return;}
    char error[512]{};auto text=ysp_geometry_json(sqlite3_user_data(result),reinterpret_cast<const char*>(sqlite3_value_text(values[0])),error,sizeof error);
    if(!text){sqlite3_result_error(result,error,-1);return;}
    sqlite3_result_text(result,text,-1,&ysp_packed_free);
}
void query(const char* contextPath,const char* geometryPath,const char* sql){
    auto geo=geometry(geometryPath);check(ysp_register_context_vfs()==SQLITE_OK,"context VFS registration failed");
    sqlite3* db=nullptr;const int opened=sqlite3_open_v2(contextPath,&db,SQLITE_OPEN_READONLY|SQLITE_OPEN_NOMUTEX,"ysp-packed-v1");
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> database(db,&sqlite3_close);
    check(opened==SQLITE_OK,db?sqlite3_errmsg(db):"SQLite open failed");
    int flags=SQLITE_UTF8|SQLITE_DETERMINISTIC;
#ifdef SQLITE_INNOCUOUS
    flags|=SQLITE_INNOCUOUS;
#endif
    check(sqlite3_create_function_v2(db,"ysp_way_points_json",1,flags,geo.get(),geometryScalar,nullptr,nullptr,nullptr)==SQLITE_OK,sqlite3_errmsg(db));
    const auto configuration="PRAGMA mmap_size=0;PRAGMA cache_size=-"+std::to_string(ysp_sqlite_cache_kib())+";PRAGMA query_only=ON;";
    check(sqlite3_exec(db,configuration.c_str(),nullptr,nullptr,nullptr)==SQLITE_OK,sqlite3_errmsg(db));
    sqlite3_stmt* statement=nullptr;check(sqlite3_prepare_v2(db,sql,-1,&statement,nullptr)==SQLITE_OK,sqlite3_errmsg(db));
    std::unique_ptr<sqlite3_stmt,decltype(&sqlite3_finalize)> prepared(statement,&sqlite3_finalize);
    std::ostringstream output;output<<std::setprecision(17)<<"{\"columns\":[";
    for(int c=0;c<sqlite3_column_count(statement);++c){if(c)output<<',';output<<quoted(sqlite3_column_name(statement,c));}output<<"],\"rows\":[";
    int code=0;bool first=true;
    while((code=sqlite3_step(statement))==SQLITE_ROW){if(!first)output<<',';first=false;output<<'[';for(int c=0;c<sqlite3_column_count(statement);++c){if(c)output<<',';switch(sqlite3_column_type(statement,c)){case SQLITE_NULL:output<<"null";break;case SQLITE_INTEGER:output<<sqlite3_column_int64(statement,c);break;case SQLITE_FLOAT:output<<sqlite3_column_double(statement,c);break;case SQLITE_BLOB:{const auto p=static_cast<const unsigned char*>(sqlite3_column_blob(statement,c));output<<"{\"blob_hex\":\"";for(int i=0;i<sqlite3_column_bytes(statement,c);++i)output<<std::hex<<std::setw(2)<<std::setfill('0')<<unsigned(p[i]);output<<std::dec<<"\"}";break;}default:{auto p=reinterpret_cast<const char*>(sqlite3_column_text(statement,c));output<<quoted(std::string(p,sqlite3_column_bytes(statement,c)));break;}}}output<<']';}
    check(code==SQLITE_DONE,sqlite3_errmsg(db));char* contextStats=ysp_context_vfs_stats_json(db);output<<"],\"geometry_io_stats\":"<<stats(geo.get())<<",\"context_io_stats\":"<<(contextStats?contextStats:"null")<<"}";ysp_packed_free(contextStats);std::cout<<output.str()<<'\n';
}
}
int main(int argc,char** argv){
    try{
        check(argc>=3,"usage: packed-runtime-check geometry FILE ID | read FILE OFFSET BYTES | scan FILE | query CONTEXT GEOMETRY SQL");
        const std::string operation=argv[1];
        if(operation=="geometry"){
            check(argc>=4,"missing geometry source ID");auto geo=geometry(argv[2]);char error[512]{};auto value=ysp_geometry_json(geo.get(),argv[3],error,sizeof error);check(value,error);std::cout<<value<<'\n';ysp_packed_free(value);
        }else if(operation=="read"){
            check(argc>=5,"missing read range");auto image=context(argv[2]);const auto offset=std::stoull(argv[3]);const auto count=std::stoull(argv[4]);check(count<=1024*1024,"read inspection limited to 1 MiB");std::vector<unsigned char> bytes(count);char error[512]{};const auto size=ysp_context_read(image.get(),offset,bytes.data(),bytes.size(),error,sizeof error);check(size>=0,error);std::cout<<"{\"bytes\":"<<size<<",\"hex\":\"";for(int64_t i=0;i<size;++i)std::cout<<std::hex<<std::setw(2)<<std::setfill('0')<<unsigned(bytes[i]);std::cout<<std::dec<<"\",\"io_stats\":"<<stats(image.get())<<"}\n";
        }else if(operation=="scan"){
            auto image=context(argv[2]);uint64_t offset=0;uint32_t crc=0;std::vector<unsigned char> bytes(262144+31);char error[512]{};for(;;){const auto count=ysp_context_read(image.get(),offset,bytes.data(),bytes.size(),error,sizeof error);check(count>=0,error);if(!count)break;crc=crc32(crc,bytes.data(),static_cast<uInt>(count));offset+=count;}std::cout<<"{\"bytes\":"<<offset<<",\"crc32\":"<<crc<<",\"io_stats\":"<<stats(image.get())<<"}\n";
        }else if(operation=="query"){
            check(argc>=5,"missing context/geometry/SQL");query(argv[2],argv[3],argv[4]);
        }else throw std::runtime_error("unknown check operation");
        return 0;
    }catch(const std::exception& error){std::cout<<"{\"error\":"<<quoted(error.what())<<"}\n";return 1;}
}
