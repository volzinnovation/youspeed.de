// Read-only Inspector bridge over the exact production app VFS/geometry reader.
#include "../shared/runtime-storage-prototype/packed_runtime.h"
#include <sqlite3.h>
#include <cstring>
#include <cctype>
#include <cstdlib>
#include <sstream>
#include <iomanip>
#include <string>
#include <stdexcept>

struct InspectorBundle { sqlite3* db=nullptr; void* geometry=nullptr; };
static void err(char* out, size_t n, const char* value) { if(out&&n){std::strncpy(out,value,n-1);out[n-1]=0;} }
static std::string quote(const unsigned char* p) {
  if(!p)return "null"; std::ostringstream s;s<<'"';
  for(;*p;++p){unsigned char c=*p;switch(c){case '"':s<<"\\\"";break;case '\\':s<<"\\\\";break;case '\n':s<<"\\n";break;case '\r':s<<"\\r";break;case '\t':s<<"\\t";break;default:if(c<32)s<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;else s<<char(c);}}
  s<<'"';return s.str();
}
static void points(sqlite3_context* c,int n,sqlite3_value** v){
  auto b=static_cast<InspectorBundle*>(sqlite3_user_data(c));
  if(n!=1||!b->geometry){sqlite3_result_error(c,"geometry unavailable",-1);return;}
  char error[512]{};char* result=ysp_geometry_json(b->geometry,reinterpret_cast<const char*>(sqlite3_value_text(v[0])),error,sizeof error);
  if(!result){sqlite3_result_error(c,"geometry read failed",-1);return;}
  sqlite3_result_text(c,result,-1,SQLITE_TRANSIENT);ysp_packed_free(result);
}
extern "C" void* inspector_bundle_open(const char* path,const char* geometry,int packed,char* error,size_t size){
  auto b=new InspectorBundle();
  try{
    if(packed&&ysp_register_context_vfs()!=SQLITE_OK)throw std::runtime_error("VFS initialization failed");
    if(geometry&&*geometry){b->geometry=ysp_geometry_open(geometry,0,error,size);if(!b->geometry)throw std::runtime_error("geometry open failed");}
    if(sqlite3_open_v2(path,&b->db,SQLITE_OPEN_READONLY|SQLITE_OPEN_NOMUTEX,packed?"ysp-packed-v1":nullptr)!=SQLITE_OK)throw std::runtime_error("bundle open failed");
    if(b->geometry)sqlite3_create_function_v2(b->db,"ysp_way_points_json",1,SQLITE_UTF8|SQLITE_DETERMINISTIC,b,points,nullptr,nullptr,nullptr);
    sqlite3_exec(b->db,"PRAGMA query_only=ON; PRAGMA mmap_size=0; PRAGMA temp_store=MEMORY; PRAGMA cache_size=-1536;",nullptr,nullptr,nullptr);
    return b;
  }catch(const std::exception& e){err(error,size,e.what());if(b->db)sqlite3_close(b->db);if(b->geometry)ysp_geometry_close(b->geometry);delete b;return nullptr;}
}
extern "C" char* inspector_bundle_query(void* handle,const char* sql,char* error,size_t size){
  auto b=static_cast<InspectorBundle*>(handle);sqlite3_stmt* statement=nullptr;
  try{
    if(!b||!sql||std::strlen(sql)>32000)throw std::runtime_error("invalid bundle query");
    const char* tail=nullptr;
    if(sqlite3_prepare_v2(b->db,sql,-1,&statement,&tail)!=SQLITE_OK||!sqlite3_stmt_readonly(statement))throw std::runtime_error("bundle query failed");
    for(;tail&&*tail;++tail)if(!std::isspace(static_cast<unsigned char>(*tail)))throw std::runtime_error("multiple statements forbidden");
    int remaining=10000;sqlite3_progress_handler(b->db,10000,[](void* p)->int{return --*static_cast<int*>(p)<=0?1:0;},&remaining);
    std::ostringstream result;result<<'[';int rows=0,status=SQLITE_ROW;
    while((status=sqlite3_step(statement))==SQLITE_ROW){
      if(++rows>10000||result.tellp()>16*1024*1024)throw std::runtime_error("bundle query limit");
      if(rows>1)result<<',';result<<'{';
      for(int i=0;i<sqlite3_column_count(statement);++i){
        if(i)result<<',';result<<quote(reinterpret_cast<const unsigned char*>(sqlite3_column_name(statement,i)))<<':';
        switch(sqlite3_column_type(statement,i)){
          case SQLITE_NULL:result<<"null";break;
          case SQLITE_INTEGER:result<<sqlite3_column_int64(statement,i);break;
          case SQLITE_FLOAT:result<<std::setprecision(17)<<sqlite3_column_double(statement,i);break;
          case SQLITE_TEXT:result<<quote(sqlite3_column_text(statement,i));break;
          default:throw std::runtime_error("bundle blob query forbidden");
        }
      }result<<'}';
    }
    if(status!=SQLITE_DONE)throw std::runtime_error("bundle query incomplete");
    result<<']';sqlite3_finalize(statement);statement=nullptr;sqlite3_progress_handler(b->db,0,nullptr,nullptr);
    const auto text=result.str();auto out=static_cast<char*>(std::malloc(text.size()+1));if(!out)throw std::bad_alloc();std::memcpy(out,text.c_str(),text.size()+1);return out;
  }catch(const std::exception& e){if(statement)sqlite3_finalize(statement);if(b)sqlite3_progress_handler(b->db,0,nullptr,nullptr);err(error,size,e.what());return nullptr;}
}
extern "C" void inspector_bundle_close(void* handle){auto b=static_cast<InspectorBundle*>(handle);if(b){if(b->db)sqlite3_close(b->db);if(b->geometry)ysp_geometry_close(b->geometry);delete b;}}
extern "C" void inspector_bundle_free(void* value){std::free(value);}
