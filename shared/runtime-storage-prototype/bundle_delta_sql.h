#ifndef YSP_BUNDLE_DELTA_SQL_H
#define YSP_BUNDLE_DELTA_SQL_H
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif
/* Publisher SQL is confined to a staged legacy map database. The same engine
 * authorizer is used by iPhone's SQLite and Android's private SQLite engine. */
int ysp_apply_bundle_delta(const char* database_path, const char* sql, size_t sql_bytes,
                           char* error, size_t error_size);
#ifdef __cplusplus
}
#endif

#ifdef YSP_BUNDLE_DELTA_SQL_IMPLEMENTATION
#include <sqlite3.h>
#include <algorithm>
#include <cctype>
#include <cstring>
#include <set>
#include <string>
#include <vector>

namespace ysp_bundle_delta {
static std::string lower(const char* value) {
    std::string result=value?value:"";
    for(char& c:result)if(c>='A'&&c<='Z')c=static_cast<char>(c-'A'+'a');
    return result;
}
static const std::set<std::string>& tables() {
    // Keep aligned with build_v3_delta_pack.py and v3_context_delta.py. Schema
    // and conditional/upcoming-path capability changes require full bundles.
    static const std::set<std::string> value={
        "ways","way_geom","ways_rtree","areas","areas_rtree","metadata",
        "city_boundary","city_boundary_rtree","city_ring","city_tile","city_place","city_place_rtree",
        "settlement_area","settlement_ring","settlement_sign","settlement_segment",
        "way_links","way_endpoints","way_tile","surface_way_network","surface_way_network_rtree",
        "tunnel_way_network","tunnel_way_network_rtree","motorway_way_network","motorway_way_network_rtree",
        "way_continuity_group","way_continuity_membership","corridor_progress","corridor_pairs"
    };
    return value;
}
static bool rtreeName(const std::string& name) {
    static const std::set<std::string> names={"ways_rtree","areas_rtree","city_boundary_rtree","city_place_rtree",
        "surface_way_network_rtree","tunnel_way_network_rtree","motorway_way_network_rtree"};
    return names.count(name)!=0;
}
struct Policy { std::set<std::string> shadows; };
static void message(char* error,size_t size,const char* text) {
    if(error&&size){const auto count=std::min(size-1,std::strlen(text));std::memcpy(error,text,count);error[count]=0;}
}

/* Only inspect the schema prefix. This is not the SQL sandbox: SQLite's
 * authorizer below checks every operation prepared/executed by publisher SQL.
 * Tokenizing also handles comments and quoted names in existing schema text. */
static std::vector<std::string> schemaPrefix(const char* raw) {
    std::vector<std::string> tokens;const char* p=raw?raw:"";
    while(*p&&tokens.size()<10){
        if(std::isspace(static_cast<unsigned char>(*p))){++p;continue;}
        if(p[0]=='-'&&p[1]=='-'){while(*p&&*p!='\n')++p;continue;}
        if(p[0]=='/'&&p[1]=='*'){p+=2;while(*p&&!(p[0]=='*'&&p[1]=='/'))++p;if(*p)p+=2;continue;}
        std::string token;
        if(*p=='\''||*p=='"'||*p=='`'||*p=='['){
            const char end=*p=='['?']':*p;++p;
            while(*p){if(*p==end){++p;if(end!=']'&&*p==end){token+=*p++;continue;}break;}token+=*p++;}
        }else if(std::isalnum(static_cast<unsigned char>(*p))||*p=='_'){
            while(std::isalnum(static_cast<unsigned char>(*p))||*p=='_')token+=*p++;
        }else token+=*p++;
        tokens.push_back(lower(token.c_str()));
    }
    return tokens;
}
static int inspectSchema(sqlite3* db,Policy& policy) {
    sqlite3_stmt* statement=nullptr;
    int code=sqlite3_prepare_v2(db,"SELECT type,name,sql FROM main.sqlite_master",-1,&statement,nullptr);
    if(code!=SQLITE_OK)return code;
    while((code=sqlite3_step(statement))==SQLITE_ROW){
        const auto type=lower(reinterpret_cast<const char*>(sqlite3_column_text(statement,0)));
        const auto name=lower(reinterpret_cast<const char*>(sqlite3_column_text(statement,1)));
        // Stored triggers/views may be unrelated to patched map tables. They
        // remain inert here; any attempted use is denied by origin below.
        if(type!="table")continue;
        const auto tokens=schemaPrefix(reinterpret_cast<const char*>(sqlite3_column_text(statement,2)));
        if(tokens.size()<2||tokens[0]!="create"){code=SQLITE_AUTH;break;}
        if(tokens[1]=="table")continue;
        size_t nameIndex=3;
        if(tokens.size()>5&&tokens[3]=="if"&&tokens[4]=="not"&&tokens[5]=="exists")nameIndex=6;
        if(tokens[1]!="virtual"||tokens.size()<=nameIndex+3||tokens[2]!="table"||tokens[nameIndex]!=name||
           tokens[nameIndex+1]!="using"||(tokens[nameIndex+2]!="rtree"&&tokens[nameIndex+2]!="rtree_i32")||
           tokens[nameIndex+3]!="("||!rtreeName(name)){code=SQLITE_AUTH;break;}
        for(const auto* suffix:{"_node","_parent","_rowid"})policy.shadows.insert(name+suffix);
    }
    sqlite3_finalize(statement);
    return code==SQLITE_DONE?SQLITE_OK:code;
}
static int authorize(void* context,int action,const char* first,const char* second,const char* database,const char* origin) {
    // Views/triggers may hide reads, writes or functions behind allowed names.
    if(origin&&*origin)return SQLITE_DENY;
    const auto& policy=*static_cast<Policy*>(context);
    switch(action){
        case SQLITE_SELECT:return SQLITE_OK; // RTree's own shadow queries also SELECT.
        case SQLITE_READ:
        case SQLITE_INSERT:
        case SQLITE_UPDATE:
        case SQLITE_DELETE:{
            if(!database||std::strcmp(database,"main")!=0)return SQLITE_DENY;
            const auto name=lower(first);
            if(tables().count(name)||policy.shadows.count(name))return SQLITE_OK;
            if(action==SQLITE_READ&&(name=="sqlite_master"||name=="sqlite_schema"))return SQLITE_OK;
            return SQLITE_DENY;
        }
        case SQLITE_TRANSACTION:{
            const auto operation=lower(first);
            return operation=="begin"||operation=="commit"||operation=="rollback"?SQLITE_OK:SQLITE_DENY;
        }
        case SQLITE_PRAGMA:
            return lower(first)=="foreign_keys"&&(lower(second)=="off"||lower(second)=="0")?SQLITE_OK:SQLITE_DENY;
        case SQLITE_FUNCTION:
            // A freshly opened RTree inspects node blobs with length(). This
            // pure built-in has no filesystem/connection capabilities.
            return lower(second)=="length"?SQLITE_OK:SQLITE_DENY;
        // Includes ATTACH/DETACH, all DDL and TEMP objects, functions,
        // writable_schema, VACUUM's attachment, and future engine operations.
        default:return SQLITE_DENY;
    }
}
}

extern "C" int ysp_apply_bundle_delta(const char* path,const char* sql,size_t bytes,char* error,size_t errorSize) {
    using namespace ysp_bundle_delta;
    if(error&&errorSize)error[0]=0;
    if(!path||!*path||!sql||std::memchr(sql,0,bytes)){
        message(error,errorSize,"Invalid delta path or embedded NUL in SQL");return SQLITE_MISUSE;
    }
    sqlite3* db=nullptr;
    int code=sqlite3_open_v2(path,&db,SQLITE_OPEN_READWRITE|SQLITE_OPEN_FULLMUTEX,nullptr);
    if(code!=SQLITE_OK){message(error,errorSize,db?sqlite3_errmsg(db):"Cannot open staged delta database");if(db)sqlite3_close(db);return code;}
    sqlite3_limit(db,SQLITE_LIMIT_ATTACHED,0);
#ifdef SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION
    sqlite3_db_config(db,SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION,0,nullptr);
#endif
#ifdef SQLITE_DBCONFIG_DEFENSIVE
    sqlite3_db_config(db,SQLITE_DBCONFIG_DEFENSIVE,1,nullptr);
#endif
#ifdef SQLITE_DBCONFIG_TRUSTED_SCHEMA
    sqlite3_db_config(db,SQLITE_DBCONFIG_TRUSTED_SCHEMA,0,nullptr);
#endif
    Policy policy;
    code=inspectSchema(db,policy);
    if(code==SQLITE_OK)code=sqlite3_set_authorizer(db,authorize,&policy);
    if(code==SQLITE_OK){
        const std::string source(sql,bytes);
        code=sqlite3_exec(db,source.c_str(),nullptr,nullptr,nullptr);
        if(code==SQLITE_OK&&!sqlite3_get_autocommit(db)){code=SQLITE_AUTH;message(error,errorSize,"Delta left an open transaction");}
        // Keep authorization installed through execution and checkpointing.
        // This engine API cannot introduce a publisher-selected pragma/path.
        if(code==SQLITE_OK)code=sqlite3_wal_checkpoint_v2(db,"main",SQLITE_CHECKPOINT_TRUNCATE,nullptr,nullptr);
    }else message(error,errorSize,"Delta database contains unsupported schema objects");
    if(code!=SQLITE_OK&&error&&errorSize&&!error[0])message(error,errorSize,sqlite3_errmsg(db));
    const int closed=sqlite3_close(db);
    if(code==SQLITE_OK&&closed!=SQLITE_OK){message(error,errorSize,"Cannot close delta database");code=closed;}
    return code;
}
#endif
#endif
