import { useMemo, useState } from "react";
import { Radio, Search } from "lucide-react";
import { AGENT_PROFILES } from "@/generated/agentProfiles";
import { AGENT_PROFILE_SKILLS } from "@/generated/agentProfileSkills";
import { FLEET_SUMMARY } from "@/generated/fleetSummary";
import { ReceiptBanner } from "@/components/ReceiptBanner";

/**
 * Live Fleet — the WS-D live-indexed fleet catalog surface.  Additive to the
 * curated Profiles gallery: it renders the 44 live agent profiles indexed off
 * the Mac Mini (value-blind identifiers/counts only) plus a skills roll-up,
 * fronted by the indexed-proof ReceiptBanner.  Reuses the curated gallery
 * brand classes (.library-*) so it reads native next to /profiles.
 */
type LiveProfile = (typeof AGENT_PROFILES)[number];

const ALL_TENANTS = "all";

function tenantOf(p: LiveProfile): string {
  // profile_key === "<source>:<tenant>:<profile_id>"
  const parts = p.profile_key.split(":");
  return parts.length >= 3 ? parts[1] : "unknown";
}

export default function LiveFleetPage() {
  const [query, setQuery] = useState("");
  const [tenant, setTenant] = useState<string>(ALL_TENANTS);

  const tenants = useMemo(() => {
    const set = new Set<string>();
    for (const p of AGENT_PROFILES) set.add(tenantOf(p));
    return [ALL_TENANTS, ...Array.from(set).sort()];
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return AGENT_PROFILES.filter((p) => {
      if (tenant !== ALL_TENANTS && tenantOf(p) !== tenant) return false;
      if (!q) return true;
      return (
        p.display_name.toLowerCase().includes(q) ||
        p.profile_id.toLowerCase().includes(q) ||
        (p.model ?? "").toLowerCase().includes(q) ||
        (p.provider ?? "").toLowerCase().includes(q)
      );
    });
  }, [query, tenant]);

  // Skills roll-up: most-enabled skills across the whole fleet.
  const topSkills = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of AGENT_PROFILE_SKILLS) {
      counts.set(row.skill_name, (counts.get(row.skill_name) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 16);
  }, []);

  const totalProfiles = FLEET_SUMMARY.counts.agent_profiles;
  const totalSkills = FLEET_SUMMARY.counts.agent_profile_skills;
  const providers = Object.keys(FLEET_SUMMARY.provider_counts).length;
  const tenantCount = Object.keys(FLEET_SUMMARY.tenant_counts).length;

  return (
    <div className="library-page normal-case flex flex-col gap-4">
      <ReceiptBanner />

      <section className="library-hero">
        <div>
          <span className="library-eyebrow">
            <Radio className="inline-block h-3 w-3" /> Live Fleet Catalog
          </span>
          <h2>Live agent fleet</h2>
          <p>
            Every agent profile indexed off the Mac Mini fleet, refreshed by the
            live indexer. Identifiers, models, and skill counts only — no prompt
            or config values are mirrored.
          </p>
        </div>
        <div className="library-hero-stats">
          <strong>{totalProfiles}</strong>
          <span>profiles</span>
          <strong>{totalSkills.toLocaleString()}</strong>
          <span>skills</span>
          <strong>{providers}</strong>
          <span>providers</span>
          <strong>{tenantCount}</strong>
          <span>tenants</span>
        </div>
      </section>

      <div className="fleet-toolbar">
        <label className="fleet-search">
          <Search className="h-3.5 w-3.5" aria-hidden />
          <input
            type="search"
            placeholder="Filter profiles…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter live fleet profiles"
          />
        </label>
        <div className="fleet-tenant-chips" role="tablist" aria-label="Tenant filter">
          {tenants.map((tn) => (
            <button
              key={tn}
              type="button"
              role="tab"
              aria-selected={tenant === tn}
              className={tenant === tn ? "is-active" : ""}
              onClick={() => setTenant(tn)}
            >
              {tn === ALL_TENANTS ? "all tenants" : tn}
            </button>
          ))}
        </div>
        <span className="fleet-count">
          {filtered.length} / {AGENT_PROFILES.length}
        </span>
      </div>

      <div className="profile-index-grid">
        {filtered.map((p) => (
          <article key={p.profile_key} className="profile-index-card live-profile-card">
            <div className="live-card-head">
              <h3>{p.display_name}</h3>
              <span className={`live-status live-status-${p.status}`}>{p.status}</span>
            </div>
            <div className="library-tag-row">
              <span>{p.model || "model tbd"}</span>
              <span>{p.provider}</span>
              <span>{p.skill_count} skills</span>
              <span>{tenantOf(p)}</span>
            </div>
          </article>
        ))}
        {filtered.length === 0 && (
          <p className="fleet-empty">No profiles match “{query}”.</p>
        )}
      </div>

      <section className="library-hero fleet-skills">
        <div>
          <span className="library-eyebrow">Fleet skills roll-up</span>
          <h2>{totalSkills.toLocaleString()} enabled skills</h2>
          <p>Most-enabled skills across the {totalProfiles} live profiles.</p>
          <div className="library-tag-row">
            {topSkills.map(([name, count]) => (
              <span key={name}>
                {name} · {count}
              </span>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
