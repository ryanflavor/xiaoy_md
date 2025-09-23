import { createBrowserRouter, Outlet } from "react-router-dom";
import { OverviewPage } from "@/pages/OverviewPage";
import { DrillControlPage } from "@/pages/DrillControlPage";
import { SubscriptionHealthPage } from "@/pages/SubscriptionHealthPage";
import { AuditTimelinePage } from "@/pages/AuditTimelinePage";
import { Layout } from "@/components";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <LayoutWrapper />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "drill", element: <DrillControlPage /> },
      { path: "health", element: <SubscriptionHealthPage /> },
      { path: "audit", element: <AuditTimelinePage /> },
    ],
  },
]);

function LayoutWrapper() {
  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}
