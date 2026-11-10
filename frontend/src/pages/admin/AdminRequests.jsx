import { useCallback, useEffect, useState } from "react";
import { Check, X, Inbox } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader, Empty, NativeSelect, Panel } from "@/components/common";
import RequestItem from "@/components/RequestItem";
import LeaveBalanceManager from "@/components/LeaveBalanceManager";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { can } from "@/lib/roles";

const STATUSES = ["pending", "approved", "rejected", "all"];

export default function AdminRequests() {
  const { user } = useAuth();
  const canApprove = can(user, "requests", "approve");
  const tabs = [["requests", "Requests"], ...(can(user, "leave") ? [["balance", "Leave Balance"]] : [])];
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("pending");
  const [type, setType] = useState("");
  const [decision, setDecision] = useState(null);
  const [comment, setComment] = useState("");
  const [tab, setTab] = useState("requests");

  const load = useCallback(() => {
    api.get("/admin/requests", { params: { status: status === "all" ? undefined : status, type: type || undefined } }).then((r) => setRows(r.data));
  }, [status, type]);
  useEffect(() => { load(); }, [load]);

  const decide = async () => {
    try {
      await api.patch(`/admin/requests/${decision.r.id}`, { status: decision.status, admin_comment: comment });
      toast.success(`Request ${decision.status}`);
      setDecision(null);
      setComment("");
      load();
    } catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <div>
      <PageHeader eyebrow="Approvals" title="Requests" desc="Review leave, advance, payslip and other employee requests, and manage leave balances." />
      <div className="flex gap-1 rounded-xl border bg-white p-1 mb-5 w-fit" data-testid="requests-tabs">
        {tabs.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} data-testid={`req-tab-${k}`} className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${tab === k ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>{l}</button>
        ))}
      </div>
      {tab === "balance" && <Panel><LeaveBalanceManager /></Panel>}
      {tab === "requests" && <>
      <div className="flex flex-col sm:flex-row gap-3 sm:items-center justify-between mb-5">
        <div className="flex gap-2 overflow-x-auto">
          {STATUSES.map((s) => (
            <button key={s} onClick={() => setStatus(s)} data-testid={`admin-req-filter-${s}`}
              className={`px-4 py-1.5 rounded-full text-sm font-medium capitalize transition-colors ${status === s ? "bg-slate-900 text-white" : "bg-white border text-slate-600 hover:text-slate-900"}`}>{s}</button>
          ))}
        </div>
        <NativeSelect value={type} onChange={(e) => setType(e.target.value)} className="sm:w-48" data-testid="admin-req-type-filter">
          <option value="">All types</option><option value="leave">Leave</option><option value="advance">Advance</option><option value="payslip">Payslip</option><option value="missed_punch">Missed Punch</option><option value="other">Other</option>
        </NativeSelect>
      </div>
      <div className="space-y-3">
        {rows.length ? rows.map((r) => (
          <RequestItem key={r.id} r={r} showEmployee>
            {r.status === "pending" && canApprove && (
              <>
                <Button size="sm" onClick={() => setDecision({ r, status: "approved" })} className="bg-emerald-600 hover:bg-emerald-700" data-testid={`admin-approve-btn-${r.id}`}><Check size={15} className="mr-1" />Approve</Button>
                <Button size="sm" variant="outline" onClick={() => setDecision({ r, status: "rejected" })} className="text-rose-600 hover:text-rose-700 hover:bg-rose-50" data-testid={`admin-reject-btn-${r.id}`}><X size={15} className="mr-1" />Reject</Button>
              </>
            )}
          </RequestItem>
        )) : <Empty icon={Inbox} text="No requests found." testId="admin-requests-empty" />}
      </div>
      </>}
      <Dialog open={!!decision} onOpenChange={(o) => !o && setDecision(null)}>
        <DialogContent className="max-w-md" data-testid="decision-dialog">
          <DialogHeader><DialogTitle className="font-display capitalize">{decision?.status === "approved" ? "Approve" : "Reject"} request</DialogTitle></DialogHeader>
          <Textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment for employee (optional)" data-testid="decision-comment" />
          <Button onClick={decide} className={decision?.status === "approved" ? "bg-emerald-600 hover:bg-emerald-700" : "bg-rose-600 hover:bg-rose-700"} data-testid="decision-confirm-btn">Confirm</Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
