function payload() {
  return {version: 1, meta: {scope: 'maximum_speed_and_zone_start', totalSourceFits: 48,
    lifecycleCheckedAt: '2026-10-09T10:00:00Z', availableUntil: '2099-10-09T11:00:00Z'},
    roadClasses: ['primary'], roads: [['bw:9007199254740993', 0, 'Straße', 'B 1', [8000000, 48000000, 100, 100]]],
    cases: [{label: '18', category: 'covered', point: [8, 48], region: [[7.999, 47.999], [8.001, 47.999], [8, 48.001]],
      clipped: true, bounded: false, prediction: 'Maximum speed 70 km/h', country: 'DE', time: '2026-10-09T10:00:00Z',
      source: 'bw', roadIds: [0], nearestRoad: 0, roadDistance: 5, portals: [],
      speedLimit: {family: 'maximum_speed', value: 70, unit: 'km/h'},
      captures: [0, 1].map(i => ({point: [8 + i / 10000, 48], end: [8, 48.004], bearing: 0, bound: 8, error: 20,
        time: '2026-10-09T10:00:0' + i + 'Z', interpolated: true})),
      scenarios: [{fov: 60, yaw: 0, status: 'estimated', point: [8, 48]}, {fov: 45, yaw: -15, status: 'degenerate', point: null}]}]};
}
module.exports = {payload};
