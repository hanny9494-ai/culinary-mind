/**
 * ResourceLock — SQLite-based concurrency control
 *
 * Manages slots for rate-limited resources:
 *   - ollama: max 1 concurrent (sequential by design)
 *   - gemini_flash: max 5 concurrent
 *   - gemini_pro: max 3 concurrent
 *   - lingya_opus: max 3 concurrent
 *
 * TTL-based expiry prevents deadlocks if a holder crashes.
 */

import Database from 'better-sqlite3';
import { v4 as uuidv4 } from 'uuid';

export interface ResourceLockResult {
  ok: boolean;
  slot_id?: string;
  reason?: string;
}

export interface ResourceSlotStatus {
  resource: string;
  capacity: number;
  in_use: number;
  available: number;
  holders: { slot_id: string; holder: string; acquired_at: number; expires_at: number }[];
}

// Resource capacity limits
const RESOURCE_LIMITS: Record<string, number> = {
  ollama: 1,
  gemini_flash: 5,
  gemini_pro: 3,
  lingya_opus: 3,
};

// Default TTL per resource (ms)
const DEFAULT_TTL: Record<string, number> = {
  ollama: 5 * 60 * 1000,       // 5 min — local inference is fast
  gemini_flash: 3 * 60 * 1000,  // 3 min
  gemini_pro: 10 * 60 * 1000,   // 10 min — reasoning can take longer
  lingya_opus: 10 * 60 * 1000,  // 10 min
};

export class ResourceLock {
  private db: Database.Database;

  constructor(db: Database.Database) {
    this.db = db;
  }

  /**
   * Acquire a slot for the given resource.
   * Returns slot_id on success, or ok=false if at capacity.
   */
  acquire(resource: string, holder: string, ttlMs?: number): ResourceLockResult {
    const capacity = RESOURCE_LIMITS[resource];
    if (capacity === undefined) {
      return { ok: false, reason: `Unknown resource: ${resource}` };
    }

    const now = Date.now();
    const ttl = ttlMs ?? DEFAULT_TTL[resource] ?? 5 * 60 * 1000;
    const expiresAt = now + ttl;

    // Expire stale locks first (prevents deadlock)
    this.db.prepare(`DELETE FROM resource_locks WHERE resource = ? AND expires_at < ?`).run(resource, now);

    // Count active slots
    const { count } = this.db.prepare(
      `SELECT COUNT(*) as count FROM resource_locks WHERE resource = ?`
    ).get(resource) as { count: number };

    if (count >= capacity) {
      return {
        ok: false,
        reason: `${resource} at capacity (${count}/${capacity}). Try again shortly.`,
      };
    }

    // Acquire
    const slotId = uuidv4();
    this.db.prepare(
      `INSERT INTO resource_locks (resource, slot_id, holder, acquired_at, expires_at) VALUES (?, ?, ?, ?, ?)`
    ).run(resource, slotId, holder, now, expiresAt);

    return { ok: true, slot_id: slotId };
  }

  /**
   * Release a previously acquired slot.
   */
  release(resource: string, slotId: string): boolean {
    const result = this.db.prepare(
      `DELETE FROM resource_locks WHERE resource = ? AND slot_id = ?`
    ).run(resource, slotId);
    return result.changes > 0;
  }

  /**
   * Get current status of a resource (or all resources).
   */
  getStatus(resource?: string): ResourceSlotStatus[] {
    const now = Date.now();
    // Clean expired locks first
    if (resource) {
      this.db.prepare(`DELETE FROM resource_locks WHERE resource = ? AND expires_at < ?`).run(resource, now);
    } else {
      this.db.prepare(`DELETE FROM resource_locks WHERE expires_at < ?`).run(now);
    }

    const resources = resource ? [resource] : Object.keys(RESOURCE_LIMITS);

    return resources.map(res => {
      const capacity = RESOURCE_LIMITS[res] ?? 0;
      const holders = this.db.prepare(
        `SELECT slot_id, holder, acquired_at, expires_at FROM resource_locks WHERE resource = ? ORDER BY acquired_at`
      ).all(res) as { slot_id: string; holder: string; acquired_at: number; expires_at: number }[];

      return {
        resource: res,
        capacity,
        in_use: holders.length,
        available: Math.max(0, capacity - holders.length),
        holders,
      };
    });
  }

  /**
   * Force release all expired locks (housekeeping).
   */
  cleanExpired(): number {
    const result = this.db.prepare(`DELETE FROM resource_locks WHERE expires_at < ?`).run(Date.now());
    return result.changes;
  }
}
