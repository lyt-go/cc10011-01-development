import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/dashboard'
const CHAIN_REFRESH = '/api/realtimemetric/chain/dashboard-refresh'
const columns = [
  "大盘编号",
  "大盘名称",
  "包含指标组",
  "布局模板",
  "刷新频率秒",
  "对比周期",
  "分享范围",
  "负责人"
]
const actions = [
  "提交大盘评审",
  "发布大盘",
  "下线大盘"
]
const statuses = [
  "草稿",
  "大盘评审中",
  "已发布",
  "已下线"
]
const stats = [
  {
    "label": "大盘配置总数",
    "value": 0
  },
  {
    "label": "已发布大盘",
    "value": 0
  },
  {
    "label": "评审中大盘",
    "value": 0
  }
]

type Row = Record<string, string | number | null>
type ChainCard = Record<string, any>

export default function DashboardView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [chainCards, setChainCards] = useState<ChainCard[] | null>(null)
  const [refreshTime, setRefreshTime] = useState('')
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const refreshChain = useCallback(async () => {
    try {
      const response = await request(CHAIN_REFRESH)
      if (!response.ok) {
        throw new Error('大盘刷新结果读取失败')
      }
      const payload = await response.json()
      setChainCards(payload['卡片'] ?? [])
      setRefreshTime(payload['刷新时间'] ?? '')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '大盘刷新失败')
    }
  }, [])

  useEffect(() => {
    void refreshChain()
  }, [refreshChain])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('大盘配置列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '监控大盘列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('监控大盘动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '监控大盘操作失败')
    }
  }

  return (
    <section className="page" data-module="dashboard">
      <header className="page-head">
        <div>
          <h2>监控大盘管理</h2>
          <p className="page-desc">配置实时监控大盘，组合指标卡片和图表形成业务全景视图。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('大盘配置登记入口尚未接入审批流')}>
            登记大盘配置
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出监控大盘清单
          </button>
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

      <div className="chain-panel">
        <div className="chain-panel-head">
          <h3>实时指标口径链刷新结果</h3>
          <button className="btn primary" type="button" onClick={() => void refreshChain()}>立即刷新</button>
        </div>
        {refreshTime && <p className="muted-text">刷新时间：{refreshTime}；每张卡片明确标注所用指标版本与数据新鲜度</p>}
        <div className="card-grid">
          {(chainCards ?? []).map((card) => (
            <article key={card['所用指标版本']} className="metric-card">
              <header>
                <strong>{card['指标名称']}</strong>
                <span className="badge badge-online">{card['所用指标版本']}</span>
              </header>
              <p className="metric-value">{card['最新指标值'] ?? '暂无计算结果'}</p>
              <dl className="kv-list compact">
                <div className="kv-row"><dt>指标编号</dt><dd>{card['指标编号']}</dd></div>
                <div className="kv-row"><dt>计算窗口秒</dt><dd>{card['计算窗口秒']}</dd></div>
                <div className="kv-row"><dt>数据新鲜度(秒)</dt><dd>{card['数据新鲜度秒'] ?? '—'}</dd></div>
                <div className="kv-row"><dt>窗口覆盖率</dt><dd>{card['窗口覆盖率'] ?? '—'}</dd></div>
                <div className="kv-row"><dt>定义指纹</dt><dd>{card['定义内容哈希']}</dd></div>
              </dl>
            </article>
          ))}
          {chainCards && chainCards.length === 0 && <p className="empty-state">当前没有已上线的指标版本</p>}
        </div>
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无监控大盘数据，可先登记大盘配置</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条监控大盘记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
