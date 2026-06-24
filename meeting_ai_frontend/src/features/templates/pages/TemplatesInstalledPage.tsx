import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Cpu } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { SkeletonCard } from "../../../shared/components/Skeleton";
import { templatesApi, type WorkspaceLink } from "../services/templatesApi";

/**
 * Phase 8F refactor — simple list of installed template links.
 * No drift/lineage state (overrides system replaces that). To
 * customize, users go to Agent Control.
 */
export default function TemplatesInstalledPage() {
  const [links, setLinks] = useState<WorkspaceLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await templatesApi.listLinks();
        if (!cancelled) setLinks(rows);
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
      <div className="px-8 py-8 max-w-6xl mx-auto">
        <header className="mb-4">
          <Link to="/templates" className="text-sm text-indigo-600 hover:underline">
            ← Back to Templates
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-2">
            Installed templates
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Templates pinned in this workspace. Edit AI behavior per
            scope in{" "}
            <Link to="/agent-control" className="text-indigo-600 inline-flex items-center gap-1">
              <Cpu className="w-3.5 h-3.5" /> Agent Control
            </Link>
            .
          </p>
        </header>

        {loading ? (
          <SkeletonCard className="h-64" />
        ) : error ? (
          <div className="p-4 bg-red-50 border border-red-200 text-red-800 rounded-lg">
            {error}
          </div>
        ) : links.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-500">
            No templates installed yet.{" "}
            <Link to="/templates/browse" className="text-indigo-600 underline">
              Browse the catalog
            </Link>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Template
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Scope kind
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Version
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Provisioned
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {links.map((l) => (
                  <tr key={l.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {l.source_template_slug}
                    </td>
                    <td className="px-4 py-3 text-gray-600 capitalize">
                      {l.source_template_kind}
                    </td>
                    <td className="px-4 py-3 text-gray-600 font-mono text-xs">
                      {l.source_template_version}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {new Date(l.provisioned_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}
