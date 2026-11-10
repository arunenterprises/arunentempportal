import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { LayoutDashboard, UserRound, CalendarClock, FileText, Wallet, Users, Inbox, BookOpen, ShieldCheck, UserCog } from "lucide-react";
import AdminUsers from "@/pages/admin/AdminUsers";
import { isStaff, homePath, can } from "@/lib/roles";
import AdminLoginActivity from "@/pages/admin/AdminLoginActivity";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import AppShell from "@/components/AppShell";
import Login from "@/pages/Login";
import EmpDashboard from "@/pages/employee/EmpDashboard";
import EmpProfile from "@/pages/employee/EmpProfile";
import EmpAttendance from "@/pages/employee/EmpAttendance";
import EmpRequests from "@/pages/employee/EmpRequests";
import EmpPayslips from "@/pages/employee/EmpPayslips";
import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminEmployees from "@/pages/admin/AdminEmployees";
import AdminEmployeeDetail from "@/pages/admin/AdminEmployeeDetail";
import AdminAttendance from "@/pages/admin/AdminAttendance";
import AdminRequests from "@/pages/admin/AdminRequests";
import AdminPayslips from "@/pages/admin/AdminPayslips";
import AdminServiceBook from "@/pages/admin/AdminServiceBook";

const EMP_NAV = [
  { key: "home", to: "/employee", label: "Home", icon: LayoutDashboard, end: true },
  { key: "profile", to: "/employee/profile", label: "Profile", icon: UserRound },
  { key: "attendance", to: "/employee/attendance", label: "Attendance", icon: CalendarClock },
  { key: "requests", to: "/employee/requests", label: "Requests", icon: FileText },
  { key: "payslips", to: "/employee/payslips", label: "Payslips", icon: Wallet },
];

const ADMIN_NAV = [
  { key: "home", to: "/admin", label: "Dashboard", icon: LayoutDashboard, end: true },
  { key: "employees", to: "/admin/employees", label: "Employees", icon: Users },
  { key: "service-book", to: "/admin/service-book", label: "Service Book", icon: BookOpen },
  { key: "attendance", to: "/admin/attendance", label: "Attendance", icon: CalendarClock },
  { key: "requests", to: "/admin/requests", label: "Requests", icon: Inbox },
  { key: "payslips", to: "/admin/payslips", label: "Payslips", icon: Wallet },
  { key: "logins", to: "/admin/login-activity", label: "Logins", icon: ShieldCheck },
  { key: "users", to: "/admin/users", label: "Users", icon: UserCog, superadmin: true },
];

const Loader = () => (
  <div className="min-h-screen grid place-items-center text-muted-foreground" data-testid="app-loading">Loading…</div>
);

const Guard = ({ role, children }) => {
  const { user } = useAuth();
  if (user === null) return <Loader />;
  if (!user) return <Navigate to="/login" replace />;
  const area = isStaff(user) ? "staff" : "employee";
  if (area !== role) return <Navigate to={homePath(user)} replace />;
  return children;
};

const Perm = ({ m, children }) => {
  const { user } = useAuth();
  const ok = m === "superadmin" ? user?.role === "superadmin" : can(user, m, "view");
  return ok ? children : <Navigate to="/admin" replace />;
};

const Home = () => {
  const { user } = useAuth();
  if (user === null) return <Loader />;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={homePath(user)} replace />;
};

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/employee" element={<Guard role="employee"><AppShell nav={EMP_NAV} area="Employee Portal" /></Guard>}>
              <Route index element={<EmpDashboard />} />
              <Route path="profile" element={<EmpProfile />} />
              <Route path="attendance" element={<EmpAttendance />} />
              <Route path="requests" element={<EmpRequests />} />
              <Route path="payslips" element={<EmpPayslips />} />
            </Route>
            <Route path="/admin" element={<Guard role="staff"><AppShell nav={ADMIN_NAV} area="HR Admin" /></Guard>}>
              <Route index element={<AdminDashboard />} />
              <Route path="employees" element={<Perm m="employees"><AdminEmployees /></Perm>} />
              <Route path="employees/:id" element={<Perm m="employees"><AdminEmployeeDetail /></Perm>} />
              <Route path="attendance" element={<Perm m="attendance"><AdminAttendance /></Perm>} />
              <Route path="requests" element={<Perm m="requests"><AdminRequests /></Perm>} />
              <Route path="payslips" element={<Perm m="payslips"><AdminPayslips /></Perm>} />
              <Route path="service-book" element={<Perm m="service_book"><AdminServiceBook /></Perm>} />
              <Route path="login-activity" element={<Perm m="logins"><AdminLoginActivity /></Perm>} />
              <Route path="users" element={<Perm m="superadmin"><AdminUsers /></Perm>} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-center" richColors />
      </AuthProvider>
    </div>
  );
}

export default App;
