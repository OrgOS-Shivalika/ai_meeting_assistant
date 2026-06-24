// Phase 7G — agent detail page with tabs.
//
// Tabs: Overview / Scopes / Editor / Versions / Playground / Analytics / Eval.
// Tabs are state-driven (no URL params for sub-tabs in 7G — admins
// rarely deep-link into a tab; can be added later).

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft, Loader2, AlertCircle,
} from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { Skeleton, SkeletonCard } from "../../../shared/components/Skeleton";
import {
  archivePromptConfig, createPromptConfig, createVersion, getAgent,
  getVersion, listPromptConfigs, listVersions, publishVersion,
} from "../api";
import type {
  AgentProfile, AgentPromptConfig, ModularPrompt, PromptVersion,
  PromptVersionSummary,
} from "../types";
import PromptEditor from "../components/PromptEditor";
import VersionHistory from "../components/VersionHistory";
import PlaygroundPanel from "../components/PlaygroundPanel";
import AnalyticsPanel from "../components/AnalyticsPanel";
import EvalPanel from "../components/EvalPanel";

type Tab = "overview" | "scopes" | "editor" | "versions" | "playground" | "analytics" | "eval";

export default function AgentDetailPage() {
  const { profileId = "" } = useParams<{ profileId: string }>();
  const [tab, setTab] = useState<Tab>("overview");
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [configs, setConfigs] = useState<AgentPromptConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const [p, c] = await Promise.all([
        getAgent(profileId),
        listPromptConfigs({ agent_profile_id: profileId }),
      ]);
      setProfile(p);
      setConfigs(c);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId]);

  // Pick the org-scoped config as the canonical "editor target" — the
  // editor + version history operate on it. Future versions of the UI
  // will let admins pick a scope.
  const orgConfig = configs.find(
    (c) => c.scope_type === "organization" && c.status === "active",
  );

  if (loading) {
    // Title strip + tab nav + 2-column body matches the real layout.
    return (
      <Layout>
        <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
          <Skeleton className="h-4 w-32" />
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-xl" />
            <div className="space-y-2">
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-3 w-48" />
            </div>
          </div>
          <div className="flex gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-24" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <SkeletonCard className="h-64 lg:col-span-2" />
            <SkeletonCard className="h-64" />
          </div>
        </div>
      </Layout>
    );
  }

  if (error || !profile) {
    return (
      <Layout>
        <div className="max-w-6xl mx-auto px-4 py-12">
          <Link
            to="/agents"
            className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to agents
          </Link>
          <div className="mt-4 p-4 bg-rose-50 border border-rose-100 rounded-xl text-sm text-rose-700">
            {error || "Agent not found."}
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        <Link
          to="/agents"
          className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to agents
        </Link>

        {/* Header */}
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight truncate">
              {profile.display_name}
            </h1>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <code className="text-xs text-slate-500 font-mono">
                {profile.slug}
              </code>
              <span className="px-1.5 py-0.5 text-[10px] font-bold text-indigo-700 bg-indigo-50 rounded">
                {profile.agent_type}
              </span>
              {profile.status === "archived" && (
                <span className="px-1.5 py-0.5 text-[10px] font-bold text-slate-500 bg-slate-100 rounded">
                  archived
                </span>
              )}
              {profile.eval_gate_required && (
                <span className="px-1.5 py-0.5 text-[10px] font-bold text-amber-700 bg-amber-50 rounded">
                  eval-gated · ≥{(profile.eval_min_score ?? 0.8).toFixed(2)}
                </span>
              )}
            </div>
            {profile.description && (
              <p className="text-sm text-slate-600 mt-2">{profile.description}</p>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 border-b border-slate-200 overflow-x-auto">
          {[
            ["overview", "Overview"],
            ["scopes", "Scopes"],
            ["editor", "Editor"],
            ["versions", "Versions"],
            ["playground", "Playground"],
            ["analytics", "Analytics"],
            ["eval", "Eval"],
          ].map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k as Tab)}
              className={`px-4 py-2 text-sm font-bold transition-colors whitespace-nowrap ${
                tab === k
                  ? "text-indigo-600 border-b-2 border-indigo-600"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Tab body */}
        <div>
          {tab === "overview" && (
            <OverviewTab profile={profile} configs={configs} />
          )}
          {tab === "scopes" && (
            <ScopesTab
              profileId={profileId}
              configs={configs}
              onChange={refresh}
            />
          )}
          {tab === "editor" && orgConfig && (
            <EditorTab
              profile={profile}
              configId={orgConfig.id}
              onPublished={refresh}
            />
          )}
          {tab === "editor" && !orgConfig && (
            <NoOrgConfigMessage profileId={profileId} onCreated={refresh} />
          )}
          {tab === "versions" && orgConfig && (
            <VersionHistory
              configId={orgConfig.id}
              onSelectVersion={() => setTab("editor")}
            />
          )}
          {tab === "versions" && !orgConfig && (
            <NoOrgConfigMessage profileId={profileId} onCreated={refresh} />
          )}
          {tab === "playground" && (
            <PlaygroundPanel profile={profile} />
          )}
          {tab === "analytics" && (
            <AnalyticsPanel profileId={profileId} />
          )}
          {tab === "eval" && <EvalPanel profileId={profileId} />}
        </div>
      </div>
    </Layout>
  );
}

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------

function OverviewTab({
  profile, configs,
}: {
  profile: AgentProfile;
  configs: AgentPromptConfig[];
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Card title="Profile metadata">
        <Field label="ID" value={profile.id} mono />
        <Field label="Slug" value={profile.slug} mono />
        <Field label="Display name" value={profile.display_name} />
        <Field label="Agent type" value={profile.agent_type} mono />
        <Field label="Status" value={profile.status} />
        <Field label="Created" value={new Date(profile.created_at).toLocaleString()} />
        <Field label="Updated" value={new Date(profile.updated_at).toLocaleString()} />
      </Card>
      <Card title="Eval gate">
        <Field label="Required" value={profile.eval_gate_required ? "Yes" : "No"} />
        <Field
          label="Min score"
          value={profile.eval_min_score !== null ? profile.eval_min_score.toFixed(2) : "—"}
        />
        <Field
          label="Fixture set"
          value={profile.eval_fixture_set_id ?? "default"}
        />
      </Card>
      <Card title="Bindings" wide>
        {configs.length === 0 ? (
          <p className="text-sm text-slate-500">
            No scope bindings yet. Open the Scopes tab to create one.
          </p>
        ) : (
          <ul className="text-sm space-y-1">
            {configs.map((c) => (
              <li key={c.id} className="flex items-center gap-2">
                <span className="px-1.5 py-0.5 text-[10px] font-bold bg-slate-100 rounded">
                  {c.scope_type}
                  {c.scope_id !== null && ` · ${c.scope_id}`}
                </span>
                <span className="text-slate-600">
                  {c.active_version_id ? "published" : "no active version"}
                </span>
                {c.status === "archived" && (
                  <span className="ml-auto text-xs text-slate-400">archived</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scopes tab
// ---------------------------------------------------------------------------

function ScopesTab({
  profileId, configs, onChange,
}: {
  profileId: string;
  configs: AgentPromptConfig[];
  onChange: () => void;
}) {
  const [scopeType, setScopeType] = useState<"organization" | "category" | "team">(
    "organization",
  );
  const [scopeId, setScopeId] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const create = async () => {
    setError("");
    setSubmitting(true);
    try {
      await createPromptConfig({
        agent_profile_id: profileId,
        scope_type: scopeType,
        scope_id:
          scopeType === "organization" ? null : parseInt(scopeId, 10) || null,
      });
      setScopeId("");
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  const archive = async (id: string) => {
    if (!window.confirm("Archive this binding? Requests at this scope will fall through to the next resolution layer.")) return;
    try {
      await archivePromptConfig(id);
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-4">
      <Card title="Add binding">
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={scopeType}
            onChange={(e) =>
              setScopeType(e.target.value as "organization" | "category" | "team")
            }
            className="px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white"
          >
            <option value="organization">organization</option>
            <option value="category">category</option>
            <option value="team">team</option>
          </select>
          {scopeType !== "organization" && (
            <input
              type="number"
              placeholder={`${scopeType} id`}
              value={scopeId}
              onChange={(e) => setScopeId(e.target.value)}
              className="w-32 px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono"
            />
          )}
          <button
            onClick={create}
            disabled={
              submitting ||
              (scopeType !== "organization" && !scopeId)
            }
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold disabled:opacity-50"
          >
            {submitting ? "Adding…" : "Add"}
          </button>
        </div>
        {error && (
          <p className="text-xs text-rose-600 font-medium mt-2">{error}</p>
        )}
      </Card>

      <div className="space-y-2">
        {configs.map((c) => (
          <div
            key={c.id}
            className="bg-white border border-slate-200 rounded-xl p-3 flex items-center gap-3"
          >
            <span className="px-2 py-0.5 text-xs font-bold bg-slate-100 rounded">
              {c.scope_type}
              {c.scope_id !== null && ` · ${c.scope_id}`}
            </span>
            <code className="text-xs text-slate-500 font-mono truncate">
              {c.id}
            </code>
            <span className="text-xs text-slate-500 ml-auto">
              {c.active_version_id
                ? "active version set"
                : "no active version"}
            </span>
            {c.status === "active" && (
              <button
                onClick={() => archive(c.id)}
                className="text-xs text-rose-600 hover:bg-rose-50 px-2 py-1 rounded"
              >
                Archive
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Editor tab — wraps PromptEditor + create-version / publish
// ---------------------------------------------------------------------------

function EditorTab({
  profile, configId, onPublished,
}: {
  profile: AgentProfile;
  configId: string;
  onPublished: () => void;
}) {
  const [latest, setLatest] = useState<PromptVersionSummary | null>(null);
  const [draft, setDraft] = useState<ModularPrompt>({});
  const [versionBody, setVersionBody] = useState<PromptVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const versions = await listVersions(configId, { limit: 1 });
        const top = versions[0] || null;
        setLatest(top);
        if (top) {
          const v = await getVersion(configId, top.id);
          setVersionBody(v);
          setDraft(v.modular_prompt_json || {});
        } else {
          setVersionBody(null);
          setDraft(profile.default_modular_prompt_json || {});
        }
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [configId, profile.default_modular_prompt_json, refreshKey]);

  const saveDraft = async () => {
    setSaving(true);
    setError("");
    try {
      const v = await createVersion(configId, {
        label: `draft-${new Date().toISOString().slice(0, 16)}`,
        modular_prompt: draft,
      });
      setLatest({
        id: v.id,
        version_number: v.version_number,
        label: v.label,
        state: v.state,
        published_at: v.published_at,
        published_by: v.published_by,
        eval_score: v.eval_score,
        seeded_from_filesystem: v.seeded_from_filesystem,
        created_by: v.created_by,
        created_at: v.created_at,
      });
      setVersionBody(v);
      setRefreshKey((x) => x + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    if (!latest) return;
    if (latest.state !== "draft") {
      setError("Latest version is not a draft. Save changes first.");
      return;
    }
    if (!window.confirm("Publish this draft as the active version?")) return;
    setPublishing(true);
    setError("");
    try {
      await publishVersion(configId, latest.id, "publish from UI");
      onPublished();
      setRefreshKey((x) => x + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="text-sm text-slate-600">
          {loading ? (
            <span className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              Loading…
            </span>
          ) : latest ? (
            <>
              Latest version:{" "}
              <span className="font-bold text-slate-900">
                v{latest.version_number}
              </span>{" "}
              ·{" "}
              <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-slate-100 text-slate-600">
                {latest.state}
              </span>
            </>
          ) : (
            <span className="text-slate-500">
              No versions yet. Saving creates v1.
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={saveDraft}
            disabled={saving}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-800 text-white rounded-lg text-sm font-semibold disabled:opacity-50 flex items-center gap-2"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            Save as draft
          </button>
          <button
            onClick={publish}
            disabled={
              publishing ||
              !latest ||
              latest.state !== "draft"
            }
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold disabled:opacity-50 flex items-center gap-2"
          >
            {publishing && <Loader2 className="w-4 h-4 animate-spin" />}
            Publish
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-rose-50 border border-rose-100 rounded-lg text-sm text-rose-700 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      <PromptEditor
        value={draft}
        onChange={setDraft}
        agentType={profile.agent_type}
        disabled={
          versionBody !== null &&
          versionBody.state !== "draft" &&
          versionBody.id === latest?.id
        }
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function NoOrgConfigMessage({
  profileId, onCreated,
}: { profileId: string; onCreated: () => void }) {
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const create = async () => {
    setError("");
    setCreating(true);
    try {
      await createPromptConfig({
        agent_profile_id: profileId,
        scope_type: "organization",
      });
      onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="p-6 bg-slate-50 border border-dashed border-slate-200 rounded-xl text-center">
      <p className="text-sm text-slate-600">
        This agent has no organization-scoped binding yet.
      </p>
      <button
        onClick={create}
        disabled={creating}
        className="mt-3 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold disabled:opacity-50"
      >
        {creating ? "Creating…" : "Create org binding"}
      </button>
      {error && (
        <p className="mt-2 text-xs text-rose-600 font-medium">{error}</p>
      )}
    </div>
  );
}

function Card({
  title, children, wide = false,
}: {
  title: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={`bg-white border border-slate-200 rounded-xl p-4 space-y-2 ${wide ? "md:col-span-2" : ""}`}>
      <h3 className="text-xs font-bold text-slate-600 uppercase tracking-wider">
        {title}
      </h3>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function Field({
  label, value, mono = false,
}: {
  label: string;
  value: string | null;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-2 text-sm">
      <span className="text-slate-500 w-24 shrink-0 text-xs">{label}</span>
      <span
        className={`${mono ? "font-mono text-xs" : ""} text-slate-800 break-all`}
      >
        {value ?? "—"}
      </span>
    </div>
  );
}
