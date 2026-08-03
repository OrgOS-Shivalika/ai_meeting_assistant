import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download, Layers, Package, Sparkles } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { SkeletonCard } from "../../../shared/components/Skeleton";
import { templatesApi } from "../services/templatesApi";
import type { BundleSummary } from "../services/templatesApi";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { BackLink, PageContainer, PageHeader } from "@/components/ui/page-header";
import { accent, tint } from "@/lib/vibrant";

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
      <PageContainer width="default">
        <BackLink as={Link} to="/templates">
          Marketplace
        </BackLink>
        <PageHeader
          title="Browse templates"
          size="sm"
          description={
            loading
              ? "Curated bundles of teams, meeting categories and agents."
              : `${bundles.length} bundle${bundles.length === 1 ? "" : "s"} you can install into your workspace.`
          }
        />

        {loading ? (
          <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} className="h-56 rounded-xl" />
            ))}
          </div>
        ) : error ? (
          <div className="rounded-lg border border-error/20 bg-error/8 p-4 text-[13px] font-medium text-error">
            {error}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-3">
            {bundles.map((b, index) => {
              const hue = accent(index);
              return (
                <Link key={b.id} to={`/templates/browse/${b.slug}`}>
                  <Card
                    variant="default"
                    className="h-full overflow-hidden rounded-xl transition-colors hover:border-muted-soft"
                  >
                    {/* Colour band — the bundle's hue, cycled across the grid. */}
                    <div
                      className="flex h-24 items-center px-6"
                      style={{ background: tint(hue, 14) }}
                    >
                      <Package className="size-8" style={{ color: hue }} />
                    </div>
                    <div className="p-5">
                      <div className="mb-1.5 flex items-start justify-between gap-2">
                        <h3 className="vb-title-md text-[17px]">
                          {b.display_name}
                        </h3>
                        {b.is_recommended_on_signup && (
                          <Badge variant="warning" className="shrink-0">
                            <Sparkles className="size-2.5" />
                            Recommended
                          </Badge>
                        )}
                      </div>
                      <p className="mb-4 line-clamp-2 min-h-9.5 text-[13px] leading-relaxed text-muted-ink">
                        {b.description}
                      </p>
                      <div className="flex items-center gap-3.5 font-mono text-xs text-muted-ink">
                        <span className="inline-flex items-center gap-1.5">
                          <Download className="size-3.5" />
                          {b.slug}
                        </span>
                        <span className="inline-flex items-center gap-1.5">
                          <Layers className="size-3.5" />v{b.version}
                        </span>
                        {b.category && (
                          <Badge variant="secondary" className="ml-auto">
                            {b.category}
                          </Badge>
                        )}
                      </div>
                    </div>
                  </Card>
                </Link>
              );
            })}
          </div>
        )}
      </PageContainer>
    </Layout>
  );
}
