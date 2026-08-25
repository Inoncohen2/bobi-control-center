/** Routes only. Page logic lives in `src/pages` and `src/features`. */

import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from '@/layouts/AppLayout';
import { AuditPage } from '@/pages/AuditPage';
import { AutomationsPage } from '@/pages/AutomationsPage';
import { CapabilitiesPage } from '@/pages/CapabilitiesPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { DevicesPage } from '@/pages/DevicesPage';
import { DiagnosticsPage } from '@/pages/DiagnosticsPage';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { NotificationsPage } from '@/pages/NotificationsPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { ShabbatPage } from '@/pages/ShabbatPage';
import { TasksPage } from '@/pages/TasksPage';
import { TestCenterPage } from '@/pages/TestCenterPage';
import { TestsPage } from '@/pages/TestsPage';
import { UsersPage } from '@/pages/UsersPage';

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="capabilities" element={<CapabilitiesPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="automations" element={<AutomationsPage />} />
        <Route path="shabbat" element={<ShabbatPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="test-center" element={<TestCenterPage />} />
        <Route path="tests" element={<TestsPage />} />
        <Route path="diagnostics" element={<DiagnosticsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="index.html" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
