#!/bin/sh
set -eu
collection_repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
collection_output_root="${1:-${TMPDIR:-/tmp}/youspeed-collection-results}"
mkdir -p "$collection_output_root"
swiftc -module-cache-path "$collection_output_root/swift-module-cache" \
  "$collection_repo_root/iphone/SpeedConsumerApp/SignCollectionContract.swift" \
  "$collection_repo_root/iphone/SpeedConsumerApp/SignCollectionSchema.swift" \
  "$collection_repo_root/iphone/SpeedConsumerApp/SignCollectionStore.swift" \
  "$collection_repo_root/iphone/SpeedConsumerApp/SignCollectionCrop.swift" \
  "$collection_repo_root/iphone/SpeedConsumerApp/SignCollectionPhoneRoadMatch.swift" \
  "$collection_repo_root/iphone/SpeedConsumerApp/SignCollectionTransport.swift" \
  "$collection_repo_root/iphone/SpeedConsumerApp/SignCollectionObserver.swift" \
  "$collection_repo_root/scripts/tsr/collection/transport_checks.swift" \
  "$collection_repo_root/scripts/tsr/collection/repeat_crop_checks.swift" \
  "$collection_repo_root/scripts/tsr/collection/phone_road_match_checks.swift" \
  "$collection_repo_root/scripts/tsr/collection/main.swift" \
  -o "$collection_output_root/swift-checks"
"$collection_output_root/swift-checks" "$collection_repo_root/shared/tsr/collection-contract-v1" "$collection_output_root" "${2:-}"
