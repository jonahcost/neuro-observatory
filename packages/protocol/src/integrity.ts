import type { EegBlock, StreamMetadata } from './generated/eeg-stream.v2';

export type MetadataVerdict = 'new-stream' | 'same-stream';
export type BlockVerdict = 'accepted' | 'duplicate' | 'out-of-order' | 'unknown-stream';

export interface IntegrityCounters {
  /** Distinct streams announced by metadata. */
  streamsStarted: number;
  blocksAccepted: number;
  /** Samples per channel accepted. */
  samplesAccepted: number;
  /** Device gaps declared by the engine via droppedSamplesBefore. */
  acquisitionGapSamples: number;
  /** Blocks missing between accepted blocks (blockSequence jumps). */
  transportDroppedBlocks: number;
  /** Samples missing across transport drops (may include gaps declared inside the dropped blocks). */
  transportGapSamples: number;
  /** Accepted blocks whose index jump is not explained by declared gaps or transport drops. */
  inconsistentBlocks: number;
  duplicateBlocks: number;
  outOfOrderBlocks: number;
  /** Blocks whose streamId does not match the active metadata. */
  unknownStreamBlocks: number;
}

export function emptyIntegrityCounters(): IntegrityCounters {
  return {
    streamsStarted: 0,
    blocksAccepted: 0,
    samplesAccepted: 0,
    acquisitionGapSamples: 0,
    transportDroppedBlocks: 0,
    transportGapSamples: 0,
    inconsistentBlocks: 0,
    duplicateBlocks: 0,
    outOfOrderBlocks: 0,
    unknownStreamBlocks: 0,
  };
}

/**
 * Consumer-side sample-integrity tracking for one connection.
 * Mirrored by `neuro_engine.protocol.integrity`; both run the shared fixtures
 * in `packages/protocol/fixtures/v2/integrity`.
 */
export class StreamIntegrityTracker {
  private streamId: string | null = null;
  private nextBlockSequence: number | null = null;
  private nextSampleIndex: number | null = null;
  private readonly counters = emptyIntegrityCounters();

  get activeStreamId(): string | null {
    return this.streamId;
  }

  onMetadata(metadata: StreamMetadata): MetadataVerdict {
    if (metadata.streamId === this.streamId) {
      return 'same-stream';
    }
    this.streamId = metadata.streamId;
    this.nextBlockSequence = null;
    this.nextSampleIndex = null;
    this.counters.streamsStarted += 1;
    return 'new-stream';
  }

  onBlock(block: EegBlock): BlockVerdict {
    const c = this.counters;
    if (this.streamId === null || block.streamId !== this.streamId) {
      c.unknownStreamBlocks += 1;
      return 'unknown-stream';
    }
    if (this.nextBlockSequence !== null && this.nextSampleIndex !== null) {
      if (block.blockSequence < this.nextBlockSequence) {
        if (block.blockSequence === this.nextBlockSequence - 1) {
          c.duplicateBlocks += 1;
          return 'duplicate';
        }
        c.outOfOrderBlocks += 1;
        return 'out-of-order';
      }
      if (block.firstSampleIndex < this.nextSampleIndex) {
        c.outOfOrderBlocks += 1;
        return 'out-of-order';
      }
      const missingSamples = block.firstSampleIndex - this.nextSampleIndex;
      const skippedBlocks = block.blockSequence - this.nextBlockSequence;
      if (skippedBlocks > 0) {
        c.transportDroppedBlocks += skippedBlocks;
        c.transportGapSamples += Math.max(0, missingSamples - block.droppedSamplesBefore);
        if (missingSamples < block.droppedSamplesBefore) {
          c.inconsistentBlocks += 1;
        }
      } else if (missingSamples !== block.droppedSamplesBefore) {
        c.inconsistentBlocks += 1;
      }
    }
    c.blocksAccepted += 1;
    c.samplesAccepted += block.sampleCount;
    c.acquisitionGapSamples += block.droppedSamplesBefore;
    this.nextBlockSequence = block.blockSequence + 1;
    this.nextSampleIndex = block.firstSampleIndex + block.sampleCount;
    return 'accepted';
  }

  snapshot(): IntegrityCounters {
    return { ...this.counters };
  }
}

/** Nominal acquisition time (engine-monotonic µs) of sample `i` within a block. */
export function sampleTimeUs(block: EegBlock, metadata: StreamMetadata, i: number): number {
  return block.firstSampleTimeUs + (i * 1_000_000) / metadata.nominalSampleRateHz;
}
