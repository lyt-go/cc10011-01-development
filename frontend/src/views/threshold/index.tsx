import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/threshold'
const CHAIN = '/api/realtimemetric/chain'
const columns = [
  "规则编号",
  "关联指标",
  "绑定版本编号",
  "绑定状态",
  "阈值下限",
  "阈值上限",
  "触发条件",
  "持续周期",
  "告警等级",
  "生效时间范围"
]
const actions = [
  "提交规则评审",
  "生效规则",
  "关闭规则"
]
const statuses = [
  "草稿",
  "规则评审中",
  "已生效",
  "已关闭"
]
const stats = [
  {
    "label": "阈值规则总数",
    "value": 0
  },
  {
    "label": "已生效规则",
    "value": 0
  },
  {
    "label": "评审中规则",
    "value": 0
  }
]

type Row = Record<string, string | number | null | boolean>
type VersionRow = Record<string, any>

export default function ThresholdView() {
  const [rows, setRows] = useState<Row[]>([])
  const [bindings, setBindings] = useState<Record<string, any>[]>([])
  const [versions, setVersions] = useState<VersionRow[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => columns.slice(0, 2), [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('阈值规则列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '阈值管理列表读取失败')
    }
  }, [filters])

  const reloadBindings = useCallback(async () => {
    const response = await request(`${ENDPOINT}/bindings`)
    if (response.ok) {
      const payload = await response.json()
      setBindings(payload.items ?? [])
    }
  }, [])

  useEffect(() => {
    void reload()
    void reloadBindings()
    void request(`${CHAIN}/versions?size=10000`).then(async (response) => {
      if (response.ok) {
        const payload = await response.json()
        setVersions((payload.items ?? []).filter((v: VersionRow) => v['状态'] === '已上线'))
      }
    })
  }, [reload, reloadBindings])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('阈值管理动作未生效，请稍后重试')
      }
      const result = await response.json()
      if (result.ok === false) {
        setErrorMessage(result.message)
        return
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '阈值管理操作失败')
    }
  }

  async function bindVersion(row: Row, versionCode: string) {
    setErrorMessage('')
    if (!versionCode) {
      setErrorMessage('请先选择要绑定的已上线定义版本')
      return
    }
    try {
      const response = await request(`${ENDPOINT}/${row.id}/bind-version`, {
        method: 'POST',
        body: JSON.stringify({ values: { 版本编号: versionCode } }),
      })
      const result = await response.json()
      if (result.ok === false) {
        setErrorMessage(result.message)
        return
      }
      setErrorMessage('')
      await Promise.all([reload(), reloadBindings()])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '版本绑定失败')
    }
  }

  return (
    <section className="page" data-module="threshold">
      <header className="page-head">
        <div>
          <h2>阈值管理管理</h2>
          <p className="page-desc">
            管理指标的阈值告警规则；规则只能绑定已上线且未失效的指标定义版本，
            指标版本变化时绑定清单同步更新，版本下线后停止产生新的阈值命中。
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('阈值规则登记入口尚未接入审批流')}>
            登记阈值规则
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出阈值管理清单
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

      <h3 className="section-title">阈值清单随指标版本同步</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>规则编号</th>
            <th>关联指标</th>
            <th>绑定版本编号</th>
            <th>绑定状态</th>
            <th>版本当前状态</th>
            <th>绑定版本指纹</th>
            <th>最近同步版本</th>
            <th>最近同步时间</th>
          </tr>
        </thead>
        <tbody>
          {bindings.map((item) => (
            <tr key={String(item['规则编号'])}>
              <td>{item['规则编号'] ?? '—'}</td>
              <td>{item['关联指标'] ?? '—'}</td>
              <td>{item['绑定版本编号'] ?? '—'}</td>
              <td>
                <span className={item['绑定状态'] === '版本有效' ? 'badge badge-online' : item['绑定状态'] === '版本失效' ? 'badge badge-offline' : 'badge badge-draft'}>
                  {item['绑定状态']}
                </span>
              </td>
              <td>{item['版本当前状态'] ?? '—'}</td>
              <td>{item['绑定版本哈希'] ?? '—'}</td>
              <td>{item['最近同步版本'] ?? '—'}</td>
              <td>{item['最近同步时间'] ?? '—'}</td>
            </tr>
          ))}
          {bindings.length === 0 && (
            <tr><td className="empty-state" colSpan={8}>暂无绑定视图数据</td></tr>
          )}
        </tbody>
      </table>

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
            <th>版本绑定操作</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td>
                <div className="bind-cell">
                  <select defaultValue="">
                    <option value="" disabled>选择已上线版本</option>
                    {versions
                      .filter((v) => !row['关联指标'] || v['指标编号'] === row['关联指标'])
                      .map((v) => (
                        <option key={v['版本编号']} value={v['版本编号']}>
                          {v['版本编号']}（{v['指标编号']}）
                        </option>
                      ))}
                  </select>
                  <button
                    className="link"
                    type="button"
                    onClick={(event) => {
                      const select = (event.currentTarget.previousElementSibling as HTMLSelectElement)
                      void bindVersion(row, select.value)
                    }}
                  >
                    绑定版本
                  </button>
                </div>
              </td>
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
              <td className="empty-state" colSpan={columns.length + 2}>暂无阈值管理数据，可先登记阈值规则</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条阈值管理记录；状态序列：{statuses.join(' → ')}</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
