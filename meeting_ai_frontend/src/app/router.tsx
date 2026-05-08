import { createBrowserRouter } from "react-router-dom";
import MeetingsPage from "../features/meetings/pages/MeetingPage";
import MeetingDetailPage from "../features/meetings/pages/MeetingDetailPage";
import MeetingTypesPage from "../features/meetings/pages/MeetingTypesPage";
import LoginPage from "../features/auth/pages/LoginPage";
import RegisterPage from "../features/auth/pages/RegisterPage";
import GoogleCallbackPage from "../features/auth/pages/GoogleCallbackPage";
import ProtectedRoute from "../features/auth/components/ProtectedRoute";
import CalendarPage from "../features/calendar/pages/CalendarPage";
import AgentControlPage from "../features/agent-control/pages/AgentControlPage";

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
        path: "/agent-control",
        element: <AgentControlPage />,
      },
      {
        path: "/auth/google/callback",
        element: <GoogleCallbackPage />,
      },
    ],
  },
]);