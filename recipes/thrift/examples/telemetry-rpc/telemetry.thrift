namespace py telemetry

struct Reading {
  1: string sensor
  2: i64 taken_at_ms
  3: double celsius
  4: list<double> samples
  5: map<string, string> tags
}

struct Summary {
  1: i32 count
  2: double mean_celsius
  3: double max_celsius
  4: string warmest_sensor
}

exception InvalidReading {
  1: string sensor
  2: string reason
}

service Telemetry {
  Summary submit(1: list<Reading> readings) throws (1: InvalidReading invalid)
}
