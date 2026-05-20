import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Loader2, Package, Sparkles, Users, Tag } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { templatesApi } from "../services/templatesApi";
import type { BundlePreview, BundlePreviewItem } from "../services/templatesApi";

// Only category + team in the new behavior-profile catalog; legacy
// 'agent' items were filtered out on the backend.
const ITEM_ICONS: Record<"category" | "team", React.ComponentType<{ className?: string }>> = {
  team: Users,
  category: Tag,
};

export default function BundlePreviewPage() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<BundlePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let cancelled = false;
    (async () => {
      try {
        const p = await templatesApi.previewBundle(slug);
        if (!cancelled) setData(p);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [slug]);

  const handleInstall = async () => {
    if (!slug || !window.confirm(`Install ${data?.display_name}? This adds the bundle's items to your workspace.`)) {
      return;
    }
    setInstalling(true);
    setInstallResult(null);
    try {
      const result = await templatesApi.install({ bundle_slug: slug });
      setInstallResult(
        `Installed ${result.workspace_link_ids.length} link${
          result.workspace_link_ids.length === 1 ? "" : "s"
        } (status: ${result.status}).`
      );
      setTimeout(() => navigate("/templates/installed"), 1500);
    } catch (e) {
      setInstallResult(`Install failed: ${(e as Error).message}`);
    } finally {
      setInstalling(false);
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center py-20 text-gray-500">
          <Loader2 className="animate-spin w-5 h-5 mr-2" /> Loading bundle…
        </div>
      </Layout>
    );
  }
  if (error || !data) {
    return (
      <Layout>
        <div className="p-8">
          <Link to="/templates/browse" className="text-sm text-indigo-600">← Back</Link>
          <div className="mt-4 p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
            {error || "Bundle not found"}
          </div>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="px-8 py-8 max-w-5xl mx-auto">
        <Link to="/templates/browse" className="text-sm text-indigo-600 hover:underline">
          ← Back to catalog
        </Link>

        <header className="flex items-start justify-between mt-3 mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-indigo-100 rounded-xl flex items-center justify-center">
              <Package className="w-6 h-6 text-indigo-600" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
                {data.display_name}
                {data.is_recommended_on_signup && (
                  <span className="flex items-center gap-1 text-xs font-semibold text-amber-700 bg-amber-100 px-2 py-0.5 rounded-full">
                    <Sparkles className="w-3 h-3" /> Recommended
                  </span>
                )}
              </h1>
              <p className="text-sm text-gray-500">{data.slug}@{data.version}</p>
            </div>
          </div>
          <button
            onClick={handleInstall}
            disabled={installing}
            className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-semibold disabled:opacity-50 flex items-center gap-2"
          >
            {installing ? <Loader2 className="animate-spin w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
            {installing ? "Installing…" : "Install bundle"}
          </button>
        </header>

        {installResult && (
          <div className="mb-4 p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg text-sm">
            {installResult}
          </div>
        )}

        <p className="text-gray-700 mb-6">{data.description}</p>

        <section className="grid grid-cols-3 gap-3 mb-6">
          <CountTile label="Teams" value={data.counts.team || 0} />
          <CountTile label="Categories" value={data.counts.category || 0} />
          <CountTile label="Agents" value={data.counts.agent || 0} />
        </section>

        <section className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {data.items.map((it) => (
            <ItemRow key={`${it.item_type}:${it.item_slug}`} item={it} />
          ))}
        </section>
      </div>
    </Layout>
  );
}

function CountTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
    </div>
  );
}

function ItemRow({ item }: { item: BundlePreviewItem }) {
  const Icon = ITEM_ICONS[item.item_type];
  const prof = item.profile;
  const displayName = (prof?.display_name as string) ?? item.item_slug;
  const description = prof?.description as string | null | undefined;
  return (
    <div className="px-5 py-3 flex items-start gap-3">
      <div className="w-8 h-8 bg-gray-100 rounded-lg flex items-center justify-center shrink-0">
        <Icon className="w-4 h-4 text-gray-600" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-900">{displayName}</span>
          <span className="text-xs text-gray-400">
            {item.item_type} · {item.item_version || "latest"}
          </span>
          {!item.resolved && (
            <span className="text-xs text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
              Unresolved
            </span>
          )}
        </div>
        {description && (
          <p className="text-sm text-gray-600 line-clamp-2 mt-0.5">{description}</p>
        )}
      </div>
    </div>
  );
}
