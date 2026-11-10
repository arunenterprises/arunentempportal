import { useCallback, useEffect, useState } from "react";
import { Plus, Pencil, Trash2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader, Panel, Field, NativeSelect, Empty } from "@/components/common";
import { api, errMsg } from "@/lib/api";
import { ROLE_LABEL, MODULE_LABEL } from "@/lib/roles";

const ACTIONS = ["view", "edit", "approve"];
const blank = (modules) => ({ name: "", email: "", mobile: "", password: "", confirm_password: "", role: "hr", active: true, permissions: Object.fromEntries(modules.map((m) => [m, { view: true, edit: false, approve: false }])) });

const PermMatrix = ({ modules, value, onChange }) => {
  const set = (m, a, v) => {
    const cur = { ...value[m], [a]: v };
    if (a !== "view" && v) cur.view = true;
    if (a === "view" && !v) { cur.edit = false; cur.approve = false; }
    onChange({ ...value, [m]: cur });
  };
  const all = (a, v) => onChange(Object.fromEntries(modules.map((m) => [m, a === "view" && !v ? { view: false, edit: false, approve: false } : { ...value[m], [a]: v, view: v || a === "view" ? v || value[m].view : value[m].view }])));
  return (
    <div className="rounded-lg border overflow-hidden" data-testid="perm-matrix">
      <div className="grid grid-cols-[1fr_repeat(3,56px)] bg-slate-50 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground px-3 py-2">
        <span>Module</span>{ACTIONS.map((a) => <button type="button" key={a} onClick={() => all(a, !modules.every((m) => value[m]?.[a]))} className="text-center hover:text-primary" data-testid={`perm-all-${a}`}>{a}</button>)}
      </div>
      {modules.map((m) => (
        <div key={m} className="grid grid-cols-[1fr_repeat(3,56px)] items-center px-3 py-2 border-t text-sm">
          <span>{MODULE_LABEL[m] || m}</span>
          {ACTIONS.map((a) => (
            <span key={a} className="grid place-items-center">
              <Checkbox checked={!!value[m]?.[a]} onCheckedChange={(v) => set(m, a, !!v)} disabled={a === "approve" && m !== "requests" && m !== "leave"} data-testid={`perm-${m}-${a}`} />
            </span>
          ))}
        </div>
      ))}
    </div>
  );
};

const UserForm = ({ modules, initial, onSaved, onClose }) => {
  const [f, setF] = useState(initial);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    if (f.password !== f.confirm_password) { toast.error("Password and Confirm password do not match"); return; }
    setBusy(true);
    try {
      const body = { ...f, password: f.password || null, confirm_password: f.confirm_password || null };
      if (f.id) await api.put(`/admin/users/${f.id}`, body); else await api.post("/admin/users", body);
      toast.success(f.id ? "User updated" : "User created");
      onSaved(); onClose();
    } catch (err) { toast.error(errMsg(err)); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="space-y-4" data-testid="user-form">
      <div className="grid sm:grid-cols-2 gap-3">
        <Field label="Name"><Input required value={f.name} onChange={set("name")} data-testid="user-name-input" /></Field>
        <Field label="Email ID"><Input required type="email" value={f.email} onChange={set("email")} data-testid="user-email-input" /></Field>
        <Field label="Mobile No"><Input value={f.mobile} onChange={(e) => setF({ ...f, mobile: e.target.value.replace(/[^\d+]/g, "") })} maxLength={13} data-testid="user-mobile-input" /></Field>
        <Field label="Role">
          <NativeSelect value={f.role} onChange={set("role")} data-testid="user-role-select">
            <option value="admin">Admin</option><option value="hr">HR</option><option value="manager">Manager</option>
          </NativeSelect>
        </Field>
        <Field label={f.id ? "New password (optional)" : "Password"}><Input type="password" required={!f.id} minLength={8} value={f.password} onChange={set("password")} autoComplete="new-password" data-testid="user-password-input" /></Field>
        <Field label="Confirm password"><Input type="password" required={!f.id || !!f.password} value={f.confirm_password} onChange={set("confirm_password")} autoComplete="new-password" data-testid="user-confirm-password-input" /></Field>
      </div>
      <div>
        <div className="text-sm font-medium mb-2">Permission · View / Edit / Approve</div>
        <PermMatrix modules={modules} value={f.permissions} onChange={(p) => setF({ ...f, permissions: p })} />
        <p className="text-[11px] text-muted-foreground mt-1.5">Approve applies to Requests and Leave. Tap a column title to tick/untick all.</p>
      </div>
      <label className="flex items-center gap-2 text-sm"><Switch checked={f.active} onCheckedChange={(v) => setF({ ...f, active: v })} data-testid="user-active-switch" />Active (can log in)</label>
      <Button type="submit" className="w-full" disabled={busy} data-testid="user-save-btn">{busy ? "Saving…" : f.id ? "Save changes" : "Create user"}</Button>
    </form>
  );
};

const summary = (p) => {
  const n = (a) => Object.values(p).filter((x) => x[a]).length;
  return `View ${n("view")} · Edit ${n("edit")} · Approve ${n("approve")}`;
};

export default function AdminUsers() {
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const load = useCallback(() => { api.get("/admin/users").then((r) => setData(r.data)).catch((e) => toast.error(errMsg(e))); }, []);
  useEffect(() => { load(); }, [load]);
  const modules = data?.modules || [];
  const remove = async (u) => {
    if (!window.confirm(`Delete user ${u.name}?`)) return;
    try { await api.delete(`/admin/users/${u.id}`); toast.success("User deleted"); load(); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div>
      <PageHeader eyebrow="SuperAdmin" title="Users & Roles" desc="Create console users, decide their role and what they can view, edit and approve."
        action={<Button onClick={() => setForm(blank(modules))} disabled={!data} data-testid="add-user-btn"><Plus size={16} className="mr-2" />Create user</Button>} />
      <Panel>
        {!data ? <div className="text-sm text-muted-foreground">Loading…</div> : !data.users.length ? <Empty text="No users." /> : (
          <div className="divide-y" data-testid="users-list">
            {data.users.map((u) => (
              <div key={u.id} className="py-3 flex flex-col sm:flex-row sm:items-center gap-3" data-testid={`user-row-${u.email}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{u.name}</span>
                    <span className={`rounded px-1.5 py-px text-[10px] font-bold uppercase tracking-wider ${u.role === "superadmin" ? "bg-amber-400 text-slate-900" : "bg-blue-100 text-blue-800"}`} data-testid={`user-role-${u.email}`}>{ROLE_LABEL[u.role]}</span>
                    {!u.active && <span className="rounded px-1.5 py-px text-[10px] font-bold bg-rose-100 text-rose-700">INACTIVE</span>}
                  </div>
                  <div className="text-xs text-muted-foreground break-all">{u.email}{u.mobile ? ` · ${u.mobile}` : ""}</div>
                  <div className="text-xs mt-0.5 inline-flex items-center gap-1 text-slate-600"><ShieldCheck size={12} />{u.role === "superadmin" ? "Full access to everything" : summary(u.permissions)}</div>
                </div>
                {u.role !== "superadmin" && (
                  <div className="flex gap-2 shrink-0">
                    <Button size="sm" variant="outline" onClick={() => setForm({ ...u, password: "", confirm_password: "" })} data-testid={`user-edit-${u.email}`}><Pencil size={13} className="mr-1" />Edit</Button>
                    <Button size="sm" variant="outline" className="text-rose-600" onClick={() => remove(u)} data-testid={`user-delete-${u.email}`}><Trash2 size={13} /></Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Panel>
      <Dialog open={!!form} onOpenChange={(o) => { if (!o) setForm(null); }}>
        <DialogContent className="max-w-xl" data-testid="user-dialog">
          <DialogHeader><DialogTitle className="font-display">{form?.id ? `Edit user · ${form.name}` : "Create user"}</DialogTitle></DialogHeader>
          {form && <UserForm modules={modules} initial={form} onSaved={load} onClose={() => setForm(null)} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
