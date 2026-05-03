import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { StateStore } from './state-store.js';
import { D68_CONFIG } from './config.js';
import { atomicWriteJson, quarantineCcLeadInbox, type QuarantineResult } from './quarantine.js';

export interface StartSessionInput {
  pid?: number | null;
  wrapperPid?: number | null;
  reason?: string;
  metadata?: Record<string, unknown>;
}

export interface StartSessionResult {
  ok: boolean;
  disabled?: boolean;
  sessionId: string | null;
  quarantineDir: string | null;
  orphanCount: number;
  summaryMessageId: string | null;
}

function ensureDir(dir: string): void {
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
}

function pidExists(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    return code === 'EPERM';
  }
}

function processStartTime(pid: number | null | undefined): string | null {
  if (!pid || !Number.isInteger(pid) || pid <= 0) return null;
  try {
    return execFileSync('ps', ['-o', 'lstart=', '-p', String(pid)], {
      encoding: 'utf-8',
      timeout: 1_000,
    }).trim() || null;
  } catch {
    return null;
  }
}

export class SessionManager {
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  constructor(private store: StateStore, private ceHubDir: string) {}

  startNewSession(input: StartSessionInput = {}): StartSessionResult {
    if (!D68_CONFIG.SESSIONS) {
      return {
        ok: true,
        disabled: true,
        sessionId: null,
        quarantineDir: null,
        orphanCount: 0,
        summaryMessageId: null,
      };
    }

    const now = Date.now();
    const reason = input.reason ?? 'manual';
    const sessionId = `sess_${randomUUID()}`;
    const pid = input.pid ?? null;
    const wrapperPid = input.wrapperPid ?? input.pid ?? null;
    const pidStartTime = processStartTime(pid);
    const wrapperPidStartTime = processStartTime(wrapperPid);
    let quarantine: QuarantineResult = {
      quarantineDir: null,
      orphanCount: 0,
      files: [],
      summaryMessageId: null,
      summaryFile: null,
    };

    this.store.transaction(() => {
      const prev = this.store.getActiveSession();
      if (prev) this.store.markSessionEnded(prev.id, 'replaced');

      if (D68_CONFIG.QUARANTINE) {
        quarantine = quarantineCcLeadInbox(this.store, this.ceHubDir, sessionId, reason, now);
      }

      this.store.createSession({
        id: sessionId,
        state: 'ACTIVE',
        pid,
        wrapper_pid: wrapperPid,
        started_at: now,
        metadata: {
          ...(input.metadata ?? {}),
          reason,
          quarantine_dir: quarantine.quarantineDir,
          orphan_count: quarantine.orphanCount,
          summary_message_id: quarantine.summaryMessageId,
          pid_start_time: pidStartTime,
          wrapper_pid_start_time: wrapperPidStartTime,
        },
      });

      this.store.createEvent({
        type: 'cc_lead.session.start',
        source: 'session-manager',
        target: 'cc-lead',
        payload: { sessionId, reason, orphanCount: quarantine.orphanCount },
      });
    });

    this.writeCurrentSession({
      session_id: sessionId,
      started_at_ms: now,
      reason,
      pid,
      wrapper_pid: wrapperPid,
      pid_start_time: pidStartTime,
      wrapper_pid_start_time: wrapperPidStartTime,
      quarantine_dir: quarantine.quarantineDir,
      orphan_count: quarantine.orphanCount,
      summary_message_id: quarantine.summaryMessageId,
    });

    return {
      ok: true,
      sessionId,
      quarantineDir: quarantine.quarantineDir,
      orphanCount: quarantine.orphanCount,
      summaryMessageId: quarantine.summaryMessageId,
    };
  }

  endSession(sessionId?: string | null, reason = 'graceful'): { ok: boolean; sessionId: string | null; disabled?: boolean } {
    if (!D68_CONFIG.SESSIONS) return { ok: true, disabled: true, sessionId: null };
    const session = sessionId ? this.store.getSession(sessionId) : this.store.getActiveSession();
    if (!session) return { ok: true, sessionId: null };
    this.store.markSessionEnded(session.id, reason);
    this.store.createEvent({
      type: 'cc_lead.session.end',
      source: 'session-manager',
      target: 'cc-lead',
      payload: { sessionId: session.id, reason },
    });
    return { ok: true, sessionId: session.id };
  }

  recordHeartbeat(sessionId: string, pid?: number | null, wrapperPid?: number | null): void {
    if (!D68_CONFIG.SESSIONS) return;
    this.store.updateSessionHeartbeat(sessionId, pid, wrapperPid);
  }

  scanOnce(): void {
    if (!D68_CONFIG.SESSIONS) return;
    const active = this.store.getActiveSession();
    if (!active) return;
    const pid = active.wrapper_pid ?? active.pid;
    const startKey = active.wrapper_pid ? 'wrapper_pid_start_time' : 'pid_start_time';
    const expectedStartTime = typeof active.metadata[startKey] === 'string'
      ? active.metadata[startKey] as string
      : null;
    const currentStartTime = expectedStartTime ? processStartTime(pid) : null;
    const pidReused = Boolean(expectedStartTime && currentStartTime && currentStartTime !== expectedStartTime);
    if (pid && (!pidExists(pid) || pidReused)) {
      this.store.markSessionEnded(active.id, 'crashed');
      this.store.createEvent({
        type: 'cc_lead.session.dead',
        source: 'session-manager',
        target: 'cc-lead',
        payload: { sessionId: active.id, pid, expectedStartTime, currentStartTime, pidReused },
      });
    }
  }

  startPidPolling(intervalMs = 5_000): void {
    if (!D68_CONFIG.SESSIONS || this.pollTimer) return;
    this.pollTimer = setInterval(() => this.scanOnce(), intervalMs);
  }

  stopPidPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private writeCurrentSession(data: Record<string, unknown>): void {
    const stateDir = join(this.ceHubDir, 'state', 'sessions');
    ensureDir(stateDir);
    atomicWriteJson(join(stateDir, 'current.json'), data);
  }
}
