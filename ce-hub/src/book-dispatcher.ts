/**
 * BookDispatcher — Book Queue management
 *
 * Reads config/books.yaml and manages assignment of books to pipeline runners.
 * Uses SQLite book_queue table for state (initialized from books.yaml on startup).
 * Supports:
 *   - get_next_book: claim the next unprocessed book for a given step
 *   - update_book_status: mark a book's step as done/failed
 *   - list_queue: view queue state
 *   - preflight_check: validate a book can be processed
 */

import Database from 'better-sqlite3';
import { readFileSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { execSync } from 'node:child_process';
import { v4 as uuidv4 } from 'uuid';

function getCwd(): string {
  return process.env.CE_HUB_CWD || process.cwd();
}

export interface BookEntry {
  id: string;
  track: string;
  title?: string;
  status: string;
  priority: number;
  assigned_to: string | null;
  assigned_at: number | null;
  prep_done_at: number | null;
  extract_done_at: number | null;
  qc_done_at: number | null;
  error: string | null;
}

export interface PreflightResult {
  ok: boolean;
  checks: Array<{ name: string; passed: boolean; detail?: string }>;
}

// ── books.yaml parser ─────────────────────────────────────────────────────────
// Simple YAML reader — only parses the fields we care about (no full YAML dep)

interface RawBookConfig {
  id: string;
  track?: string;
  priority?: number;
  l0_status?: string;
  recipe_status?: string;
}

function loadBooksYaml(): RawBookConfig[] {
  const yamlPath = join(getCwd(), 'config', 'books.yaml');
  if (!existsSync(yamlPath)) {
    console.warn('[book-dispatcher] config/books.yaml not found');
    return [];
  }

  const text = readFileSync(yamlPath, 'utf-8');
  const books: RawBookConfig[] = [];
  let current: Partial<RawBookConfig> | null = null;

  for (const line of text.split('\n')) {
    // Top-level list item
    if (line.match(/^- /)) {
      if (current?.id) books.push(current as RawBookConfig);
      current = {};
      const rest = line.slice(2);
      const m = rest.match(/^(\w+):\s*(.+)/);
      if (m) (current as Record<string, unknown>)[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
    } else if (current && line.match(/^\s+\w+:/)) {
      const m = line.match(/^\s+(\w+):\s*(.+)/);
      if (m) {
        const v = m[2].trim().replace(/^["']|["']$/g, '');
        (current as Record<string, unknown>)[m[1]] = isNaN(Number(v)) ? v : Number(v);
      }
    }
  }
  if (current?.id) books.push(current as RawBookConfig);
  return books;
}

// ── BookDispatcher ─────────────────────────────────────────────────────────────

export class BookDispatcher {
  private db: Database.Database;

  constructor(db: Database.Database) {
    this.db = db;
    this.syncFromBooksYaml();
  }

  /**
   * Sync books.yaml into book_queue table (idempotent).
   * New books get status='pending'; existing entries keep their status.
   */
  syncFromBooksYaml(): number {
    const books = loadBooksYaml();
    let added = 0;
    for (const b of books) {
      const existing = this.db.prepare('SELECT book_id FROM book_queue WHERE book_id = ?').get(b.id);
      if (!existing) {
        // Infer track from l0_status / title / id
        const track = b.track ?? this.inferTrack(b);
        const priority = b.priority ?? 1;
        // Map existing status from books.yaml
        const status = this.mapStatus(b);
        this.db.prepare(
          `INSERT INTO book_queue (book_id, track, priority, status) VALUES (?, ?, ?, ?)`
        ).run(b.id, track, priority, status);
        added++;
      }
    }
    if (added > 0) console.log(`[book-dispatcher] Synced ${added} new books from books.yaml`);
    return added;
  }

  private inferTrack(b: RawBookConfig): string {
    // Engineering textbooks → Track A, culinary/recipe books → Track B
    const id = b.id.toLowerCase();
    const trackAHints = ['singh', 'heldman', 'van_boekel', 'rao', 'toledo', 'sahin', 'belitz', 'fennema', 'jay', 'handbook', 'engineering', 'kinetic'];
    if (trackAHints.some(h => id.includes(h))) return 'A';
    return 'B';
  }

  private mapStatus(b: RawBookConfig): string {
    if (b.l0_status === 'done' && b.recipe_status === 'done') return 'qc_done';
    if (b.l0_status === 'done') return 'extract_done';
    if (b.l0_status === 'running') return 'assigned';
    return 'pending';
  }

  /**
   * Claim the next available book for processing.
   * Returns null if queue is empty or all books are busy.
   */
  getNextBook(params: {
    track?: string;
    step?: 'prep' | 'extract' | 'qc';
    assignedTo: string;
  }): BookEntry | null {
    const now = Date.now();

    // Determine what status the book must be in to be eligible
    const requiredStatus = params.step === 'extract' ? 'prep_done' : params.step === 'qc' ? 'extract_done' : 'pending';

    let query = `SELECT * FROM book_queue WHERE status = ? `;
    const args: unknown[] = [requiredStatus];

    if (params.track) {
      query += `AND track = ? `;
      args.push(params.track);
    }

    query += `ORDER BY priority ASC, book_id ASC LIMIT 1`;

    const row = this.db.prepare(query).get(...args) as Record<string, unknown> | undefined;
    if (!row) return null;

    const bookId = row.book_id as string;

    // Claim it atomically
    this.db.prepare(
      `UPDATE book_queue SET status = 'assigned', assigned_to = ?, assigned_at = ? WHERE book_id = ?`
    ).run(params.assignedTo, now, bookId);

    return this.getBook(bookId);
  }

  /**
   * Update a book's status after a pipeline step completes.
   */
  updateBookStatus(bookId: string, step: 'prep' | 'extract' | 'qc', status: 'done' | 'failed', error?: string): void {
    const now = Date.now();
    const updates: Record<string, unknown> = {};

    if (step === 'prep' && status === 'done') {
      updates.status = 'prep_done';
      updates.prep_done_at = now;
    } else if (step === 'extract' && status === 'done') {
      updates.status = 'extract_done';
      updates.extract_done_at = now;
    } else if (step === 'qc' && status === 'done') {
      updates.status = 'qc_done';
      updates.qc_done_at = now;
    } else {
      updates.status = 'pending';  // Re-queue on failure
      updates.assigned_to = null;
      updates.error = error ?? 'unknown error';
    }

    const setClauses = Object.keys(updates).map(k => `${k} = ?`).join(', ');
    this.db.prepare(`UPDATE book_queue SET ${setClauses} WHERE book_id = ?`).run(...Object.values(updates), bookId);
  }

  getBook(bookId: string): BookEntry | null {
    const r = this.db.prepare('SELECT * FROM book_queue WHERE book_id = ?').get(bookId) as Record<string, unknown> | undefined;
    if (!r) return null;
    return {
      id: r.book_id as string,
      track: r.track as string,
      status: r.status as string,
      priority: r.priority as number,
      assigned_to: r.assigned_to as string | null,
      assigned_at: r.assigned_at as number | null,
      prep_done_at: r.prep_done_at as number | null,
      extract_done_at: r.extract_done_at as number | null,
      qc_done_at: r.qc_done_at as number | null,
      error: r.error as string | null,
    };
  }

  listQueue(filter?: { track?: string; status?: string }): BookEntry[] {
    let q = 'SELECT * FROM book_queue WHERE 1=1';
    const args: string[] = [];
    if (filter?.track) { q += ' AND track = ?'; args.push(filter.track); }
    if (filter?.status) { q += ' AND status = ?'; args.push(filter.status); }
    q += ' ORDER BY priority ASC, book_id ASC';
    const rows = this.db.prepare(q).all(...args) as Record<string, unknown>[];
    return rows.map(r => this.getBook(r.book_id as string)!);
  }

  /**
   * Run preflight checks for a book before pipeline starts.
   */
  async preflight(bookId: string, steps: number[]): Promise<PreflightResult> {
    const checks: PreflightResult['checks'] = [];
    const cwd = getCwd();

    // 1. Book exists in queue
    const book = this.getBook(bookId);
    checks.push({ name: 'book_in_registry', passed: book !== null });

    // 2. Input file exists (PDF or md)
    const extensions = ['.pdf', '.epub', '.md', '.txt'];
    const bookDir = join(cwd, 'output', bookId);
    const pdfPath = join(cwd, 'Documents', '食物科学计算书籍', `${bookId}.pdf`);
    const inputExists = existsSync(pdfPath) || existsSync(bookDir);
    checks.push({ name: 'input_file_exists', passed: inputExists, detail: inputExists ? pdfPath : `Not found in ${bookDir} or ${pdfPath}` });

    // 3. Ollama reachable (if steps 4/5)
    if (steps.some(s => s >= 4)) {
      try {
        const resp = await fetch('http://localhost:11434/api/tags', { signal: AbortSignal.timeout(5000) });
        checks.push({ name: 'ollama_reachable', passed: resp.ok });
      } catch {
        checks.push({ name: 'ollama_reachable', passed: false, detail: 'Connection refused or timeout' });
      }
    }

    // 4. TOC config exists (if step 4)
    if (steps.includes(4)) {
      const tocPath = join(cwd, 'config', 'mc_toc.json');
      if (existsSync(tocPath)) {
        try {
          const toc = JSON.parse(readFileSync(tocPath, 'utf-8'));
          checks.push({ name: 'toc_configured', passed: bookId in toc, detail: bookId in toc ? 'TOC found' : `Book ${bookId} not in mc_toc.json` });
        } catch {
          checks.push({ name: 'toc_configured', passed: false, detail: 'Failed to parse mc_toc.json' });
        }
      } else {
        checks.push({ name: 'toc_configured', passed: false, detail: 'mc_toc.json not found' });
      }
    }

    // 5. Disk space > 5GB
    try {
      const dfOut = execSync(`df -k "${cwd}"`, { encoding: 'utf-8' });
      const lines = dfOut.trim().split('\n');
      const parts = lines[lines.length - 1].split(/\s+/);
      const freeKb = parseInt(parts[3] ?? '0');
      const freeGb = freeKb / 1024 / 1024;
      checks.push({ name: 'disk_space_gt_5gb', passed: freeGb > 5, detail: `${freeGb.toFixed(1)} GB free` });
    } catch {
      checks.push({ name: 'disk_space_gt_5gb', passed: false, detail: 'Could not check disk space' });
    }

    // 6. Track configured
    if (book) {
      checks.push({ name: 'track_configured', passed: ['A', 'B'].includes(book.track), detail: `Track: ${book.track}` });
    }

    const ok = checks.every(c => c.passed);
    return { ok, checks };
  }
}
