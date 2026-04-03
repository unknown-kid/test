import { useEffect, useRef, useState, useCallback } from 'react'
import { Button, Space, Tooltip } from 'antd'
import { ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons'
import type { HighlightInfo, AnnotationInfo } from '../api/annotations'

let pdfjsLib: any = null
const getPdfjs = async () => {
  if (!pdfjsLib) {
    pdfjsLib = await import('pdfjs-dist')
    pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdf.worker.js'
  }
  return pdfjsLib
}

interface SelectionInfo {
  text: string
  rects: Array<{ x: number; y: number; w: number; h: number }>
  pageIndex: number
  clientRect: DOMRect
}

interface PdfViewerProps {
  url: string
  highlights: HighlightInfo[]
  annotations: AnnotationInfo[]
  readOnly: boolean
  onTextSelect?: (info: SelectionInfo) => void
  onDeleteHighlight?: (id: string) => void
  onDeleteAnnotation?: (id: string) => void
}

export type { SelectionInfo }

interface PageInfo { width: number; height: number }

function mergeRects(rects: Array<{ x: number; y: number; w: number; h: number }>) {
  if (rects.length <= 1) return rects
  const sorted = [...rects].sort((a, b) => a.y - b.y || a.x - b.x)
  const merged: typeof rects = [{ ...sorted[0] }]
  for (let i = 1; i < sorted.length; i++) {
    const curr = sorted[i]
    const prev = merged[merged.length - 1]
    const yOverlap = Math.abs(curr.y - prev.y) < Math.max(prev.h, curr.h) * 0.6
    const xTouching = curr.x <= prev.x + prev.w + 0.01
    if (yOverlap && xTouching) {
      const right = Math.max(prev.x + prev.w, curr.x + curr.w)
      const bottom = Math.max(prev.y + prev.h, curr.y + curr.h)
      prev.x = Math.min(prev.x, curr.x)
      prev.y = Math.min(prev.y, curr.y)
      prev.w = right - prev.x
      prev.h = bottom - prev.y
    } else {
      merged.push({ ...curr })
    }
  }
  return merged
}

const TEXT_LAYER_CSS = `
.pdf-page-container { position: relative; }
.pdf-page-container canvas { display: block; }
.pdf-text-layer {
  position: absolute;
  text-align: initial;
  left: 0;
  top: 0;
  overflow: clip;
  opacity: 1;
  line-height: 1;
  text-size-adjust: none;
  -webkit-text-size-adjust: none;
  forced-color-adjust: none;
  transform-origin: 0 0;
  z-index: 2;
}
.pdf-text-layer :is(span, br) {
  color: transparent;
  position: absolute;
  white-space: pre;
  cursor: text;
  transform-origin: 0% 0%;
}
.pdf-text-layer span::selection { background: rgba(0,100,255,0.3); }
.pdf-text-layer br::selection { background: rgba(0,100,255,0.3); }
.pdf-hl-layer {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}
.pdf-hl-item {
  position: absolute;
  border-radius: 2px;
  pointer-events: none;
}
.pdf-hl-item.highlight { background: rgba(255,235,59,0.4); }
.pdf-hl-item.annotation {
  background: rgba(33,150,243,0.3);
  border-bottom: 2px solid rgba(33,150,243,0.6);
}
.pdf-ctx-menu {
  position: fixed;
  z-index: 9999;
  background: #fff;
  border-radius: 6px;
  box-shadow: 0 3px 12px rgba(0,0,0,0.2);
  padding: 4px 0;
  min-width: 160px;
}
.pdf-ctx-menu-item {
  padding: 6px 16px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}
.pdf-ctx-menu-item:hover { background: #f5f5f5; }
.pdf-ctx-menu-item.danger { color: #ff4d4f; }
.pdf-ctx-menu-item.disabled { color: #999; cursor: default; }
.pdf-ctx-menu-item.disabled:hover { background: transparent; }
.pdf-ctx-menu-divider { height: 1px; background: #f0f0f0; margin: 4px 0; }
.pdf-zoom-bar {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 10;
  display: flex;
  gap: 4px;
  background: rgba(0,0,0,0.6);
  border-radius: 6px;
  padding: 4px 8px;
  align-items: center;
}
.pdf-zoom-bar .ant-btn { color: #fff !important; }
.pdf-zoom-bar .anticon { color: #fff !important; }
.pdf-main-scroll { overflow-y: auto; overflow-x: hidden; }
.pdf-main-scroll { overscroll-behavior: contain; }
.pdf-top-hscroll {
  overflow-x: auto;
  overflow-y: hidden;
  flex-shrink: 0;
}
.pdf-top-hscroll::-webkit-scrollbar { height: 8px; }
.pdf-top-hscroll::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.25); border-radius: 4px; }
`

export default function PdfViewer({ url, highlights, annotations, readOnly, onTextSelect, onDeleteHighlight, onDeleteAnnotation }: PdfViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const topScrollRef = useRef<HTMLDivElement>(null)
  const syncingRef = useRef(false)
  const pdfDocRef = useRef<any>(null)
  const renderTasksRef = useRef<Map<number, any>>(new Map())
  const renderedRef = useRef<Set<number>>(new Set())
  const observerRef = useRef<IntersectionObserver | null>(null)
  const scaleRef = useRef(1.5)
  const highlightsRef = useRef(highlights)
  const annotationsRef = useRef(annotations)

  const [scale, setScale] = useState(1.5)
  const [numPages, setNumPages] = useState(0)
  const [pageInfos, setPageInfos] = useState<PageInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; type: 'highlight' | 'annotation'; id: string; content?: string } | null>(null)
  const [contentWidth, setContentWidth] = useState(0)

  // Compute content width for top scrollbar
  useEffect(() => {
    if (pageInfos.length) {
      setContentWidth(Math.max(...pageInfos.map(info => info.width * scale)))
    }
  }, [pageInfos, scale])

  // Sync top scrollbar ↔ main container
  const syncFromTop = useCallback(() => {
    if (syncingRef.current) return
    syncingRef.current = true
    if (containerRef.current && topScrollRef.current) {
      containerRef.current.scrollLeft = topScrollRef.current.scrollLeft
    }
    syncingRef.current = false
  }, [])
  const syncFromMain = useCallback(() => {
    if (syncingRef.current) return
    syncingRef.current = true
    if (containerRef.current && topScrollRef.current) {
      topScrollRef.current.scrollLeft = containerRef.current.scrollLeft
    }
    syncingRef.current = false
  }, [])

  useEffect(() => { highlightsRef.current = highlights }, [highlights])
  useEffect(() => { annotationsRef.current = annotations }, [annotations])
  useEffect(() => { scaleRef.current = scale }, [scale])

  // Inject CSS once
  useEffect(() => {
    const id = 'pdf-viewer-styles'
    if (!document.getElementById(id)) {
      const style = document.createElement('style')
      style.id = id
      style.textContent = TEXT_LAYER_CSS
      document.head.appendChild(style)
    }
  }, [])

  // Render highlights for a page
  const renderHighlights = useCallback((hlDiv: HTMLDivElement, pageIndex: number, vw: number, vh: number) => {
    hlDiv.innerHTML = ''
    const items = [
      ...highlightsRef.current.filter(h => h.position_data?.pageIndex === pageIndex).map(h => ({ ...h, _type: 'highlight' as const })),
      ...annotationsRef.current.filter(a => a.position_data?.pageIndex === pageIndex).map(a => ({ ...a, _type: 'annotation' as const })),
    ]
    for (const item of items) {
      for (const r of (item.position_data?.rects || [])) {
        const d = document.createElement('div')
        d.className = `pdf-hl-item ${item._type}`
        d.dataset.id = item.id
        d.dataset.type = item._type
        if (item._type === 'annotation') d.dataset.content = (item as any).content || ''
        d.style.left = `${r.x * vw}px`
        d.style.top = `${r.y * vh}px`
        d.style.width = `${r.w * vw}px`
        d.style.height = `${r.h * vh}px`
        hlDiv.appendChild(d)
      }
    }
  }, [])

  // Render a single page
  const renderPage = useCallback(async (pageNum: number, pageEl: HTMLDivElement) => {
    const existing = renderTasksRef.current.get(pageNum)
    if (existing) { existing.cancel(); renderTasksRef.current.delete(pageNum) }
    const pdfDoc = pdfDocRef.current
    if (!pdfDoc) return

    const page = await pdfDoc.getPage(pageNum)
    const curScale = scaleRef.current
    const viewport = page.getViewport({ scale: curScale })
    const dpr = window.devicePixelRatio || 1

    pageEl.innerHTML = ''
    pageEl.style.width = `${viewport.width}px`
    pageEl.style.height = `${viewport.height}px`
    pageEl.style.setProperty('--scale-factor', String(curScale))

    // Canvas
    const canvas = document.createElement('canvas')
    canvas.width = viewport.width * dpr
    canvas.height = viewport.height * dpr
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`
    pageEl.appendChild(canvas)
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)

    const renderTask = page.render({ canvasContext: ctx, viewport })
    renderTasksRef.current.set(pageNum, renderTask)
    try { await renderTask.promise } catch (e: any) {
      if (e?.name === 'RenderingCancelledException') return
      throw e
    }

    // Text layer
    const textContent = await page.getTextContent()
    const textDiv = document.createElement('div')
    textDiv.className = 'pdf-text-layer'
    pageEl.appendChild(textDiv)
    const pdfjs = await getPdfjs()
    const tl = new pdfjs.TextLayer({ textContentSource: textContent, container: textDiv, viewport })
    await tl.render()

    // Highlight layer
    const hlDiv = document.createElement('div')
    hlDiv.className = 'pdf-hl-layer'
    pageEl.appendChild(hlDiv)
    renderHighlights(hlDiv, pageNum - 1, viewport.width, viewport.height)
  }, [renderHighlights])

  // Load PDF document
  useEffect(() => {
    if (!url) return
    let cancelled = false
    const load = async () => {
      setLoading(true); setError('')
      try {
        const pdfjs = await getPdfjs()
        const doc = await pdfjs.getDocument(url).promise
        if (cancelled) return
        pdfDocRef.current = doc
        setNumPages(doc.numPages)
        const infos: PageInfo[] = []
        for (let i = 1; i <= doc.numPages; i++) {
          const p = await doc.getPage(i)
          const vp = p.getViewport({ scale: 1 })
          infos.push({ width: vp.width, height: vp.height })
        }
        if (!cancelled) setPageInfos(infos)
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'PDF加载失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [url])

  // Setup IntersectionObserver for lazy page rendering
  const setupObserver = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    if (observerRef.current) observerRef.current.disconnect()
    const obs = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        const pn = Number((entry.target as HTMLElement).dataset.page)
        if (entry.isIntersecting && !renderedRef.current.has(pn)) {
          renderedRef.current.add(pn)
          renderPage(pn, entry.target as HTMLDivElement)
        }
      }
    }, { root: container, rootMargin: '200px' })
    observerRef.current = obs
    container.querySelectorAll<HTMLDivElement>('[data-page]').forEach(p => obs.observe(p))
  }, [renderPage])

  useEffect(() => {
    if (numPages && pageInfos.length) setupObserver()
    return () => { observerRef.current?.disconnect() }
  }, [numPages, pageInfos, setupObserver])

  // Re-render all on scale change
  useEffect(() => {
    if (!numPages || !containerRef.current) return
    renderedRef.current.clear()
    containerRef.current.querySelectorAll<HTMLDivElement>('[data-page]').forEach(p => {
      const pn = Number(p.dataset.page)
      const info = pageInfos[pn - 1]
      if (info) {
        p.style.width = `${info.width * scale}px`
        p.style.height = `${info.height * scale}px`
        p.innerHTML = ''
      }
    })
    setupObserver()
  }, [scale, numPages, pageInfos, setupObserver])

  // Re-render highlights when data changes
  useEffect(() => {
    if (!containerRef.current) return
    containerRef.current.querySelectorAll<HTMLDivElement>('[data-page]').forEach(pageEl => {
      const hlDiv = pageEl.querySelector<HTMLDivElement>('.pdf-hl-layer')
      if (!hlDiv) return
      const pn = Number(pageEl.dataset.page)
      const info = pageInfos[pn - 1]
      if (!info) return
      renderHighlights(hlDiv, pn - 1, info.width * scale, info.height * scale)
    })
  }, [highlights, annotations, scale, pageInfos, renderHighlights])

  // Text selection handler
  useEffect(() => {
    if (readOnly || !onTextSelect) return
    const container = containerRef.current
    if (!container) return
    const handleMouseUp = () => {
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed || !sel.toString().trim()) return
      const text = sel.toString()
      const range = sel.getRangeAt(0)
      const clientRect = range.getBoundingClientRect()
      let pageEl: HTMLElement | null = range.startContainer.parentElement
      while (pageEl && !pageEl.dataset.page) pageEl = pageEl.parentElement
      if (!pageEl) return
      const pn = Number(pageEl.dataset.page)
      const info = pageInfos[pn - 1]
      if (!info) return
      const pr = pageEl.getBoundingClientRect()
      const vw = info.width * scale, vh = info.height * scale
      const rects: Array<{ x: number; y: number; w: number; h: number }> = []
      const cr = range.getClientRects()
      for (let i = 0; i < cr.length; i++) {
        const r = cr[i]
        rects.push({ x: (r.left - pr.left) / vw, y: (r.top - pr.top) / vh, w: r.width / vw, h: r.height / vh })
      }
      onTextSelect({ text, rects: mergeRects(rects), pageIndex: pn - 1, clientRect })
    }
    container.addEventListener('mouseup', handleMouseUp)
    return () => container.removeEventListener('mouseup', handleMouseUp)
  }, [readOnly, onTextSelect, scale, pageInfos])

  // Right-click context menu on highlights/annotations
  useEffect(() => {
    if (readOnly) return
    const container = containerRef.current
    if (!container) return
    const handleCtx = (e: MouseEvent) => {
      const items = container.querySelectorAll<HTMLDivElement>('.pdf-hl-item')
      for (const item of items) {
        const rect = item.getBoundingClientRect()
        if (e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom) {
          e.preventDefault()
          setCtxMenu({ x: e.clientX, y: e.clientY, type: item.dataset.type as any, id: item.dataset.id!, content: item.dataset.content })
          return
        }
      }
    }
    container.addEventListener('contextmenu', handleCtx)
    return () => container.removeEventListener('contextmenu', handleCtx)
  }, [readOnly])

  // Close context menu
  useEffect(() => {
    if (!ctxMenu) return
    const close = () => setCtxMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => { window.removeEventListener('click', close); window.removeEventListener('scroll', close, true) }
  }, [ctxMenu])

  // Ctrl + mouse wheel zoom; also handle horizontal scroll for trackpad/shift+wheel
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const handleWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        const delta = e.deltaY > 0 ? -0.1 : 0.1
        setScale(s => Math.min(5, Math.max(0.5, +(s + delta).toFixed(2))))
        return
      }
      // Horizontal scroll: trackpad deltaX or shift+wheel
      const dx = e.deltaX || (e.shiftKey ? e.deltaY : 0)
      if (dx) {
        e.preventDefault()
        container.scrollLeft += dx
        if (topScrollRef.current) topScrollRef.current.scrollLeft = container.scrollLeft
        return
      }
      // Prevent wheel chain to outer containers when reaching top/bottom.
      if (e.deltaY !== 0) {
        const atTop = container.scrollTop <= 0
        const atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 1
        if ((e.deltaY < 0 && atTop) || (e.deltaY > 0 && atBottom)) {
          e.preventDefault()
        }
      }
    }
    container.addEventListener('wheel', handleWheel, { passive: false })
    return () => container.removeEventListener('wheel', handleWheel)
  }, [])

  const zoomIn = () => setScale(s => Math.min(5, +(s + 0.25).toFixed(2)))
  const zoomOut = () => setScale(s => Math.max(0.5, +(s - 0.25).toFixed(2)))

  if (error) return <div style={{ padding: 40, textAlign: 'center', color: '#ff4d4f' }}>{error}</div>

  return (
    <div style={{ position: 'relative', height: '100%', background: '#f0f0f0', display: 'flex', flexDirection: 'column' }}>
      <div className="pdf-zoom-bar">
        <Tooltip title="缩小 (Ctrl+滚轮)">
          <Button type="text" icon={<ZoomOutOutlined />} onClick={zoomOut} size="small" />
        </Tooltip>
        <span style={{ color: '#fff', fontSize: 12, minWidth: 40, textAlign: 'center' }}>{Math.round(scale * 100)}%</span>
        <Tooltip title="放大 (Ctrl+滚轮)">
          <Button type="text" icon={<ZoomInOutlined />} onClick={zoomIn} size="small" />
        </Tooltip>
      </div>
      {contentWidth > 0 && (
        <div ref={topScrollRef} className="pdf-top-hscroll" onScroll={syncFromTop}>
          <div style={{ width: contentWidth, height: 1 }} />
        </div>
      )}
      <div ref={containerRef} className="pdf-main-scroll" onScroll={syncFromMain} style={{ flex: 1, padding: '8px 0' }}>
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 100 }}>
            <span style={{ color: '#999' }}>加载中...</span>
          </div>
        ) : (
          pageInfos.map((info, i) => (
            <div key={i} data-page={i + 1} className="pdf-page-container" style={{
              width: info.width * scale, height: info.height * scale,
              margin: '8px auto', background: '#fff', boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
            }} />
          ))
        )}
      </div>
      {ctxMenu && (
        <div className="pdf-ctx-menu" style={{ left: ctxMenu.x, top: ctxMenu.y }} onClick={e => e.stopPropagation()}>
          {ctxMenu.type === 'annotation' && ctxMenu.content && (
            <>
              <div className="pdf-ctx-menu-item disabled" style={{ maxWidth: 300, whiteSpace: 'normal', lineHeight: 1.4 }}>{ctxMenu.content}</div>
              <div className="pdf-ctx-menu-divider" />
            </>
          )}
          <div className="pdf-ctx-menu-item danger" onClick={() => {
            if (ctxMenu.type === 'highlight') onDeleteHighlight?.(ctxMenu.id)
            else onDeleteAnnotation?.(ctxMenu.id)
            setCtxMenu(null)
          }}>删除{ctxMenu.type === 'highlight' ? '高亮' : '批注'}</div>
        </div>
      )}
    </div>
  )
}
