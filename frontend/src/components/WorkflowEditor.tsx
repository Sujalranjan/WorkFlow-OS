import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  CatalogActionInfo,
  CatalogGroup,
  EditorIssue,
  EditorStep,
  ParameterMode,
  WorkflowDefinitionInput,
  getCatalog,
  getWorkflowDefinition,
  listWorkflowVersions,
  saveWorkflowDefinition,
  validateWorkflowDefinition,
} from '../api';
import { Alert, Loading, formatTime, useAction, useLoad } from '../ui';

const human = (key: string) => key.replace(/_/g, ' ');
const MODE_LABEL: Record<ParameterMode | 'default', string> = {
  upstream: 'From an earlier step',
  fixed: 'Fixed value',
  runtime: 'Ask when the run starts',
  default: 'Default',
};

/** Edit a workflow's steps and where each input comes from. Saving creates a new version that must be approved again. */
export const WorkflowEditor: React.FC<{ workflowId: string; onSaved: () => void; onCancel: () => void }> = ({
  workflowId,
  onSaved,
  onCancel,
}) => {
  const loaded = useLoad(async () => {
    const [definition, catalog] = await Promise.all([getWorkflowDefinition(workflowId), getCatalog()]);
    return { definition, catalog };
  }, [workflowId]);
  if (loaded.error) return <Alert>{loaded.error}</Alert>;
  if (!loaded.data) return <Loading />;
  return <EditorForm {...loaded.data} workflowId={workflowId} onSaved={onSaved} onCancel={onCancel} />;
};

const EditorForm: React.FC<{
  workflowId: string;
  definition: Awaited<ReturnType<typeof getWorkflowDefinition>>;
  catalog: CatalogGroup[];
  onSaved: () => void;
  onCancel: () => void;
}> = ({ workflowId, definition, catalog, onSaved, onCancel }) => {
  const actions = useMemo(() => {
    const map = new Map<string, CatalogActionInfo>();
    catalog.forEach((g) => g.actions.forEach((a) => map.set(a.action_id, a)));
    return map;
  }, [catalog]);
  const [title, setTitle] = useState(definition.title);
  const [description, setDescription] = useState(definition.description);
  const [steps, setSteps] = useState<EditorStep[]>(definition.steps);
  const [note, setNote] = useState('');
  const [adding, setAdding] = useState('');
  const [issues, setIssues] = useState<EditorIssue[]>([]);
  const action = useAction();

  const body: WorkflowDefinitionInput = { base_version: definition.version, title, description, steps, note: note.trim() || undefined };

  // Check the edit on the server as it changes (the same rules saving uses).
  const seq = useRef(0);
  useEffect(() => {
    const mine = ++seq.current;
    const t = window.setTimeout(() => {
      validateWorkflowDefinition(workflowId, body)
        .then((r) => mine === seq.current && setIssues(r.issues))
        .catch((e: Error) =>
          mine === seq.current && setIssues([{ level: 'error', message: e.message, step: null, parameter: null }]),
        );
    }, 350);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, description, JSON.stringify(steps)]);

  const errors = issues.filter((i) => i.level === 'error');
  const label = (id: string) => {
    const a = actions.get(id);
    return a ? `${a.application}: ${a.description}` : id;
  };
  // Run values available to step i: what the steps before it produce.
  const availableAt = (i: number) => {
    const out: { key: string; from: string }[] = [];
    steps.slice(0, i).forEach((s) =>
      (actions.get(s.catalog_action)?.produces || []).forEach((key) => {
        if (!out.some((o) => o.key === key)) out.push({ key, from: label(s.catalog_action) });
      }),
    );
    return out;
  };

  const update = (i: number, step: EditorStep) => setSteps((cur) => cur.map((s, j) => (j === i ? step : s)));
  const move = (i: number, by: number) =>
    setSteps((cur) => {
      const next = [...cur];
      const [s] = next.splice(i, 1);
      next.splice(i + by, 0, s);
      return next;
    });
  const remove = (i: number) => setSteps((cur) => cur.filter((_, j) => j !== i));
  const addStep = () => {
    const a = actions.get(adding);
    if (!a) return;
    const avail = availableAt(steps.length).map((x) => x.key);
    const parameters: EditorStep['parameters'] = {};
    a.parameters.forEach((p) => {
      if (p.default_upstream && avail.includes(p.default_upstream)) parameters[p.name] = { mode: 'upstream', value: p.default_upstream };
      else if (p.required) parameters[p.name] = { mode: 'runtime' };
    });
    setSteps((cur) => [...cur, { catalog_action: a.action_id, parameters }]);
    setAdding('');
  };

  const save = () => {
    if (
      !window.confirm(
        'Save these changes as a new version?\n\nThe workflow will need to be approved again before it runs, and email triggers wait until then.',
      )
    )
      return;
    action.run('save', () => saveWorkflowDefinition(workflowId, body), 'Saved as a new version. It needs approval before it runs.').then(
      (res) => res && onSaved(),
    );
  };

  return (
    <section className="card card-highlight">
      <div className="card-head">
        <h2>Edit workflow</h2>
        <span className="muted small">from version {definition.version}</span>
      </div>
      <div className="form">
        <label className="field">
          Title
          <input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          Description
          <textarea rows={2} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
      </div>

      <h3>Steps</h3>
      {issues
        .filter((i) => i.step === null)
        .map((i) => (
          <Alert key={i.message} tone={i.level === 'error' ? 'error' : 'info'}>
            {i.message}
          </Alert>
        ))}
      <ol className="editor-steps">
        {steps.map((s, i) => {
          const a = actions.get(s.catalog_action);
          const stepIssues = issues.filter((x) => x.step === i && !x.parameter);
          const avail = availableAt(i);
          return (
            <li key={`${s.step_id || 'new'}-${i}`} className="editor-step">
              <div className="editor-step-head">
                <span className="run-step-num">{i + 1}</span>
                <div className="editor-step-title">
                  <strong>{label(s.catalog_action)}</strong>
                  {a && <span className={`badge badge-${a.risk_level === 'high' ? 'bad' : a.risk_level === 'medium' ? 'warn' : 'good'}`}>{a.risk_level} risk</span>}
                  {!s.step_id && <span className="badge badge-info">new</span>}
                </div>
                <div className="editor-step-actions">
                  <button className="btn-secondary btn-small" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
                    ↑
                  </button>
                  <button className="btn-secondary btn-small" aria-label="Move down" disabled={i === steps.length - 1} onClick={() => move(i, 1)}>
                    ↓
                  </button>
                  <button className="btn-danger btn-small" aria-label="Remove step" disabled={steps.length === 1} onClick={() => remove(i)}>
                    ✕
                  </button>
                </div>
              </div>
              {stepIssues.map((x) => (
                <div key={x.message} className={x.level === 'error' ? 'error-text small' : 'muted small'}>
                  {x.message}
                </div>
              ))}
              {a && a.parameters.length > 0 && (
                <div className="editor-params">
                  {a.parameters.map((p) => {
                    const choice = s.parameters[p.name];
                    const mode: ParameterMode | 'default' = choice ? choice.mode : 'default';
                    const paramIssues = issues.filter((x) => x.step === i && x.parameter === p.name);
                    const setChoice = (next: ParameterMode | 'default', value?: string) => {
                      const params = { ...s.parameters };
                      if (next === 'default') delete params[p.name];
                      else params[p.name] = { mode: next, value: value ?? (next === 'upstream' ? avail.find((x) => x.key === p.default_upstream)?.key || avail[0]?.key : '') };
                      update(i, { ...s, parameters: params });
                    };
                    return (
                      <div key={p.name} className="editor-param">
                        <div className="small">
                          <strong>{human(p.name)}</strong> <span className="muted">{p.description}</span>
                        </div>
                        <div className="editor-param-row">
                          <select value={mode} onChange={(e) => setChoice(e.target.value as ParameterMode | 'default')}>
                            <option value="upstream">{MODE_LABEL.upstream}</option>
                            <option value="fixed">{MODE_LABEL.fixed}</option>
                            <option value="runtime">{MODE_LABEL.runtime}</option>
                            {!p.required && <option value="default">{MODE_LABEL.default}</option>}
                          </select>
                          {mode === 'upstream' && (
                            <select value={choice?.value || ''} onChange={(e) => setChoice('upstream', e.target.value)}>
                              <option value="">Choose…</option>
                              {avail.map((x) => (
                                <option key={x.key} value={x.key}>
                                  {human(x.key)} ({x.from})
                                </option>
                              ))}
                            </select>
                          )}
                          {mode === 'fixed' && (
                            <input value={choice?.value || ''} maxLength={1000} onChange={(e) => setChoice('fixed', e.target.value)} />
                          )}
                        </div>
                        {paramIssues.map((x) => (
                          <div key={x.message} className={x.level === 'error' ? 'error-text small' : 'muted small'}>
                            {x.message}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ol>

      <div className="inline-form">
        <select value={adding} onChange={(e) => setAdding(e.target.value)} aria-label="Step to add">
          <option value="">Add a step…</option>
          {catalog.map((g) => (
            <optgroup key={g.key} label={g.name}>
              {g.actions.map((a) => (
                <option key={a.action_id} value={a.action_id}>
                  {a.description}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <button className="btn-secondary" disabled={!adding} onClick={addStep}>
          Add step
        </button>
      </div>
      {definition.context_steps.length > 0 && (
        <p className="muted small">
          {definition.context_steps.length} recorded context step(s) (such as switching windows) are not run and are not part of an
          edited version; they stay visible in version {definition.version}.
        </p>
      )}

      <label className="field">
        What changed and why (shown in the history)
        <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="e.g. label processed emails" />
      </label>
      {action.error && <Alert>{action.error}</Alert>}
      <div className="actions">
        <button disabled={action.busy !== null || errors.length > 0} onClick={save}>
          {action.busy === 'save' ? 'Saving…' : errors.length ? `Fix ${errors.length} problem${errors.length === 1 ? '' : 's'} first` : 'Save new version'}
        </button>
        <button className="btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
};

/** Every saved version, newest first, with what changed. */
export const VersionHistory: React.FC<{ workflowId: string; reloadKey: string }> = ({ workflowId, reloadKey }) => {
  const data = useLoad(() => listWorkflowVersions(workflowId), [workflowId, reloadKey]);
  if (!data.data || data.data.versions.length < 2) return null;
  return (
    <section className="card">
      <h2>Version history</h2>
      <ol className="history">
        {data.data.versions.map((v) => (
          <li key={v.version}>
            <div>
              <strong>Version {v.version}</strong>
              {v.version === data.data!.current_version && <span className="badge badge-info">current</span>}{' '}
              <span className="muted small">
                {v.created_by ? `by ${v.created_by} · ` : ''}
                {formatTime(v.created_at)}
              </span>
            </div>
            {v.note && <div className="small">{v.note}</div>}
            {v.changes.length > 0 && (
              <ul className="muted small">
                {v.changes.map((c, i) => (
                  <li key={i}>{c.text}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
};
