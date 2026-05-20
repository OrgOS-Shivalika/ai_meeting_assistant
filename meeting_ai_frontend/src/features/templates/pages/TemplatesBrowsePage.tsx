import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Sparkles, Package } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { templatesApi } from "../services/templatesApi";
import type { BundleSummary } from "../services/templatesApi";

export default function TemplatesBrowsePage() {
  const [bundles, setBundles] = useState<BundleSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await templatesApi.listBundles();
        if (!cancelled) setBundles(data);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <Layout>
      <div className="px-8 py-8 max-w-7xl mx-auto">
        <header className="mb-6">
          <Link to="/templates" className="text-sm text-indigo-600 hover:underline">
            ← Back to Templates
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-2">Template catalog</h1>
          <p className="text-sm text-gray-500 mt-1">
            Curated bundles of teams, meeting categories, and AI agents you
            can install into your workspace in one click.
          </p>
        </header>

        {loading ? (
          <div className="flex items-center justify-center py-20 text-gray-500">
            <Loader2 className="animate-spin w-5 h-5 mr-2" /> Loading bundles…
          </div>
        ) : error ? (
          <div className="p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
            {error}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {bundles.map((b) => (
              <Link
                key={b.id}
                to={`/templates/browse/${b.slug}`}
                className="block bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md transition relative"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 bg-indigo-100 rounded-lg flex items-center justify-center">
                      <Package className="w-4 h-4 text-indigo-600" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-900">{b.display_name}</h3>
                      <p className="text-xs text-gray-500">{b.slug}@{b.version}</p>
                    </div>
                  </div>
                  {b.is_recommended_on_signup && (
                    <span className="flex items-center gap-1 text-xs font-semibold text-amber-700 bg-amber-100 px-2 py-0.5 rounded-full">
                      <Sparkles className="w-3 h-3" /> Recommended
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-600 line-clamp-2">{b.description}</p>
                {b.category && (
                  <span className="inline-block mt-3 text-xs font-medium text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                    {b.category}
                  </span>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
