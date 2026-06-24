import { jsx as _jsx } from "react/jsx-runtime";
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
        element: _jsx(AppShell, {}),
        children: [
            { index: true, element: _jsx(Navigate, { to: "/dashboard", replace: true }) },
            { path: "dashboard", element: _jsx(DashboardPage, {}) },
            { path: "alerts", element: _jsx(AlertsPage, {}) },
            { path: "factories", element: _jsx(FactoriesPage, {}) },
            { path: "factories/:fid", element: _jsx(FactoryPage, {}) },
            { path: "factories/:fid/reports", element: _jsx(ReportsPage, {}) },
            { path: "factories/:fid/recordings", element: _jsx(RecordingsPage, {}) },
            { path: "factories/:fid/sites/:sid", element: _jsx(SitePage, {}) },
            { path: "factories/:fid/sites/:sid/cameras/new", element: _jsx(CameraCreatePage, {}) },
            {
                path: "factories/:fid/sites/:sid/cameras/:cid",
                element: _jsx(CameraPage, {}),
                children: [
                    { index: true, element: _jsx(Navigate, { to: "live", replace: true }) },
                    { path: "live", element: _jsx(LiveTab, {}) },
                    { path: "zones", element: _jsx(ZonesTab, {}) },
                    { path: "rules", element: _jsx(RulesTab, {}) },
                ],
            },
        ],
    },
]);
