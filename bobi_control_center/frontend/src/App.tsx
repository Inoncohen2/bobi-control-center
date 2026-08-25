/** Routes only. Page logic lives in `src/pages` and `src/features`. */

import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from '@/layouts/AppLayout';
import { CapabilitiesPage } from '@/pages/CapabilitiesPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { DevicesPage } from '@/pages/DevicesPage';
import { DiagnosticsPage } from '@/pages/DiagnosticsPage';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { RulesPage } from '@/pages/RulesPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { ShabbatPage } from '@/pages/ShabbatPage';
import { TasksPage } from '@/pages/TasksPage';
import { TestCenterPage } from '@/pages/TestCenterPage';
import { UsersPage } from '@/pages/UsersPage';

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="capabilities" element={<CapabilitiesPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="rules" element={<RulesPage />} />
        {/* Phase 1 called this screen "automations"; keep old links working. */}
        <Route path="automations" element={<Navigate to="/rules" replace />} />
        <Route path="shabbat" element={<ShabbatPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="test-center" element={<TestCenterPage />} />
        <Route path="diagnostics" element={<DiagnosticsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
