import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppLayout } from '../components/AppLayout'
import { AttackPathsPage } from '../pages/AttackPathsPage'
import { LoginPage } from '../pages/LoginPage'
import { MonitorPage } from '../pages/MonitorPage'
import { ProjectCreatePage } from '../pages/ProjectCreatePage'
import { ProjectDetailPage } from '../pages/ProjectDetailPage'
import { ProjectListPage } from '../pages/ProjectListPage'
import { ReportPage } from '../pages/ReportPage'
import { SettingsPage } from '../pages/SettingsPage'
import { VulnerabilitiesPage } from '../pages/VulnerabilitiesPage'
import { useAuthStore } from '../store/auth'

function RequireAuth({ children }: { children: ReactNode }) {
  const token = useAuthStore((state) => state.token)
  const location = useLocation()
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}

function RequireAdmin({ children }: { children: ReactNode }) {
  const user = useAuthStore((state) => state.user)
  if (user?.role !== 'admin') {
    return <Navigate to="/projects" replace />
  }
  return <>{children}</>
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/projects" element={<ProjectListPage />} />
        <Route path="/projects/new" element={<ProjectCreatePage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route path="/projects/:id/monitor" element={<MonitorPage />} />
        <Route
          path="/projects/:id/vulnerabilities"
          element={<VulnerabilitiesPage />}
        />
        <Route path="/projects/:id/attack-paths" element={<AttackPathsPage />} />
        <Route path="/projects/:id/report" element={<ReportPage />} />
        <Route
          path="/settings"
          element={
            <RequireAdmin>
              <SettingsPage />
            </RequireAdmin>
          }
        />
      </Route>
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}
