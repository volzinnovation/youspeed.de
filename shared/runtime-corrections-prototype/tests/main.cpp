#include "../runtime_corrections.hpp"
#include <cstdio>
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>

int main(int argc, char** argv) {
    std::string result = ysp_corrections_selftest_json();
    std::cout << result << '\n';
    if (result.find("\"failed\":0") == std::string::npos) return 1;
    if (argc > 1) {
        using namespace ysp::corrections;
        // Exercise actual filesystem persistence in the host/CLI harness.
        Record r; r.id = "persistence-test"; r.anchor.sourceID = 42; r.anchor.fingerprint = "fixture";
        r.rules.rawTags = {{"maxspeed", "30"}}; r.rules.clauses = {{Limit::numeric(30), {}}};
        r.provenance.originalBundle = "fixture"; r.provenance.basisBundle = "fixture"; r.provenance.author = "test";
        Overlay original, restored; std::string error;
        if (original.put(r, 0).status != WriteStatus::Written || !original.save(argv[1], error) || !Overlay::load(argv[1], restored, error) || original.encode() != restored.encode()) {
            std::cerr << "Filesystem roundtrip failed: " << error << '\n'; return 2;
        }
        std::cout << "{\"filesystem_roundtrip\":true,\"bytes\":" << restored.encode().size() << "}\n";
        std::string disk = ysp_corrections_persistence_selftest_json(argv[1]); std::cout << disk << '\n';
        if (disk.find("\"created_reopened\":true") == std::string::npos || disk.find("\"amended_reopened\":true") == std::string::npos || disk.find("\"tombstoned_reopened\":true") == std::string::npos || disk.find("\"history_preserved\":true") == std::string::npos) return 3;
        std::remove(argv[1]);
    }
    std::cout << ysp_corrections_dataset_probe_json(1234567890123LL, 9876543210123LL, "bw:test:one", 10000) << '\n';
    if (argc > 2) {
        std::ifstream input(argv[2]); std::ostringstream text; text << input.rdbuf(); if (!input) return 4;
        std::string path = std::string(argv[1]) + "-source";
        std::string probe = ysp_corrections_source_node_probe_json(text.str().c_str(), path.c_str()); std::cout << probe << '\n';
        if (probe.find("\"failed\":0") == std::string::npos) return 5;
        for (auto invalid : {"[]", "{}", "{\"osm_node_id\":1,\"osm_node_id\":2}", "{\"a\":[[[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]]}"}) {
            std::string rejected = ysp_corrections_source_node_probe_json(invalid, path.c_str());
            if (rejected.find("\"failed\":1") == std::string::npos || rejected.find("\"error\":") == std::string::npos) return 6;
        }
        std::remove(path.c_str());
    }
    return 0;
}
