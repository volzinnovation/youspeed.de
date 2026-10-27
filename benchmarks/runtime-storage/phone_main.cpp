#include "runtime_storage.h"
#include <fstream>
#include <iostream>
#include <sstream>
#include <cstdlib>
#include <sqlite3.h>

extern "C" const char* ysp_corrections_selftest_json();
extern "C" const char* ysp_corrections_persistence_selftest_json(const char*);
extern "C" const char* ysp_corrections_source_node_probe_json(const char*,const char*);
extern "C" char* storage_nodes_benchmark_json(const char*,const char*,const char*,int);
extern "C" char* storage_node_json(const char*,const char*,long long);
extern "C" void storage_nodes_free(void*);

static std::string readFile(const char* path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error(std::string("Cannot open corpus: ")+path);
    std::ostringstream text; text << input.rdbuf(); return text.str();
}

static bool validate(const char* json,const char* predicate) {
    if (!json) return false;
    sqlite3* db=nullptr;sqlite3_stmt* statement=nullptr;bool ok=false;
    if (sqlite3_open(":memory:",&db)==SQLITE_OK) {
        std::string sql="SELECT json_valid(?1) AND ("+std::string(predicate)+")";
        if(sqlite3_prepare_v2(db,sql.c_str(),-1,&statement,nullptr)==SQLITE_OK) {
            sqlite3_bind_text(statement,1,json,-1,SQLITE_TRANSIENT);
            ok=sqlite3_step(statement)==SQLITE_ROW&&sqlite3_column_int(statement,0)==1;
        }
    }
    sqlite3_finalize(statement);sqlite3_close(db);return ok;
}

int main(int argc,char** argv) {
    if (argc==5 && std::string(argv[1])=="--road-parity") {
        try {
            const auto csv=readFile(argv[4]);
            char* result=storage_query_batch_json(argv[2],argv[3],csv.c_str());
            const bool passed=validate(result,"json_type(?1)='array' AND json_array_length(?1)>0");
            std::cout << (result?result:"null") << '\n';
            storage_free(result);return passed?0:1;
        } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 3;}
    }
    if (argc!=8) {
        std::cerr << "storage_phone_runner KIND ROAD_PATH ROAD_QUERIES NODE_PATH NODE_QUERIES REPS SCRATCH_JOURNAL\n";
        return 2;
    }
    try {
        const auto roadCSV=readFile(argv[3]),nodeCSV=readFile(argv[5]);
        const int repetitions=std::atoi(argv[6]);
        char* road=storage_benchmark_json(argv[1],argv[2],roadCSV.c_str(),repetitions);
        char* nodes=storage_nodes_benchmark_json(argv[1],argv[4],nodeCSV.c_str(),repetitions);
        const char* overlay=ysp_corrections_selftest_json();
        const char* persistence=ysp_corrections_persistence_selftest_json(argv[7]);
        char* source=storage_node_json(argv[1],argv[4],2532969814LL);
        const auto sourceJournal=std::string(argv[7])+".source-node";
        const char* amendment=ysp_corrections_source_node_probe_json(source,sourceJournal.c_str());
        const bool passed=validate(road,"json_extract(?1,'$.error') IS NULL AND json_extract(?1,'$.query_count')>0")
            &&validate(nodes,"json_extract(?1,'$.error') IS NULL AND json_extract(?1,'$.query_count')>0")
            &&validate(overlay,"json_extract(?1,'$.failed')=0 AND json_extract(?1,'$.tests')>0")
            &&validate(persistence,"json_extract(?1,'$.created_reopened')=1 AND json_extract(?1,'$.amended_reopened')=1 AND json_extract(?1,'$.tombstoned_reopened')=1 AND json_extract(?1,'$.history_preserved')=1")
            &&validate(amendment,"json_extract(?1,'$.error')='' AND json_extract(?1,'$.failed')=0 AND json_extract(?1,'$.tests')>0");
        std::cout << "{\"storage\":" << (road?road:"null")
                  << ",\"generic_speed_nodes\":" << (nodes?nodes:"null")
                  << ",\"correction_overlay_selftest\":" << (overlay?overlay:"null")
                  << ",\"correction_persistence_selftest\":" << (persistence?persistence:"null")
                  << ",\"source_amendment_probe\":" << (amendment?amendment:"null")
                  << ",\"overall_success\":" << (passed?"true":"false")
#ifdef __ANDROID__
                  << ",\"platform\":\"Android native isolated benchmark\""
#else
                  << ",\"platform\":\"Host native benchmark\""
#endif
                  << "}\n";
        storage_free(road);storage_nodes_free(nodes);storage_nodes_free(source);
        return passed?0:1;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';return 3;
    }
}
