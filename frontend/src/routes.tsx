import { createBrowserRouter, Navigate } from "react-router-dom";
import AppShell from "./layout/AppShell";
import DashboardPage from "./features/dashboard/DashboardPage";
import AlertsPage from "./features/alerts/AlertsPage";
import FactoriesPage from "./features/factories/FactoriesPage";
import FactoryPage from "./features/factories/FactoryPage";
import SitePage from "./features/sites/SitePage";
import CameraCreatePage from "./features/cameras/CameraCreatePage";
import CameraPage from "./features/cameras/CameraPage";
import ReportsPage from "./features/reports/ReportsPage";
import RecordingsPage from "./features/recordings/RecordingsPage";
import LiveTab from "./features/cameras/LiveTab";
import ZonesTab from "./features/cameras/ZonesTab";
import RulesTab from "./features/cameras/RulesTab";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "alerts", element: <AlertsPage /> },
      { path: "factories", element: <FactoriesPage /> },
      { path: "factories/:fid", element: <FactoryPage /> },
      { path: "factories/:fid/reports", element: <ReportsPage /> },
      { path: "factories/:fid/recordings", element: <RecordingsPage /> },
      { path: "factories/:fid/sites/:sid", element: <SitePage /> },
      { path: "factories/:fid/sites/:sid/cameras/new", element: <CameraCreatePage /> },
      {
        path: "factories/:fid/sites/:sid/cameras/:cid",
        element: <CameraPage />,
        children: [
          { index: true, element: <Navigate to="live" replace /> },
          { path: "live", element: <LiveTab /> },
          { path: "zones", element: <ZonesTab /> },
          { path: "rules", element: <RulesTab /> },
        ],
      },
    ],
  },
]);
