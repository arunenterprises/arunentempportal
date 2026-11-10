import { useCallback, useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Plus, Search, Users, RefreshCw, Printer } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, Panel, Empty, Badge2 } from "@/components/common";
import EmployeeFormDialog from "@/components/EmployeeFormDialog";
import { AccessSwitch } from "@/components/EmployeeAccess";
import CredentialSlipsDialog, { SlipsPreview } from "@/components/CredentialSlips";
import { api, errMsg, fmtDate } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { can } from "@/lib/roles";

const SyncBar = ({ onDone }) => {
  const { user } = useAuth();
  const canEdit = can(user, "employees", "edit");
  const [last, setLast] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get("/admin/vendor-sync/status").then((r) => setLast(r.data)); }, []);
  const sync = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/admin/vendor-sync");
      if (data.status === "success") toast.success(`Synced: ${data.result.created} new, ${data.result.updated} updated, ${data.result.attendance_months_pushed} attendance month(s) sent`);
      else toast.error(data.error || data.detail || "Sync failed");
      api.get("/admin/vendor-sync/status").then((r) => setLast(r.data));
      onDone();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  return (
    <Panel className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-3" data-testid="vendor-sync-bar">
      <div>
        <div className="font-semibold"><a href="https://erp.arunenterprisespryg.in" target="_blank" rel="noreferrer" className="text-primary hover:underline" data-testid="main-erp-link">Arun Enterprises Main ERP Link</a></div>
        <div className="text-sm text-muted-foreground" data-testid="vendor-sync-status">
          Employees come from Arun Enterprises ERP (HR Management, Employee Code = primary key); attendance is sent back. Auto-sync every hour.
          {last && <> Last sync: {new Date(last.started_at).toLocaleString("en-IN")} · <span className={last.status === "success" ? "text-emerald-600" : "text-rose-600"}>{last.status}</span></>}
        </div>
      </div>
      {canEdit && <Button variant="outline" onClick={sync} disabled={busy} data-testid="vendor-sync-btn"><RefreshCw size={15} className={`mr-2 ${busy ? "animate-spin" : ""}`} />{busy ? "Syncing…" : "Sync now"}</Button>}
    </Panel>
  );
};

export default function AdminEmployees() {
  const { user } = useAuth();
  const canEdit = can(user, "employees", "edit");
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [slipsOpen, setSlipsOpen] = useState(false);
  const [slips, setSlips] = useState(null);
  const navigate = useNavigate();

  const load = useCallback(() => { api.get("/admin/employees").then((r) => setRows(r.data)); }, []);
  useEffect(() => { load(); }, [load]);

  const s = q.toLowerCase();
  const shown = rows.filter((e) => [e.name, e.employee_id, e.short_code, e.email, e.department, e.designation].some((v) => (v || "").toLowerCase().includes(s)));
  const missing = rows.filter((e) => !e.short_code).length;
  const genCodes = async () => {
    try {
      const { data } = await api.post("/admin/employees/short-codes/generate", { overwrite: false });
      toast.success(`Short code generated for ${data.generated} employee(s)`);
      load();
    } catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <div>
      <PageHeader eyebrow="People" title="Employees" desc="Create employee accounts and manage their records."
        action={<div className="flex flex-wrap gap-2">
          {canEdit && <>
          <Button onClick={genCodes} disabled={!missing} className="bg-emerald-600 hover:bg-emerald-700 text-white px-4" data-testid="generate-short-codes-btn">{missing ? `Create Short ID (${missing})` : "Short IDs ready"}</Button>
          <Button variant="outline" onClick={() => setSlipsOpen(true)} data-testid="credential-slips-btn"><Printer size={16} className="mr-2" />Credential slips</Button>
          <Button onClick={() => setOpen(true)} data-testid="add-employee-btn"><Plus size={16} className="mr-2" />Add employee</Button>
          </>}
        </div>} />
      <SyncBar onDone={load} />
      <Panel>
        <div className="relative mb-5 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, ID, short code, department…" className="pl-9" data-testid="employee-search-input" />
        </div>
        {shown.length ? (
          <div className="overflow-x-auto -mx-5 sm:-mx-6">
            <table className="rtable w-full text-sm min-w-[760px]" data-testid="employees-table">
              <thead>
                <tr className="text-left text-xs uppercase tracking-widest text-muted-foreground border-b">
                  <th className="px-5 sm:px-6 py-3 font-semibold">Employee</th>
                  <th className="px-3 py-3 font-semibold">Short Code / ID</th>
                  <th className="px-3 py-3 font-semibold">Department</th>
                  <th className="px-3 py-3 font-semibold">Designation</th>
                  <th className="px-3 py-3 font-semibold">Joined</th>
                  <th className="px-3 py-3 font-semibold">Status</th>
                  <th className="px-5 sm:px-6 py-3 font-semibold">Portal Live</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {shown.map((e) => (
                  <tr key={e.id} onClick={() => navigate(`/admin/employees/${e.id}`)} className="cursor-pointer hover:bg-slate-50 transition-colors" data-testid={`employee-row-${e.employee_id}`}>
                    <td className="px-5 sm:px-6 py-3">
                      <Link to={`/admin/employees/${e.id}`} onClick={(ev) => ev.stopPropagation()} className="font-semibold text-primary hover:underline" data-testid={`employee-link-${e.employee_id}`}>{e.name}</Link>
                      <div className="text-xs font-mono font-semibold text-slate-700 mt-0.5">{e.employee_id}</div>
                    </td>
                    <td className="px-3 py-3" data-label="Short Code / ID">{e.short_code ? <span className="inline-flex rounded-md bg-emerald-50 text-emerald-800 border border-emerald-200 px-2 py-0.5 font-mono text-xs font-bold tracking-wider" data-testid={`short-code-${e.short_code}`}>{e.short_code}</span> : <span className="text-xs text-muted-foreground">Not created</span>}</td>
                    <td className="px-3 py-3" data-label="Department">{e.department || "—"}</td>
                    <td className="px-3 py-3" data-label="Designation">{e.designation || "—"}</td>
                    <td className="px-3 py-3 whitespace-nowrap" data-label="Joined">{fmtDate(e.joining_date)}</td>
                    <td className="px-3 py-3" data-label="Status"><Badge2 tone={e.active !== false ? "approved" : "rejected"}>{e.active !== false ? "Active" : "Inactive"}</Badge2></td>
                    <td className="px-5 sm:px-6 py-3" data-label="Portal Live" onClick={(ev) => ev.stopPropagation()}>{canEdit ? <AccessSwitch employee={e} onChange={(u) => setRows((rs) => rs.map((x) => (x.id === u.id ? u : x)))} /> : <span className="text-xs font-semibold">{e.portal_enabled === false ? "Unlive" : "Live"}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty icon={Users} text={rows.length ? "No matching employees." : "No employees yet. Click “Add employee” to create the first account."} testId="employees-empty" />}
      </Panel>
      <EmployeeFormDialog open={open} onOpenChange={setOpen} onSaved={load} />
      <CredentialSlipsDialog open={slipsOpen} onOpenChange={setSlipsOpen} employees={rows} onIssued={(d) => { setSlips(d); load(); }} />
      <SlipsPreview data={slips} onClose={() => setSlips(null)} />
    </div>
  );
}
