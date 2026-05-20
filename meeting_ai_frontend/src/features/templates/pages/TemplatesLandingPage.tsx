import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Cpu, Package, Layers } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { templatesApi, type LinkSummary } from "../services/templatesApi";

/**
 * Phase 8F refactor — templates landing reduced to an install hub.
 * The real product surface is Agent Control. This page exists for
 * "install or change templates" intent.
 */
export default function TemplatesLandingPage() {
  const [summary, setSummary] = useState<LinkSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await templatesApi.linksSummary();
        if (!cancelled) setSummary(s);
      } catch {
        // soft-fail: page still renders the action tiles
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <Layout>
      <div className="px-8 py-8 max-w-5xl mx-auto">
        <header className="mb-8">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-gray-400">
            Templates
          </p>
          <h1 className="text-2xl font-bold text-gray-900 mt-1">
            Behavior templates
          </h1>
          <p className="text-sm text-gray-500 mt-1 max-w-2xl">
            Templates distribute prebuilt AI behavior profiles into your
            workspace. After installing, customize behavior in{" "}
            <Link to="/agent-control" className="text-indigo-600 underline">
              Agent Control
            </Link>
            .
          </p>
        </header>

        <section className="grid grid-cols-3 gap-4 mb-8">
          <ActionCard
            icon={Package}
            title="Browse catalog"
            description="See available bundles + behavior profiles. Install with one click."
            href="/templates/browse"
          />
          <ActionCard
            icon={Layers}
            title="Installed templates"
            description={
              loading
                ? "Counting…"
                : summary
                ? `${summary.total} link${summary.total === 1 ? "" : "s"} active in your workspace.`
                : "Templates installed in this workspace."
            }
            href="/templates/installed"
          />
          <ActionCard
            icon={Cpu}
            title="Agent Control"
            description="Customize the AI's behavior across categories + teams."
            href="/agent-control"
            primary
          />
        </section>

        {summary && summary.total > 0 && (
          <section className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">
              Installed breakdown
            </h2>
            <ul className="space-y-1.5">
              {Object.entries(summary.by_source_template_kind).map(([k, v]) => (
                <li key={k} className="flex justify-between text-sm">
                  <span className="text-gray-700 capitalize">{k}</span>
                  <span className="font-semibold text-gray-900">{v}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Layout>
  );
}

function ActionCard({
  icon: Icon, title, description, href, primary = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  href: string;
  primary?: boolean;
}) {
  return (
    <Link
      to={href}
      className={`block rounded-xl border p-5 hover:shadow-sm transition ${
        primary
          ? "bg-indigo-50 border-indigo-200"
          : "bg-white border-gray-200"
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`w-5 h-5 ${primary ? "text-indigo-600" : "text-gray-500"}`} />
        <h3 className="font-semibold text-gray-900">{title}</h3>
        <ArrowRight className="w-4 h-4 text-gray-300 ml-auto" />
      </div>
      <p className="text-sm text-gray-600">{description}</p>
    </Link>
  );
}
