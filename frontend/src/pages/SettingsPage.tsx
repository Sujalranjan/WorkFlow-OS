import React, { useState } from 'react';
import { Role, User, createApiKey, createUser, listApiKeys, listUsers, revokeApiKey, updateUser } from '../api';
import { Alert, Badge, Empty, Loading, PageHeader, timeAgo, useAction, useLoad, useSession } from '../ui';

const ROLE_HELP: Record<Role, string> = {
  viewer: 'Sees everything, changes nothing',
  approver: 'Also creates, approves and runs workflows and answers paused runs',
  admin: 'Also manages email triggers, users and API keys',
};

export const SettingsPage: React.FC = () => (
  <>
    <PageHeader title="Settings" subtitle="People who can sign in, and keys for the desktop agent and browser extension." />
    <UsersSection />
    <ApiKeysSection />
  </>
);

const UsersSection: React.FC = () => {
  const users = useLoad(listUsers, []);
  const action = useAction();
  const me = useSession().user;
  const [adding, setAdding] = useState(false);

  const change = (u: User, changes: Parameters<typeof updateUser>[1], done: string) =>
    action.run(`user-${u.user_id}`, () => updateUser(u.user_id, changes), done).then(() => users.reload());

  return (
    <section className="card">
      <div className="card-head">
        <h2>Users</h2>
        {!adding && (
          <button className="btn-secondary" onClick={() => setAdding(true)}>
            Add user
          </button>
        )}
      </div>
      {action.error && <Alert>{action.error}</Alert>}
      {action.notice && <Alert tone="ok">{action.notice}</Alert>}
      {adding && (
        <NewUserForm
          busy={action.busy !== null}
          onCancel={() => setAdding(false)}
          onCreate={(input) =>
            action
              .run('create-user', () => createUser(input), `Added ${input.email}. Share the password with them securely.`)
              .then((u) => {
                if (u) setAdding(false);
                users.reload();
              })
          }
        />
      )}
      {users.loading && !users.data ? (
        <Loading />
      ) : (
        <ul className="rows">
          {(users.data || []).map((u) => (
            <li key={u.user_id} className="trigger">
              <div className="trigger-main">
                <div className="row-title">
                  {u.name} {u.user_id === me.user_id && <span className="muted small">(you)</span>}{' '}
                  {!u.active && <Badge status="paused" label="Disabled" />}
                </div>
                <span className="muted small">
                  {u.email} · last sign-in {timeAgo(u.last_login_at)}
                </span>
              </div>
              <div className="actions">
                <select
                  aria-label={`Role for ${u.email}`}
                  value={u.role}
                  disabled={u.user_id === me.user_id || action.busy !== null}
                  onChange={(e) => change(u, { role: e.target.value as Role }, `${u.email} is now ${e.target.value}.`)}
                >
                  {(Object.keys(ROLE_HELP) as Role[]).map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                {u.user_id !== me.user_id && (
                  <button
                    className={u.active ? 'btn-danger' : 'btn-secondary'}
                    disabled={action.busy !== null}
                    onClick={() =>
                      change(u, { active: !u.active }, u.active ? `${u.email} can no longer sign in.` : `${u.email} can sign in again.`)
                    }
                  >
                    {u.active ? 'Disable' : 'Enable'}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <ul className="muted small role-help">
        {(Object.entries(ROLE_HELP) as [Role, string][]).map(([r, text]) => (
          <li key={r}>
            <strong>{r}</strong>: {text}
          </li>
        ))}
      </ul>
    </section>
  );
};

const NewUserForm: React.FC<{
  busy: boolean;
  onCancel: () => void;
  onCreate: (input: { email: string; name: string; role: Role; password: string }) => void;
}> = ({ busy, onCancel, onCreate }) => {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<Role>('viewer');
  const [password, setPassword] = useState('');
  return (
    <form
      className="form subform"
      onSubmit={(e) => {
        e.preventDefault();
        onCreate({ email: email.trim(), name: name.trim(), role, password });
      }}
    >
      <div className="form-row">
        <label className="field">
          Name
          <input required value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          Email
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          Role
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(Object.keys(ROLE_HELP) as Role[]).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Temporary password
          <input
            type="password"
            autoComplete="new-password"
            minLength={12}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <span className="muted small">At least 12 characters.</span>
        </label>
      </div>
      <div className="actions">
        <button type="submit" disabled={busy}>
          Add user
        </button>
        <button type="button" className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
};

const ApiKeysSection: React.FC = () => {
  const keys = useLoad(listApiKeys, []);
  const action = useAction();
  const [name, setName] = useState('');
  const [created, setCreated] = useState<string | null>(null);

  return (
    <section className="card">
      <h2>API keys</h2>
      <p className="muted small">
        The desktop agent and browser extension use a key to send activity. A key can only send activity events: it
        cannot read data, approve or run anything. Set it as <code>WORKFLOWOS_API_KEY</code> for the agent, or paste it
        into the extension's options.
      </p>
      {action.error && <Alert>{action.error}</Alert>}
      {created && (
        <Alert tone="ok">
          Copy this key now; it will not be shown again:
          <div className="secret-row">
            <code className="secret">{created}</code>
            <button
              className="btn-secondary"
              onClick={() => navigator.clipboard?.writeText(created).catch(() => undefined)}
            >
              Copy
            </button>
          </div>
        </Alert>
      )}
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          action
            .run('create-key', () => createApiKey(name.trim()))
            .then((res) => {
              if (res) {
                setCreated(res.key);
                setName('');
              }
              keys.reload();
            });
        }}
      >
        <input required value={name} placeholder="Where it is used, e.g. Work laptop agent" onChange={(e) => setName(e.target.value)} />
        <button type="submit" disabled={action.busy !== null || !name.trim()}>
          Create key
        </button>
      </form>
      {keys.data && keys.data.length === 0 ? (
        <Empty title="No keys yet." />
      ) : (
        <ul className="rows">
          {(keys.data || []).map((k) => (
            <li key={k.key_id} className="trigger">
              <div className="trigger-main">
                <div className="row-title">
                  {k.name} {k.revoked_at && <Badge status="paused" label="Revoked" />}
                </div>
                <span className="muted small">
                  <code>{k.prefix}…</code> · created by {k.created_by} {timeAgo(k.created_at)} · last used{' '}
                  {timeAgo(k.last_used_at)}
                </span>
              </div>
              {!k.revoked_at && (
                <div className="actions">
                  <button
                    className="btn-danger"
                    disabled={action.busy !== null}
                    onClick={() => {
                      if (window.confirm(`Revoke "${k.name}"? Anything using it stops sending activity.`)) {
                        action.run(`revoke-${k.key_id}`, () => revokeApiKey(k.key_id)).then(() => keys.reload());
                      }
                    }}
                  >
                    Revoke
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};
