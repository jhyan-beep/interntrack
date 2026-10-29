import { type FormEvent, useState } from "react";
import { forgotPassword, login, register, resetPassword } from "./api";
import type { User } from "./types";

export default function AuthScreen({
  onAuthenticated,
  notice = ""
}: {
  onAuthenticated: (user: User) => void;
  notice?: string;
}) {
  const initialResetToken = new URLSearchParams(window.location.search).get("reset_token") ?? "";
  const [mode, setMode] = useState<"login" | "register" | "forgot" | "reset">(
    initialResetToken ? "reset" : "login"
  );
  const [resetToken] = useState(initialResetToken);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      if (mode === "forgot") {
        await forgotPassword(email);
        setMessage("If that account exists, a password reset email is on its way.");
        setMode("login");
      } else if (mode === "reset") {
        await resetPassword(resetToken, password);
        window.history.replaceState({}, "", window.location.pathname);
        setMessage("Password updated. Sign in with your new password.");
        setPassword("");
        setMode("login");
      } else {
        const user = mode === "login" ? await login(email, password) : await register(email, password);
        onAuthenticated(user);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not continue. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  function switchMode() {
    setMode((current) => current === "login" ? "register" : "login");
    setError("");
    setMessage("");
  }

  const isLogin = mode === "login";
  const isRegister = mode === "register";
  const isForgot = mode === "forgot";
  const isReset = mode === "reset";

  return (
    <main className="auth-shell">
      <section className="auth-story">
        <a className="brand auth-brand" href="/" aria-label="InternTrack home">
          <span className="brand-mark" aria-hidden="true">IT</span>
          <span>Intern<span>Track</span></span>
        </a>
        <div className="auth-copy">
          <p className="eyebrow">A calmer internship search</p>
          <h1>Every application.<br /><em>One clear path.</em></h1>
          <p>Track opportunities, stay ahead of deadlines, and know exactly where your search stands.</p>
          <div className="auth-proof">
            <span>01</span><p><strong>Stay organized</strong>Keep roles, links, notes, and dates together.</p>
            <span>02</span><p><strong>See momentum</strong>Turn your pipeline into useful progress.</p>
            <span>03</span><p><strong>Keep it private</strong>Your applications belong only to your account.</p>
          </div>
        </div>
      </section>

      <section className="auth-form-side">
        <div className="auth-card">
          <p className="eyebrow">{isLogin ? "Welcome back" : isRegister ? "Create your workspace" : "Account recovery"}</p>
          <h2>{isLogin ? "Sign in to InternTrack" : isRegister ? "Start tracking smarter" : isForgot ? "Reset your password" : "Choose a new password"}</h2>
          <p className="auth-subtitle">
            {isLogin ? "Your next opportunity is waiting." : isRegister ? "Free to start. No credit card required." : isForgot ? "We will send a secure reset link if the account exists." : "Use at least 8 characters for your new password."}
          </p>
          <form onSubmit={handleSubmit}>
            {!isReset && <label>Email address<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" /></label>}
            {!isForgot && <label>{isReset ? "New password" : "Password"}<input type="password" autoComplete={isLogin ? "current-password" : "new-password"} required minLength={isRegister || isReset ? 8 : 1} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={isRegister || isReset ? "At least 8 characters" : "Your password"} /></label>}
            {isLogin && <button className="auth-forgot" type="button" onClick={() => { setMode("forgot"); setError(""); setMessage(""); }}>Forgot password?</button>}
            {(notice || message) && <p className="form-success" role="status">{message || notice}</p>}
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="button primary auth-submit" type="submit" disabled={submitting}>{submitting ? "Please wait…" : isLogin ? "Sign in" : isRegister ? "Create account" : isForgot ? "Send reset link" : "Update password"}</button>
          </form>
          <p className="auth-switch">{isLogin ? "New to InternTrack?" : isRegister ? "Already have an account?" : "Remembered your password?"} <button type="button" onClick={isForgot || isReset ? () => { setMode("login"); setError(""); } : switchMode}>{isLogin ? "Create an account" : "Sign in"}</button></p>
          <p className="auth-legal">By continuing, you agree to keep your account secure. Your password is stored as a one-way hash.</p>
        </div>
      </section>
    </main>
  );
}

