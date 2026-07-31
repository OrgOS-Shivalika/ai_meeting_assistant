import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Cpu, Package, Layers } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { templatesApi, type LinkSummary } from "../services/templatesApi";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageContainer } from "@/components/ui/page-header";
import { accent, tint } from "@/lib/vibrant";

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
      <PageContainer width="default">
        {/* Marketplace hero — one lavender feature card, 28px radius. */}
        <div className="relative mb-5 overflow-hidden rounded-3xl bg-lavender p-11">
          <div className="pointer-events-none absolute -top-10 -right-5 size-56 rounded-full bg-white/25" />
          <div className="relative max-w-[560px]">
            <p className="mb-3.5 text-xs font-semibold tracking-[1.5px] text-ink/70 uppercase">
              Template marketplace
            </p>
            <h1 className="mb-3.5 font-display text-[40px] leading-[1.05] font-medium tracking-[-1.6px] text-ink">
              Bootstrap your workspace in an afternoon.
            </h1>
            <p className="mb-6 text-[15px] leading-relaxed text-ink/80">
              Install ready-made agent bundles — categories, prompt configs and
              boards — tuned for how your team meets. Customize the behavior
              afterwards in Agent Control.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild>
                <Link to="/templates/browse">
                  Browse templates
                  <ArrowRight />
                </Link>
              </Button>
              <Button variant="onColor" asChild>
                <Link to="/templates/installed">Installed</Link>
              </Button>
            </div>
          </div>
        </div>

        <h2 className="vb-title-lg mt-7 mb-4">Browse by use case</h2>
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <ActionCard
            icon={Package}
            title="Browse catalog"
            description="Available bundles and behavior profiles. Install with one click."
            href="/templates/browse"
            tone={0}
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
            tone={1}
          />
          <ActionCard
            icon={Cpu}
            title="Agent control"
            description="Tune the agents' behavior across categories and teams."
            href="/agent-control"
            tone={2}
          />
        </section>

        {summary && summary.total > 0 && (
          <Card variant="default" className="mt-5 rounded-xl p-6">
            <h2 className="vb-title-md mb-3.5">Installed breakdown</h2>
            <ul className="flex flex-col gap-2.5">
              {Object.entries(summary.by_source_template_kind).map(([k, v]) => (
                <li
                  key={k}
                  className="flex justify-between border-b border-hairline-soft pb-2.5 text-[13px] last:border-0 last:pb-0"
                >
                  <span className="text-body capitalize">{k}</span>
                  <span className="font-mono text-ink">{v}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </PageContainer>
    </Layout>
  );
}

function ActionCard({
  icon: Icon,
  title,
  description,
  href,
  tone = 0,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  href: string;
  /** Position in the accent cycle. */
  tone?: number;
}) {
  const hue = accent(tone);
  return (
    <Link to={href} className="group block h-full">
      <Card variant="default" className="h-full rounded-xl p-6">
        <span
          className="mb-4 inline-flex size-10 items-center justify-center rounded-md"
          style={{ background: tint(hue, 14), color: hue }}
        >
          <Icon className="size-[19px]" />
        </span>
        <div className="flex items-center gap-2">
          <h3 className="vb-title-md">{title}</h3>
          <ArrowRight className="ml-auto size-4 text-muted-soft transition-transform group-hover:translate-x-0.5 group-hover:text-ink" />
        </div>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted-ink">
          {description}
        </p>
      </Card>
    </Link>
  );
}
