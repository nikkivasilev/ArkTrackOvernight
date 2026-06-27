import { createBrowserRouter, Navigate } from "react-router-dom";
import AppShell from "./layout/AppShell";
import DashboardPage from "./features/dashboard/DashboardPage";
import FactoriesPage from "./features/factories/FactoriesPage";
import FactoryPage from "./features/factories/FactoryPage";
import SitePage from "./features/sites/SitePage";
import CameraPage from "./features/cameras/CameraPage";
import RecordingsPage from "./features/recordings/RecordingsPage";
import AnalysisTab from "./features/cameras/AnalysisTab";
import ZonesTab from "./features/cameras/ZonesTab";
import RulesTab from "./features/cameras/RulesTab";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "factories", element: <FactoriesPage /> },
      { path: "factories/:fid", element: <FactoryPage /> },
      { path: "factories/:fid/recordings", element: <RecordingsPage /> },
      { path: "factories/:fid/sites/:sid", element: <SitePage /> },
      {
        path: "factories/:fid/sites/:sid/cameras/:cid",
        element: <CameraPage />,
        children: [
          { index: true, element: <Navigate to="analysis" replace /> },
          { path: "analysis", element: <AnalysisTab /> },
          { path: "zones", element: <ZonesTab /> },
          { path: "rules", element: <RulesTab /> },
        ],
      },
    ],
  },
]);
