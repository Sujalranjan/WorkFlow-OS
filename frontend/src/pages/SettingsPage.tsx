import React, { useState } from 'react';
import {
  HubSpotProperty,
  Integrations,
  Role,
  SlackChannels,
  User,
  createApiKey,
  createUser,
  disconnectGmail,
  getHubSpotProperties,
  getIntegrations,
  listApiKeys,
  listSlackChannels,
  listUsers,
  removeGmailClient,
  removeHubSpot,
  removeSlack,
  revokeApiKey,
  saveGmailClient,
  saveHubSpot,
  saveHubSpotSettings,
  saveSlack,
  startGmailConnect,
  updateUser,
} from '../api';
import { Alert, Badge, Empty, Loading, PageHeader, go, timeAgo, useAction, useLoad, useRoute, useSession } from '../ui';

const ROLE_HELP: Record<Role, string> = {
  viewer: 'Sees everything, changes nothing',
  approver: 'Also creates, approves and runs workflows and answers paused runs',
  admin: 'Also manages email triggers, users and API keys',
};

export const SettingsPage: React.FC = () => (
  <>
    <PageHeader
      title="Settings"
      subtitle="Connected services, people who can sign in, and keys for the desktop agent and browser extension."
    />
    <IntegrationsSection />
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

const GMAIL_ERRORS: Record<string, string> = {
  expired: 'That sign-in link expired or was already used. Try Connect Gmail again.',
  denied: 'Google sign-in was cancelled or access was not granted.',
  exchange_failed: 'Google rejected the sign-in. Check the client ID, secret and that the redirect URI below is registered.',
  scope: 'Read-only Gmail access was not granted. Tick the Gmail permission on the consent screen.',
  no_refresh_token:
    "Google did not issue a long-lived token. Remove WorkFlowOS under your Google Account > Security > Third-party access, then connect again.",
  client_changed: 'The OAuth client changed during sign-in. Try again.',
  network: 'The server could not reach Google to finish signing in. Check its internet connection and try again.',
};

const IntegrationsSection: React.FC = () => {
  const info = useLoad(getIntegrations, []);
  const action = useAction();
  const [, outcome, code] = useRoute();
  const update = (p: Promise<Integrations | undefined>) => p.then(() => info.reload());

  return (
    <section className="card">
      <h2>Integrations</h2>
      <p className="muted small">
        Credentials are stored encrypted on the server and are never shown again after saving.
      </p>
      {outcome === 'gmail-connected' && (
        <Alert tone="ok">
          Gmail connected. <button className="link" onClick={() => go('settings')}>Dismiss</button>
        </Alert>
      )}
      {outcome === 'gmail-error' && (
        <Alert>
          {GMAIL_ERRORS[code || ''] || 'Connecting Gmail failed.'}{' '}
          <button className="link" onClick={() => go('settings')}>Dismiss</button>
        </Alert>
      )}
      {action.error && <Alert>{action.error}</Alert>}
      {action.notice && <Alert tone="ok">{action.notice}</Alert>}
      {info.error && <Alert>{info.error}</Alert>}
      {!info.data ? (
        <Loading />
      ) : (
        <>
          <GmailCard info={info.data} action={action} update={update} />
          <HubSpotCard info={info.data} action={action} update={update} />
          <SlackCard info={info.data} action={action} update={update} />
        </>
      )}
    </section>
  );
};

type CardProps = {
  info: Integrations;
  action: ReturnType<typeof useAction>;
  update: (p: Promise<Integrations | undefined>) => Promise<void>;
};

const GmailCard: React.FC<CardProps> = ({ info, action, update }) => {
  const g = info.gmail;
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [changingClient, setChangingClient] = useState(false);
  const busy = action.busy !== null;
  const showClientForm = !g.client_configured || changingClient;

  return (
    <div className="subform">
      <div className="card-head">
        <h3>Gmail (read-only)</h3>
        {g.connected ? <Badge status="completed" label="Connected" /> : <Badge status="paused" label="Not connected" />}
      </div>
      {g.connected && (
        <p className="muted small">
          {g.source === 'settings'
            ? `${g.account || 'Account'} · connected by ${g.connected_by || 'unknown'} ${timeAgo(g.connected_at)}`
            : 'Using token.json on the server. Connect here to manage it from the dashboard instead.'}
        </p>
      )}

      {showClientForm ? (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            const done = g.connected ? 'OAuth client saved. Click Reconnect Gmail to sign in with it.' : 'OAuth client saved.';
            update(action.run('gmail-client', () => saveGmailClient(clientId, clientSecret), done)).then(() => {
              setClientId('');
              setClientSecret('');
              setChangingClient(false);
            });
          }}
        >
          <p className="muted small">
            In Google Cloud Console, create an OAuth client ID of type <strong>Web application</strong> with this
            authorized redirect URI, enable the Gmail API, then paste the client ID and secret:
          </p>
          <code className="secret">{g.redirect_uri}</code>
          <div className="form-row">
            <label className="field">
              Client ID
              <input required value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="….apps.googleusercontent.com" />
            </label>
            <label className="field">
              Client secret
              <input required type="password" autoComplete="off" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
            </label>
          </div>
          <div className="actions">
            <button type="submit" disabled={busy}>
              Save OAuth client
            </button>
            {changingClient && (
              <button type="button" className="btn-secondary" onClick={() => setChangingClient(false)}>
                Cancel
              </button>
            )}
            {changingClient && g.client_source === 'settings' && (
              <button
                type="button"
                className="btn-secondary"
                disabled={busy}
                title="Forget the client saved here and use credentials.json on the server, if there is one"
                onClick={() =>
                  update(action.run('gmail-client-remove', removeGmailClient, 'Saved OAuth client removed.')).then(() =>
                    setChangingClient(false)
                  )
                }
              >
                Remove saved client
              </button>
            )}
          </div>
          {g.connected && (
            <p className="muted small">The current connection keeps working until you reconnect with the new client.</p>
          )}
        </form>
      ) : (
        <>
          <p className="muted small">
            OAuth client <code>{g.client_id}</code> ({g.client_source === 'settings' ? 'saved here' : 'from credentials.json'}).
            Redirect URI: <code>{g.redirect_uri}</code>
          </p>
          <div className="actions">
            <button
              disabled={busy}
              onClick={() =>
                action.run('gmail-connect', startGmailConnect).then((res) => {
                  if (res) window.location.assign(res.authorization_url);
                })
              }
            >
              {g.connected ? 'Reconnect Gmail' : 'Connect Gmail'}
            </button>
            {g.connected && g.source === 'settings' && (
              <button
                className="btn-danger"
                disabled={busy}
                onClick={() => {
                  if (window.confirm('Disconnect Gmail? Email triggers and Gmail steps stop working until it is connected again.')) {
                    update(action.run('gmail-disconnect', disconnectGmail, 'Gmail disconnected.'));
                  }
                }}
              >
                Disconnect
              </button>
            )}
            <button className="btn-secondary" disabled={busy} onClick={() => setChangingClient(true)}>
              Change OAuth client
            </button>
          </div>
        </>
      )}
    </div>
  );
};

const SlackCard: React.FC<CardProps> = ({ info, action, update }) => {
  const sl = info.slack;
  // 'token': paste a (new) token; 'channel': pick a channel with the saved token; null: summary
  const [mode, setMode] = useState<'token' | 'channel' | null>(null);
  const [token, setToken] = useState('');
  const [found, setFound] = useState<SlackChannels | null>(null);
  const [channel, setChannel] = useState('');
  const busy = action.busy !== null;
  const editing = !sl.configured || mode !== null;
  const usingSavedToken = sl.configured && mode === 'channel';
  const channelLabel = sl.channel_name ? `#${sl.channel_name}` : sl.channel_id;

  const reset = () => {
    setMode(null);
    setToken('');
    setFound(null);
    setChannel('');
  };

  const findChannels = (withToken: string | null) =>
    action.run('slack-channels', () => listSlackChannels(withToken)).then((res) => {
      if (!res) return;
      setFound(res);
      setChannel(sl.channel_id && res.channels.some((c) => c.id === sl.channel_id) ? sl.channel_id : '');
    });

  const save = () =>
    update(
      action.run('slack-save', () => saveSlack(usingSavedToken ? null : token, channel), (r) =>
        r.slack.bot_in_channel === false ? 'Saved, but the bot is not in that channel yet (see below).' : 'Slack settings saved.'
      )
    ).then(reset);

  const picked = found?.channels.find((c) => c.id === channel);

  return (
    <div className="subform">
      <div className="card-head">
        <h3>Slack</h3>
        {sl.configured ? <Badge status="completed" label="Configured" /> : <Badge status="paused" label="Not set up" />}
      </div>
      {sl.configured && (
        <p className="muted small">
          Posting to <code>{channelLabel}</code>
          {sl.channel_name ? ` (${sl.channel_id})` : ''}
          {sl.team ? ` in ${sl.team}` : ''}
          {sl.source === 'settings'
            ? ` · saved by ${sl.updated_by || 'unknown'} ${timeAgo(sl.updated_at)}`
            : ' · from SLACK_BOT_TOKEN / SLACK_CHANNEL_ID on the server'}
        </p>
      )}
      {sl.configured && sl.bot_in_channel === false && !editing && (
        <Alert>
          The bot is not a member of <code>{channelLabel}</code>, so Slack steps will fail. In Slack, open the channel and
          run <code>/invite @your-bot</code>, then save the channel again here to re-check.
        </Alert>
      )}

      {editing ? (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            if (found) save();
            else findChannels(usingSavedToken ? null : token);
          }}
        >
          {!usingSavedToken && (
            <>
              <p className="muted small">
                Use a bot token (<code>xoxb-…</code>) with <code>chat:write</code> and <code>channels:history</code>. Add{' '}
                <code>channels:read</code> (and <code>groups:read</code> for private channels) to choose the channel from a
                list. Invite the bot to the channel.
              </p>
              <label className="field">
                Bot token
                <input
                  required
                  type="password"
                  autoComplete="off"
                  value={token}
                  onChange={(e) => {
                    setToken(e.target.value);
                    setFound(null);
                  }}
                />
              </label>
            </>
          )}

          {found && (
            <>
              {found.notes.map((n) => (
                <p key={n} className="muted small">
                  {n}
                </p>
              ))}
              {found.can_list && found.channels.length > 0 ? (
                <label className="field">
                  Channel
                  <select required value={channel} onChange={(e) => setChannel(e.target.value)}>
                    <option value="">Choose…</option>
                    {found.channels.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.is_private ? '🔒 ' : '#'}
                        {c.name}
                        {c.is_member ? '' : ' (bot not invited)'}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label className="field">
                  Channel ID
                  <input required value={channel} onChange={(e) => setChannel(e.target.value.trim())} placeholder="C0123456789" />
                </label>
              )}
              {picked && !picked.is_member && (
                <p className="muted small">
                  The bot is not in #{picked.name} yet. Invite it in Slack (<code>/invite @your-bot</code>) before the first run.
                </p>
              )}
            </>
          )}

          <div className="actions">
            <button type="submit" disabled={busy || (!!found && !channel)}>
              {found ? 'Save' : usingSavedToken ? 'Load channels' : 'Check token'}
            </button>
            {sl.configured && (
              <button type="button" className="btn-secondary" onClick={reset}>
                Cancel
              </button>
            )}
          </div>
        </form>
      ) : (
        <div className="actions">
          {sl.source === 'settings' && (
            <button
              disabled={busy}
              onClick={() => {
                setMode('channel');
                findChannels(null);
              }}
            >
              Change channel
            </button>
          )}
          <button className="btn-secondary" disabled={busy} onClick={() => setMode('token')}>
            Change token
          </button>
          {sl.source === 'settings' && (
            <button
              className="btn-danger"
              disabled={busy}
              onClick={() => {
                if (window.confirm('Remove the Slack token? Slack steps stop working until a token is saved again.')) {
                  update(action.run('slack-remove', removeSlack, 'Slack token removed.'));
                }
              }}
            >
              Remove
            </button>
          )}
        </div>
      )}
    </div>
  );
};

const HubSpotCard: React.FC<CardProps> = ({ info, action, update }) => {
  const hs = info.hubspot;
  const [token, setToken] = useState('');
  const [editing, setEditing] = useState(false);
  const [properties, setProperties] = useState<HubSpotProperty[] | null>(null);
  const [property, setProperty] = useState('');
  const [value, setValue] = useState('');
  const busy = action.busy !== null;
  const showTokenForm = !hs.configured || editing;
  const chosen = properties?.find((p) => p.name === property);

  const loadProperties = () =>
    action.run('hubspot-properties', getHubSpotProperties).then((list) => {
      if (!list) return;
      setProperties(list);
      setProperty(hs.status_property || '');
      setValue(hs.status_value || '');
    });

  return (
    <div className="subform">
      <div className="card-head">
        <h3>HubSpot</h3>
        {hs.configured ? <Badge status="completed" label="Connected" /> : <Badge status="paused" label="Not set up" />}
      </div>
      {hs.configured && (
        <p className="muted small">
          {hs.portal_id ? `Account ${hs.portal_id}` : 'Connected'}
          {hs.source === 'settings'
            ? ` · saved by ${hs.updated_by || 'unknown'} ${timeAgo(hs.updated_at)}`
            : ' · from HUBSPOT_ACCESS_TOKEN on the server'}
        </p>
      )}

      {showTokenForm ? (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            update(action.run('hubspot-save', () => saveHubSpot(token), 'HubSpot key checked and saved.')).then(() => {
              setToken('');
              setEditing(false);
            });
          }}
        >
          <p className="muted small">
            In HubSpot, create a <strong>service key</strong> with the scopes <code>crm.objects.contacts.read</code>,{' '}
            <code>crm.objects.contacts.write</code> and <code>crm.schemas.contacts.read</code>, then paste it here. An existing
            private-app token also works.
          </p>
          <label className="field">
            Service key or private-app token
            <input
              required
              minLength={20}
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <div className="actions">
            <button type="submit" disabled={busy}>
              Check and save
            </button>
            {editing && (
              <button type="button" className="btn-secondary" onClick={() => setEditing(false)}>
                Cancel
              </button>
            )}
          </div>
        </form>
      ) : (
        <>
          <p className="muted small">
            {hs.status_property ? (
              <>
                "Update contact" steps write <code>{hs.status_property_label || hs.status_property}</code>
                {hs.status_value && (
                  <>
                    {' '}
                    (default value <code>{hs.status_value}</code>)
                  </>
                )}
                .
              </>
            ) : (
              'Choose which contact property "Update contact" steps write. Until then those steps are blocked.'
            )}
          </p>
          {properties ? (
            <form
              className="form"
              onSubmit={(e) => {
                e.preventDefault();
                update(
                  action.run('hubspot-settings', () => saveHubSpotSettings(property, value.trim() || null), 'HubSpot property saved.')
                ).then(() => setProperties(null));
              }}
            >
              <div className="form-row">
                <label className="field">
                  Contact property
                  <select
                    required
                    value={property}
                    onChange={(e) => {
                      setProperty(e.target.value);
                      setValue('');
                    }}
                  >
                    <option value="">Choose…</option>
                    {properties.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.label} ({p.name})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  Default value (optional)
                  {chosen && chosen.options.length > 0 ? (
                    <select value={value} onChange={(e) => setValue(e.target.value)}>
                      <option value="">None</option>
                      {chosen.options.map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Used when a run gives no value" />
                  )}
                </label>
              </div>
              <div className="actions">
                <button type="submit" disabled={busy || !property}>
                  Save property
                </button>
                <button type="button" className="btn-secondary" onClick={() => setProperties(null)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <div className="actions">
              {hs.source === 'settings' && (
                <button disabled={busy} onClick={loadProperties}>
                  {hs.status_property ? 'Change property' : 'Choose property'}
                </button>
              )}
              <button className="btn-secondary" disabled={busy} onClick={() => setEditing(true)}>
                Change key
              </button>
              {hs.source === 'settings' && (
                <button
                  className="btn-danger"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm('Remove the HubSpot key? HubSpot steps stop working until a key is saved again.')) {
                      update(action.run('hubspot-remove', removeHubSpot, 'HubSpot key removed.'));
                    }
                  }}
                >
                  Remove
                </button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
