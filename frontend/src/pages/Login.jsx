import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Camera, MapPin, FileCheck2, Loader2, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/common";
import { useAuth } from "@/context/AuthContext";
import { errMsg } from "@/lib/api";
import { homePath } from "@/lib/roles";

const FEATURES = [
  [Camera, "Attendance", "Selfie punch"],
  [MapPin, "GPS", "Live location"],
  [FileCheck2, "Requests", "Leave / Payslip"],
];

const ADDRESS = "209H/1F/1, Ops Nagar, Kalindipuram, Prayagraj, UP 211011";
const PHONE = "9429694552";
const EMAIL = "info@arunenterprises.online";
const WEB = "www.arunenterprises.com.in";

const Brand = ({ light }) => (
  <div className="flex items-center gap-4" data-testid={light ? "login-company-card-mobile" : "login-company-card"}>
    <img src="/arun-logo.jpg" alt="Arun Enterprises logo" className="h-14 w-14 rounded-xl object-contain p-1 bg-white shrink-0 ring-1 ring-slate-200" />
    <div>
      <div className={`font-display text-2xl tracking-tight ${light ? "text-slate-900 font-bold" : "font-semibold"}`} data-testid={light ? "login-company-name-mobile" : "login-company-name"}>ARUN ENTERPRISES</div>
      <div className={`text-[10px] uppercase tracking-[0.2em] mt-1 ${light ? "text-slate-500" : "text-slate-300"}`}>Our quality oriented service's is first priority</div>
    </div>
  </div>
);

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={homePath(user)} replace />;

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const u = await login(identifier, password);
      navigate(homePath(u));
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-[1.05fr_1fr]">
      <section className="hidden lg:flex flex-col justify-between text-white p-14 bg-gradient-to-br from-[#0b1a3a] via-[#0f2350] to-[#0b1a3a]">
        <Brand />
        <div className="text-center rise">
          <h1 className="text-6xl font-semibold tracking-tight">Employee Portal</h1>
          <div className="text-3xl tracking-[0.12em] text-blue-400 mt-4 font-display">FOR ARUN ENTERPRISES</div>
          <div className="h-px w-20 bg-blue-500/60 mx-auto my-8" />
          <p className="text-lg text-slate-200">Attendance, service record, leave and payslips in one place.</p>
          <div className="flex justify-center gap-10 mt-12 text-left">
            {FEATURES.map(([Icon, t, d], i) => (
              <div key={t} className="border-l-2 border-blue-500/70 pl-3 rise" style={{ animationDelay: `${i * 90}ms` }}>
                <Icon size={18} className="text-blue-300 mb-2" />
                <div className="font-semibold">{t}</div>
                <div className="text-sm text-slate-400">{d}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="text-sm text-slate-400 leading-relaxed" data-testid="login-company-address">
          {ADDRESS}<br />Toll Free: <a href={`tel:${PHONE}`} className="hover:text-white">{PHONE}</a> · <a href={`mailto:${EMAIL}`} className="hover:text-white">{EMAIL}</a> · {WEB}
        </div>
      </section>

      <section className="flex flex-col items-center justify-center p-6 sm:p-12">
        <form onSubmit={submit} className="w-full max-w-md space-y-6 rise" data-testid="login-form">
          <div className="lg:hidden mb-4"><Brand light /></div>
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] font-semibold text-primary mb-3"><Lock size={14} />Secure access</div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">Sign in to your portal</h2>
            <p className="text-sm text-muted-foreground mt-2">Use your Employee Code / Email provided by HR.</p>
          </div>
          <Field label="Employee Code / Short Code / Email / SuperAdmin">
            <Input required value={identifier} onChange={(e) => setIdentifier(e.target.value)} placeholder="AE0005, full employee code or email" className="h-11" data-testid="login-email-input" />
          </Field>
          <Field label="Password">
            <Input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-11" data-testid="login-password-input" />
          </Field>
          {error && <div className="text-sm text-rose-700 bg-rose-50 rounded-md px-3 py-2" data-testid="login-error">{error}</div>}
          <Button type="submit" disabled={busy} className="w-full h-11 text-base" data-testid="login-submit-button">
            {busy && <Loader2 size={16} className="mr-2 animate-spin" />}Sign in
          </Button>
          <p className="text-xs text-muted-foreground">Forgot password? Contact your HR / admin to reset it.</p>
          <div className="border-t pt-6 text-center text-xs text-slate-500 leading-relaxed" data-testid="login-footer-address">
            {ADDRESS}<br />Toll Free: {PHONE} · {EMAIL}<br />{WEB}
          </div>
        </form>
      </section>
    </div>
  );
}
