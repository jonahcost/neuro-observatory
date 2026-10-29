export interface EEGFrame {
  schemaVersion: 1;
  deviceId: string;
  sequence: number;
  timestampMs: number;
  sampleRateHz: number;
  channelLabels: string[];
  samplesUv: number[][];
}

export interface DeviceStatus {
  deviceId: string;
  connected: boolean;
  channelCount: number;
  sampleRateHz: number;
}
