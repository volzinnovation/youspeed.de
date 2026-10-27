#include "packed_benchmark.h"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
int main(int argc,char** argv){if(argc<5){std::cerr<<"packed-runtime-bench MODE DATABASE GEOMETRY_OR_DASH QUERIES.csv [REPS]\n";return 2;}std::ifstream source(argv[4]);if(!source)return 2;std::ostringstream csv;csv<<source.rdbuf();char* report=ysp_storage_benchmark_json(argv[1],argv[2],argv[3],csv.str().c_str(),argc>5?std::atoi(argv[5]):3,64*1024*1024);if(!report)return 3;std::cout<<report<<'\n';const bool passed=std::string(report).find("\"overall_success\":true")!=std::string::npos;ysp_storage_benchmark_free(report);return passed?0:1;}
