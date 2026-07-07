import { useMemo } from "react";
import { INDEX_RUN_RECEIPT } from "@/generated/indexRunReceipt";

/**
 * Indexed-proof strip for the Live Fleet surface.  Reads the value-blind
 * INDEX_RUN_RECEIPT emitted by the WS-D fleet indexer and renders the
 * provenance facts (run id, indexed-at, feed counts, source, content hash)
 * plus a freshness state derived from indexed_at:
 *   fresh (green)  — within 48h
 *   stale (amber)  — 48h..7d
 *   old   (red)    — older than 7d
 * Styling reuses the curated gallery brand palette (.library-hero / cream
 * card) — no new colors are introduced; the freshness dot uses the existing
 * --color-success / --color-warning / --color-destructive theme tokens.
 */
function shortHash(value: string, len = 8): string {
  return value ? value.slice(0, len) : "—";
}

function formatIndexedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

type Freshness = { state: "fresh" | "stale" | "old"; label: string };

function freshnessFor(iso: string): Freshness {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return { state: "old", label: "unknown" };
  const ageMs = Date.now() - then;
  const ageHours = ageMs / 36e5;
  if (ageHours <= 48) return { state: "fresh", label: "live · fresh" };
  if (ageHours <= 24 * 7) return { state: "stale", label: "aging" };
  return { state: "old", label: "stale" };
}

export function ReceiptBanner() {
  const r = INDEX_RUN_RECEIPT;
  const fresh = useMemo(() => freshnessFor(r.indexed_at), [r.indexed_at]);
  const profiles = r.feed_counts.agent_profiles;
  const skills = r.feed_counts.agent_profile_skills;

  return (
    <section className="library-hero receipt-banner" aria-label="Fleet index provenance">
      <div>
        <div className="receipt-topline">
          <span className="library-eyebrow">Live Fleet Index · {r.source}</span>
          <span
            className={`receipt-freshness ${fresh.state}`}
            title={`indexed ${formatIndexedAt(r.indexed_at)}`}
          >
            <span aria-hidden className="dot" />
            {fresh.label}
          </span>
        </div>
        <h2>Indexed proof</h2>
        <div className="receipt-meta">
          <code>run {shortHash(r.run_id)}</code>
          <code>hash {shortHash(r.content_hash)}</code>
          <code>schema {r.schema_version}</code>
          <code>{r.validation_status}</code>
          <code>indexed {formatIndexedAt(r.indexed_at)}</code>
        </div>
      </div>
      <div className="library-hero-stats">
        <strong>{profiles}</strong>
        <span>profiles</span>
        <strong>{skills.toLocaleString()}</strong>
        <span>skills</span>
      </div>
    </section>
  );
}

export default ReceiptBanner;
