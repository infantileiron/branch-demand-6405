# 栖川 · 服务网点需求预估

让8个售后网点用连续日量比较周季节朴素与Holt趋势预测，并把未来7日工单量转成可签核的排班人数参考。

## 真实业务场景

栖川售后每天由8位网点值班员汇总工单到达量，排班组在 `栖川_网点日结_20261114.xlsx` 中复制上周星期分布，再手工加减人数。痛点：漏日常被当零量、趋势调整没有回测、排班人数和依据版本难追溯。上游是售后工单日结；本项目替代连续性核对、预测比较与人数换算；下游是网点负责人核对技能、休息和班次后安排人员。

五个模块：日量导入（逐条表单/API，含修订）、回测设置、预测对比、排班建议、区域协调。核心实体为DailyVolume、ForecastRun、Region/RegionRun、Staffing，分别贯穿数据库、模式、业务服务/控制、路由和前端；另有用户与审计。提交任务时冻结原始记录与参数，之后补录不改变旧预测。区域版本另有冻结成员同日期日量的功能：每次计算都锁定区域全部成员在共同日期窗口内的逐日量，窗口外边缘日单独记入`excluded_edge_days`，不参与聚合。

|角色|可访问|典型动作|
|---|---|---|
|admin|全部，独占审计和签核|签核下周排班建议|
|analyst|业务读写、计算、导出|补录日量、固定参数后提交预测、起草排班、建区域并发布区域版本|
|viewer|业务只读、导出；服务器拒绝写入/计算|下载冻结预测JSON、查看区域分担依据|

## 启动与演示账号

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 [localhost:18208](http://localhost:18208)，API [localhost:19208/docs](http://localhost:19208/docs)，数据库映射17708。账号 `admin@demo.local`、`analyst@demo.local`、`viewer@demo.local`，密码均 `Demo123!`。`SEED_DEMO=true`使后端启动时自动seed；自然键为网点+日期，重复执行不新增也不覆盖人工修订。种子包含8网点各70日（2026-09-06至2026-11-14），合计560条，固定随机seed=3109；三账号；两个演示区域（栖川城区：川北/川南/东河/西浦，各层同选季节朴素、逐日零差额；山前片区：山前为强趋势会选Holt，与区域存在需分摊的差额）。

## 一天的操作剧本

1. 08:50 viewer查看川北等8网点昨日工单日结。
2. 09:00 analyst核对CSV上游记录，确认每个网点日期连续。
3. 09:10 在日量导入补录川北2026-11-15、42单，说明“周末日结”；缺日必须补真实值，不能静默填0。
3b. 09:15 在区域协调用栖川城区（川北/川南/东河/西浦）冻结共同日期窗口并提交区域计算；查看区域与各网点回测MAE、可信度和逐日调整前后，再发布本周版本。
4. 09:20 选择川北，回测14日，固定α=.6、β=.2，命名“11月下周网点需求”。
5. 09:30 提交worker任务；刷新预测对比，检查两个模型的MAE/MAPE与回测曲线。
6. 09:40 对比未来7日，选择与现场情况相符的模型；以每日单人12单生成排班参考。
7. 10:00 analyst写明轮休/技能约束；10:10 admin核对并签核，不能重复签核。区域版本发布后，各网点未签核排班自动切到新版并重算人数；同周已有签核排班时发布新版被拒，旧版保持发布态。
8. 10:20 viewer下载 `branch-demand-<id>.json`，作为下周排班会议的冻结证据。

## 核心算法与边界

输入为一个网点的连续非负整数日量（上限100000）。重复网点+日期返回409，无效日期/负数返回422。预测前要求至少`回测天数+28`个连续日量；日期缺口、重复日期、样本不足置任务failed，指出缺口并允许补录后重新提交。

周季节朴素预测下一日使用最近第7日前的实际值，未来7日重复最后一周。Holt初始水平为首值，趋势为第二值减首值，之后：`l_t=α y_t+(1−α)(l_(t−1)+b_(t−1))`，`b_t=β(l_t−l_(t−1))+(1−β)b_(t−1)`；未来h步为`l_t+h b_t`。α、β在提交前指定，不使用回测真值调参。

末7–21日作滚动一步回测，每个回测日只用此前历史重新拟合。较早验证日的实际值在后续日成为过去数据，这是walk-forward，不用未来信息。MAE=平均绝对误差（包括实际为0的日）；MAPE仅对实际非0的日计算百分比，同时报告使用日数/零实际日数，全部为0则MAPE为null。以回测MAE较低者作参考选择，同分选季节朴素。该回测同时用于选模，不能宣称独立最终泛化精度。

回测预测先截负为0；未来预测同样截断，再用floor(raw+0.5)四舍五入成非负整数，保留raw及clipped标记。最后用全部历史拟合两个未来7日序列。结果保存冻结记录、参数、checksum、回测逐日明细与两组未来预测。排班人数=`ceil(预测单量/单人日容量)`；容量需1–1000，由业务输入。不处理技能、休息、缺勤、轮班组合优化；不自动替代现场排班决定。

## 区域协调规则

区域成员必须≥2个网点。计算前冻结成员在**共同日期窗口**（各成员最早日的最大值到最晚日的较小值）内的日量：窗口内任一天任一成员缺日，整组直接failed并列出缺口，绝不把缺日当零量；窗口外成员各自的边缘日不影响本次冻结。区域日量=成员同日日量之和，区域与每个网点都独立走同一套末7–21日滚动一步回测并各自选模。

可信度按入选模型的回测MAE定义：`1/(1+MAE)`，仅用于排序与展示；区域逐日预测是总量锚点，网点独立预测之和与区域的差额按各网点MAE占全体MAE的比例分摊（MAE越大承担越多；全部MAE为0时平均分摊），校正后可正可负，最终用最大余数法取非负整数，保证**每日网点之和严格等于区域**，且始终非负。版本结果保存区域/网点两组未来预测、逐日调整前后、Δ、分摊额、权重与规则说明。该误差仍是选模用回测误差，不是独立泛化精度。

状态流转`pending→running→done|failed`。任一网点失败，整组failed且不可发布，其它网点状态仍记录以便定位；重试沿用同一条`region_run`和同一组id，只重算、不新建组；客户端可带`request_key`做提交幂等（同区域同key直接返回原组）。发布要求整组done且成员结果齐全，只能发布同周最新成功版本。发布新版时同区域同周旧版被标记`superseded_by`；该周未签核排班（按网点一行）原地切到新版版本、模型、逐日人数与依据，容量与业务说明保留；已退出区域的网点草稿随替换删除。若同周已有签核排班，发布整次失败并保留旧版发布态。发布与签核在进程内按区域互斥，并以`SELECT … FOR UPDATE`行锁兜底；签核时校验引用的版本仍是当前发布版，因此不会留下“已签核却引用旧版”的记录，也不会留下引用旧版的未签核排班。`GET /region-runs/{id}/basis`与各排班`basis`字段给出调整前后、权重、MAE/MAPE与逐日人数。

## 工程结构与环境

|部分|技术|
|---|---|
|后端/计算|Python3.11、FastAPI、SQLAlchemy；纯Python确定性Holt/季节法|
|前端|原生HTML/CSS/ES modules、SVG真实回测曲线|
|运行|Nginx1.27、PostgreSQL16、Redis7、单Python worker|

`frontend/src`按api、stores、types、components/common、hooks、pages、router、utils、constants分工；backend/src按routes、controllers、services、models、schemas、middlewares、utils、constants、config分工。表格/字段/状态标签在多页共用；表单hooks和HTML转义工具分离。请求ID、安全响应头两个中间件，写操作审计、全局异常恢复提示。JWT默认有效8小时。

恰好五服务：backend等待db/redis健康，worker还等待backend，frontend等待backend。所有服务有healthcheck；worker每轮更新`/tmp/heartbeat`，先消费`demand:region_runs`再消费`demand:runs`，处理真实预测/区域协调并在`/artifacts`共享卷写单点预测JSON。启动时恢复queued/running单点任务与pending/running区域组。数据库、Redis、结果各有命名卷。Nginx `/api/`转发后端根路由；worker启动恢复queued/running任务。清理：`docker compose down -v --remove-orphans`。

环境变量见.env.example：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO、NETWORK_SUBNET。显式10.253.109.0/24用于规避当前机默认网络池耗尽，移机可调整。演示凭据/JWT密钥部署时替换。本地开发可先起db/redis，在backend安装requirements，设置DATABASE_URL/REDIS_URL/JWT_SECRET，再`uvicorn src.main:app --reload`；前端沿用Nginx或同源代理。ORM建初表，migrations保留DDL，无在线版本迁移器。

区域相关表：regions、region_members、region_runs（唯一`region_id+week+version`与`region_id+request_key`）、region_run_members（每网点一行状态与结果）；staffings新增region_id、region_run_id、branch、week、basis列，后端启动时对旧表做`ALTER TABLE … ADD COLUMN`补齐。共享枚举：ROLES、STATES、BRANCHES、MODELS，后端src/constants/enums.py和schemas/business.py，前端src/constants/enums.js；存储列见models/entities.py。所有计算和人数换算在后端，前端只展示。

## 范围与证据

小型演示为逐条录入/修订，无CSV批量上传、删除、分页、自动超参搜索或外部排班发布；区域成员仍在建档/调整时选择，不做跨区域自动重分配；协调只保证总量与整数非负，不做技能、班次、休息的整数规划。无置信区间或节假日外生变量；单worker，不宣称多worker exactly-once。时间序列按业务日，不涉及小时时区换算。字体依赖Google Fonts，断网回退serif/sans-serif。

真实测试、截图和已知差异放在 `../../test-artifacts/gb-3109/`，源码不放证据。`backend/tests`包含协调算法（零误差等权、大负差额仍非负、整数合计、按MAE分摊）、冻结缺日整组失败、失败重试同组、request_key幂等、发布替换/阻止替换/回滚、发布与签核并发、版本回退拒绝、成员退出清理等用例；另有浏览器完整流程截图。测试用SQLite+fakeredis驱动同一套服务与路由。许可证MIT，见LICENSE。
