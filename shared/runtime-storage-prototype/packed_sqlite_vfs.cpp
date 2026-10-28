#include "packed_runtime.h"
#define YSP_BUNDLE_DELTA_SQL_IMPLEMENTATION
#include "bundle_delta_sql.h"
#include <sqlite3.h>
#include <algorithm>
#include <cstring>
#include <limits>
#include <mutex>

namespace {
constexpr const char* VFS_NAME="ysp-packed-v1";
constexpr int CONTEXT_STATS_CONTROL=0x59535001;
struct PackedFile {sqlite3_file base;void* context;};
sqlite3_vfs packedVfs{};
sqlite3_vfs* underlying=nullptr;
std::mutex registrationMutex;

PackedFile* packed(sqlite3_file* file){return reinterpret_cast<PackedFile*>(file);}
int closeFile(sqlite3_file* file){ysp_context_close(packed(file)->context);packed(file)->context=nullptr;file->pMethods=nullptr;return SQLITE_OK;}
int readFile(sqlite3_file* file,void* out,int bytes,sqlite3_int64 offset){
    if(bytes<0||offset<0)return SQLITE_IOERR_READ;
    char error[512]{};const auto read=ysp_context_read(packed(file)->context,static_cast<uint64_t>(offset),out,static_cast<size_t>(bytes),error,sizeof error);
    if(read<0){sqlite3_log(SQLITE_IOERR_READ,"Packed context read: %s",error);return SQLITE_IOERR_READ;}
    if(read<bytes){std::memset(static_cast<unsigned char*>(out)+read,0,static_cast<size_t>(bytes-read));return SQLITE_IOERR_SHORT_READ;}
    return SQLITE_OK;
}
int writeFile(sqlite3_file*,const void*,int,sqlite3_int64){return SQLITE_READONLY;}
int truncateFile(sqlite3_file*,sqlite3_int64){return SQLITE_READONLY;}
int syncFile(sqlite3_file*,int){return SQLITE_OK;}
int sizeFile(sqlite3_file* file,sqlite3_int64* size){const auto value=ysp_context_size(packed(file)->context);if(value>uint64_t(std::numeric_limits<sqlite3_int64>::max()))return SQLITE_IOERR_FSTAT;*size=static_cast<sqlite3_int64>(value);return SQLITE_OK;}
int lockFile(sqlite3_file*,int){return SQLITE_OK;}
int unlockFile(sqlite3_file*,int){return SQLITE_OK;}
int reservedFile(sqlite3_file*,int* locked){*locked=0;return SQLITE_OK;}
int controlFile(sqlite3_file* file,int operation,void* argument){
    if(operation==CONTEXT_STATS_CONTROL){if(!argument)return SQLITE_MISUSE;auto output=static_cast<char**>(argument);*output=ysp_context_stats_json(packed(file)->context);return *output?SQLITE_OK:SQLITE_NOMEM;}
    if(operation==SQLITE_FCNTL_MMAP_SIZE){if(argument)*static_cast<sqlite3_int64*>(argument)=0;return SQLITE_OK;}
    if(operation==SQLITE_FCNTL_VFSNAME){if(argument){auto output=static_cast<char**>(argument);*output=sqlite3_mprintf("%s",VFS_NAME);if(!*output)return SQLITE_NOMEM;}return SQLITE_OK;}
    if(operation==SQLITE_FCNTL_SIZE_HINT)return SQLITE_OK;
    return SQLITE_NOTFOUND;
}
int sectorSize(sqlite3_file*){return 4096;}
int capabilities(sqlite3_file*){return SQLITE_IOCAP_IMMUTABLE;}
const sqlite3_io_methods packedMethods={1,closeFile,readFile,writeFile,truncateFile,syncFile,sizeFile,lockFile,unlockFile,reservedFile,controlFile,sectorSize,capabilities,nullptr,nullptr,nullptr,nullptr,nullptr,nullptr};

int openFile(sqlite3_vfs*,const char* name,sqlite3_file* file,int flags,int* outFlags){
    if(!(flags&SQLITE_OPEN_MAIN_DB))return underlying->xOpen(underlying,name,file,flags,outFlags);
    file->pMethods=nullptr;
    if(!name||(flags&SQLITE_OPEN_READWRITE)||(flags&SQLITE_OPEN_CREATE))return SQLITE_CANTOPEN;
    char error[512]{};void* context=ysp_context_open(name,0,error,sizeof error);
    if(!context){sqlite3_log(SQLITE_CANTOPEN,"Packed context open: %s",error);return SQLITE_CANTOPEN;}
    auto result=packed(file);result->context=context;result->base.pMethods=&packedMethods;
    if(outFlags)*outFlags=SQLITE_OPEN_READONLY;return SQLITE_OK;
}
int deleteFile(sqlite3_vfs*,const char* name,int sync){return underlying->xDelete(underlying,name,sync);}
int accessFile(sqlite3_vfs*,const char* name,int flags,int* result){return underlying->xAccess(underlying,name,flags,result);}
int fullPath(sqlite3_vfs*,const char* name,int size,char* output){return underlying->xFullPathname(underlying,name,size,output);}
void* openLibrary(sqlite3_vfs*,const char* path){return underlying->xDlOpen?underlying->xDlOpen(underlying,path):nullptr;}
void libraryError(sqlite3_vfs*,int size,char* error){if(underlying->xDlError)underlying->xDlError(underlying,size,error);else if(size)error[0]=0;}
void (*librarySymbol(sqlite3_vfs*,void* library,const char* symbol))(void){return underlying->xDlSym?underlying->xDlSym(underlying,library,symbol):nullptr;}
void closeLibrary(sqlite3_vfs*,void* library){if(underlying->xDlClose)underlying->xDlClose(underlying,library);}
int randomBytes(sqlite3_vfs*,int size,char* output){return underlying->xRandomness(underlying,size,output);}
int sleepTime(sqlite3_vfs*,int micros){return underlying->xSleep(underlying,micros);}
int currentTime(sqlite3_vfs*,double* result){return underlying->xCurrentTime(underlying,result);}
int lastError(sqlite3_vfs*,int size,char* output){return underlying->xGetLastError?underlying->xGetLastError(underlying,size,output):0;}
int currentTime64(sqlite3_vfs*,sqlite3_int64* result){if(underlying->iVersion>=2&&underlying->xCurrentTimeInt64)return underlying->xCurrentTimeInt64(underlying,result);double day=0;const int code=underlying->xCurrentTime(underlying,&day);*result=static_cast<sqlite3_int64>(day*86400000.0);return code;}
}

extern "C" int ysp_register_context_vfs(void){
    std::lock_guard<std::mutex> lock(registrationMutex);
    const int initialized=sqlite3_initialize();if(initialized!=SQLITE_OK)return initialized;
    if(sqlite3_vfs_find(VFS_NAME))return SQLITE_OK;
    underlying=sqlite3_vfs_find(nullptr);if(!underlying)return SQLITE_NOTFOUND;
    packedVfs.iVersion=2;packedVfs.szOsFile=std::max<int>(static_cast<int>(sizeof(PackedFile)),underlying->szOsFile);
    packedVfs.mxPathname=underlying->mxPathname;packedVfs.zName=VFS_NAME;packedVfs.pAppData=underlying;
    packedVfs.xOpen=openFile;packedVfs.xDelete=deleteFile;packedVfs.xAccess=accessFile;packedVfs.xFullPathname=fullPath;
    packedVfs.xDlOpen=openLibrary;packedVfs.xDlError=libraryError;packedVfs.xDlSym=librarySymbol;packedVfs.xDlClose=closeLibrary;
    packedVfs.xRandomness=randomBytes;packedVfs.xSleep=sleepTime;packedVfs.xCurrentTime=currentTime;packedVfs.xGetLastError=lastError;packedVfs.xCurrentTimeInt64=currentTime64;
    return sqlite3_vfs_register(&packedVfs,0);
}

extern "C" char* ysp_context_vfs_stats_json(void* database){
    if(!database)return nullptr;
    char* result=nullptr;
    if(sqlite3_file_control(static_cast<sqlite3*>(database),"main",CONTEXT_STATS_CONTROL,&result)!=SQLITE_OK){ysp_packed_free(result);return nullptr;}
    return result;
}
