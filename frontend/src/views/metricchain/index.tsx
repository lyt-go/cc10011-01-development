import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const CHAIN = '/api/realtimemetric/chain'
const STATUS_FLOW = ['草稿', '评审中', '已上线', '已下线']

type Row = Record<string, any>

interface TabProps {
  notify: (message: string, ok?: boolean) => void
  reloadVersions: () => Promise<void>
  versions: Row[]
  streams: Row[]
}

async function postJson(path: string, body: Record<string, any>): Promise<Row> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return response.json()
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === '已上线' ? 'badge badge-online'
      : status === '已下线' ? 'badge badge-offline'
        : status === '评审中' ? 'badge badge-review'
          : 'badge badge-draft'
  return <span className={cls}>{status}</span>
}

/** 标签一：不可变定义版本与单向生命周期。 */
function VersionTab({ notify, reloadVersions, versions, streams }: TabProps) {
  const [statusFilter, setStatusFilter] = useState('')
  const [keyword, setKeyword] = useState('')
  const [showDraftForm, setShowDraftForm] = useState(false)
  const [form, setForm] = useState<Record<string, any>>({
    指标编号: '', 指标名称: '', 计算窗口秒: 60, 聚合函数: 'avg',
    数据源流: streams[0]?.['流编号'] ?? '', 维度字段组: '', 精度位数: 4,
    延迟容忍毫秒: 3000, 度量字段: '', 变更说明: '',
  })
  const [computeSummary, setComputeSummary] = useState<Row | null>(null)

  const filtered = useMemo(() => versions.filter((row) =>
    (!statusFilter || row['状态'] === statusFilter)
    && (!keyword || String(row['指标编号']).includes(keyword)),
  ), [versions, statusFilter, keyword])

  async function runAction(action: string, row: Row) {
    const result = await postJson(`${CHAIN}/versions/${row['版本编号']}/actions`, { values: { action } })
    notify(result.message, result.ok)
    if (result.ok) await reloadVersions()
  }

  async function compute(row: Row) {
    const result = await postJson(`${CHAIN}/compute`, { values: { 版本编号: row['版本编号'] } })
    notify(result.message, result.ok)
    if (result.ok) setComputeSummary(result.entry)
  }

  async function submitDraft() {
    const values = { ...form, 维度字段组: String(form.维度字段组 || '').split(',').map((s) => s.trim()).filter(Boolean) }
    const result = await postJson(`${CHAIN}/versions`, { values })
    notify(result.message, result.ok)
    if (result.ok) {
      setShowDraftForm(false)
      await reloadVersions()
    }
  }

  const columns = ['版本编号', '指标编号', '指标名称', '版本序号', '状态', '计算窗口秒', '聚合函数', '数据源流', '维度字段组', '精度位数', '内容哈希', '上线时间', '失效时间']

  return (
    <>
      <div className="toolbar">
        <label className="filter-item">
          <span>指标编号</span>
          <input value={keyword} placeholder="按指标编号检索" onChange={(e) => setKeyword(e.target.value)} />
        </label>
        <label className="filter-item">
          <span>生命周期状态</span>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">全部</option>
            {STATUS_FLOW.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <button className="btn primary" type="button" onClick={() => setShowDraftForm((v) => !v)}>
          {showDraftForm ? '收起草稿表单' : '新建草稿版本'}
        </button>
      </div>

      {showDraftForm && (
        <div className="form-panel">
          <h4>草稿是唯一允许编辑口径的阶段；提交评审后定义冻结、不可改写</h4>
          <div className="form-grid">
            <label><span>指标编号</span><input value={form.指标编号} onChange={(e) => setForm({ ...form, 指标编号: e.target.value })} /></label>
            <label><span>指标名称</span><input value={form.指标名称} onChange={(e) => setForm({ ...form, 指标名称: e.target.value })} /></label>
            <label><span>计算窗口秒</span><input type="number" value={form.计算窗口秒} onChange={(e) => setForm({ ...form, 计算窗口秒: Number(e.target.value) })} /></label>
            <label><span>聚合函数</span>
              <select value={form.聚合函数} onChange={(e) => setForm({ ...form, 聚合函数: e.target.value })}>
                {['sum', 'avg', 'count', 'max', 'min'].map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </label>
            <label><span>数据源流</span>
              <select value={form.数据源流} onChange={(e) => setForm({ ...form, 数据源流: e.target.value })}>
                {streams.map((s) => <option key={s['流编号']} value={s['流编号']}>{s['流编号']}（{s['流名称']}）</option>)}
              </select>
            </label>
            <label><span>维度字段组（逗号分隔）</span><input value={form.维度字段组} placeholder="channel,region" onChange={(e) => setForm({ ...form, 维度字段组: e.target.value })} /></label>
            <label><span>精度位数</span><input type="number" value={form.精度位数} onChange={(e) => setForm({ ...form, 精度位数: Number(e.target.value) })} /></label>
            <label><span>延迟容忍毫秒</span><input type="number" value={form.延迟容忍毫秒} onChange={(e) => setForm({ ...form, 延迟容忍毫秒: Number(e.target.value) })} /></label>
            <label><span>度量字段（count 可留空）</span><input value={form.度量字段} onChange={(e) => setForm({ ...form, 度量字段: e.target.value })} /></label>
            <label className="span-2"><span>变更说明</span><input value={form.变更说明} onChange={(e) => setForm({ ...form, 变更说明: e.target.value })} /></label>
          </div>
          <div className="toolbar">
            <button className="btn primary" type="button" onClick={() => void submitDraft()}>登记草稿版本</button>
          </div>
        </div>
      )}

      {computeSummary && (
        <div className="note-text">
          最近一次计算：新增窗口 {computeSummary['本次新增窗口']}，跳过已存在窗口 {computeSummary['跳过已存在窗口']}，
          窗口覆盖率 {computeSummary['窗口覆盖率']}，数据新鲜度 {computeSummary['数据新鲜度秒']} 秒，
          阈值命中新增 {computeSummary['阈值命中新增']}，恢复点窗口序号 {computeSummary['恢复点窗口序号']}
        </div>
      )}

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => <th key={c}>{c}</th>)}
            <th>不可变</th>
            <th>生命周期动作</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((row) => (
            <tr key={row['版本编号']}>
              {columns.map((c) => (
                <td key={c}>
                  {c === '状态' ? <StatusBadge status={row[c]} />
                    : c === '维度字段组' ? (row[c] || []).join('、')
                    : (row[c] ?? '—')}
                </td>
              ))}
              <td>{row['不可变'] ? '已冻结' : '可编辑'}</td>
              <td className="row-actions">
                {row['状态'] === '草稿' && (
                  <button className="link" type="button" onClick={() => void runAction('提交评审', row)}>提交评审（冻结）</button>
                )}
                {row['状态'] === '评审中' && (
                  <button className="link" type="button" onClick={() => void runAction('发布上线', row)}>发布上线（校验）</button>
                )}
                {row['状态'] === '已上线' && (
                  <>
                    <button className="link" type="button" onClick={() => void compute(row)}>立即计算</button>
                    <button className="link danger" type="button" onClick={() => void runAction('下线指标', row)}>下线指标</button>
                  </>
                )}
                {row['状态'] === '已下线' && <span className="muted-text">生命周期已终结</span>}
              </td>
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr><td className="empty-state" colSpan={columns.length + 2}>暂无符合条件的定义版本</td></tr>
          )}
        </tbody>
      </table>
      <p className="hint-text">合法顺序：草稿 → 评审中 → 已上线 → 已下线，只能单向逐段推进，不能跳步或倒回。</p>
    </>
  )
}

/** 标签二：只追加的计算结果数据集，携带新鲜度与窗口覆盖率。 */
function DatasetTab({ notify, versions }: TabProps) {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [versionFilter, setVersionFilter] = useState('')

  const load = useCallback(async () => {
    const query = new URLSearchParams()
    if (versionFilter) query.set('version_code', versionFilter)
    query.set('size', '10000')
    const response = await request(`${CHAIN}/dataset?${query.toString()}`)
    if (!response.ok) {
      notify('结果数据集读取失败', false)
      return
    }
    const payload = await response.json()
    setRows(payload.items ?? [])
    setTotal(payload.total ?? 0)
  }, [versionFilter, notify])

  useEffect(() => { void load() }, [load])

  const columns = ['数据集版本号', '版本编号', '指标名称', '窗口起点', '窗口终点', '窗口序号', '维度组合', '指标值', '事件数', '数据新鲜度秒', '窗口覆盖率', '覆盖窗口数', '应覆盖窗口数', '定义内容哈希', '写入时间']
  return (
    <>
      <div className="toolbar">
        <label className="filter-item">
          <span>定义版本</span>
          <select value={versionFilter} onChange={(e) => setVersionFilter(e.target.value)}>
            <option value="">全部版本</option>
            {versions.map((v) => <option key={v['版本编号']} value={v['版本编号']}>{v['版本编号']}（{v['指标名称']}）</option>)}
          </select>
        </label>
        <button className="btn" type="button" onClick={() => void load()}>刷新数据集</button>
      </div>
      <table className="data-table">
        <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}<th>完整窗口</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row['id']}>
              {columns.map((c) => (
                <td key={c}>{c === '维度组合' ? JSON.stringify(row[c]) : (row[c] ?? '—')}</td>
              ))}
              <td>{row['是否完整窗口'] ? '是' : '否'}</td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td className="empty-state" colSpan={columns.length + 1}>暂无计算结果，请先在「定义版本」页对已上线版本执行立即计算</td></tr>}
        </tbody>
      </table>
      <p className="hint-text">共 {total} 条窗口结果；数据集只追加，中断恢复从上一完整窗口继续，已写入结果不会被覆盖。</p>
    </>
  )
}

/** 标签三：阈值命中（只追加），下线指标不再产生新命中。 */
function HitsTab({ notify }: TabProps) {
  const [rows, setRows] = useState<Row[]>([])
  const [ruleKeyword, setRuleKeyword] = useState('')

  const load = useCallback(async () => {
    const query = new URLSearchParams({ size: '10000' })
    if (ruleKeyword) query.set('rule_code', ruleKeyword)
    const response = await request(`${CHAIN}/hits?${query.toString()}`)
    if (!response.ok) {
      notify('阈值命中读取失败', false)
      return
    }
    const payload = await response.json()
    setRows(payload.items ?? [])
  }, [ruleKeyword, notify])

  useEffect(() => { void load() }, [load])

  const columns = ['命中编号', '规则编号', '绑定版本编号', '指标编号', '窗口起点', '窗口终点', '维度组合', '指标值', '阈值下限', '阈值上限', '数据新鲜度秒', '命中时间', '处置状态']
  return (
    <>
      <div className="toolbar">
        <label className="filter-item">
          <span>规则编号</span>
          <input value={ruleKeyword} placeholder="按规则编号检索" onChange={(e) => setRuleKeyword(e.target.value)} />
        </label>
        <button className="btn" type="button" onClick={() => void load()}>刷新命中</button>
      </div>
      <table className="data-table">
        <thead><tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row['命中编号']}>
              {columns.map((c) => <td key={c}>{c === '维度组合' ? JSON.stringify(row[c]) : (row[c] ?? '—')}</td>)}
            </tr>
          ))}
          {rows.length === 0 && <tr><td className="empty-state" colSpan={columns.length}>暂无阈值命中；规则需绑定已上线版本并生效后，随窗口计算产生命中</td></tr>}
        </tbody>
      </table>
      <p className="hint-text">命中结果只追加；指标定义版本下线后关联规则标记版本失效，不再产生新的阈值命中，旧命中保留。</p>
    </>
  )
}

/** 标签四：发布详情与新旧版本并排差异。 */
function DetailDiffTab({ versions }: TabProps) {
  const [detailCode, setDetailCode] = useState(versions[0]?.['版本编号'] ?? '')
  const [detail, setDetail] = useState<Row | null>(null)
  const [left, setLeft] = useState('')
  const [right, setRight] = useState('')
  const [diff, setDiff] = useState<Row | null>(null)

  async function loadDetail(code: string) {
    if (!code) return
    const response = await request(`${CHAIN}/versions/${code}/publish-detail`)
    if (response.ok) setDetail(await response.json())
  }

  async function loadDiff() {
    if (!left || !right) return
    const response = await request(`${CHAIN}/diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`)
    if (response.ok) setDiff(await response.json())
  }

  useEffect(() => { void loadDetail(detailCode) }, [detailCode])
  useEffect(() => {
    if (versions.length >= 2 && !right) {
      setLeft(versions[0]['版本编号'])
      setRight(versions[1]['版本编号'])
    }
  }, [versions, right])

  const detailFields = ['版本编号', '指标编号', '指标名称', '状态', '计算窗口秒', '聚合函数', '数据源流', '维度字段组', '精度位数', '内容哈希', '上线时间', '失效时间', '校验结论', '数据新鲜度', '最近窗口起点', '数据集版本号', '窗口覆盖率', '已写入窗口数']

  return (
    <div className="split-panels">
      <section className="panel">
        <h4>发布详情</h4>
        <label className="filter-item">
          <span>选择定义版本</span>
          <select value={detailCode} onChange={(e) => setDetailCode(e.target.value)}>
            {versions.map((v) => <option key={v['版本编号']} value={v['版本编号']}>{v['版本编号']}（{v['指标名称']}）</option>)}
          </select>
        </label>
        {detail && (
          <dl className="kv-list">
            {detailFields.map((f) => (
              <div key={f} className="kv-row">
                <dt>{f}</dt>
                <dd>{Array.isArray(detail[f]) ? detail[f].join('、') : (detail[f] ?? '—')}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section className="panel">
        <h4>新旧版本并排差异</h4>
        <div className="toolbar">
          <label className="filter-item">
            <span>左版本</span>
            <select value={left} onChange={(e) => setLeft(e.target.value)}>
              {versions.map((v) => <option key={v['版本编号']} value={v['版本编号']}>{v['版本编号']}</option>)}
            </select>
          </label>
          <label className="filter-item">
            <span>右版本</span>
            <select value={right} onChange={(e) => setRight(e.target.value)}>
              {versions.map((v) => <option key={v['版本编号']} value={v['版本编号']}>{v['版本编号']}</option>)}
            </select>
          </label>
          <button className="btn primary" type="button" onClick={() => void loadDiff()}>对比口径</button>
        </div>
        {diff && (
          <table className="data-table diff-table">
            <thead>
              <tr><th>口径字段</th><th>{diff['左版本']['版本编号']}</th><th>{diff['右版本']['版本编号']}</th></tr>
            </thead>
            <tbody>
              {(diff['差异项'] as Row[]).length === 0 && (
                <tr><td className="empty-state" colSpan={3}>两版本口径完全一致（指纹 {diff['左版本']['内容哈希']}）</td></tr>
              )}
              {(diff['差异项'] as Row[]).map((item) => (
                <tr key={item['字段']} className="changed">
                  <td>{item['字段']}</td>
                  <td>{Array.isArray(item['旧版本']) ? item['旧版本'].join('、') : String(item['旧版本'] ?? '—')}</td>
                  <td>{Array.isArray(item['新版本']) ? item['新版本'].join('、') : String(item['新版本'] ?? '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

/** 标签五：大盘刷新，明确显示所用指标版本与数据新鲜度。 */
function DashboardTab({ notify }: TabProps) {
  const [refresh, setRefresh] = useState<Row | null>(null)

  async function doRefresh() {
    const response = await request(`${CHAIN}/dashboard-refresh`)
    if (!response.ok) {
      notify('大盘刷新失败', false)
      return
    }
    setRefresh(await response.json())
  }

  return (
    <>
      <div className="toolbar">
        <button className="btn primary" type="button" onClick={() => void doRefresh()}>刷新大盘结果</button>
        {refresh && <span className="muted-text">刷新时间：{refresh['刷新时间']}，共 {refresh['卡片数']} 张卡片</span>}
      </div>
      <div className="card-grid">
        {(refresh?.['卡片'] ?? []).map((card: Row) => (
          <article key={card['所用指标版本']} className="metric-card">
            <header>
              <strong>{card['指标名称']}</strong>
              <StatusBadge status="已上线" />
            </header>
            <p className="metric-value">{card['最新指标值'] ?? '暂无计算结果'}</p>
            <dl className="kv-list compact">
              <div className="kv-row"><dt>指标编号</dt><dd>{card['指标编号']}</dd></div>
              <div className="kv-row"><dt>所用指标版本</dt><dd>{card['所用指标版本']}</dd></div>
              <div className="kv-row"><dt>定义指纹</dt><dd>{card['定义内容哈希']}</dd></div>
              <div className="kv-row"><dt>计算窗口秒</dt><dd>{card['计算窗口秒']}</dd></div>
              <div className="kv-row"><dt>数据新鲜度(秒)</dt><dd>{card['数据新鲜度秒'] ?? '—'}</dd></div>
              <div className="kv-row"><dt>窗口覆盖率</dt><dd>{card['窗口覆盖率'] ?? '—'}</dd></div>
              <div className="kv-row"><dt>最新窗口起点</dt><dd>{card['最新窗口起点'] ?? '—'}</dd></div>
            </dl>
          </article>
        ))}
        {refresh && refresh['卡片'].length === 0 && <p className="empty-state">当前没有已上线指标版本</p>}
      </div>
    </>
  )
}

const TABS = [
  { key: 'versions', label: '定义版本与发布' },
  { key: 'dataset', label: '计算结果数据集' },
  { key: 'hits', label: '阈值命中' },
  { key: 'detail', label: '发布详情与差异' },
  { key: 'dashboard', label: '大盘刷新' },
]

export default function MetricChainView() {
  const [tab, setTab] = useState('versions')
  const [versions, setVersions] = useState<Row[]>([])
  const [streams, setStreams] = useState<Row[]>([])
  const [message, setMessage] = useState('')
  const [messageOk, setMessageOk] = useState(true)

  const notify = useCallback((text: string, ok = true) => {
    setMessage(text)
    setMessageOk(ok)
  }, [])

  const reloadVersions = useCallback(async () => {
    const response = await request(`${CHAIN}/versions?size=10000`)
    if (response.ok) {
      const payload = await response.json()
      setVersions(payload.items ?? [])
    }
  }, [])

  useEffect(() => {
    void reloadVersions()
    void request(`${CHAIN}/streams`).then(async (r) => {
      if (r.ok) setStreams((await r.json()).items ?? [])
    })
  }, [reloadVersions])

  const stats = useMemo(() => [
    { label: '定义版本总数', value: versions.length },
    { label: '已上线版本', value: versions.filter((v) => v['状态'] === '已上线').length },
    { label: '评审中版本', value: versions.filter((v) => v['状态'] === '评审中').length },
    { label: '已下线版本', value: versions.filter((v) => v['状态'] === '已下线').length },
  ], [versions])

  const tabProps: TabProps = { notify, reloadVersions, versions, streams }

  return (
    <section className="page" data-module="metricchain">
      <header className="page-head">
        <div>
          <h2>实时指标口径链</h2>
          <p className="page-desc">
            数据源流 → 不可变定义版本 → 发布校验 → 窗口计算 → 只追加结果数据集（新鲜度/覆盖率可追溯）
            → 阈值按版本绑定消费；生命周期沿草稿、评审中、已上线、已下线单向推进。
          </p>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <nav className="tabs">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`tab-btn ${tab === item.key ? 'active' : ''}`}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {message && <p className={messageOk ? 'note-text' : 'error-text'}>{message}</p>}

      {tab === 'versions' && <VersionTab {...tabProps} />}
      {tab === 'dataset' && <DatasetTab {...tabProps} />}
      {tab === 'hits' && <HitsTab {...tabProps} />}
      {tab === 'detail' && <DetailDiffTab {...tabProps} />}
      {tab === 'dashboard' && <DashboardTab {...tabProps} />}
    </section>
  )
}
