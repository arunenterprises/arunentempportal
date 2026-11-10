import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Users, UserCheck, Hourglass, Plane, ArrowRight, AlarmClock } from "lucide-react";
import { PageHeader, Panel, StatCard, Empty } from "@/components/common";
import RequestItem from "@/components/RequestItem";
import AttendanceTable from "@/components/AttendanceTable";
import { api, fmtDate } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { can } from "@/lib/roles";

export default function AdminDashboard() {
  const [s, setS] = useState(null);
  const [reqs, setReqs] = useState([]);
  const [att, setAtt] = useState([]);

  const { user } = useAuth();
  useEffect(() => {
    api.get("/admin/stats").then((r) => {
      setS(r.data);
      if (can(user, "attendance")) { api.get("/admin/attendance", { params: { date: r.data.today } }).then((a) => setAtt(a.data)).catch(() => {}); }
    }).catch(() => {});
    if (can(user, "requests")) { api.get("/admin/requests", { params: { status: "pending" } }).then((r) => setReqs(r.data.slice(0, 4))).catch(() => {}); }
  }, [user]);

  return (
    <div className="space-y-8">
      <PageHeader eyebrow="HR Overview" title="Dashboard" desc={s ? `Today · ${fmtDate(s.today)}` : ""} />
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 sm:gap-4" data-testid="admin-stats-grid">
        <StatCard compact icon={Users} label="Active employees" value={s?.employees ?? "–"} testId="stat-employees" />
        <StatCard compact icon={UserCheck} label="Present today" value={s?.present_today ?? "–"} testId="stat-present-today" tone="bg-emerald-50 text-emerald-600" delay={60} />
        <StatCard compact icon={AlarmClock} label="Late today" value={s?.late_today ?? "–"} testId="stat-late-today" tone="bg-orange-50 text-orange-600" delay={90} />
        <StatCard compact icon={Hourglass} label="Pending requests" value={s?.pending_requests ?? "–"} testId="stat-pending-requests" tone="bg-amber-50 text-amber-600" delay={120} />
        <StatCard compact icon={Plane} label="On leave today" value={s?.on_leave_today ?? "–"} testId="stat-on-leave" tone="bg-rose-50 text-rose-600" delay={180} className="col-span-2 md:col-span-1" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <Panel className="lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-display text-lg font-semibold">Pending approvals</h3>
            <Link to="/admin/requests" className="text-sm font-semibold text-primary hover:underline inline-flex items-center gap-1" data-testid="goto-admin-requests">All <ArrowRight size={14} /></Link>
          </div>
          <div className="space-y-3">{reqs.length ? reqs.map((r) => <RequestItem key={r.id} r={r} showEmployee />) : <Empty text="All caught up." />}</div>
        </Panel>
        <Panel className="lg:col-span-3 min-w-0">
          <h3 className="font-display text-lg font-semibold mb-4">Today's attendance</h3>
          <AttendanceTable rows={att} showEmployee />
        </Panel>
      </div>
    </div>
  );
}
