import { ArrowLeft, Building2, ChevronRight, FolderOpen, Loader2, Users } from "lucide-react";
import { Link } from "react-router-dom";
import type { ActiveScope, ScopeListItem, ScopesResponse } from "../types";

/**
 * Agent Control left-rail tree.
 *
 *   Workspace Defaults                ← global org policy
 *   ─────────────────────────
 *   Engineering                       ← category (department)
 *     Backend                         ←   team
 *     Frontend                        ←   team
 *     DevOps                          ←   team
 *   Sales
 *     SDR
 *     Account Executive
 *   ...
 *   Orphan Teams                      ← teams whose parent category
 *     ...                                isn't installed (shouldn't
 *                                        happen with new provisioning,
 *                                        but rendered defensively)
 *
 * Each row shows an override-count badge when the scope has any
 * overrides. The future-ready hint per spec: row layout has room
 * to nest agents under teams without restructuring.
 */
export default function ScopeSidebar({
  data,
  loading,
  active,
  onSelect,
}: {
  data: ScopesResponse | null;
  loading: boolean;
  active: ActiveScope;
  onSelect: (scope: ActiveScope) => void;
}) {
  return (
    <aside className="w-72 h-full bg-white border-r border-gray-200 overflow-y-auto">
      <div className="px-4 py-4 border-b border-gray-100">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-[11px] font-medium text-gray-500 hover:text-gray-900"
          title="Back to app"
        >
          <ArrowLeft className="w-3 h-3" />
          Exit Agent Control
        </Link>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 mt-3">
          Agent Control
        </p>
        <h2 className="text-sm font-bold text-gray-900 mt-0.5">
          Behavior scopes
        </h2>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-10 text-gray-400">
          <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading…
        </div>
      )}

      {!loading && data && (
        <div className="py-2">
          {/* Workspace defaults — always at the top */}
          <ScopeRow
            label="Workspace Defaults"
            sublabel="Organization-wide AI policy"
            icon={Building2}
            active={active.type === "workspace"}
            badgeCount={data.workspace_overrides_count}
            onClick={() =>
              onSelect({
                type: "workspace", id: null,
                display_name: "Workspace Defaults",
              })
            }
          />

          <SectionHeader label="Categories" />

          {data.categories.length === 0 && data.teams.length === 0 ? (
            <EmptyHint text="Install a bundle from Templates to populate this list." />
          ) : (
            <CategoryTree
              categories={data.categories}
              teams={data.teams}
              active={active}
              onSelect={onSelect}
            />
          )}
        </div>
      )}
    </aside>
  );
}


function CategoryTree({
  categories, teams, active, onSelect,
}: {
  categories: ScopeListItem[];
  teams: ScopeListItem[];
  active: ActiveScope;
  onSelect: (scope: ActiveScope) => void;
}) {
  // Group teams by their parent category id.
  const teamsByParent = new Map<number, ScopeListItem[]>();
  const orphans: ScopeListItem[] = [];
  for (const t of teams) {
    if (t.parent_id == null) {
      orphans.push(t);
      continue;
    }
    const bucket = teamsByParent.get(t.parent_id);
    if (bucket) bucket.push(t);
    else teamsByParent.set(t.parent_id, [t]);
  }

  return (
    <>
      {categories.map((cat) => (
        <CategoryNode
          key={cat.id}
          category={cat}
          teams={teamsByParent.get(cat.id) || []}
          active={active}
          onSelect={onSelect}
        />
      ))}
      {orphans.length > 0 && (
        <>
          <SectionHeader label="Standalone Teams" />
          {orphans.map((t) => (
            <ScopeRow
              key={`team-${t.id}`}
              label={t.name}
              sublabel={t.template_slug || undefined}
              icon={ChevronRight}
              indent={1}
              active={active.type === "team" && active.id === t.id}
              badgeCount={t.override_count}
              onClick={() =>
                onSelect({
                  type: "team", id: t.id,
                  parent_id: null,
                  display_name: t.name,
                })
              }
            />
          ))}
        </>
      )}
    </>
  );
}


function CategoryNode({
  category, teams, active, onSelect,
}: {
  category: ScopeListItem;
  teams: ScopeListItem[];
  active: ActiveScope;
  onSelect: (scope: ActiveScope) => void;
}) {
  return (
    <>
      <ScopeRow
        label={category.name}
        sublabel={category.template_slug || undefined}
        icon={FolderOpen}
        active={active.type === "category" && active.id === category.id}
        badgeCount={category.override_count}
        onClick={() =>
          onSelect({
            type: "category", id: category.id,
            display_name: category.name,
          })
        }
      />
      {teams.map((t) => (
        <ScopeRow
          key={`team-${t.id}`}
          label={t.name}
          sublabel={t.template_slug || undefined}
          icon={Users}
          indent={1}
          active={active.type === "team" && active.id === t.id}
          badgeCount={t.override_count}
          onClick={() =>
            onSelect({
              type: "team", id: t.id,
              parent_id: t.parent_id ?? null,
              display_name: t.name,
            })
          }
        />
      ))}
    </>
  );
}


function SectionHeader({ label }: { label: string }) {
  return (
    <div className="mt-4 mb-1 px-4">
      <span className="text-[11px] font-semibold uppercase tracking-widest text-gray-500">
        {label}
      </span>
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <p className="px-4 py-2 text-xs text-gray-400 italic">{text}</p>
  );
}

function ScopeRow({
  label,
  sublabel,
  icon: Icon,
  active,
  badgeCount = 0,
  indent = 0,
  onClick,
}: {
  label: string;
  sublabel?: string;
  icon: React.ComponentType<{ className?: string }>;
  active: boolean;
  badgeCount?: number;
  indent?: number;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{ paddingLeft: 16 + indent * 16 }}
      className={`w-full text-left flex items-start gap-2 pr-4 py-2 transition ${
        active
          ? "bg-indigo-50 border-l-2 border-indigo-600"
          : "border-l-2 border-transparent hover:bg-gray-50"
      }`}
    >
      <Icon
        className={`w-4 h-4 mt-0.5 shrink-0 ${active ? "text-indigo-600" : "text-gray-400"}`}
      />
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-medium truncate ${active ? "text-indigo-900" : "text-gray-800"}`}>
          {label}
        </p>
        {sublabel && (
          <p className="text-[11px] text-gray-500 truncate">{sublabel}</p>
        )}
      </div>
      {badgeCount > 0 && (
        <span
          className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-indigo-600 text-white text-[10px] font-bold mt-0.5"
          title={`${badgeCount} override${badgeCount === 1 ? "" : "s"}`}
        >
          {badgeCount}
        </span>
      )}
    </button>
  );
}
