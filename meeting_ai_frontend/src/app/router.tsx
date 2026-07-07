import { createBrowserRouter } from "react-router-dom";
import MeetingsPage from "../features/meetings/pages/MeetingPage";
import MeetingDetailPage from "../features/meetings/pages/MeetingDetailPage";
import MeetingTypesPage from "../features/meetings/pages/MeetingTypesPage";
import ActionItemsPage from "../features/meetings/pages/ActionItemsPage";
import LoginPage from "../features/auth/pages/LoginPage";
import RegisterPage from "../features/auth/pages/RegisterPage";
import GoogleCallbackPage from "../features/auth/pages/GoogleCallbackPage";
import ProtectedRoute from "../features/auth/components/ProtectedRoute";
import CalendarPage from "../features/calendar/pages/CalendarPage";
import AgentControlPage from "../features/agent-control/pages/AgentControlPage";
import HarnessRunsPage from "../features/agent-control/pages/HarnessRunsPage";
import HarnessMetricsPage from "../features/agent-control/pages/HarnessMetricsPage";
import AgentsListPage from "../features/agents/pages/AgentsListPage";
import AgentDetailPage from "../features/agents/pages/AgentDetailPage";
import KnowledgeHubPage from "../features/knowledge/pages/KnowledgeHubPage";
import KnowledgeGraphPage from "../features/knowledge/pages/KnowledgeGraphPage";
import DashboardPage from "../features/dashboard/pages/DashboardPage";
import AskPage from "../features/ask/pages/AskPage";
import IntegrationsPage from "../features/integrations/pages/IntegrationsPage";
import TemplatesLandingPage from "../features/templates/pages/TemplatesLandingPage";
import TemplatesBrowsePage from "../features/templates/pages/TemplatesBrowsePage";
import BundlePreviewPage from "../features/templates/pages/BundlePreviewPage";
import TemplatesInstalledPage from "../features/templates/pages/TemplatesInstalledPage";
import MembersPage from "../features/members/pages/MembersPage";
import ReportsPage from "../features/reports/pages/ReportsPage";
import BoardListPage from "../features/kanban/pages/BoardListPage";
import BoardLayout from "../features/kanban/pages/BoardLayout";
import BoardPage from "../features/kanban/pages/BoardPage";
import BoardSummaryPage from "../features/kanban/pages/BoardSummaryPage";
import SettingsPage from "../features/settings/pages/SettingsPage";

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/register",
    element: <RegisterPage />,
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: "/",
        element: <MeetingsPage />,
      },
      {
        path: "/meeting/:id",
        element: <MeetingDetailPage />,
      },
      {
        path: "/calendar",
        element: <CalendarPage />,
      },
      {
        path: "/meeting-types",
        element: <MeetingTypesPage />,
      },
      {
        path: "/action-items",
        element: <ActionItemsPage />,
      },
      {
        path: "/agent-control",
        element: <AgentControlPage />,
      },
      {
        path: "/agent-control/runs",
        element: <HarnessRunsPage />,
      },
      {
        path: "/agent-control/metrics",
        element: <HarnessMetricsPage />,
      },
      {
        path: "/agents",
        element: <AgentsListPage />,
      },
      {
        path: "/agents/:profileId",
        element: <AgentDetailPage />,
      },
      {
        path: "/knowledge-hub",
        element: <KnowledgeHubPage />,
      },
      {
        path: "/knowledge-graph",
        element: <KnowledgeGraphPage />,
      },
      {
        path: "/dashboard",
        element: <DashboardPage />,
      },
      {
        path: "/ask",
        element: <AskPage />,
      },
      {
        path: "/auth/google/callback",
        element: <GoogleCallbackPage />,
      },
      {
        path: "/integrations",
        element: <IntegrationsPage />,
      },
      {
        path: "/templates",
        element: <TemplatesLandingPage />,
      },
      {
        path: "/templates/browse",
        element: <TemplatesBrowsePage />,
      },
      {
        path: "/templates/browse/:slug",
        element: <BundlePreviewPage />,
      },
      {
        path: "/templates/installed",
        element: <TemplatesInstalledPage />,
      },
      {
        path: "/members",
        element: <MembersPage />,
      },
      {
        path: "/reports",
        element: <ReportsPage />,
      },
      {
        path: "/settings",
        element: <SettingsPage />,
      },
      {
        path: "/boards",
        element: <BoardListPage />,
      },
      {
        // Phase 14 — nested routes. BoardLayout owns Layout + the
        // useBoard fetch + the shared header + tabs, so switching
        // between Board view and Summary view doesn't remount any
        // of that. Children render via <Outlet />.
        path: "/board/:id",
        element: <BoardLayout />,
        children: [
          { index: true, element: <BoardPage /> },
          { path: "summary", element: <BoardSummaryPage /> },
        ],
      },
    ],
  },
]);