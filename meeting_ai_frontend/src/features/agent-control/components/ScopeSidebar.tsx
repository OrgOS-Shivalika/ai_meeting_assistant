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
    <aside className="w-80 h-full bg-[#fbfbfb] border-r border-gray-200 overflow-y-auto">
      <div className="px-6 py-8 border-b border-gray-100 bg-white">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] text-gray-400 hover:text-indigo-600 transition-colors"
          title="Back to app"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Exit OS Control
        </Link>
        <div className="mt-8">
          <p className="text-[10px] font-black uppercase tracking-[0.3em] text-indigo-600/50">
            Runtime Policy
          </p>
          <h2 className="text-xl font-black text-gray-900 mt-1 tracking-tight">
            Scope Tree
          </h2>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-20 text-gray-300">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      )}

      {!loading && data && (
        <div className="py-6">
          {/* Workspace defaults — always at the top */}
          <div className="px-3 mb-8">
            <ScopeRow
              label="Workspace Defaults"
              sublabel="Global org-wide policy"
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
          </div>

          <div className="px-3">
            <SectionHeader label="Organization Categories" />

            {data.categories.length === 0 && data.teams.length === 0 ? (
              <EmptyHint text="Install a department bundle to populate the hierarchy." />
            ) : (
              <CategoryTree
                categories={data.categories}
                teams={data.teams}
                active={active}
                onSelect={onSelect}
              />
            )}
          </div>
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
    <div className="space-y-6">
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
        <div className="pt-4 border-t border-gray-100">
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
        </div>
      )}
    </div>
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
    <div className="space-y-1">
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
      <div className="space-y-1 mt-1">
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
      </div>
    </div>
  );
}


function SectionHeader({ label }: { label: string }) {
  return (
    <div className="mb-3 px-3">
      <span className="text-[9px] font-black uppercase tracking-[0.25em] text-gray-400">
        {label}
      </span>
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <p className="px-3 py-2 text-xs text-gray-400 font-medium italic">{text}</p>
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
      style={{ paddingLeft: 12 + indent * 16 }}
      className={`w-full text-left flex items-start gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 ${
        active
          ? "bg-white shadow-md shadow-indigo-500/10 ring-1 ring-black/5"
          : "hover:bg-gray-100/50"
      }`}
    >
      <div className={`p-1.5 rounded-lg shrink-0 ${active ? "bg-indigo-600 text-white shadow-sm" : "bg-gray-100 text-gray-400"}`}>
        <Icon className="w-3.5 h-3.5" />
      </div>
      <div className="flex-1 min-w-0 py-0.5">
        <p className={`text-xs font-bold truncate ${active ? "text-gray-900" : "text-gray-600"}`}>
          {label}
        </p>
        {sublabel && (
          <p className={`text-[10px] font-bold uppercase tracking-tighter truncate ${active ? "text-indigo-400" : "text-gray-400"}`}>
            {sublabel}
          </p>
        )}
      </div>
      {badgeCount > 0 && (
        <span
          className={`inline-flex items-center justify-center min-w-[18px] h-4.5 px-1.5 rounded-full text-[9px] font-black mt-1 ${
            active ? "bg-indigo-100 text-indigo-600" : "bg-gray-200 text-gray-500"
          }`}
          title={`${badgeCount} active overrides`}
        >
          {badgeCount}
        </span>
      )}
    </button>
  );
}
