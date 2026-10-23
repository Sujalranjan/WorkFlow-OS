import React, { useState } from 'react';
import { Session, login } from '../api';
import { Alert, errorText } from '../ui';

export const LoginPage: React.FC<{ onSignedIn: (session: Session) => void; notice?: string | null }> = ({
  onSignedIn,
  notice,
}) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await login(email.trim(), password));
    } catch (err) {
      setError(errorText(err));
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand login-brand">
          <span className="brand-mark" aria-hidden="true">W</span>
          <span>WorkFlowOS</span>
        </div>
        <h1>Sign in</h1>
        {notice && !error && <Alert tone="info">{notice}</Alert>}
        {error && <Alert>{error}</Alert>}
        <label className="field">
          Email
          <input type="email" autoComplete="username" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="muted small">
          No account? Ask an admin. The first admin is created on the server with{' '}
          <code>python backend/app/cli.py create-user --role admin</code>.
        </p>
      </form>
    </main>
  );
};
