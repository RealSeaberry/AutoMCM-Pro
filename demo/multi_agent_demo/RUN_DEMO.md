# 多 Agent 并行 Demo 运行手册

验证目标：
- ✅ 流水线初始化
- ✅ `parallel-start` 同时启动两个子问题
- ✅ 两个 Agent 并发建模 + 验证
- ✅ `parallel-all-done` 汇总
- ✅ draw-image 生成流程图（有 auth 时）

预计耗时：**10 分钟**（在 Codex 中运行）

---

## 准备：初始化工作区和流水线

在 `AutoMCM-Pro/` 目录下，依次发给 Codex：

### 消息 1 — 初始化工作区
```
Run these commands:
python scripts/setup_workspace.py
python scripts/pipeline_manager.py init --mode ap --contest cumcm
```

预期输出：
```
[pipeline] 流水线初始化完成
  模式: AP
  竞赛: CUMCM
  起始阶段: problem_analysis
```

---

### 消息 2 — 完成 problem_analysis（跳过，直接 approve）
```
Run:
python scripts/pipeline_manager.py start-stage problem_analysis
python scripts/pipeline_manager.py request-review \
  --stage problem_analysis \
  --summary "Demo 题目：咖啡馆利润最大化（LP）+ 销量趋势预测（回归）" \
  --results "问题一：LP，问题二：线性回归" \
  --next data_preprocessing
python scripts/pipeline_manager.py advance problem_analysis
```

---

### 消息 3 — 完成 data_preprocessing（跳过，直接 approve）
```
Run:
python scripts/pipeline_manager.py start-stage data_preprocessing
python scripts/pipeline_manager.py advance data_preprocessing
```

---

### 消息 4 — 并行启动两个子问题 ⭐
```
Run:
python scripts/pipeline_manager.py parallel-start model_1_build model_2_build
python scripts/pipeline_manager.py status
```

预期输出中看到：
```
▶  model_1_build                    in_progress
▶  model_2_build                    in_progress
```

---

### 消息 5a（子 Agent 1）— 问题一：线性规划

> 在 Codex 中这是一个独立的 Agent，但 demo 里顺序执行即可。

```
I am sub-agent for model_1_build (LP optimization).

Step 1: start stage
python scripts/pipeline_manager.py start-stage model_1_build

Step 2: create and run the model
Write and run CUMCM_Workspace/src/models/problem1_lp.py with this content:

"""
Cafe LP: maximize profit = 8*x_A + 5*x_B
subject to:
  15*x_A + 10*x_B <= 1500   (coffee beans)
  200*x_A          <= 12000  (milk)
  3*x_A  + 2*x_B  <= 240    (labor)
  x_A, x_B >= 0
"""
from scipy.optimize import linprog
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import os

os.makedirs('CUMCM_Workspace/latex/images', exist_ok=True)

# linprog minimizes, so negate profit
c = [-8, -5]
A_ub = [[15, 10], [200, 0], [3, 2]]
b_ub = [1500, 12000, 240]
bounds = [(0, None), (0, None)]
res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method='highs')

x_A, x_B = res.x
profit = -res.fun
print(f"x_A* = {x_A:.2f} cups/day")
print(f"x_B* = {x_B:.2f} cups/day")
print(f"Max profit = ¥{profit:.2f}/day")

# Plot feasible region
fig, ax = plt.subplots(figsize=(6, 5))
x = np.linspace(0, 110, 400)
ax.fill_between(x,
    np.minimum.reduce([
        (1500 - 15*x) / 10,
        12000 / 200 * np.ones_like(x),
        (240 - 3*x) / 2,
    ]), 0, alpha=0.2, color='blue', label='Feasible region')
ax.axvline(12000/200, color='orange', linestyle='--', label='Milk constraint')
ax.plot(x, (1500-15*x)/10, 'g--', label='Bean constraint')
ax.plot(x, (240-3*x)/2, 'r--', label='Labor constraint')
ax.plot(x_A, x_B, 'k*', markersize=14, label=f'Optimal ({x_A:.0f}, {x_B:.0f})')
ax.set_xlim(0, 105); ax.set_ylim(0, 130)
ax.set_xlabel('Latte (cups/day)'); ax.set_ylabel('Americano (cups/day)')
ax.set_title('Problem 1: Feasible Region & Optimal Solution')
ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig('CUMCM_Workspace/latex/images/fig01_lp_feasible.png', dpi=150)
print("Figure saved.")
```

Then write and run the verification:
```
Write and run CUMCM_Workspace/src/verifications/verify_problem1_lp.py:

from scipy.optimize import linprog
import numpy as np

c = [-8, -5]
A_ub = [[15, 10], [200, 0], [3, 2]]
b_ub = [1500, 12000, 240]
bounds = [(0, None), (0, None)]
res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method='highs')
x_A, x_B = res.x

checks = []
checks.append(("V-OPT-1a", 15*x_A + 10*x_B <= 1500 + 1e-6, f"bean: {15*x_A+10*x_B:.1f}≤1500"))
checks.append(("V-OPT-1b", 200*x_A <= 12000 + 1e-6,          f"milk: {200*x_A:.0f}≤12000"))
checks.append(("V-OPT-1c", 3*x_A + 2*x_B <= 240 + 1e-6,      f"labor: {3*x_A+2*x_B:.1f}≤240"))
checks.append(("V-OPT-2",  x_A >= 0 and x_B >= 0,             "non-negative"))

# Perturbation test
profit_opt = 8*x_A + 5*x_B
perturbed = max(8*(x_A*1.001) + 5*x_B, 8*x_A + 5*(x_B*1.001))
checks.append(("V-OPT-3", profit_opt >= perturbed - 1e-3, "perturbation test"))

print("="*55)
print("VERIFICATION REPORT — problem1_lp")
print("="*55)
all_pass = True
for cid, result, detail in checks:
    s = "✓ PASS" if result else "✗ FAIL"
    if not result: all_pass = False
    print(f"  [{cid}] {s}  {detail}")
print("="*55)
print(f"OVERALL: {'ALL PASS' if all_pass else 'FAILED'}")
```

Then advance:
```
python scripts/pipeline_manager.py start-stage model_1_verify
python scripts/pipeline_manager.py advance model_1_verify
```

---

### 消息 5b（子 Agent 2）— 问题二：线性回归

```
I am sub-agent for model_2_build (linear regression).

Write and run CUMCM_Workspace/src/models/problem2_regression.py:

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats
import os

os.makedirs('CUMCM_Workspace/latex/images', exist_ok=True)

t = np.arange(1, 15)
y = np.array([73,73,73,83,83,83,93,89,93,102,100,109,108,117])

slope, intercept, r, p, se = stats.linregress(t, y)
r2 = r**2
print(f"β0 = {intercept:.4f},  β1 = {slope:.4f}")
print(f"R² = {r2:.4f}")

# Predictions for days 15-17
t_pred = np.array([15, 16, 17])
y_pred = intercept + slope * t_pred
n = len(t)
t_mean = t.mean()
s_err = np.sqrt(((y - (intercept + slope*t))**2).sum() / (n-2))
t_crit = stats.t.ppf(0.975, df=n-2)
pred_interval = t_crit * s_err * np.sqrt(1 + 1/n + (t_pred - t_mean)**2 / ((t - t_mean)**2).sum())

print("\nPredictions:")
for i, (day, yp, pi) in enumerate(zip(t_pred, y_pred, pred_interval)):
    print(f"  Day {day}: {yp:.1f}  95%CI [{yp-pi:.1f}, {yp+pi:.1f}]")

# Plot
fig, ax = plt.subplots(figsize=(7, 4))
ax.scatter(t, y, color='steelblue', zorder=5, label='Observed')
t_all = np.linspace(1, 17, 200)
ax.plot(t_all, intercept + slope*t_all, 'r-', label=f'Fit: y={intercept:.1f}+{slope:.2f}t')
ax.scatter(t_pred, y_pred, color='red', marker='^', s=80, zorder=5, label='Forecast')
ax.set_xlabel('Day'); ax.set_ylabel('Total Sales (cups)')
ax.set_title(f'Problem 2: Sales Trend  R²={r2:.3f}')
ax.legend(); ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig('CUMCM_Workspace/latex/images/fig02_regression.png', dpi=150)
print("Figure saved.")
```

Then verify and advance:
```
Write and run CUMCM_Workspace/src/verifications/verify_problem2_regression.py:

import numpy as np
from scipy import stats

t = np.arange(1, 15)
y = np.array([73,73,73,83,83,83,93,89,93,102,100,109,108,117])
slope, intercept, r, p, se = stats.linregress(t, y)
residuals = y - (intercept + slope * t)

checks = []
checks.append(("V-REG-1", r**2 > 0.90, f"R²={r**2:.4f} > 0.90"))

# Shapiro-Wilk
from scipy.stats import shapiro
stat_sw, p_sw = shapiro(residuals)
checks.append(("V-REG-2", p_sw > 0.05, f"Shapiro-Wilk p={p_sw:.3f}"))

# Durbin-Watson (manual)
dw = np.sum(np.diff(residuals)**2) / np.sum(residuals**2)
checks.append(("V-REG-3", 1.0 < dw < 3.0, f"Durbin-Watson={dw:.3f}"))

# 5-fold CV
fold = len(t) // 5
cv_errors = []
for i in range(5):
    mask = np.ones(len(t), dtype=bool)
    mask[i*fold:(i+1)*fold] = False
    sl, ic, *_ = stats.linregress(t[mask], y[mask])
    pred = ic + sl * t[~mask]
    cv_errors.extend((y[~mask] - pred).tolist())
cv_rmse = np.sqrt(np.mean(np.array(cv_errors)**2))
in_rmse = np.sqrt(np.mean(residuals**2))
checks.append(("V-REG-4", cv_rmse / in_rmse < 1.5, f"CV-RMSE/RMSE={cv_rmse/in_rmse:.3f}"))

print("="*55)
print("VERIFICATION REPORT — problem2_regression")
print("="*55)
all_pass = True
for cid, result, detail in checks:
    s = "✓ PASS" if result else "✗ FAIL"
    if not result: all_pass = False
    print(f"  [{cid}] {s}  {detail}")
print("="*55)
print(f"OVERALL: {'ALL PASS' if all_pass else 'FAILED'}")
```

Then:
```
python scripts/pipeline_manager.py start-stage model_2_verify
python scripts/pipeline_manager.py advance model_2_verify
```

---

### 消息 6 — 汇总并行结果 ⭐
```
Run:
python scripts/pipeline_manager.py parallel-all-done model_1_verify model_2_verify
python scripts/pipeline_manager.py parallel-status model_1_verify model_2_verify
python scripts/pipeline_manager.py status
```

预期：
```
[pipeline] ✓ 并行组全部完成: ['model_1_verify', 'model_2_verify']
```

---

### 消息 7 — draw-image（检测 auth，有则生成，无则跳过）⭐
```
Run auth check first:
python scripts/draw_image.py --check

If exit code is 0 (api_key), then run:
python scripts/draw_image.py \
  --prompt "Clean technical flowchart on white background. Steps: (1) Initialize Pipeline → (2) Data Preprocessing → Parallel branch: [Model 1: LP Optimization] and [Model 2: Linear Regression] simultaneously → (3) Merge: Both verified → (4) Sensitivity Analysis → (5) LaTeX Writing → (6) PDF Output. Style: professional, blue/gray, sans-serif, clear arrows showing parallel branches merging." \
  --output CUMCM_Workspace/latex/images/fig00_pipeline_flow.png \
  --size 1536x1024 \
  --quality medium

If exit code is 2 (codex_oauth or none), skip and note: figure will use placeholder.
```

---

### 消息 8 — 收尾（可选，完整走完流水线）
```
Run:
python scripts/pipeline_manager.py start-stage sensitivity_analysis
python scripts/pipeline_manager.py advance sensitivity_analysis
python scripts/pipeline_manager.py start-stage latex_draft
python scripts/pipeline_manager.py advance latex_draft
python scripts/pipeline_manager.py start-stage final_compile
python scripts/pipeline_manager.py advance final_compile
python scripts/pipeline_manager.py status
```

最终状态应全部显示 `✓ approved`。

---

## 验证检查清单

运行完毕后确认以下文件存在：

```bash
ls CUMCM_Workspace/src/models/
# → problem1_lp.py  problem2_regression.py

ls CUMCM_Workspace/src/verifications/
# → verify_problem1_lp.py  verify_problem2_regression.py

ls CUMCM_Workspace/latex/images/
# → fig01_lp_feasible.png  fig02_regression.png
# → fig00_pipeline_flow.png（如果 draw-image 可用）

python scripts/pipeline_manager.py status
# → 所有阶段应为 ✓ approved
```
