import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Loader2, Package, Sparkles, Users, Tag } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { Skeleton, SkeletonCard } from "../../../shared/components/Skeleton";
import { templatesApi } from "../services/templatesApi";
import type { BundlePreview, BundlePreviewItem } from "../services/templatesApi";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IconChip } from "@/components/ui/icon-chip";
import { BackLink, PageContainer } from "@/components/ui/page-header";

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
        <PageContainer width="narrow" className="space-y-6">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-40 w-full rounded-2xl" />
          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-[1fr_260px]">
            <div className="space-y-2.5">
              {Array.from({ length: 4 }).map((_, i) => (
                <SkeletonCard key={i} className="h-18 rounded-md" />
              ))}
            </div>
            <SkeletonCard className="h-52 rounded-lg" />
          </div>
        </PageContainer>
      </Layout>
    );
  }
  if (error || !data) {
    return (
      <Layout>
        <PageContainer width="narrow">
          <BackLink as={Link} to="/templates/browse">
            Browse
          </BackLink>
          <div className="rounded-lg border border-error/20 bg-error/8 p-4 text-[13px] font-medium text-error">
            {error || "Bundle not found"}
          </div>
        </PageContainer>
      </Layout>
    );
  }

  return (
    <Layout>
      <PageContainer width="narrow">
        <BackLink as={Link} to="/templates/browse">
          Browse
        </BackLink>

        {/* Header band — the bundle's own saturated card. */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-6 rounded-2xl bg-pink p-9 text-white">
          <div className="flex items-center gap-[18px]">
            <span className="inline-flex size-15 items-center justify-center rounded-[16px] bg-white/20">
              <Package className="size-7" />
            </span>
            <div>
              <h1 className="flex flex-wrap items-center gap-2.5 font-display text-[30px] font-medium tracking-[-1px]">
                {data.display_name}
                {data.is_recommended_on_signup && (
                  <Badge variant="onDark">
                    <Sparkles className="size-2.5" />
                    Recommended
                  </Badge>
                )}
              </h1>
              <p className="mt-1.5 text-sm opacity-85">{data.description}</p>
            </div>
          </div>
          <Button onClick={handleInstall} disabled={installing}>
            {installing ? (
              <Loader2 className="animate-spin" />
            ) : (
              <CheckCircle2 />
            )}
            {installing ? "Installing…" : "Install bundle"}
          </Button>
        </div>

        {installResult && (
          <div className="mb-5 rounded-lg border border-success/25 bg-success/8 p-3.5 text-[13px] font-medium text-success">
            {installResult}
          </div>
        )}

        <div className="grid grid-cols-1 items-start gap-6 md:grid-cols-[1fr_260px]">
          {/* Contents */}
          <div>
            <h3 className="vb-title-md mb-3.5">What's included</h3>
            <div className="flex flex-col gap-2.5">
              {data.items.map((it) => (
                <ItemRow key={`${it.item_type}:${it.item_slug}`} item={it} />
              ))}
            </div>
          </div>

          {/* Meta */}
          <Card variant="default" className="p-5">
            <h3 className="vb-title-sm mb-3.5">Details</h3>
            <div className="flex flex-col gap-3 text-[13px]">
              <MetaRow label="Teams" value={data.counts.team || 0} mono />
              <MetaRow label="Categories" value={data.counts.category || 0} mono />
              <MetaRow label="Items" value={data.items.length} mono />
              <MetaRow label="Version" value={data.version} mono />
              <MetaRow label="Slug" value={data.slug} mono />
            </div>
          </Card>
        </div>
      </PageContainer>
    </Layout>
  );
}

function MetaRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | number;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-muted-ink">{label}</span>
      <span className={mono ? "truncate font-mono text-ink" : "truncate text-ink"}>
        {value}
      </span>
    </div>
  );
}

function ItemRow({ item }: { item: BundlePreviewItem }) {
  const Icon = ITEM_ICONS[item.item_type];
  const prof = item.profile;
  const displayName = (prof?.display_name as string) ?? item.item_slug;
  const description = prof?.description as string | null | undefined;
  // Team vs. category get distinct hues so a long list stays scannable.
  const hue = item.item_type === "team" ? "var(--vb-info)" : "var(--vb-pink)";
  return (
    <div className="flex items-center gap-3.5 rounded-md border border-hairline bg-canvas p-4">
      <IconChip color={hue} className="size-[38px] rounded-[11px] [&_svg]:size-4">
        <Icon />
      </IconChip>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-ink">{displayName}</span>
          {!item.resolved && <Badge variant="warning">Unresolved</Badge>}
        </div>
        {description && (
          <p className="mt-0.5 line-clamp-2 text-xs text-muted-ink">
            {description}
          </p>
        )}
      </div>
      <Badge variant="secondary" className="shrink-0 capitalize">
        {item.item_type} · {item.item_version || "latest"}
      </Badge>
    </div>
  );
}
