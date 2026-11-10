import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { ArrowLeft, Pencil, Trash2, KeyRound, Printer, BookOpen } from "lucide-react";
import { LeaveBalanceAdmin } from "@/components/LeaveBalance";
import { AppraisalsModule, AttendanceModule, RequestsModule, PayslipsModule } from "@/components/EmployeeModules";
import { SlipsPreview, issueSlips } from "@/components/CredentialSlips";
import MediaCard from "@/components/MediaCard";
import { ResetPasswordDialog, AccessSwitch } from "@/components/EmployeeAccess";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Panel, Info, Field, NativeSelect, ShortBadge } from "@/components/common";
import { ShortCodeControl } from "@/components/ShortCodeControl";
import EmployeeFormDialog from "@/components/EmployeeFormDialog";
import ServiceTimeline from "@/components/ServiceTimeline";
import SalaryBreakup from "@/components/SalaryBreakup";
import { api, errMsg, fmtDate, fmtINR, localDate } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { can } from "@/lib/roles";

const TYPES = ["promotion", "transfer", "increment", "appraisal", "training", "award", "joining", "other"];

export const AddRecord = ({ userId, onAdded, onCancel }) => {
  const [f, setF] = useState({ date: localDate(), type: "promotion", title: "", notes: "" });
  const submit = async (e) => {
    e.preventDefault();
    try {
      await api.post("/admin/service-records", { ...f, user_id: userId });
      toast.success("Service record added");
      setF({ ...f, title: "", notes: "" });
      onAdded();
    } catch (err) { toast.error(errMsg(err)); }
  };
  return (
    <form onSubmit={submit} className="mb-6 rounded-lg bg-slate-50 p-4 grid grid-cols-2 gap-3" data-testid="add-service-form">
      <Field label="Date"><Input type="date" required value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} className="bg-white" data-testid="sr-date" /></Field>
      <Field label="Type"><NativeSelect value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} data-testid="sr-type">{TYPES.map((t) => <option key={t} value={t} className="capitalize">{t}</option>)}</NativeSelect></Field>
      <Field label="Title" className="col-span-2"><Input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="e.g. Promoted to Senior Executive" className="bg-white" data-testid="sr-title" /></Field>
      <Field label="Notes" className="col-span-2"><Input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className="bg-white" data-testid="sr-notes" /></Field>
      <div className="col-span-2 flex gap-2">
        <Button type="submit" data-testid="sr-submit">Save</Button>
        <Button type="button" variant="ghost" onClick={onCancel} data-testid="sr-cancel">Cancel</Button>
      </div>
    </form>
  );
};

const TAB_MODULE = { service: "service_book", appraisals: "service_book", attendance: "attendance", requests: "requests", payslips: "payslips" };

export default function AdminEmployeeDetail() {
  const { id } = useParams();
  return <EmployeeRecord id={id} />;
}

const TABS = [["profile", "Profile"], ["salary", "Salary & Leave"], ["service", "Service Book"], ["appraisals", "Appraisals"], ["attendance", "Attendance"], ["requests", "Requests"], ["payslips", "Payslips"]];

export function EmployeeRecord({ id, embedded }) {
  const { user } = useAuth();
  const canEdit = can(user, "employees", "edit");
  const navigate = useNavigate();
  const [e, setE] = useState(null);
  const [records, setRecords] = useState([]);
  const [edit, setEdit] = useState(false);
  const [adding, setAdding] = useState(false);
  const [del, setDel] = useState(false);
  const [reset, setReset] = useState(false);
  const [media, setMedia] = useState(null);
  const [slips, setSlips] = useState(null);
  const [slipConfirm, setSlipConfirm] = useState(false);
  const [tab, setTab] = useState("profile");
  const printSlip = async () => {
    try { setSlips(await issueSlips([id])); setE((x) => ({ ...x, must_change_password: true })); } catch (err) { toast.error(errMsg(err)); }
  };

  const loadRecords = useCallback(() => { api.get("/admin/service-records", { params: { user_id: id } }).then((r) => setRecords(r.data)); }, [id]);
  useEffect(() => {
    api.get(`/admin/employees/${id}`).then((r) => setE(r.data)).catch(() => navigate("/admin/employees"));
    api.get(`/admin/employees/${id}/media`).then((r) => setMedia(r.data));
    loadRecords();
  }, [id, navigate, loadRecords]);

  const uploadMedia = async (kind, dataUrl) => {
    try { const { data } = await api.post(`/admin/employees/${id}/media`, { [kind]: dataUrl }); setMedia(data); toast.success(`${kind === "photo" ? "Photo" : "Signature"} updated`); } catch (err) { toast.error(errMsg(err)); }
  };

  const removeRecord = async (rid) => { await api.delete(`/admin/service-records/${rid}`); loadRecords(); };
  const removeEmployee = async () => {
    try { await api.delete(`/admin/employees/${id}`); toast.success("Employee deleted"); navigate("/admin/employees"); } catch (err) { toast.error(errMsg(err)); }
  };

  if (!e) return <div className="text-muted-foreground">Loading…</div>;

  const groups = [
    ["Job", [["Employee ID", e.employee_id], ["Short code", e.short_code], ["Department", e.department], ["Designation", e.designation], ["Joining date", fmtDate(e.joining_date)], ["Location", e.location], ["Project site", e.project_site], ["Reporting manager", e.reporting_manager]]],
    ["Personal & contact", [["Email", e.email], ["Phone", e.phone], ["Date of birth", fmtDate(e.dob)], ["Gender", e.gender], ["Father's name", e.father_name], ["Address", e.address]]],
    ["Bank & statutory", [["Bank", e.bank_name], ["Account no.", e.bank_account], ["IFSC", e.ifsc], ["PAN", e.pan], ["UAN / PF", e.uan]]],
  ];

  const Group = ({ title, items }) => (
    <section>
      <h4 className="text-xs uppercase tracking-widest font-semibold text-primary mb-3">{title}</h4>
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-x-6 gap-y-4">{items.filter(([, v]) => v !== undefined).map(([l, v]) => <Info key={l} label={l} value={v} />)}</div>
    </section>
  );

  const live = e.portal_enabled !== false;
  const gross = (e.basic || 0) + (e.hra || 0) + (e.allowances || 0);
  const facts = [["Joining date", fmtDate(e.joining_date)], ["Location", e.location], ["Phone", e.phone], ["Gross / month", fmtINR(gross)]];

  return (
    <div className="space-y-6">
      {!embedded && <Link to="/admin/employees" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground" data-testid="back-to-employees"><ArrowLeft size={14} />Employees</Link>}

      <section className="rounded-2xl bg-[hsl(var(--sidebar))] text-white grid-bg overflow-hidden rise" data-testid="employee-hero">
        <div className="p-6 sm:p-8 flex flex-col sm:flex-row sm:items-center gap-6">
          {media?.photo
            ? <img src={media.photo} alt={e.name} className="h-28 w-24 rounded-xl object-cover ring-4 ring-white/10 shrink-0" data-testid="hero-photo" />
            : <div className="h-28 w-24 rounded-xl bg-white/10 grid place-items-center text-3xl font-display font-bold shrink-0">{e.name?.[0]}</div>}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs tracking-widest text-blue-300">{e.employee_id}</span><ShortBadge code={e.short_code} className="!text-[11px]" /></div>
            <h1 className="text-2xl sm:text-4xl font-extrabold tracking-tight mt-1" data-testid="hero-name">{e.name}</h1>
            <div className="text-slate-300 mt-1">{[e.designation, e.department].filter(Boolean).join(" · ") || "—"}</div>
            <div className="flex flex-wrap gap-2 mt-3 text-xs font-semibold">
              <span className={`rounded-full px-2.5 py-0.5 ${e.active !== false ? "bg-emerald-400/15 text-emerald-300" : "bg-rose-400/15 text-rose-300"}`}>{e.active !== false ? "Active" : "Inactive"}</span>
              <span className={`rounded-full px-2.5 py-0.5 ${live ? "bg-blue-400/15 text-blue-200" : "bg-rose-400/15 text-rose-300"}`}>Portal {live ? "Live" : "Unlive"}</span>
              {e.source === "vendor" && <span className="rounded-full px-2.5 py-0.5 bg-white/10 text-slate-200">Vendor HR</span>}
            </div>
          </div>
        </div>
        {canEdit && <div className="px-6 sm:px-8 py-4 border-t border-white/10 grid grid-cols-2 sm:flex sm:flex-wrap items-center gap-2 [&>*]:justify-center sm:[&>*]:justify-start" data-testid="hero-actions">
          <span className="rounded-md bg-white/10 px-3 h-9 inline-flex items-center gap-2 text-sm" data-testid="portal-access-control">Portal {live ? "Live" : "Unlive"} <AccessSwitch employee={e} onChange={setE} /></span>
          <Button size="sm" variant="secondary" onClick={() => setEdit(true)} data-testid="edit-employee-btn"><Pencil size={14} className="mr-2" />Edit details</Button>
          <ShortCodeControl employee={e} onChange={setE} />
          <Button size="sm" variant="secondary" onClick={() => setReset(true)} data-testid="reset-password-btn"><KeyRound size={14} className="mr-2" />Reset password</Button>
          <Button size="sm" variant="secondary" onClick={() => setSlipConfirm(true)} data-testid="print-slip-btn"><Printer size={14} className="mr-2" />Print slip</Button>
          {!embedded && <Button size="sm" variant="secondary" asChild data-testid="open-service-book-btn"><Link to={`/admin/service-book?id=${e.id}`}><BookOpen size={14} className="mr-2" />Service book</Link></Button>}
          <Button size="sm" variant="secondary" onClick={() => setDel(true)} className="text-rose-600 hover:text-rose-700 sm:ml-auto" data-testid="delete-employee-btn"><Trash2 size={14} className="mr-2" />Delete</Button>
        </div>}
        <div className="grid grid-cols-2 lg:grid-cols-4 border-t border-white/10">
          {facts.map(([l, v], i) => (
            <div key={l} className={`px-6 sm:px-8 py-4 ${i % 2 ? "border-l" : ""} ${i >= 2 ? "border-t lg:border-t-0" : ""} lg:border-l first:border-l-0 border-white/10`}>
              <div className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">{l}</div>
              <div className="font-semibold mt-1 truncate">{v || "—"}</div>
            </div>
          ))}
        </div>
      </section>

      <div className="flex gap-1 overflow-x-auto rounded-xl border bg-white p-1" role="tablist" data-testid="record-tabs">
        {TABS.filter(([k]) => can(user, TAB_MODULE[k] || "employees")).map(([k, l]) => (
          <button key={k} role="tab" onClick={() => setTab(k)} data-testid={`record-tab-${k}`}
            className={`whitespace-nowrap rounded-lg px-4 py-2 text-sm font-medium transition-colors ${tab === k ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>{l}</button>
        ))}
      </div>

      {tab === "profile" && (
        <Panel data-testid="employee-detail-info">
          <div className="flex flex-col md:flex-row gap-8">
            <div className="flex-1 min-w-0 space-y-7">{groups.map(([t, items]) => <Group key={t} title={t} items={items} />)}</div>
            <div className="md:w-52 shrink-0 md:border-l md:pl-6"><MediaCard media={media} onUpload={uploadMedia} stacked /></div>
          </div>
        </Panel>
      )}
      {tab === "salary" && (
        <div className="space-y-6">
          <Panel data-testid="salary-panel"><h3 className="font-display text-lg font-semibold mb-4">Salary breakup</h3><SalaryBreakup e={e} wide /></Panel>
          {can(user, "leave") && <Panel data-testid="leave-balance-panel"><h3 className="font-display text-lg font-semibold mb-4">Leave balance</h3><LeaveBalanceAdmin userId={e.id} /></Panel>}
        </div>
      )}
      {tab === "service" && (
        <Panel data-testid="service-record-panel">
          <div className="flex items-center justify-between mb-5">
            <h3 className="font-display text-lg font-semibold">Service book entries</h3>
            {!adding && <Button size="sm" variant="outline" onClick={() => setAdding(true)} data-testid="sr-open-form">+ Add entry</Button>}
          </div>
          {adding && <AddRecord userId={id} onAdded={() => { loadRecords(); setAdding(false); }} onCancel={() => setAdding(false)} />}
          <ServiceTimeline records={records} onDelete={removeRecord} />
        </Panel>
      )}
      {tab === "appraisals" && <Panel><AppraisalsModule userId={e.id} /></Panel>}
      {tab === "attendance" && <Panel><AttendanceModule userId={e.id} /></Panel>}
      {tab === "requests" && <Panel><RequestsModule userId={e.id} /></Panel>}
      {tab === "payslips" && <Panel><PayslipsModule userId={e.id} /></Panel>}
      <EmployeeFormDialog open={edit} onOpenChange={setEdit} employee={e} onSaved={setE} />
      <ResetPasswordDialog open={reset} onOpenChange={setReset} employee={e} />
      <SlipsPreview data={slips} onClose={() => setSlips(null)} />
      <AlertDialog open={slipConfirm} onOpenChange={setSlipConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Generate credential slip?</AlertDialogTitle>
            <AlertDialogDescription>A NEW password will be set for {e.name}. The old password will stop working.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="cancel-slip">Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={printSlip} data-testid="confirm-slip">Generate</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={del} onOpenChange={setDel}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {e.name}?</AlertDialogTitle>
            <AlertDialogDescription>This permanently removes the employee and all their attendance, requests, payslips and service records. To only block login, set status to Inactive instead.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="cancel-delete-employee">Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={removeEmployee} className="bg-rose-600 hover:bg-rose-700" data-testid="confirm-delete-employee">Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
