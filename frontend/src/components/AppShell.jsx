import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LogOut, KeyRound } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import ChangePasswordForm from "@/components/ChangePasswordForm";
import { useAuth } from "@/context/AuthContext";
import { isStaff, can, ROLE_LABEL, NAV_MODULE } from "@/lib/roles";

const initials = (n = "") => n.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();

const Brand = ({ area }) => (
  <div className="flex items-center gap-3">
    <img src="/arun-logo.jpg" alt="Arun Enterprises logo" className="h-10 w-10 rounded-lg object-contain p-0.5 bg-white shrink-0" data-testid="shell-logo" />
    <div className="leading-tight">
      <div className="font-display font-bold text-lg tracking-tight">ARUN ENTERPRISES</div>
      <div className="text-[10px] uppercase tracking-[0.2em] opacity-60">{area}</div>
    </div>
  </div>
);

export default function AppShell({ nav: allNav, area: baseArea }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const doLogout = () => { logout(); navigate("/login"); };
  const [pwOpen, setPwOpen] = useState(false);
  const isAdmin = isStaff(user);
  const roleLabel = ROLE_LABEL[user?.role] || "";
  const area = isAdmin ? `${roleLabel} Console` : baseArea;
  const nav = isAdmin ? allNav.filter((n) => (n.superadmin ? user.role === "superadmin" : !NAV_MODULE[n.key] || can(user, NAV_MODULE[n.key], "view"))) : allNav;
  const pwBtn = (cls, testId) => isAdmin && (
    <button onClick={() => setPwOpen(true)} data-testid={testId} className={cls} aria-label="Change password" title="Change password"><KeyRound size={16} /></button>
  );

  return (
    <div className="min-h-screen bg-background">
      <aside className="hidden md:flex fixed inset-y-0 left-0 w-64 flex-col bg-[hsl(var(--sidebar))] text-slate-100 grid-bg">
        <div className="px-6 py-7"><Brand area={area} /></div>
        <nav className="flex-1 px-3 space-y-1">
          {nav.map(({ key, to, label, icon: Icon, end }) => (
            <NavLink key={key} to={to} end={end} data-testid={`nav-${key}`}
              className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${isActive ? "bg-primary text-white" : "text-slate-300 hover:bg-white/10 hover:text-white"}`}>
              <Icon size={18} />{label}
            </NavLink>
          ))}
        </nav>
        <div className="m-3 rounded-xl bg-white/5 border border-white/10 p-3 flex items-center gap-3">
          <div className="h-9 w-9 rounded-full bg-slate-700 grid place-items-center text-xs font-bold">{initials(user?.name)}</div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold truncate" data-testid="nav-user-name">{user?.name}</div>
            {isAdmin && <div className="inline-flex rounded bg-amber-400/90 text-slate-900 px-1.5 py-px text-[10px] font-bold uppercase tracking-wider my-0.5" data-testid="nav-user-role">{roleLabel}</div>}
            <div className="text-xs text-slate-400 truncate">{user?.short_code ? `${user.short_code} · ` : ""}{user?.employee_id || user?.email}</div>
          </div>
          {pwBtn("p-2 rounded-md text-slate-300 hover:text-white hover:bg-white/10 transition-colors", "admin-change-password-btn")}
          <button onClick={doLogout} data-testid="nav-logout-btn" className="p-2 rounded-md text-slate-300 hover:text-white hover:bg-white/10 transition-colors" aria-label="Logout"><LogOut size={16} /></button>
        </div>
      </aside>

      <header className="md:hidden sticky top-0 z-30 bg-[hsl(var(--sidebar))] text-white px-4 py-3 flex items-center justify-between">
        <Brand area={area} />
        <div className="flex items-center">
          {isAdmin && <span className="mr-1 rounded bg-amber-400 text-slate-900 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider" data-testid="mobile-user-role">{roleLabel}</span>}
          {pwBtn("p-2 rounded-md hover:bg-white/10", "mobile-admin-change-password-btn")}
          <button onClick={doLogout} data-testid="mobile-logout-btn" className="p-2 rounded-md hover:bg-white/10" aria-label="Logout"><LogOut size={18} /></button>
        </div>
      </header>

      <Dialog open={pwOpen} onOpenChange={setPwOpen}>
        <DialogContent className="max-w-sm" data-testid="admin-change-password-dialog">
          <DialogHeader><DialogTitle className="font-display">Change password</DialogTitle></DialogHeader>
          <ChangePasswordForm onDone={() => setPwOpen(false)} />
        </DialogContent>
      </Dialog>

      <main className="md:pl-64 pb-24 md:pb-12">
        <div className="max-w-6xl mx-auto px-4 sm:px-8 py-6 sm:py-10"><Outlet /></div>
      </main>

      <nav className="md:hidden fixed bottom-0 inset-x-0 z-30 bg-white border-t grid" style={{ gridTemplateColumns: `repeat(${nav.length}, minmax(0, 1fr))` }}>
        {nav.map(({ key, to, label, icon: Icon, end }) => (
          <NavLink key={key} to={to} end={end} data-testid={`mnav-${key}`}
            className={({ isActive }) => `flex flex-col items-center gap-1 py-2.5 px-0.5 text-[10px] leading-tight text-center font-medium whitespace-nowrap overflow-hidden ${isActive ? "text-primary" : "text-slate-500"}`}>
            <Icon size={20} /><span className="truncate max-w-full">{nav.length > 5 ? ({ Dashboard: "Home", Employees: "Staff", "Service Book": "Book", Attendance: "Attend" }[label] || label) : label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
