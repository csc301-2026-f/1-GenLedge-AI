import { useEffect, useRef, useState } from 'react'
import { Alert, Btn, Modal, T } from '../../shared'
import { ACCEPTED_FILES, MAX_FILE_BYTES, importFile } from './client'
import type { SavedSource } from './client'

export function UploadFileModal({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [result, setResult] = useState<SavedSource | null>(null)
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement | null>(null)
  const active = useRef<AbortController | null>(null)
  useEffect(() => () => active.current?.abort(), [])

  function select(files: FileList | null) {
    setResult(null)
    setFile(null)
    setError('')
    if (!files?.length) return
    if (files.length !== 1) return setError('Select one file at a time.')
    const selected = files[0]
    const extension = '.' + selected.name.split('.').pop()?.toLowerCase()
    if (!ACCEPTED_FILES.split(',').includes(extension)) return setError('Choose a CSV, TSV, XLSX, XLS, JSON, or NDJSON file.')
    if (selected.size > MAX_FILE_BYTES) return setError('File exceeds the 25 MB limit (25,000,000 bytes).')
    if (!selected.size) return setError('The selected file is empty.')
    setFile(selected)
  }

  async function save() {
    if (!file || active.current) return
    const controller = new AbortController()
    active.current = controller
    setBusy(true)
    setError('')
    setResult(null)
    const timeout = setTimeout(() => controller.abort(), 120_000)
    try {
      const data = await importFile(file, controller.signal)
      if (!controller.signal.aborted) { setResult(data); onImported() }
    } catch (error) {
      setError(controller.signal.aborted ? 'Import completion could not be confirmed. Refresh the source list before retrying.'
        : error instanceof Error ? error.message : 'Unable to import this file.')
    } finally {
      clearTimeout(timeout)
      active.current = null
      setBusy(false)
    }
  }

  return (
    <Modal title="Import Source File" onClose={() => { if (!busy) onClose() }} width={540}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Alert type="info">Files are fully validated before saving. Uploading the same filename updates its existing source. Supported: CSV, TSV, XLSX, XLS, JSON, NDJSON. Maximum 25 MB per file and 50,000 records per collection.</Alert>
        <div onDragOver={event => event.preventDefault()} onDrop={event => {
          event.preventDefault()
          if (!busy) select(event.dataTransfer.files)
        }} style={{ border: `2px dashed ${T.border}`, borderRadius: 3, padding: 24, background: T.tableHead }}>
          <p style={{ marginBottom: 12 }}>Drop a file here or choose a file</p>
          <Btn variant="secondary" disabled={busy} onClick={() => input.current?.click()}>Choose File</Btn>
          <input ref={input} id="source-file" aria-label="Source file" type="file" accept={ACCEPTED_FILES} disabled={busy} hidden
            onChange={event => { select(event.target.files); event.target.value = '' }} />
          {file && <p style={{ marginTop: 12, overflowWrap: 'anywhere' }}>Selected: {file.name} ({file.size.toLocaleString()} bytes)</p>}
        </div>
        {error && <div role="alert"><Alert type="error">{error}</Alert></div>}
        {busy && <p role="status">Validating and saving all collections…</p>}
        {result && <div role="status" style={{ maxHeight: 280, overflow: 'auto' }}>
          <Alert type="success">Import complete. {result.collections.length} collection(s) saved.</Alert>
          {result.collections.map(collection => <div key={collection.collectionId} style={{ marginTop: 12 }}>
            <strong>{collection.name}</strong> — {collection.rowCount.toLocaleString()} record{collection.rowCount === 1 ? '' : 's'}
            {collection.warnings.length > 0 && <details>
              <summary>{collection.warnings.length} header correction(s)</summary>
              <ul>{collection.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
            </details>}
          </div>)}
        </div>}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 8, borderTop: `1px solid ${T.border}` }}>
          <Btn variant="secondary" disabled={busy} onClick={onClose}>Close</Btn>
          <Btn variant="primary" disabled={!file || busy || !!result} onClick={save}>{busy ? 'Importing…' : 'Import File'}</Btn>
        </div>
      </div>
    </Modal>
  )
}
