"""化工批次标准化KMeans分群与轮廓诊断。"""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

FEATURES = ["temperature_c", "pressure_bar", "residence_min", "yield_pct"]
LABELS = ["反应温度(℃)", "釜压(bar)", "停留时间(min)", "收率(%)"]


def metadata():
    return {
        "name": "化工批次工况分群", "short": "batch-clusters",
        "tagline": "从成批工况中找出运行族群，辨认稳定窗口与边缘批次。",
        "client": "青禾精细化学 · 4人过程优化小组 · 180批已完成的实验釜记录",
        "workflow": "工艺工程师按温度区间手工分组，再逐张比对釜压、停留时间与收率。",
        "pains": ["不同单位导致距离被温度主导", "人为分组难覆盖多变量工况", "分群数量凭经验缺少轮廓质量依据"],
        "upstream": "实验釜完工记录 reactor_batches_2026Q4.csv",
        "downstream": "工艺评审会选择下一轮小试的候选运行窗口",
        "entities": ["实验釜批次", "工况分群试验", "工艺评审简报"],
        "dataset_name": "青禾实验釜180批温压时收率记录",
        "columns": [{"key": "batch_id", "label": "批次", "type": "string"}] + [{"key": k, "label": l, "type": "number"} for k, l in zip(FEATURES, LABELS)],
        "parameters": [{"key": "clusters", "label": "工况族群数量K", "type": "number", "default": 3, "min": 2, "max": 6}],
        "workbench_title": "标准化工况分群", "action_label": "计算族群与轮廓质量", "unit": "批次",
        "accent": "oklch(51% 0.12 115)", "style": "specimen-lab-press",
        "seed_story": ["09:00 工艺员导入 reactor_batches_2026Q4.csv 的180批记录", "09:10 确认温度、釜压、停留时间和收率四列完整", "09:20 创建K=3的标准化分群试验", "09:21 后端计算Z分数、KMeans和轮廓系数", "09:30 工艺员查看各族群原单位中心及批次数", "09:40 改为K=4复查是否把稳定族群过度切开", "10:00 下载族群摘要交评审会", "16:00 管理员将评审简报设为每周内部归档"],
        "method": "对四个特征做Z分数标准化后，KMeans(n_init=20,random_state=42)拟合；用欧氏距离轮廓系数评估分离度；中心反变换回业务单位。",
        "limitations": ["KMeans偏好球形且相近规模的群", "将收率作为分群特征，不是收率预测模型", "分群标签无好坏含义，不能直接形成生产指令"],
    }


def seed_records():
    rng = np.random.default_rng(1010)
    centers = [[78, 2.2, 46, 89], [96, 3.6, 30, 94], [112, 5.1, 22, 83]]
    scales = [2.2, 0.18, 2.4, 1.6]
    rows = []
    for i in range(180):
        values = rng.normal(centers[i % 3], scales)
        rows.append({"batch_id": f"QH-{i+1:03}", **{k: round(float(v), 2) for k, v in zip(FEATURES, values)}})
    return rows


def parse_matrix(records):
    """把记录解析为有限数值矩阵，并执行业务口径校验。"""
    try:
        x = np.asarray([[float(row[f]) for f in FEATURES] for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("温度、釜压、停留时间、收率须完整且为数值。") from exc
    if not np.isfinite(x).all():
        raise ValueError("工况须为有限值，釜压与停留时间须正数，收率须0~100。")
    if (x[:, 1:3] <= 0).any() or (x[:, 3] < 0).any() or (x[:, 3] > 100).any():
        raise ValueError("工况须为有限值，釜压与停留时间须正数，收率须0~100。")
    return x


def validate_fit_matrix(x, k):
    if len(x) < max(30, k * 5):
        raise ValueError("至少需要30条记录，且每个候选族群平均至少5条。")
    if np.unique(x, axis=0).shape[0] < k or np.std(x, axis=0).min() < 1e-9:
        raise ValueError("需要至少K种不同工况，且四个特征均须有变化。")


def fit_model(x, k):
    """定稿试验的标准拟合：Z分数标准化 + KMeans，返回拟合器与原始标签。"""
    scaler = StandardScaler()
    z = scaler.fit_transform(x)
    model = KMeans(n_clusters=k, n_init=20, random_state=42)
    assignment = model.fit_predict(z)
    centers = scaler.inverse_transform(model.cluster_centers_)
    score = float(silhouette_score(z, assignment))
    # 以温度排序稳定显示标签，避免把算法内部随机标签误当业务等级。
    order = np.argsort(centers[:, 0])
    return scaler, model, assignment, centers, order, score


def calibration_from_job(records, params):
    """从定稿分群重放同口径拟合，导出可复现的归群口径快照。

    盲测试验不重新拟合，只沿用这里保存的标准化尺度（mean/scale）与
    标准化簇中心，按最近中心归群。
    """
    k = _parse_k(params)
    x = parse_matrix(records)
    validate_fit_matrix(x, k)
    scaler, model, assignment, centers, order, score = fit_model(x, k)
    # 显示标签按中心温度排序；保存 显示标签 -> 算法簇编号 的映射。
    label_to_cluster = {display: int(cluster) for display, cluster in enumerate(order, 1)}
    return {
        "features": FEATURES,
        "k": k,
        "mean": [round(float(v), 8) for v in scaler.mean_],
        "scale": [round(float(v), 8) for v in scaler.scale_],
        # 标准化空间中的簇中心，按显示标签（温度升序）排列。
        "centers_z": [[round(float(v), 8) for v in model.cluster_centers_[label_to_cluster[d]]] for d in range(1, k + 1)],
        # 业务单位中心，同序排列，供页面展示口径对照。
        "centers_native": [[round(float(v), 4) for v in centers[label_to_cluster[d]]] for d in range(1, k + 1)],
        "label_to_cluster": label_to_cluster,
        "baseline_silhouette": round(score, 4),
        "method": metadata()["method"],
    }


def assign_with_calibration(records, calibration):
    """盲测归群：用定稿尺度标准化盲测记录，再按最近定稿中心指派显示标签。

    不触碰 KMeans 拟合，盲测数据不会影响定稿尺度与中心。
    返回 (display_labels, native_centers_rows, detail_rows)。
    """
    feats = calibration["features"]
    mean = np.asarray(calibration["mean"], dtype=float)
    scale = np.asarray(calibration["scale"], dtype=float)
    centers_z = np.asarray(calibration["centers_z"], dtype=float)
    k = int(calibration["k"])
    try:
        x = np.asarray([[float(row[f]) for f in feats] for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("温度、釜压、停留时间、收率须完整且为数值。") from exc
    if not np.isfinite(x).all() or (x[:, 1:3] <= 0).any() or (x[:, 3] < 0).any() or (x[:, 3] > 100).any():
        raise ValueError("工况须为有限值，釜压与停留时间须正数，收率须0~100。")
    if np.std(x, axis=0).min() < 1e-9:
        raise ValueError("盲测批次的四个特征均须有变化。")
    z = (x - mean) / scale
    # 欧氏距离最近中心；显示标签即定稿的温度排序标签（1..K）。
    distances = np.linalg.norm(z[:, None, :] - centers_z[None, :, :], axis=2)
    nearest = np.argmin(distances, axis=1) + 1
    rows = []
    for i, row in enumerate(records):
        rows.append({
            "batch_id": str(row.get("batch_id", f"BLIND-{i+1}")),
            "cluster": f"工况族群{int(nearest[i])}",
            "distance": round(float(distances[i, nearest[i] - 1]), 4),
            **{f: round(float(v), 2) for f, v in zip(feats, x[i])},
        })
    summary_rows = []
    for display in range(1, k + 1):
        mask = nearest == display
        n = int(mask.sum())
        center_native = calibration["centers_native"][display - 1]
        summary_rows.append({
            "cluster": f"工况族群{display}", "count": n,
            "share_pct": round(n / len(records) * 100, 1),
            **{f: round(float(v), 2) for f, v in zip(feats, center_native)},
        })
    return [int(v) for v in nearest], summary_rows, rows


def _parse_k(params):
    try:
        raw_k = float(params.get("clusters", 3))
        k = int(raw_k)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("K须为2~6的整数。") from exc
    if raw_k != k or not 2 <= k <= 6:
        raise ValueError("K须为2~6的整数。")
    return k


def analyze(records, params):
    k = _parse_k(params)
    x = parse_matrix(records)
    validate_fit_matrix(x, k)
    scaler, model, assignment, centers, order, score = fit_model(x, k)
    rows = []
    chart_labels = []
    chart_values = [[] for _ in FEATURES]
    for display, cluster in enumerate(order, 1):
        n = int(np.sum(assignment == cluster))
        center = centers[cluster]
        rows.append({"cluster": f"工况族群{display}", "count": n, "share_pct": round(n / len(records) * 100, 1), **{f: round(float(v), 2) for f, v in zip(FEATURES, center)}})
        chart_labels.append(f"族群{display}")
        for j in range(len(FEATURES)):
            chart_values[j].append(round(float(model.cluster_centers_[cluster, j]), 3))
    best = max(rows, key=lambda row: row["yield_pct"])
    return {
        "summary": f"{len(records)}批工况分为{k}个族群；轮廓系数{score:.3f}，中心已还原为温度、釜压、时间和收率。",
        "metrics": [{"label": "轮廓系数", "value": round(score, 4)}, {"label": "族群数量", "value": k}, {"label": "批次数", "value": len(records)}, {"label": "标准化簇内平方和", "value": round(float(model.inertia_), 3)}],
        "table": {"columns": [{"key": "cluster", "label": "工况族群"}, {"key": "count", "label": "批次数"}, {"key": "share_pct", "label": "占比(%)"}] + [{"key": f, "label": l} for f, l in zip(FEATURES, LABELS)], "rows": rows},
        "chart": {"type": "bar", "labels": chart_labels, "series": [{"name": f"{LABELS[j]} Z中心", "values": chart_values[j]} for j in range(len(FEATURES))]},
        "findings": [f"{best['cluster']}的中心收率最高，为{best['yield_pct']}%；应结合温压窗口安排独立小试复核。", f"最小族群{min(row['count'] for row in rows)}批、最大族群{max(row['count'] for row in rows)}批；小群体可能对应边缘运行条件。", "对比不同K时优先观察轮廓系数与中心可解释性，簇内平方和随K增大通常会下降。"],
        "method": metadata()["method"], "warnings": ["分群用于探索，不表明某温压组合可安全放大。"] + (["轮廓系数低于0.25，当前工况分离较弱。"] if score < 0.25 else []),
    }
