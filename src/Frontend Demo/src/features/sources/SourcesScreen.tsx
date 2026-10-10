import React, { useState, useMemo, useEffect, useRef } from 'react'
import { T, cx, StatusPill, Btn, TextInput, SelectInput, Ico, Pager, SortIcon, TH, TR, TD, FilterBar, SearchBox, FilterSelect, PageHeader, Panel, InfoRow, Modal, Alert } from '../../shared'
import type { Screen, Nav } from '../../app/types'
import type { SortDir } from '../../shared'
import { SOURCES_DATA } from './data'

// ─── US2 — Data Sources ───────────────────────────────────────────────────────
const DB_FIELDS: Record<string, { label: string; fields: { key: string; label: string; type?: string; placeholder?: string }[] }> = {
  mongodb: {
    label: 'MongoDB',
    fields: [
      { key: 'url', label: 'Connection URL', placeholder: 'mongodb+srv://user:pass@cluster.mongodb.net/dbname' },
      { key: 'token', label: 'API Token / Password', type: 'password', placeholder: '••••••••••••' },
      { key: 'database', label: 'Database Name', placeholder: 'production' },
    ],
  },
  documentdb: {
    label: 'Amazon DocumentDB',
    fields: [
      { key: 'url', label: 'Connection URL', placeholder: 'mongodb://user:pass@cluster.region.docdb.amazonaws.com:27017' },
      { key: 'token', label: 'Password', type: 'password', placeholder: '••••••••••••' },
      { key: 'database', label: 'Database Name', placeholder: 'mydb' },
      { key: 'tlsCAFile', label: 'TLS CA Certificate Path', placeholder: '/path/to/rds-combined-ca-bundle.pem' },
    ],
  },
  postgresql: {
    label: 'PostgreSQL',
    fields: [
      { key: 'host', label: 'Host', placeholder: 'db.example.com' },
      { key: 'port', label: 'Port', placeholder: '5432' },
      { key: 'database', label: 'Database Name', placeholder: 'mydb' },
      { key: 'user', label: 'Username', placeholder: 'postgres' },
      { key: 'token', label: 'Password', type: 'password', placeholder: '••••••••••••' },
    ],
  },
  mysql: {
    label: 'MySQL / MariaDB',
    fields: [
      { key: 'host', label: 'Host', placeholder: 'db.example.com' },
      { key: 'port', label: 'Port', placeholder: '3306' },
      { key: 'database', label: 'Database Name', placeholder: 'mydb' },
      { key: 'user', label: 'Username', placeholder: 'root' },
      { key: 'token', label: 'Password', type: 'password', placeholder: '••••••••••••' },
    ],
  },
  mssql: {
    label: 'Microsoft SQL Server',
    fields: [
      { key: 'host', label: 'Server / Host', placeholder: 'sqlserver.example.com' },
      { key: 'port', label: 'Port', placeholder: '1433' },
      { key: 'database', label: 'Database Name', placeholder: 'AdventureWorks' },
      { key: 'user', label: 'Username', placeholder: 'sa' },
      { key: 'token', label: 'Password', type: 'password', placeholder: '••••••••••••' },
    ],
  },
  elasticsearch: {
    label: 'Elasticsearch',
    fields: [
      { key: 'url', label: 'Cluster URL', placeholder: 'https://my-cluster.es.io:9200' },
      { key: 'token', label: 'API Key', type: 'password', placeholder: 'base64-encoded-api-key' },
      { key: 'index', label: 'Index Pattern', placeholder: 'logs-*' },
    ],
  },
  bigquery: {
    label: 'Google BigQuery',
    fields: [
      { key: 'project', label: 'Project ID', placeholder: 'my-gcp-project' },
      { key: 'dataset', label: 'Dataset', placeholder: 'analytics' },
      { key: 'token', label: 'Service Account JSON Key', type: 'password', placeholder: 'Paste JSON key content…' },
    ],
  },
  snowflake: {
    label: 'Snowflake',
    fields: [
      { key: 'url', label: 'Account URL', placeholder: 'myorg-myaccount.snowflakecomputing.com' },
      { key: 'user', label: 'Username', placeholder: 'SVCACCOUNT' },
      { key: 'token', label: 'Password / Private Key', type: 'password', placeholder: '••••••••••••' },
      { key: 'database', label: 'Database', placeholder: 'PROD_DB' },
      { key: 'warehouse', label: 'Warehouse', placeholder: 'COMPUTE_WH' },
    ],
  },
}

function ConnectDatabaseModal({ onClose, onConnect }: { onClose: () => void; onConnect: () => void }) {
  const [dbType, setDbType] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [owner, setOwner] = useState('')
  const [env, setEnv] = useState('production')

  const config = dbType ? DB_FIELDS[dbType] : null

  const setVal = (key: string, v: string) => setValues(prev => ({ ...prev, [key]: v }))

  const canSubmit = dbType && config && config.fields.every(f => values[f.key]?.trim()) && owner.trim()

  return (
    <Modal title="Connect Database" onClose={onClose} width={500}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <SelectInput
          label="Database Type"
          value={dbType}
          onChange={v => { setDbType(v); setValues({}) }}
          options={Object.entries(DB_FIELDS).map(([k, v]) => ({ value: k, label: v.label }))}
        />

        {config && (
          <>
            <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
              {config.fields.map(f => (
                <TextInput
                  key={f.key}
                  label={f.label}
                  type={f.type ?? 'text'}
                  value={values[f.key] ?? ''}
                  onChange={v => setVal(f.key, v)}
                  placeholder={f.placeholder}
                />
              ))}
            </div>
            <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
              <TextInput label="Source Owner / Team" value={owner} onChange={setOwner} placeholder="e.g. Finance Ops" />
              <SelectInput label="Target Environment" value={env} onChange={setEnv}
                options={[{ value: 'production', label: 'Production (intake-acme-prod)' }, { value: 'staging', label: 'Staging (intake-acme-stg)' }]} />
            </div>
          </>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 8, borderTop: `1px solid ${T.border}` }}>
          <Btn variant="secondary" onClick={onClose}>Cancel</Btn>
          <Btn variant="primary" disabled={!canSubmit} onClick={() => { onClose(); onConnect() }}>
            <Ico.Database /> Test &amp; Connect
          </Btn>
        </div>
      </div>
    </Modal>
  )
}

export function SourcesScreen({ onNav, onAdvance, onInvalidate }: { onNav: Nav; onAdvance: () => void; onInvalidate: () => void }) {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [page, setPage] = useState(1)
  const [sortCol, setSortCol] = useState('lastIngested')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [showUpload, setShowUpload] = useState(false)
  const [showConnect, setShowConnect] = useState(false)

  const handleSort = (col: string) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const filtered = useMemo(() => {
    let d = [...SOURCES_DATA]
    if (search) d = d.filter(r => r.name.toLowerCase().includes(search.toLowerCase()) || r.owner.toLowerCase().includes(search.toLowerCase()) || r.id.toLowerCase().includes(search.toLowerCase()))
    if (statusFilter) d = d.filter(r => r.status === statusFilter)
    if (typeFilter) d = d.filter(r => r.type === typeFilter)
    d.sort((a, b) => {
      const v = sortDir === 'asc' ? 1 : -1
      if (sortCol === 'documents') return (a.documents - b.documents) * v
      const aVal = (a as any)[sortCol] ?? ''
      const bVal = (b as any)[sortCol] ?? ''
      return aVal < bVal ? -v : aVal > bVal ? v : 0
    })
    return d
  }, [search, statusFilter, typeFilter, sortCol, sortDir])

  const pageSize = 10
  const paged = filtered.slice((page - 1) * pageSize, page * pageSize)

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', background: T.bg }}>
      <PageHeader
        title="Data Sources"
        subtitle="Manage ingestion sources: uploaded files and connected databases"
        actions={
          <>
            <Btn variant="secondary" onClick={() => setShowConnect(true)}><Ico.Database /> Connect Database</Btn>
            <Btn variant="primary" onClick={() => setShowUpload(true)}><Ico.Upload /> Upload File</Btn>
          </>
        }
      />

      {/* Summary row */}
      <div style={{ display: 'flex', gap: 1, padding: '12px 20px', background: T.bg, flexShrink: 0 }}>
        {[
          { label: 'Total Sources', value: '7' },
          { label: 'Active / Connected', value: '5' },
          { label: 'Total Documents', value: '390,689' },
          { label: 'Collections', value: '16' },
          { label: 'Last Activity', value: '08:47 today' },
        ].map(s => (
          <div key={s.label} style={{ flex: 1, background: T.surface, border: `1px solid ${T.border}`, padding: '10px 14px', marginRight: 8, borderRadius: 3 }}>
            <div style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMid, marginBottom: 4 }}>{s.label}</div>
            <div style={{ fontSize: `calc(${18}px * var(--font-scale, 1))`, fontWeight: 700, color: T.text }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Table panel */}
      <div style={{ flex: 1, padding: '0 20px 20px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 3, display: 'flex', flexDirection: 'column', overflow: 'hidden', flex: 1 }}>
          <FilterBar>
            <SearchBox value={search} onChange={v => { setSearch(v); setPage(1) }} placeholder="Search by name, owner, source ID…" width={290} />
            <FilterSelect value={statusFilter} onChange={v => { setStatusFilter(v); setPage(1) }} placeholder="All Statuses"
              options={[{ value: 'ready', label: 'Ready' }, { value: 'ingesting', label: 'Ingesting' }, { value: 'connected', label: 'Connected' }]} />
            <FilterSelect value={typeFilter} onChange={v => { setTypeFilter(v); setPage(1) }} placeholder="All Types"
              options={[{ value: 'XLSX', label: 'XLSX' }, { value: 'CSV', label: 'CSV' }, { value: 'JSON', label: 'JSON' }, { value: 'NDJSON', label: 'NDJSON' }, { value: 'MongoDB', label: 'MongoDB' }]} />
            {(search || statusFilter || typeFilter) && (
              <Btn variant="ghost" onClick={() => { setSearch(''); setStatusFilter(''); setTypeFilter('') }}>Clear filters</Btn>
            )}
            <span style={{ marginLeft: 'auto', fontSize: `calc(${12}px * var(--font-scale, 1))`, color: T.textMid }}>{filtered.length} result{filtered.length !== 1 ? 's' : ''}</span>
          </FilterBar>

          <div style={{ overflow: 'auto', flex: 1 }}>
            <table style={{ minWidth: 860 }}>
              <thead>
                <tr>
                  <TH label="Source ID" col="id" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={100} />
                  <TH label="Source Name" col="name" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
                  <TH label="Type" col="type" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={80} />
                  <TH label="Owner" col="owner" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={140} />
                  <TH label="Collections" col="collections" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={100} align="right" />
                  <TH label="Documents" col="documents" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={110} align="right" />
                  <TH label="Status" col="status" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={110} />
                  <TH label="Last Ingested" col="lastIngested" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} width={150} />
                  <th style={{ width: 120, minWidth: 120, position: 'sticky', right: 0, zIndex: 3, background: T.tableHead, borderBottom: `1px solid ${T.border}`, boxShadow: '-1px 0 0 0 var(--c-dfe1e6)' }} />
                </tr>
              </thead>
              <tbody>
                {paged.map(row => (
                  <TR key={row.id} onClick={onAdvance}
                    actions={<div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 4 }}>
                      <Btn variant="ghost" onClick={onAdvance}><Ico.Search /> Discover</Btn>
                      <Btn variant="ghost" onClick={onInvalidate}><Ico.Edit /></Btn>
                    </div>}>
                    <TD mono muted tooltip={row.id}>{row.id}</TD>
                    <TD tooltip={row.name}><span style={{ color: 'var(--link-color)', fontWeight: 500 }}>{row.name}</span></TD>
                    <TD tooltip={row.type}><span style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, fontWeight: 600, background: T.tableHead, border: `1px solid ${T.border}`, borderRadius: 2, padding: '1px 6px', color: T.textMid }}>{row.type}</span></TD>
                    <TD muted tooltip={row.owner}>{row.owner}</TD>
                    <TD mono right tooltip={String(row.collections)}>{row.collections}</TD>
                    <TD mono right tooltip={row.documents.toLocaleString()}>{row.documents.toLocaleString()}</TD>
                    <TD tooltip={row.status}><StatusPill status={row.status} /></TD>
                    <TD mono muted nowrap tooltip={row.lastIngested}>{row.lastIngested}</TD>
                  </TR>
                ))}
                {paged.length === 0 && (
                  <tr><td colSpan={9} style={{ padding: '32px 16px', textAlign: 'center', color: T.textMid, fontSize: `calc(${13}px * var(--font-scale, 1))`}}>No records match the current filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <Pager total={filtered.length} page={page} pageSize={pageSize} onPage={setPage} />
        </div>
      </div>

      {showConnect && (
        <ConnectDatabaseModal onClose={() => setShowConnect(false)} onConnect={onAdvance} />
      )}

      {showUpload && (
        <Modal title="Upload Source File" onClose={() => setShowUpload(false)} width={460}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Alert type="info">Supported formats: CSV, TSV, XLSX, XLS, JSON, NDJSON, MongoDB, DocumentDB. Maximum 25 MB per file or 50,000 rows per worksheet.</Alert>
            <div style={{ border: `2px dashed ${T.border}`, borderRadius: 3, padding: '32px 24px', textAlign: 'center', background: T.tableHead }}>
              <div style={{ color: T.textMid, marginBottom: 8 }}><Ico.Upload /></div>
              <p style={{ fontSize: `calc(${13}px * var(--font-scale, 1))`, color: T.textMid }}>Drag and drop files here, or <span style={{ color: 'var(--link-color)', cursor: 'pointer' }}>browse to select</span></p>
              <p style={{ fontSize: `calc(${11}px * var(--font-scale, 1))`, color: T.textMuted, marginTop: 4 }}>Each worksheet will become a separate source collection</p>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <TextInput label="Source Owner / Team" value="Finance Ops" onChange={() => {}} />
              <SelectInput label="Target Environment" value="production" onChange={() => {}}
                options={[{ value: 'production', label: 'Production (intake-acme-prod)' }, { value: 'staging', label: 'Staging (intake-acme-stg)' }]} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 8, borderTop: `1px solid ${T.border}` }}>
              <Btn variant="secondary" onClick={() => setShowUpload(false)}>Cancel</Btn>
              <Btn variant="primary" onClick={() => { setShowUpload(false); onAdvance() }}><Ico.Upload /> Upload & Proceed</Btn>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
