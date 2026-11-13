import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Loading } from "./components/states";

// Each screen loads on first visit, so the map and chart libraries arrive only where they are used.
const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const FieldMap = lazy(() => import("./pages/FieldMap").then((m) => ({ default: m.FieldMap })));
const AssetExplorer = lazy(() => import("./pages/AssetExplorer").then((m) => ({ default: m.AssetExplorer })));
const TelemetryLab = lazy(() => import("./pages/TelemetryLab").then((m) => ({ default: m.TelemetryLab })));
const AerialInspection = lazy(() => import("./pages/AerialInspection").then((m) => ({ default: m.AerialInspection })));
const DecisionCenter = lazy(() => import("./pages/DecisionCenter").then((m) => ({ default: m.DecisionCenter })));
const Maintenance = lazy(() => import("./pages/Maintenance").then((m) => ({ default: m.Maintenance })));
const DataLineage = lazy(() => import("./pages/DataLineage").then((m) => ({ default: m.DataLineage })));
const ExperimentReports = lazy(() => import("./pages/ExperimentReports").then((m) => ({ default: m.ExperimentReports })));
const NotFound = lazy(() => import("./pages/NotFound").then((m) => ({ default: m.NotFound })));

export function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading label="Loading screen" />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="map" element={<FieldMap />} />
            <Route path="assets" element={<AssetExplorer />} />
            <Route path="assets/:assetId" element={<AssetExplorer />} />
            <Route path="telemetry" element={<TelemetryLab />} />
            <Route path="aerial" element={<AerialInspection />} />
            <Route path="decisions" element={<DecisionCenter />} />
            <Route path="maintenance" element={<Maintenance />} />
            <Route path="lineage" element={<DataLineage />} />
            <Route path="reports" element={<ExperimentReports />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
