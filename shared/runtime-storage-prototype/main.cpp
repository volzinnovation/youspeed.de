#include "runtime_storage.h"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
int main(int argc, char** argv) {
    if(argc < 5) { std::cerr << "rsbench benchmark KIND PATH QUERIES.csv [REPS]\nrsbench dump KIND PATH QUERIES.csv\nrsbench query KIND PATH LAT LON RADIUS\nrsbench way KIND PATH WAY_ID\n"; return 2; }
    char* result=nullptr;
    if(std::string(argv[1])=="benchmark" || std::string(argv[1])=="dump") {
        std::ifstream file(argv[4]); if(!file) return 2;
        std::ostringstream csv; csv << file.rdbuf();
        result=std::string(argv[1])=="dump" ? storage_query_batch_json(argv[2],argv[3],csv.str().c_str()) : storage_benchmark_json(argv[2],argv[3],csv.str().c_str(),argc>5?std::atoi(argv[5]):3);
    } else if(std::string(argv[1])=="query" && argc>=7) {
        result=storage_query_json(argv[2],argv[3],std::stod(argv[4]),std::stod(argv[5]),std::stod(argv[6]));
    } else if(std::string(argv[1])=="way") {
        result=storage_way_json(argv[2],argv[3],std::stoll(argv[4]));
    } else return 2;
    if(!result) return 3;
    std::cout << result << '\n'; bool failed=std::string(result).find("\"error\":")!=std::string::npos;
    storage_free(result); return failed?1:0;
}
