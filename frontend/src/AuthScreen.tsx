import { type FormEvent, useState } from "react";
import { login, register } from "./api";
import type { User } from "./types";

export default function AuthScreen({
  onAuthenticated
}: {
  onAuthenticated: (user: User) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const user = mode === "login" ? await login(email, password) : await register(email, password);
      onAuthenticated(user);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not continue. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  function switchMode() {
    setMode((current) => current === "login" ? "register" : "login");
    setError("");
  }

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
          <p className="eyebrow">{mode === "login" ? "Welcome back" : "Create your workspace"}</p>
          <h2>{mode === "login" ? "Sign in to InternTrack" : "Start tracking smarter"}</h2>
          <p className="auth-subtitle">
            {mode === "login" ? "Your next opportunity is waiting." : "Free to start. No credit card required."}
          </p>
          <form onSubmit={handleSubmit}>
            <label>Email address<input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" /></label>
            <label>Password<input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={mode === "register" ? 8 : 1} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "register" ? "At least 8 characters" : "Your password"} /></label>
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="button primary auth-submit" type="submit" disabled={submitting}>{submitting ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
          </form>
          <p className="auth-switch">{mode === "login" ? "New to InternTrack?" : "Already have an account?"} <button type="button" onClick={switchMode}>{mode === "login" ? "Create an account" : "Sign in"}</button></p>
          <p className="auth-legal">By continuing, you agree to keep your account secure. Your password is stored as a one-way hash.</p>
        </div>
      </section>
    </main>
  );
}
