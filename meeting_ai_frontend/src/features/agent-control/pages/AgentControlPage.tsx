import { useCallback, useEffect, useState } from "react";
import ScopeSidebar from "../components/ScopeSidebar";
import BehaviorEditor from "../components/BehaviorEditor";
import { behaviorApi } from "../services/behaviorApi";
import type { ActiveScope, ScopesResponse } from "../types";

/**
 * Phase 8E — Agent Control dashboard. Primary product UI.
 *
 * Renders WITHOUT the main app Layout wrapper: Agent Control takes
 * over the full viewport so users can edit behavior without the
 * meeting-app sidebar competing for horizontal space. An exit-app
 * link in the ScopeSidebar header sends users back to the dashboard.
 *
 *   ┌─────────────┬───────────────────────────────────────────────┐
 *   │  Workspace  │   Behavior editor (11 accordions)              │
 *   │  Categories │     · Master Prompt                            │
 *   │   Teams…    │     · Enabled Agents                           │
 *   │             │     · Retrieval / Memory / Output …            │
 *   └─────────────┴───────────────────────────────────────────────┘
 *
 * Every editable value carries an inheritance badge + Reset-to-Inherited.
 * The UI only writes sparse overrides — the resolver remains the source
 * of truth for the merged BehaviorProfile.
 */
export default function AgentControlPage() {
  const [scopes, setScopes] = useState<ScopesResponse | null>(null);
  const [scopesLoading, setScopesLoading] = useState(true);
  const [active, setActive] = useState<ActiveScope>({
    type: "workspace", id: null, display_name: "Workspace Defaults",
  });

  // Stable identity so BehaviorEditor's prop reference doesn't change
  // every render — prevents an infinite fetch loop in its useEffect.
  const loadScopes = useCallback(async () => {
    setScopesLoading(true);
    try {
      const data = await behaviorApi.scopes();
      setScopes(data);
    } finally {
      setScopesLoading(false);
    }
  }, []);

  useEffect(() => { loadScopes(); }, [loadScopes]);

  return (
    <div className="flex h-screen w-screen bg-[#fafafa] overflow-hidden">
      <ScopeSidebar
        data={scopes}
        loading={scopesLoading}
        active={active}
        onSelect={setActive}
      />
      <main className="flex-1 flex flex-col h-full overflow-hidden">
        <BehaviorEditor scope={active} onSidebarRefresh={loadScopes} />
      </main>
    </div>
  );
}
