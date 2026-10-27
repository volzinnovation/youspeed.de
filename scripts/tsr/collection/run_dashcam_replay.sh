#!/bin/sh
set -eu
if [ "$#" -lt 3 ]; then
  echo "Usage: run_dashcam_replay.sh VIDEO MODEL_PACK OUTPUT [INTERVAL [START [END]]]" >&2
  exit 2
fi
replay_repo_root="$(cd "$(dirname "$0")/../../.." && pwd)"
replay_output="$3"
mkdir -p "$replay_output"
swiftc -module-cache-path "$replay_output/swift-module-cache" \
  "$replay_repo_root/iphone/SpeedConsumerApp/SignCollectionContract.swift" \
  "$replay_repo_root/iphone/SpeedConsumerApp/SignCollectionSchema.swift" \
  "$replay_repo_root/iphone/SpeedConsumerApp/SignCollectionStore.swift" \
  "$replay_repo_root/iphone/SpeedConsumerApp/SignCollectionTransport.swift" \
  "$replay_repo_root/iphone/SpeedConsumerApp/SignCollectionCrop.swift" \
  "$replay_repo_root/iphone/SpeedConsumerApp/SignCollectionPhoneRoadMatch.swift" \
  "$replay_repo_root/iphone/SpeedConsumerApp/SignCollectionObserver.swift" \
  "$replay_repo_root/scripts/tsr/collection/replay_dashcam.swift" \
  -o "$replay_output/replay-dashcam"
"$replay_output/replay-dashcam" "$@"
