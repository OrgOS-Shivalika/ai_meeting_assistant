import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Cpu, Package, Plus } from "lucide-react";
import Layout from "../../../shared/components/Layout";
import { SkeletonCard } from "../../../shared/components/Skeleton";
import { templatesApi, type WorkspaceLink } from "../services/templatesApi";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { BackLink, PageContainer, PageHeader } from "@/components/ui/page-header";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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
      <PageContainer width="narrow">
        <BackLink as={Link} to="/templates">
          Marketplace
        </BackLink>
        <PageHeader
          title="Installed templates"
          size="sm"
          description={
            <>
              {links.length} bundle{links.length === 1 ? "" : "s"} active in this
              workspace. Tune the behavior per scope in{" "}
              <Link
                to="/agent-control"
                className="inline-flex items-center gap-1 font-semibold text-ink hover:underline"
              >
                <Cpu className="size-3.5" /> Agent control
              </Link>
              .
            </>
          }
          actions={
            <Button asChild>
              <Link to="/templates/browse">
                <Plus />
                Add bundle
              </Link>
            </Button>
          }
        />

        {loading ? (
          <SkeletonCard className="h-64 rounded-lg" />
        ) : error ? (
          <div className="rounded-lg border border-error/20 bg-error/8 p-4 text-[13px] font-medium text-error">
            {error}
          </div>
        ) : links.length === 0 ? (
          <EmptyState
            icon={Package}
            color="var(--vb-lavender)"
            title="Nothing installed yet"
            description="Install a bundle and it seeds categories, prompt configs and boards in one click."
            action={
              <Button asChild>
                <Link to="/templates/browse">Browse the catalog</Link>
              </Button>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Template</TableHead>
                <TableHead>Scope kind</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Provisioned</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {links.map((l) => (
                <TableRow key={l.id}>
                  <TableCell className="font-medium text-ink">
                    {l.source_template_slug}
                  </TableCell>
                  <TableCell className="text-body capitalize">
                    {l.source_template_kind}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-ink">
                    {l.source_template_version}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-ink">
                    {new Date(l.provisioned_at).toLocaleDateString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </PageContainer>
    </Layout>
  );
}
