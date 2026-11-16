# 实时指标计算与监控大盘平台

面向实时指标计算引擎、多维度下钻分析、告警阈值管理、指标异常检测、数据服务开放与可视化看板配置的数据分析与应用工程平台。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 实时指标 | `realtimemetric` | 指标定义 | 指标编号、指标名称、计算窗口秒 |
| 监控大盘 | `dashboard` | 大盘配置 | 大盘编号、大盘名称、包含指标组 |
| 多维下钻 | `drilldown` | 下钻路径 | 路径编号、起始维度、下钻层级序列 |
| 阈值管理 | `threshold` | 阈值规则 | 规则编号、关联指标、阈值下限 |
| 异常检测 | `anomalydetect` | 检测模型 | 模型编号、监控指标、检测算法 |
| 数据服务 | `dataservice` | 服务接口 | 服务编号、服务名称、接口路径 |
| 告警历史 | `alarmhistory` | 告警记录 | 记录编号、告警规则、触发时间 |
| 同比环比 | `comparison` | 对比配置 | 配置编号、目标指标、对比类型 |
| 聚合配置 | `aggregate` | 聚合规则 | 规则编号、源数据粒度、目标粒度 |
| 筛选预设 | `filterpreset` | 预设模板 | 预设编号、预设名称、维度条件组 |
| 用户洞察 | `userinsight` | 洞察报告 | 报告编号、分析主题、目标人群 |
| 事件分析 | `eventanalysis` | 分析模型 | 模型编号、事件名称、分组维度 |
| 分群画像 | `segmentprofile` | 画像定义 | 画像编号、分群名称、筛选规则 |
| 趋势预测 | `trendforecast` | 预测方案 | 方案编号、预测指标、算法模型 |
| 可视化模板 | `viztemplate` | 图表模板 | 模板编号、图表类型、数据绑定 |
| 订阅推送 | `subscription` | 订阅配置 | 订阅编号、订阅内容、接收人 |
| 维度映射 | `dimensionmap` | 映射规则 | 规则编号、原始维度名、标准维度名 |
| 数据质量分 | `qualityscore` | 评分规则 | 规则编号、数据集名称、完整性权重 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 实时指标口径链

口径链把「数据源流 → 不可变定义版本 → 发布校验 → 窗口计算 → 只追加结果数据集
→ 阈值按版本绑定消费」串成一条可发布、可追溯的链，后端实现在
`app/services/metric_chain.py`、`app/routers/metric_chain.py`，前端页面在
`frontend/src/views/metricchain/`（导航「指标口径链」）。

关键边界：

- **不可变定义版本**：版本带口径内容指纹（`内容哈希`），提交评审即冻结；
  草稿是唯一可改口径的阶段，已上线/已下线版本不可改写，改口径只能新建版本。
- **单向生命周期**：草稿 → 评审中 → 已上线 → 已下线，只能相邻推进，不能跳步或倒回。
- **发布校验**：上线时校验计算窗口、数据源流、维度字段组、精度；同指标只保留一个
  在线版本，新版本上线时旧版本置失效但记录保留，阈值仍可追溯到所绑定的完整版本。
- **只追加数据集**：`/api/realtimemetric/chain/dataset` 每行携带数据新鲜度秒、
  窗口覆盖率、覆盖/应覆盖窗口数与定义指纹；中断恢复从上一完整窗口继续，不覆盖已写入结果。
- **阈值版本绑定**：`/api/threshold/{id}/bind-version` 只接受已上线且未失效的版本，
  绑定记录版本指纹；版本下线后关联规则标记「版本失效」，不再产生新命中，旧命中保留。
  阈值清单同步视图见 `/api/threshold/bindings`。
- **大盘刷新**：`/api/realtimemetric/chain/dashboard-refresh` 每张卡片显式标注
  所用指标版本、定义指纹、数据新鲜度与窗口覆盖率。
- **发布详情与并排差异**：`/versions/{code}/publish-detail` 与 `/diff?left=&right=`。

端到端验证脚本（标准库实现，需先启动后端）：

```bash
python3 -I backend_tests/test_chain_e2e.py
```


领域：数据工程
子方向：数据分析与数据应用
