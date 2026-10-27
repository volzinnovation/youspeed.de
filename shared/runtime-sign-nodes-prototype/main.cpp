#include "runtime_sign_nodes.h"
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
int main(int argc,char** argv){
    if(argc<4){std::cerr<<"nodebench benchmark KIND PATH QUERIES.csv [REPETITIONS]\nnodebench roundtrip KIND PATH\nnodebench node KIND PATH NODE_ID\nnodebench query KIND PATH LAT LON RADIUS\n";return 2;}
    char* result=nullptr;std::string command=argv[1];
    if(command=="benchmark"&&argc>=5){std::ifstream file(argv[4]);if(!file)return 2;std::ostringstream csv;csv<<file.rdbuf();result=storage_nodes_benchmark_json(argv[2],argv[3],csv.str().c_str(),argc>5?std::atoi(argv[5]):3);}
    else if(command=="roundtrip")result=storage_nodes_roundtrip_json(argv[2],argv[3]);
    else if(command=="node"&&argc>=5)result=storage_node_json(argv[2],argv[3],std::stoll(argv[4]));
    else if(command=="query"&&argc>=7)result=storage_nodes_query_json(argv[2],argv[3],std::stod(argv[4]),std::stod(argv[5]),std::stod(argv[6]));
    else if(command=="compare"&&argc>=7){std::ifstream file(argv[6]);if(!file)return 2;std::ostringstream csv;csv<<file.rdbuf();result=storage_nodes_compare_json(argv[2],argv[3],argv[4],argv[5],csv.str().c_str());}
    else return 2;
    if(!result)return 3;std::string text=result;storage_nodes_free(result);std::cout<<text<<'\n';return text.find("\"error\":")==std::string::npos?0:1;
}
