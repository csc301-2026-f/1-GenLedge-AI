import { useEffect, useRef, useState } from 'react'
import { T, Btn, StatusPill, PageHeader, Alert, TypeTag } from '../../shared'
import type { Nav } from '../../app/types'
import { createJob, editJob, forget, readJob, readPackage, requestKey, RoutingError, store, type Decision, type Job, type ReviewPackage } from './client'

export function RouteScreen({ jobId, owner, onJob, onNav, onInvalidate }: {
  jobId: string; owner: string; onJob: (id: string) => void; onNav: Nav; onInvalidate: () => void
}) {
  const [job, setJob] = useState<Job | null>(null)
  const [review, setReview] = useState<ReviewPackage | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [saving, setSaving] = useState(false)
  const busy = useRef(false)

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    setJob(null); setReview(null); setError(''); setNotice('')
    async function refresh() {
      try {
        const status = await readJob(jobId)
        const result = await readPackage(jobId)
        if (!active) return
        setJob({ ...status, status: result.status, failure: result.failure })
        setReview(result.payload)
        if (['queued', 'running', 'revising', 'edit_requested', 'approval_requested', 'cancelling'].includes(result.status)) timer = setTimeout(refresh, 1000)
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : 'Unable to load routing.')
      }
    }
    void refresh()
    return () => { active = false; clearTimeout(timer) }
  }, [jobId, attempt])

  async function decide(target: string, decision: Decision) {
    if (busy.current) return
    busy.current = true; setSaving(true); setError(''); setNotice('')
    const scope = `edit:${owner}:${jobId}:${target}`
    // Retain a successful receipt too, so submitting the same decision replays.
    const choiceScope = `${scope}:${decision}`
    // A change of intent gets a fresh ID, even if the previous response was lost.
    forget(`${scope}:${decision === 'accept' ? 'reject' : 'accept'}`)
    try {
      const result = await editJob(jobId, requestKey(choiceScope), target, decision)
      const latest = await readPackage(jobId)
      setReview(latest.payload)
      setNotice(result.replayed ? 'Decision already saved; replay confirmed.' : 'Decision saved.')
      onInvalidate()
    } catch (e) {
      if (e instanceof RoutingError && e.status < 500) forget(choiceScope)
      setError(e instanceof Error ? e.message : 'Unable to save decision.')
    } finally { busy.current = false; setSaving(false) }
  }

  async function retry() {
    if (!job || busy.current) return
    busy.current = true; setSaving(true); setError('')
    const scope = `retry:${owner}:${jobId}`
    try {
      const result = await createJob(job.source_snapshot_id, requestKey(scope))
      store(`active:${owner}`, result.job_id)
      onJob(result.job_id)
    } catch (e) {
      if (e instanceof RoutingError && e.status < 500) forget(scope)
      setError(e instanceof Error ? e.message : 'Unable to retry routing.')
    } finally { busy.current = false; setSaving(false) }
  }

  return <div className="fade-in" style={{ height: '100%', overflow: 'auto', background: T.bg, color: T.text }}>
    <PageHeader title="AI Routing Results" subtitle="Review the saved proposals and record a decision for each table."
      actions={<Btn disabled={saving} onClick={() => onNav('discover')}>Schema Discovery</Btn>} />
    <div style={{ padding: 20, display: 'grid', gap: 16 }}>
      <div role="status" aria-live="polite">{job ? <><StatusPill status={job.status} /> · Model mode: <strong>{job.model_mode ?? 'Not resolved'}</strong> · Snapshot: {job.source_snapshot_id}</> : 'Loading routing job…'}</div>
      {error && <div role="alert"><Alert type="error">{error}</Alert><Btn onClick={() => setAttempt(n => n + 1)} disabled={saving}>Reload status</Btn></div>}
      {notice && <div role="status">{notice}</div>}
      {job?.status === 'blocked' && <Alert type="warning">This proposal has blockers. Review the findings below. Decisions are saved without clearing validation blockers.</Alert>}
      {job?.status === 'failed' && <div role="alert"><Alert type="error">{job.failure?.message ?? 'Routing failed.'}</Alert>{job.failure?.retryable && <Btn onClick={() => void retry()} disabled={saving}>Retry routing</Btn>}</div>}
      {job && ['queued', 'running'].includes(job.status) && <p>Routing is {job.status}. You can refresh this page; the saved job will be reopened.</p>}
      {job?.status === 'cancelled' && <p>This routing job was cancelled.</p>}
      {review && <>
        <h2>Proposed tables ({review.model_draft.tables.length})</h2>
        {review.model_draft.tables.map(table => <section key={table.id} aria-label={table.name} style={{ background: T.surface, border: `1px solid ${T.border}`, padding: 16, borderRadius: 4 }}>
          <h3>{table.name} · {review.is_new[table.id] === true ? 'New table' : review.is_new[table.id] === false ? 'Reuse table' : 'Table action unavailable'}</h3>
          <p>{table.rationale}</p>
          <p>Merge key: <code>{table.key.join(' + ')}</code></p>
          <p>Decision: <strong>{review.decisions[table.id] ?? 'Not reviewed'}</strong></p>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <Btn disabled={saving || !['blocked', 'awaiting_review'].includes(job?.status ?? '')} onClick={() => void decide(table.id, 'accept')}>Accept</Btn>
            <Btn disabled={saving || !['blocked', 'awaiting_review'].includes(job?.status ?? '')} onClick={() => void decide(table.id, 'reject')}>Reject</Btn>
          </div>
          <table><thead><tr><th>Source fields</th><th>Target column</th><th>Type</th><th>Confidence</th><th>Reason</th></tr></thead>
            <tbody>{table.attributes.map(attribute => {
              const mapping = review.mapping_draft.mappings.find(m => m.target === `${table.id}.${attribute.id}`)
              return <tr key={attribute.id}><td>{mapping?.sources.join(', ') ?? 'No validated mapping'}</td><td>{attribute.id}</td><td><TypeTag type={attribute.type} /></td><td>{Math.round(attribute.confidence * 100)}%</td><td>{mapping?.rationale ?? '—'}</td></tr>
            })}</tbody>
          </table>
        </section>)}
        <section aria-label="Findings"><h2>Findings ({review.findings.length})</h2>
          {review.findings.length === 0 && <p>No validation findings.</p>}
          {review.findings.map((finding, index) => <p key={index}><strong>{finding.severity} · {finding.code}</strong>{finding.target && ` · ${finding.target}`} — {finding.message}</p>)}
        </section>
        <section aria-label="Coverage"><h2>Source coverage</h2><table><thead><tr><th>Source field</th><th>Disposition</th><th>Reason</th></tr></thead><tbody>
          {review.coverage.map((field, i) => <tr key={i}><td>{field.resource_id}.{field.field_path}</td><td>{field.disposition}</td><td>{field.reason}</td></tr>)}
        </tbody></table></section>
        {[...review.model_draft.unresolved, ...review.mapping_draft.unresolved].length > 0 && <section><h2>Unresolved</h2>{[...review.model_draft.unresolved, ...review.mapping_draft.unresolved].map((text, i) => <p key={i}>{text}</p>)}</section>}
      </>}
    </div>
  </div>
}
